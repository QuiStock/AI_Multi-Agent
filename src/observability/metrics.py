"""Pure metric aggregations over persisted traces and usage events."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from math import ceil, isfinite
from typing import Any

from src.observability.usage.ai_usage_repository import USAGE_SOURCE_LABELS

_MILLION = 1_000_000
_SLO_MAX_P95_MS = 20_000
_SLO_MAX_ERROR_RATE = 0.05
_PROJECTED_USAGE_SOURCES = frozenset(
    {
        "judge_jev",
        "summary_generation",
        "title_generation",
        "faq_embedding_query",
        "memory_embedding_query",
    }
)
_OPERATIONAL_USAGE_SOURCES = frozenset(
    {"lab", "faq_embedding_index", "memory_embedding_index"}
)


@dataclass(frozen=True, slots=True)
class ModelPricing:
    """USD rates per million input and output tokens for one exact model ID."""

    input_usd_per_million_tokens: float
    output_usd_per_million_tokens: float

    def __post_init__(self) -> None:
        rates = (self.input_usd_per_million_tokens, self.output_usd_per_million_tokens)
        if any(not isfinite(rate) or rate < 0 for rate in rates):
            raise ValueError("Os preços precisam ser finitos e não negativos")


@dataclass(slots=True)
class _TraceMetricTotals:
    trace_count: int = 0
    completed_traces: int = 0
    error_traces: int = 0
    turn_durations: list[float] = field(default_factory=list)
    completed_trace_cost_usd: float = 0.0
    completed_trace_unpriced_calls: int = 0
    components: dict[str, dict[str, Any]] = field(
        default_factory=lambda: defaultdict(_new_group)
    )
    models: dict[str, dict[str, Any]] = field(
        default_factory=lambda: defaultdict(_new_model_group)
    )
    span_count: int = 0
    error_spans: int = 0
    qwen_call_count: int = 0
    qwen_trace_count: int = 0
    trace_status_by_id: dict[str, object] = field(default_factory=dict)
    jev_span_trace_ids: set[str] = field(default_factory=set)
    latency_by_day: dict[date, list[float]] = field(
        default_factory=lambda: defaultdict(list)
    )
    priced_cost_by_day: dict[date, float] = field(
        default_factory=lambda: defaultdict(float)
    )


@dataclass(slots=True)
class _SLOObservations:
    terminal_trace_count: int = 0
    completed_traces: int = 0
    latency_good: int = 0
    latency_bad: int = 0
    durations: list[float] = field(default_factory=list)
    terminal_trace_ids: set[str] = field(default_factory=set)
    jev_span_trace_ids: set[str] = field(default_factory=set)
    model_calls: dict[str, dict[str, int]] = field(
        default_factory=lambda: defaultdict(lambda: {"good": 0, "bad": 0})
    )


@dataclass(slots=True)
class _ApplicationCostTotals:
    groups: dict[tuple[str, str], dict[str, Any]] = field(
        default_factory=lambda: defaultdict(_new_usage_group)
    )
    conversations: set[str] = field(default_factory=set)
    resolution_count: int = 0
    conversation_cost_usd: float = 0.0
    conversation_unpriced_calls: int = 0
    operational_cost_usd: float = 0.0
    operational_unpriced_calls: int = 0
    jev_span_trace_ids: set[str] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class _ApplicationPricing:
    model_pricing: Mapping[str, ModelPricing]
    source_pricing: Mapping[str, ModelPricing]
    embedding_model: str
    embedding_pricing: ModelPricing


def calculate_span_cost(
    span: Mapping[str, Any],
    model_pricing: Mapping[str, ModelPricing],
    usage_source_pricing: Mapping[str, ModelPricing] | None = None,
) -> float | None:
    """Return a span's estimated USD cost when its model and usage are known."""
    model = _text(span.get("model"), "")
    if span.get("kind") != "llm" or not model:
        return None

    input_tokens = _token_count(span.get("input_tokens"))
    output_tokens = _token_count(span.get("output_tokens"))
    if input_tokens is None and output_tokens is None:
        return None

    source = _span_usage_source(span)
    pricing = (usage_source_pricing or {}).get(source, model_pricing.get(model))
    cost = _priced_call_cost(pricing, input_tokens, output_tokens)
    return round(cost, 8) if cost is not None else None


def calculate_usage_event_cost(
    event: Mapping[str, Any],
    *,
    model_pricing: Mapping[str, ModelPricing],
    usage_source_pricing: Mapping[str, ModelPricing],
) -> float | None:
    """Estimate cost for a call recorded outside the trace span tree."""
    model = _text(event.get("model"), "")
    source = _text(event.get("source"), "")
    input_tokens = _token_count(event.get("input_tokens"))
    output_tokens = _token_count(event.get("output_tokens"))
    if input_tokens is None and output_tokens is None:
        return None
    pricing = usage_source_pricing.get(source, model_pricing.get(model))
    cost = _priced_call_cost(pricing, input_tokens, output_tokens)
    return round(cost, 8) if cost is not None else None


def calculate_metrics(
    traces: Iterable[Mapping[str, Any]],
    *,
    model_pricing: Mapping[str, ModelPricing] | None = None,
    usage_source_pricing: Mapping[str, ModelPricing] | None = None,
    usage_events: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Calculate turn, component, model, token, cost, and fallback metrics.

    p95 uses nearest rank: the value at ``ceil(0.95 * sample_count)``.
    Costs require exact rates and usage for every billable token direction. An
    incomplete total is ``None``; the known subtotal and missing-data reasons
    remain visible.
    JEV model spans are priced by service source; legacy JEV usage events remain
    readable for older traces. Qwen fallback counts come from Qwen model spans.
    """
    pricing = model_pricing or {}
    source_pricing = usage_source_pricing or {}
    totals = _aggregate_trace_metrics(traces, pricing, source_pricing)
    _aggregate_legacy_jev_usage(totals, usage_events, pricing, source_pricing)
    component_results = {
        key: _group_result(group) for key, group in sorted(totals.components.items())
    }
    model_results = {
        key: _model_result(key, group) for key, group in sorted(totals.models.items())
    }
    token_metrics, cost_metrics = _token_and_cost_results(totals.models)
    cost_metrics.update(
        {
            "completed_trace_count": totals.completed_traces,
            "completed_trace_unpriced_calls": totals.completed_trace_unpriced_calls,
            "cost_per_completed_trace_usd": (
                round(totals.completed_trace_cost_usd / totals.completed_traces, 8)
                if totals.completed_traces > 0
                and totals.completed_trace_unpriced_calls == 0
                else None
            ),
        }
    )
    error_rate = _rate(totals.error_traces, totals.trace_count)
    p95_ms = _distribution(totals.turn_durations)["p95_ms"]
    slo_ok = _slo_passes(
        totals.trace_count,
        len(totals.turn_durations),
        p95_ms,
        error_rate,
    )

    most_used_model = next(
        iter(
            sorted(
                model_results,
                key=lambda model: (-model_results[model]["calls"], model),
            )
        ),
        None,
    )
    agent_latency = [
        {
            "name": key.removeprefix("node:"),
            "average_ms": result["latency"]["average_ms"],
        }
        for key, result in component_results.items()
        if key.startswith("node:")
    ]
    agent_latency.sort(
        key=lambda entry: (
            entry["average_ms"] is None,
            -(entry["average_ms"] or 0),
            entry["name"],
        )
    )

    return {
        "traces": {
            "count": totals.trace_count,
            "completed_count": totals.completed_traces,
            "error_count": totals.error_traces,
            "error_rate": error_rate,
            "latency": _distribution(totals.turn_durations),
        },
        "spans": {
            "count": totals.span_count,
            "error_count": totals.error_spans,
            "error_rate": _rate(totals.error_spans, totals.span_count),
        },
        "tokens": token_metrics,
        "cost": cost_metrics,
        "fallback": {
            "qwen_call_count": totals.qwen_call_count,
            "qwen_trace_count": totals.qwen_trace_count,
            "rate": _rate(totals.qwen_trace_count, totals.trace_count),
        },
        "components": component_results,
        "models": model_results,
        "board": {
            "slo_ok": slo_ok,
            "most_used_model": most_used_model,
            "agent_latency": agent_latency,
        },
        "latency_series": _latency_series(totals.latency_by_day),
        "cumulative_cost_series": _cumulative_cost_series(totals.priced_cost_by_day),
    }


def _aggregate_trace_metrics(
    traces: Iterable[Mapping[str, Any]],
    model_pricing: Mapping[str, ModelPricing],
    source_pricing: Mapping[str, ModelPricing],
) -> _TraceMetricTotals:
    totals = _TraceMetricTotals()
    for trace in traces:
        totals.trace_count += 1
        status = trace.get("status")
        trace_id = trace.get("trace_id")
        if isinstance(trace_id, str):
            totals.trace_status_by_id[trace_id] = status
        totals.completed_traces += status == "completed"
        totals.error_traces += status == "error"
        spans = trace.get("spans")
        safe_spans = spans if isinstance(spans, list) else []
        duration = _number(trace.get("duration_ms"))
        if duration is None:
            duration = _turn_duration(safe_spans)
        if duration is not None:
            totals.turn_durations.append(duration)
        span_count, error_spans, cost_usd, unpriced_calls = _aggregate_trace_spans(
            safe_spans,
            totals.models,
            totals.components,
            model_pricing,
            source_pricing,
        )
        totals.span_count += span_count
        totals.error_spans += error_spans
        qwen_calls = _qwen_call_count(safe_spans)
        totals.qwen_call_count += qwen_calls
        totals.qwen_trace_count += qwen_calls > 0
        if status == "completed":
            totals.completed_trace_cost_usd += cost_usd
            totals.completed_trace_unpriced_calls += unpriced_calls
        _record_daily_trace_metrics(
            _utc_day(trace.get("started_at")),
            duration,
            cost_usd,
            totals.latency_by_day,
            totals.priced_cost_by_day,
        )
        if isinstance(trace_id, str) and any(
            isinstance(span, Mapping) and _span_usage_source(span) == "judge_jev"
            for span in safe_spans
        ):
            totals.jev_span_trace_ids.add(trace_id)
    return totals


def _aggregate_legacy_jev_usage(
    totals: _TraceMetricTotals,
    usage_events: Iterable[Mapping[str, Any]],
    model_pricing: Mapping[str, ModelPricing],
    source_pricing: Mapping[str, ModelPricing],
) -> None:
    for event in usage_events:
        event_trace_id = event.get("trace_id")
        if (
            event.get("source") != "judge_jev"
            or not isinstance(event_trace_id, str)
            or event_trace_id not in totals.trace_status_by_id
            or event_trace_id in totals.jev_span_trace_ids
        ):
            continue
        model = _text(event.get("model"), "unknown")
        group = totals.models[model]
        _record_call(group, event.get("status"), _number(event.get("duration_ms")))
        event_cost = _record_tokens_and_cost(
            group,
            input_tokens=_token_count(event.get("input_tokens")),
            output_tokens=_token_count(event.get("output_tokens")),
            pricing=source_pricing.get("judge_jev", model_pricing.get(model)),
        )
        if totals.trace_status_by_id[event_trace_id] == "completed":
            if event_cost is None:
                totals.completed_trace_unpriced_calls += 1
            else:
                totals.completed_trace_cost_usd += event_cost
        event_day = _utc_day(event.get("timestamp"))
        if event_day is not None and event_cost is not None:
            totals.priced_cost_by_day[event_day] += event_cost


def _utc_day(value: object) -> date | None:
    if not isinstance(value, datetime):
        return None
    timestamp = value.replace(tzinfo=UTC) if value.tzinfo is None else value
    return timestamp.astimezone(UTC).date()


def _span_usage_source(span: Mapping[str, Any]) -> str:
    attributes = span.get("attributes")
    if not isinstance(attributes, Mapping):
        return ""
    source = attributes.get("usage_source")
    return source if isinstance(source, str) else ""


def _aggregate_trace_spans(
    spans: list[Any],
    models: dict[str, dict[str, Any]],
    components: dict[str, dict[str, Any]],
    pricing: Mapping[str, ModelPricing],
    source_pricing: Mapping[str, ModelPricing],
) -> tuple[int, int, float, int]:
    span_count = error_spans = unpriced_calls = 0
    trace_cost_usd = 0.0
    for span in spans:
        if not isinstance(span, Mapping):
            continue
        kind = _text(span.get("kind"), "unknown")
        if kind == "turn":
            continue

        span_count += 1
        span_status = span.get("status")
        error_spans += span_status == "error"
        span_duration = _number(span.get("duration_ms"))

        if kind != "llm":
            name = _text(span.get("name"), "unknown")
            _record_call(components[f"{kind}:{name}"], span_status, span_duration)
            continue

        model = _text(span.get("model"), "unknown")
        group = models[model]
        _record_call(group, span_status, span_duration)
        input_tokens = _token_count(span.get("input_tokens"))
        output_tokens = _token_count(span.get("output_tokens"))
        model_price = source_pricing.get(_span_usage_source(span), pricing.get(model))
        _record_tokens_and_cost(
            group,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            pricing=model_price,
        )
        if model_price is None or input_tokens is None or output_tokens is None:
            unpriced_calls += 1
            continue
        trace_cost_usd += (
            input_tokens * model_price.input_usd_per_million_tokens
            + output_tokens * model_price.output_usd_per_million_tokens
        ) / _MILLION

    return span_count, error_spans, trace_cost_usd, unpriced_calls


def _record_daily_trace_metrics(
    trace_day: date | None,
    duration_ms: float | None,
    cost_usd: float,
    latency_by_day: dict[date, list[float]],
    priced_cost_by_day: dict[date, float],
) -> None:
    if trace_day is None:
        return
    if duration_ms is not None:
        latency_by_day[trace_day].append(duration_ms)
    else:
        latency_by_day[trace_day]
    priced_cost_by_day[trace_day] += cost_usd


def _slo_passes(
    trace_count: int,
    duration_count: int,
    p95_ms: float | None,
    error_rate: float | None,
) -> bool | None:
    if trace_count == 0:
        return None
    return (
        duration_count == trace_count
        and p95_ms is not None
        and p95_ms <= _SLO_MAX_P95_MS
        and error_rate is not None
        and error_rate <= _SLO_MAX_ERROR_RATE
    )


def _latency_series(latency_by_day: dict[date, list[float]]) -> list[dict[str, Any]]:
    return [
        {
            "date": day,
            "duration_ms": sum(samples) / len(samples) if samples else None,
            "sample_count": len(samples),
        }
        for day, samples in sorted(latency_by_day.items())
    ]


def _cumulative_cost_series(
    priced_cost_by_day: dict[date, float],
) -> list[dict[str, Any]]:
    cumulative_cost = 0.0
    series: list[dict[str, Any]] = []
    for day, daily_cost in sorted(priced_cost_by_day.items()):
        cumulative_cost += daily_cost
        series.append({"date": day, "cumulative_cost_usd": round(cumulative_cost, 8)})
    return series


def calculate_slo_metrics(  # noqa: PLR0913
    traces: Iterable[Mapping[str, Any]],
    *,
    usage_events: Iterable[Mapping[str, Any]] = (),
    window_started_at: datetime,
    window_ended_at: datetime,
    environment: str | None,
    latency_target_ms: float = 20_000,
) -> dict[str, Any]:
    """Calculate service objectives from filtered terminal traces/spans.

    Traces without a recorded duration count as bad latency observations so
    missing instrumentation cannot make the latency objective look healthier.
    Model success is calculated independently for each model. The caller passes
    the selected date and identity filters; status is deliberately not a filter.
    """
    observations = _collect_slo_observations(traces, latency_target_ms)
    _add_legacy_jev_slo_events(observations, usage_events)

    completion = _slo_result(
        observations.completed_traces,
        observations.terminal_trace_count - observations.completed_traces,
        target_rate=0.95,
    )
    latency = _slo_result(
        observations.latency_good,
        observations.latency_bad,
        target_rate=0.95,
    )
    latency.update(
        {
            "p95_ms": _distribution(observations.durations)["p95_ms"],
            "duration_sample_count": len(observations.durations),
            "target_p95_ms": latency_target_ms,
        }
    )
    period_error_rate = _rate(
        observations.terminal_trace_count - observations.completed_traces,
        observations.terminal_trace_count,
    )
    period_slo_ok = _slo_passes(
        observations.terminal_trace_count,
        len(observations.durations),
        latency["p95_ms"],
        period_error_rate,
    )
    models = {
        model: {
            "model": model,
            **_slo_result(group["good"], group["bad"], target_rate=0.95),
        }
        for model, group in sorted(observations.model_calls.items())
    }
    return {
        "window": {
            "started_at": window_started_at,
            "ended_at": window_ended_at,
            "duration_days": round(
                max(
                    0.0,
                    (window_ended_at - window_started_at).total_seconds() / 86_400,
                ),
                3,
            ),
            "environment": environment,
        },
        "period_slo_ok": period_slo_ok,
        "turn_completion": completion,
        "turn_latency": latency,
        "models": models,
    }


def _collect_slo_observations(
    traces: Iterable[Mapping[str, Any]],
    latency_target_ms: float,
) -> _SLOObservations:
    observations = _SLOObservations()
    for trace in traces:
        trace_status = trace.get("status")
        if trace_status not in {"completed", "error"}:
            continue
        trace_id = trace.get("trace_id")
        if isinstance(trace_id, str):
            observations.terminal_trace_ids.add(trace_id)
        observations.terminal_trace_count += 1
        observations.completed_traces += trace_status == "completed"
        spans = trace.get("spans")
        safe_spans = spans if isinstance(spans, list) else []
        duration = _number(trace.get("duration_ms"))
        if duration is None:
            duration = _turn_duration(safe_spans)
        if duration is not None:
            observations.durations.append(duration)
        if duration is not None and duration <= latency_target_ms:
            observations.latency_good += 1
        else:
            observations.latency_bad += 1
        _count_trace_model_calls(observations, trace_id, safe_spans)
    return observations


def _count_trace_model_calls(
    observations: _SLOObservations,
    trace_id: object,
    spans: list[Any],
) -> None:
    for span in spans:
        if not isinstance(span, Mapping) or span.get("kind") != "llm":
            continue
        if _span_usage_source(span) == "judge_jev" and isinstance(trace_id, str):
            observations.jev_span_trace_ids.add(trace_id)
        group = observations.model_calls[_text(span.get("model"), "unknown")]
        if span.get("status") == "completed":
            group["good"] += 1
        elif span.get("status") == "error":
            group["bad"] += 1


def _add_legacy_jev_slo_events(
    observations: _SLOObservations,
    usage_events: Iterable[Mapping[str, Any]],
) -> None:
    for event in usage_events:
        trace_id = event.get("trace_id")
        if (
            event.get("source") != "judge_jev"
            or not isinstance(trace_id, str)
            or trace_id not in observations.terminal_trace_ids
            or trace_id in observations.jev_span_trace_ids
        ):
            continue
        group = observations.model_calls[_text(event.get("model"), "unknown")]
        if event.get("status") == "completed":
            group["good"] += 1
        elif event.get("status") == "error":
            group["bad"] += 1


def calculate_application_cost(  # noqa: PLR0913
    traces: Iterable[Mapping[str, Any]],
    usage_events: Iterable[Mapping[str, Any]],
    *,
    model_pricing: Mapping[str, ModelPricing],
    usage_source_pricing: Mapping[str, ModelPricing] | None = None,
    embedding_model: str,
    embedding_input_usd_per_million_tokens: float,
    embedding_tier: str,
) -> dict[str, Any]:
    """Aggregate estimated AI spend by source across every app environment."""
    embedding_pricing = ModelPricing(
        input_usd_per_million_tokens=embedding_input_usd_per_million_tokens,
        output_usd_per_million_tokens=0,
    )
    source_pricing = usage_source_pricing or {}
    pricing = _ApplicationPricing(
        model_pricing=model_pricing,
        source_pricing=source_pricing,
        embedding_model=embedding_model,
        embedding_pricing=embedding_pricing,
    )
    totals = _ApplicationCostTotals()
    _collect_trace_application_costs(
        totals,
        traces,
        model_pricing,
        source_pricing,
    )
    _collect_usage_application_costs(totals, usage_events, pricing)
    return _format_application_cost(
        totals,
        embedding_model,
        embedding_tier,
        embedding_input_usd_per_million_tokens,
    )


def _collect_trace_application_costs(
    totals: _ApplicationCostTotals,
    traces: Iterable[Mapping[str, Any]],
    model_pricing: Mapping[str, ModelPricing],
    source_pricing: Mapping[str, ModelPricing],
) -> None:
    for trace in traces:
        trace_id = trace.get("trace_id")
        conversation_id = _normalized_id(trace.get("conversation_id"))
        if conversation_id:
            totals.conversations.add(conversation_id)
        totals.resolution_count += _is_business_resolution(trace)
        spans = trace.get("spans")
        if not isinstance(spans, list):
            continue
        for span in spans:
            if not isinstance(span, Mapping) or span.get("kind") != "llm":
                continue
            usage_source = _span_usage_source(span)
            if usage_source == "judge_jev" and isinstance(trace_id, str):
                totals.jev_span_trace_ids.add(trace_id)
            model = _text(span.get("model"), "unknown")
            source = usage_source if usage_source == "judge_jev" else "agent_turn"
            _record_application_cost_call(
                totals,
                source=source,
                model=model,
                status=span.get("status"),
                input_tokens=_token_count(span.get("input_tokens")),
                output_tokens=_token_count(span.get("output_tokens")),
                pricing=source_pricing.get(source, model_pricing.get(model)),
                conversation_id=conversation_id,
                projectable=True,
            )


def _collect_usage_application_costs(
    totals: _ApplicationCostTotals,
    usage_events: Iterable[Mapping[str, Any]],
    pricing: _ApplicationPricing,
) -> None:
    for event in usage_events:
        source = event.get("source")
        if not isinstance(source, str) or source not in USAGE_SOURCE_LABELS:
            continue
        if source == "agent_turn" or _is_jev_event_already_in_trace(
            totals,
            source,
            event.get("trace_id"),
        ):
            continue
        model = _text(event.get("model"), "unknown")
        event_pricing = _usage_event_pricing(
            source,
            model,
            pricing,
        )
        conversation_id = _normalized_id(event.get("conversation_id"))
        projectable = source in _PROJECTED_USAGE_SOURCES and bool(conversation_id)
        _record_application_cost_call(
            totals,
            source=source,
            model=model,
            status=event.get("status"),
            input_tokens=_token_count(event.get("input_tokens")),
            output_tokens=_token_count(event.get("output_tokens")),
            pricing=event_pricing,
            conversation_id=conversation_id,
            projectable=projectable,
        )


def _record_application_cost_call(  # noqa: PLR0913
    totals: _ApplicationCostTotals,
    *,
    source: str,
    model: str,
    status: object,
    input_tokens: int | None,
    output_tokens: int | None,
    pricing: ModelPricing | None,
    conversation_id: str | None,
    projectable: bool,
) -> None:
    call_cost = _record_usage_call(
        totals.groups[(source, model)],
        status=status,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        pricing=pricing,
    )
    if projectable and conversation_id:
        totals.conversations.add(conversation_id)
        if call_cost is None:
            totals.conversation_unpriced_calls += 1
        else:
            totals.conversation_cost_usd += call_cost
    elif call_cost is None:
        totals.operational_unpriced_calls += 1
    else:
        totals.operational_cost_usd += call_cost


def _is_jev_event_already_in_trace(
    totals: _ApplicationCostTotals,
    source: str,
    trace_id: object,
) -> bool:
    return (
        source == "judge_jev"
        and isinstance(trace_id, str)
        and trace_id in totals.jev_span_trace_ids
    )


def _usage_event_pricing(
    source: str,
    model: str,
    pricing: _ApplicationPricing,
) -> ModelPricing | None:
    if "embedding" in source:
        return pricing.embedding_pricing if model == pricing.embedding_model else None
    return pricing.source_pricing.get(source, pricing.model_pricing.get(model))


def _normalized_id(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _format_application_cost(
    totals: _ApplicationCostTotals,
    embedding_model: str,
    embedding_tier: str,
    embedding_input_usd_per_million_tokens: float,
) -> dict[str, Any]:
    origins: list[dict[str, Any]] = []
    priced_subtotal_usd = 0.0
    priced_calls = unpriced_calls = 0
    for (source, model), group in sorted(totals.groups.items()):
        subtotal = group["priced_subtotal_usd"]
        priced_subtotal_usd += subtotal
        priced_calls += group["priced_calls"]
        unpriced_calls += group["unpriced_calls"]
        origins.append(
            {
                "source": source,
                "label": USAGE_SOURCE_LABELS[source],
                "model": model,
                "calls": group["calls"],
                "completed_count": group["completed"],
                "error_count": group["errors"],
                "input_tokens": (
                    group["input_tokens"] if group["input_observations"] else None
                ),
                "output_tokens": (
                    group["output_tokens"] if group["output_observations"] else None
                ),
                "calls_with_usage": group["complete_usage"],
                "calls_without_usage": group["missing_usage"],
                "calls_missing_usage": group["calls_missing_usage"],
                "calls_missing_price": group["calls_missing_price"],
                "calls_missing_both": group["calls_missing_both"],
                "priced_calls": group["priced_calls"],
                "unpriced_calls": group["unpriced_calls"],
                "estimated_cost_usd": (
                    round(subtotal, 8) if group["unpriced_calls"] == 0 else None
                ),
                "priced_subtotal_usd": round(subtotal, 8),
            }
        )

    return {
        "currency": "USD",
        "estimated_total_usd": (
            round(priced_subtotal_usd, 8) if unpriced_calls == 0 else None
        ),
        "conversation_count": len(totals.conversations),
        "resolution_count": totals.resolution_count,
        "conversation_variable_cost_usd": (
            round(totals.conversation_cost_usd, 8)
            if totals.conversation_unpriced_calls == 0
            else None
        ),
        "conversation_variable_unpriced_calls": totals.conversation_unpriced_calls,
        "operational_cost_usd": (
            round(totals.operational_cost_usd, 8)
            if totals.operational_unpriced_calls == 0
            else None
        ),
        "operational_unpriced_calls": totals.operational_unpriced_calls,
        "priced_subtotal_usd": round(priced_subtotal_usd, 8),
        "priced_calls": priced_calls,
        "unpriced_calls": unpriced_calls,
        "embedding_model": embedding_model,
        "embedding_tier": embedding_tier,
        "embedding_input_usd_per_million_tokens": (
            embedding_input_usd_per_million_tokens
        ),
        "origins": origins,
    }


def calculate_cost_projections(
    *,
    conversation_variable_cost_usd: object,
    conversation_count: int,
    resolution_count: int,
) -> dict[str, Any]:
    """Project observed conversation spend at five conversations per user/week."""
    total = _number(conversation_variable_cost_usd)
    per_conversation = (
        total / conversation_count
        if total is not None and conversation_count > 0
        else None
    )
    return {
        "conversation_count": conversation_count,
        "resolution_count": resolution_count,
        "cost_per_conversation_usd": (
            round(per_conversation, 8) if per_conversation is not None else None
        ),
        "cost_per_resolution_usd": (
            round(total / resolution_count, 8)
            if total is not None and resolution_count > 0
            else None
        ),
        "weekly_cost_100_users_usd": (
            per_conversation * 5 * 100 if per_conversation is not None else None
        ),
        "weekly_cost_1000_users_usd": (
            per_conversation * 5 * 1000 if per_conversation is not None else None
        ),
    }


def _is_business_resolution(trace: Mapping[str, Any]) -> bool:
    return trace.get("status") == "completed"


def _slo_result(
    good_count: int,
    bad_count: int,
    *,
    target_rate: float,
) -> dict[str, Any]:
    total_count = good_count + bad_count
    if total_count == 0:
        actual_rate = None
        consumed = remaining = None
        status = "no_data"
    else:
        actual_rate = good_count / total_count
        error_rate = bad_count / total_count
        error_budget_rate = 1 - target_rate
        consumed = round(error_rate / error_budget_rate * 100, 2)
        remaining = round(max(0, 100 - consumed), 2)
        status = "met" if actual_rate >= target_rate else "breached"
    return {
        "target_rate": target_rate,
        "actual_rate": round(actual_rate, 6) if actual_rate is not None else None,
        "good_count": good_count,
        "bad_count": bad_count,
        "total_count": total_count,
        "error_budget_consumed_pct": consumed,
        "error_budget_remaining_pct": remaining,
        "status": status,
    }


def _new_group() -> dict[str, Any]:
    return {"calls": 0, "completed": 0, "errors": 0, "durations": []}


def _new_model_group() -> dict[str, Any]:
    return {
        **_new_group(),
        "input_tokens": 0,
        "output_tokens": 0,
        "input_observations": 0,
        "output_observations": 0,
        "complete_usage": 0,
        "partial_usage": 0,
        "missing_usage": 0,
        "priced_subtotal_usd": 0.0,
        "priced_calls": 0,
        "unpriced_calls": 0,
    }


def _new_usage_group() -> dict[str, Any]:
    return {
        "calls": 0,
        "completed": 0,
        "errors": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "input_observations": 0,
        "output_observations": 0,
        "complete_usage": 0,
        "missing_usage": 0,
        "priced_subtotal_usd": 0.0,
        "priced_calls": 0,
        "unpriced_calls": 0,
        "calls_missing_usage": 0,
        "calls_missing_price": 0,
        "calls_missing_both": 0,
    }


def _record_usage_call(
    group: dict[str, Any],
    *,
    status: object,
    input_tokens: int | None,
    output_tokens: int | None,
    pricing: ModelPricing | None,
) -> float | None:
    group["calls"] += 1
    group["completed"] += status == "completed"
    group["errors"] += status == "error"
    if input_tokens is not None:
        group["input_tokens"] += input_tokens
        group["input_observations"] += 1
    if output_tokens is not None:
        group["output_tokens"] += output_tokens
        group["output_observations"] += 1

    if input_tokens is not None and output_tokens is not None:
        group["complete_usage"] += 1
    else:
        group["missing_usage"] += 1

    cost = _priced_call_cost(pricing, input_tokens, output_tokens)
    if cost is None:
        group["unpriced_calls"] += 1
        usage_complete = input_tokens is not None and output_tokens is not None
        if pricing is None and usage_complete:
            group["calls_missing_price"] += 1
        elif pricing is None:
            group["calls_missing_both"] += 1
        else:
            group["calls_missing_usage"] += 1
        return None
    group["priced_subtotal_usd"] += cost
    group["priced_calls"] += 1
    return cost


def _record_call(group: dict[str, Any], status: object, duration: float | None) -> None:
    group["calls"] += 1
    group["completed"] += status == "completed"
    group["errors"] += status == "error"
    if duration is not None:
        group["durations"].append(duration)


def _record_tokens_and_cost(
    group: dict[str, Any],
    *,
    input_tokens: int | None,
    output_tokens: int | None,
    pricing: ModelPricing | None,
) -> float | None:
    if input_tokens is not None:
        group["input_tokens"] += input_tokens
        group["input_observations"] += 1
    if output_tokens is not None:
        group["output_tokens"] += output_tokens
        group["output_observations"] += 1

    if input_tokens is not None and output_tokens is not None:
        group["complete_usage"] += 1
    elif input_tokens is not None or output_tokens is not None:
        group["partial_usage"] += 1
    else:
        group["missing_usage"] += 1

    cost = _priced_call_cost(pricing, input_tokens, output_tokens)
    if cost is None:
        group["unpriced_calls"] += 1
        return None
    group["priced_subtotal_usd"] += cost
    group["priced_calls"] += 1
    return cost


def _priced_call_cost(
    pricing: ModelPricing | None,
    input_tokens: int | None,
    output_tokens: int | None,
) -> float | None:
    if pricing is None:
        return None
    if pricing.input_usd_per_million_tokens and input_tokens is None:
        return None
    if pricing.output_usd_per_million_tokens and output_tokens is None:
        return None
    return (
        (input_tokens or 0) * pricing.input_usd_per_million_tokens
        + (output_tokens or 0) * pricing.output_usd_per_million_tokens
    ) / _MILLION


def _group_result(group: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "calls": group["calls"],
        "completed_count": group["completed"],
        "error_count": group["errors"],
        "error_rate": _rate(group["errors"], group["calls"]),
        "latency": _distribution(group["durations"]),
    }


def _model_result(name: str, group: Mapping[str, Any]) -> dict[str, Any]:
    result = _group_result(group)
    result.update(
        {
            "model": name,
            "input_tokens": (
                group["input_tokens"] if group["input_observations"] else None
            ),
            "output_tokens": (
                group["output_tokens"] if group["output_observations"] else None
            ),
            "calls_with_complete_usage": group["complete_usage"],
            "calls_with_partial_usage": group["partial_usage"],
            "calls_without_usage": group["missing_usage"],
            "estimated_cost_usd": (
                round(group["priced_subtotal_usd"], 8)
                if group["unpriced_calls"] == 0
                else None
            ),
            "priced_subtotal_usd": round(group["priced_subtotal_usd"], 8),
            "priced_calls": group["priced_calls"],
            "unpriced_calls": group["unpriced_calls"],
        }
    )
    return result


def _token_and_cost_results(
    models: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    groups = list(models.values())
    llm_calls = sum(group["calls"] for group in groups)
    priced_calls = sum(group["priced_calls"] for group in groups)
    unpriced_calls = sum(group["unpriced_calls"] for group in groups)
    subtotal = sum(group["priced_subtotal_usd"] for group in groups)
    input_observations = sum(group["input_observations"] for group in groups)
    output_observations = sum(group["output_observations"] for group in groups)

    return (
        {
            "llm_calls": llm_calls,
            "input_tokens": (
                sum(group["input_tokens"] for group in groups)
                if input_observations
                else None
            ),
            "output_tokens": (
                sum(group["output_tokens"] for group in groups)
                if output_observations
                else None
            ),
            "calls_with_complete_usage": sum(
                group["complete_usage"] for group in groups
            ),
            "calls_with_partial_usage": sum(group["partial_usage"] for group in groups),
            "calls_without_usage": sum(group["missing_usage"] for group in groups),
        },
        {
            "currency": "USD",
            "estimated_total_usd": (
                round(subtotal, 8) if llm_calls == 0 or unpriced_calls == 0 else None
            ),
            "priced_subtotal_usd": round(subtotal, 8),
            "priced_calls": priced_calls,
            "unpriced_calls": unpriced_calls,
        },
    )


def _qwen_call_count(spans: list[Any]) -> int:
    count = 0
    for span in spans:
        if not isinstance(span, Mapping) or span.get("kind") != "llm":
            continue
        model = span.get("model")
        if isinstance(model, str) and "qwen" in model.casefold():
            count += 1
    return count


def _turn_duration(spans: list[Any]) -> float | None:
    for span in spans:
        if isinstance(span, Mapping) and span.get("kind") == "turn":
            return _number(span.get("duration_ms"))
    return None


def _distribution(durations: list[float]) -> dict[str, Any]:
    if not durations:
        return {"sample_count": 0, "average_ms": None, "p95_ms": None, "max_ms": None}
    ordered = sorted(durations)
    p95_index = max(0, ceil(0.95 * len(ordered)) - 1)
    return {
        "sample_count": len(ordered),
        "average_ms": round(sum(ordered) / len(ordered), 3),
        "p95_ms": round(ordered[p95_index], 3),
        "max_ms": round(ordered[-1], 3),
    }


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if isfinite(number) and number >= 0 else None


def _token_count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _text(value: object, fallback: str) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else fallback
