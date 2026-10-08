"""Pure metric aggregations over persisted traces and usage events."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from math import ceil, isfinite
from typing import Any

from src.observability.ai_usage_repository import USAGE_SOURCE_LABELS

_MILLION = 1_000_000


@dataclass(frozen=True, slots=True)
class ModelPricing:
    """USD rates per million input and output tokens for one exact model ID."""

    input_usd_per_million_tokens: float
    output_usd_per_million_tokens: float

    def __post_init__(self) -> None:
        rates = (self.input_usd_per_million_tokens, self.output_usd_per_million_tokens)
        if any(not isfinite(rate) or rate < 0 for rate in rates):
            raise ValueError("Os preços precisam ser finitos e não negativos")


def calculate_metrics(
    traces: Iterable[Mapping[str, Any]],
    *,
    model_pricing: Mapping[str, ModelPricing] | None = None,
) -> dict[str, Any]:
    """Calculate turn, component, model, token, cost, and fallback metrics.

    p95 uses nearest rank: the value at ``ceil(0.95 * sample_count)``.
    Costs require an exact model rate and both token counts. An incomplete
    total is ``None``; its known subtotal and unpriced call count remain visible.
    Fallback rate requires an explicit boolean ``fallback_used`` on every trace.
    """
    pricing = model_pricing or {}
    trace_count = completed_traces = error_traces = 0
    turn_durations: list[float] = []
    completed_trace_cost_usd = 0.0
    completed_trace_unpriced_calls = 0
    components: dict[str, dict[str, Any]] = defaultdict(_new_group)
    models: dict[str, dict[str, Any]] = defaultdict(_new_model_group)
    span_count = error_spans = observed_fallbacks = fallback_signals = 0

    for trace in traces:
        trace_count += 1
        status = trace.get("status")
        completed_traces += status == "completed"
        error_traces += status == "error"
        duration = _number(trace.get("duration_ms"))

        spans = trace.get("spans")
        if not isinstance(spans, list):
            spans = []
        if duration is None:
            duration = _turn_duration(spans)
        if duration is not None:
            turn_durations.append(duration)

        trace_cost_usd = 0.0
        trace_unpriced_calls = 0

        fallback_used, has_signal = _fallback_signal(trace, spans)
        observed_fallbacks += fallback_used
        fallback_signals += has_signal

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

            if kind == "llm":
                model = _text(span.get("model"), "unknown")
                group = models[model]
                _record_call(group, span_status, span_duration)
                input_tokens = _token_count(span.get("input_tokens"))
                output_tokens = _token_count(span.get("output_tokens"))
                model_price = pricing.get(model)
                _record_tokens_and_cost(
                    group,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    pricing=model_price,
                )
                if model_price is None or input_tokens is None or output_tokens is None:
                    trace_unpriced_calls += 1
                else:
                    trace_cost_usd += (
                        input_tokens * model_price.input_usd_per_million_tokens
                        + output_tokens * model_price.output_usd_per_million_tokens
                    ) / _MILLION
            else:
                name = _text(span.get("name"), "unknown")
                key = f"{kind}:{name}"
                _record_call(components[key], span_status, span_duration)

        if status == "completed":
            completed_trace_cost_usd += trace_cost_usd
            completed_trace_unpriced_calls += trace_unpriced_calls

    component_results = {
        key: _group_result(group) for key, group in sorted(components.items())
    }
    model_results = {
        key: _model_result(key, group) for key, group in sorted(models.items())
    }
    token_metrics, cost_metrics = _token_and_cost_results(models)
    cost_metrics.update(
        {
            "completed_trace_count": completed_traces,
            "completed_trace_unpriced_calls": completed_trace_unpriced_calls,
            "cost_per_completed_trace_usd": (
                round(completed_trace_cost_usd / completed_traces, 8)
                if completed_traces > 0 and completed_trace_unpriced_calls == 0
                else None
            ),
        }
    )
    signal_coverage = _rate(fallback_signals, trace_count)

    return {
        "traces": {
            "count": trace_count,
            "completed_count": completed_traces,
            "error_count": error_traces,
            "error_rate": _rate(error_traces, trace_count),
            "latency": _distribution(turn_durations),
        },
        "spans": {
            "count": span_count,
            "error_count": error_spans,
            "error_rate": _rate(error_spans, span_count),
        },
        "tokens": token_metrics,
        "cost": cost_metrics,
        "fallback": {
            "observed_trace_count": observed_fallbacks,
            "trace_signal_count": fallback_signals,
            "signal_coverage": signal_coverage,
            "rate": (
                _rate(observed_fallbacks, trace_count)
                if trace_count > 0 and fallback_signals == trace_count
                else None
            ),
        },
        "components": component_results,
        "models": model_results,
    }


def calculate_slo_metrics(
    traces: Iterable[Mapping[str, Any]],
    *,
    window_started_at: datetime,
    window_ended_at: datetime,
    environment: str | None,
    latency_target_ms: float = 20_000,
) -> dict[str, Any]:
    """Calculate rolling-window service objectives from terminal traces/spans.

    Traces without a recorded duration count as bad latency observations so
    missing instrumentation cannot make the latency objective look healthier.
    Model success is calculated independently for each model.
    """
    terminal_trace_count = completed_traces = 0
    latency_good = latency_bad = 0
    durations: list[float] = []
    model_calls: dict[str, dict[str, int]] = defaultdict(lambda: {"good": 0, "bad": 0})

    for trace in traces:
        trace_status = trace.get("status")
        if trace_status not in {"completed", "error"}:
            continue

        terminal_trace_count += 1
        if trace_status == "completed":
            completed_traces += 1

        spans = trace.get("spans")
        if not isinstance(spans, list):
            spans = []
        duration = _number(trace.get("duration_ms"))
        if duration is None:
            duration = _turn_duration(spans)
        if duration is not None:
            durations.append(duration)
        if duration is not None and duration <= latency_target_ms:
            latency_good += 1
        else:
            latency_bad += 1

        for span in spans:
            if not isinstance(span, Mapping) or span.get("kind") != "llm":
                continue
            model = _text(span.get("model"), "unknown")
            group = model_calls[model]
            if span.get("status") == "completed":
                group["good"] += 1
            elif span.get("status") == "error":
                group["bad"] += 1

    completion = _slo_result(
        completed_traces,
        terminal_trace_count - completed_traces,
        target_rate=0.995,
    )
    latency = _slo_result(latency_good, latency_bad, target_rate=0.95)
    latency.update(
        {
            "p95_ms": _distribution(durations)["p95_ms"],
            "duration_sample_count": len(durations),
            "target_p95_ms": latency_target_ms,
        }
    )
    models = {
        model: {
            "model": model,
            **_slo_result(group["good"], group["bad"], target_rate=0.99),
        }
        for model, group in sorted(model_calls.items())
    }
    return {
        "window": {
            "started_at": window_started_at,
            "ended_at": window_ended_at,
            "duration_days": 28,
            "environment": environment,
        },
        "turn_completion": completion,
        "turn_latency": latency,
        "models": models,
    }


def calculate_application_cost(
    traces: Iterable[Mapping[str, Any]],
    usage_events: Iterable[Mapping[str, Any]],
    *,
    model_pricing: Mapping[str, ModelPricing],
    embedding_model: str,
    embedding_input_usd_per_million_tokens: float,
    embedding_tier: str,
) -> dict[str, Any]:
    """Aggregate estimated AI spend by source across every app environment."""
    embedding_pricing = ModelPricing(
        input_usd_per_million_tokens=embedding_input_usd_per_million_tokens,
        output_usd_per_million_tokens=0,
    )
    groups: dict[tuple[str, str], dict[str, Any]] = defaultdict(_new_usage_group)

    for trace in traces:
        spans = trace.get("spans")
        if not isinstance(spans, list):
            continue
        for span in spans:
            if not isinstance(span, Mapping) or span.get("kind") != "llm":
                continue
            model = _text(span.get("model"), "unknown")
            _record_usage_call(
                groups[("agent_turn", model)],
                status=span.get("status"),
                input_tokens=_token_count(span.get("input_tokens")),
                output_tokens=_token_count(span.get("output_tokens")),
                pricing=model_pricing.get(model),
            )

    for event in usage_events:
        source = event.get("source")
        if (
            not isinstance(source, str)
            or source not in USAGE_SOURCE_LABELS
            or source == "agent_turn"
        ):
            continue
        model = _text(event.get("model"), "unknown")
        is_embedding = "embedding" in source
        if is_embedding:
            pricing = embedding_pricing if model == embedding_model else None
        else:
            pricing = model_pricing.get(model)
        _record_usage_call(
            groups[(source, model)],
            status=event.get("status"),
            input_tokens=_token_count(event.get("input_tokens")),
            output_tokens=_token_count(event.get("output_tokens")),
            pricing=pricing,
        )

    origins: list[dict[str, Any]] = []
    priced_subtotal_usd = 0.0
    priced_calls = unpriced_calls = 0
    for (source, model), group in sorted(groups.items()):
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
    }


def _record_usage_call(
    group: dict[str, Any],
    *,
    status: object,
    input_tokens: int | None,
    output_tokens: int | None,
    pricing: ModelPricing | None,
) -> None:
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

    if pricing is None or input_tokens is None or output_tokens is None:
        group["unpriced_calls"] += 1
        return
    group["priced_subtotal_usd"] += (
        input_tokens * pricing.input_usd_per_million_tokens
        + output_tokens * pricing.output_usd_per_million_tokens
    ) / _MILLION
    group["priced_calls"] += 1


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
) -> None:
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

    if pricing is None or input_tokens is None or output_tokens is None:
        group["unpriced_calls"] += 1
        return

    group["priced_subtotal_usd"] += (
        input_tokens * pricing.input_usd_per_million_tokens
        + output_tokens * pricing.output_usd_per_million_tokens
    ) / _MILLION
    group["priced_calls"] += 1


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


def _fallback_signal(trace: Mapping[str, Any], spans: list[Any]) -> tuple[bool, bool]:
    marker = trace.get("fallback_used")
    observed = marker is True
    has_trace_signal = isinstance(marker, bool)
    for span in spans:
        if not isinstance(span, Mapping):
            continue
        attributes = span.get("attributes")
        if isinstance(attributes, Mapping) and attributes.get("fallback_used") is True:
            observed = True
    return observed, has_trace_signal


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
