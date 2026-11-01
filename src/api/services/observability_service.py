from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from src import config
from src.memory.conversations.mongo_repository import MongoConversationRepository
from src.observability.metrics import (
    ModelPricing,
    calculate_application_cost,
    calculate_cost_projections,
    calculate_metrics,
    calculate_slo_metrics,
    calculate_span_cost,
    calculate_usage_event_cost,
)
from src.observability.traces.trace_repository import MongoTraceRepository, TraceStatus
from src.observability.usage.ai_usage_repository import MongoAIUsageRepository


class ObservabilityService:
    """Read conversations and traces and aggregate observability metrics."""

    def __init__(
        self,
        traces: MongoTraceRepository,
        conversations: MongoConversationRepository,
        ai_usage: MongoAIUsageRepository | None = None,
    ) -> None:
        self._traces = traces
        self._conversations = conversations
        self._ai_usage = ai_usage

    def list_conversations(  # noqa: PLR0913
        self,
        *,
        updated_from: datetime | None = None,
        updated_to: datetime | None = None,
        consumer_id: str | None = None,
        conversation_id: str | None = None,
        status: Literal["active", "ended"] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        conversations, total = self._conversations.list_observability_conversations(
            updated_from=updated_from,
            updated_to=updated_to,
            consumer_id=consumer_id,
            conversation_id=conversation_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        return {
            "conversations": conversations,
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def get_conversation(
        self,
        *,
        conversation_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any] | None:
        return self._conversations.get_observability_conversation(
            conversation_id=conversation_id,
            limit=limit,
            offset=offset,
        )

    def calculate_metrics(  # noqa: PLR0913
        self,
        *,
        started_from: datetime,
        started_to: datetime,
        conversation_id: str | None = None,
        consumer_id: str | None = None,
        environment: str | None = None,
        status: TraceStatus | None = None,
    ) -> dict[str, Any]:
        self._validate_period(started_from, started_to)
        conversation_ids = self._conversation_ids(consumer_id)
        traces = self._traces.iter_traces(
            started_from=started_from,
            started_to=started_to,
            conversation_id=conversation_id,
            conversation_ids=conversation_ids,
            environment=environment,
            status=status,
        )
        settings = config.get_settings()
        model_pricing = self._model_pricing(settings)
        # TypeSafe's Jev pricing is tied to its service/source, since its API
        # may return a concrete version even when configured with an alias.
        usage_source_pricing = {
            "judge_jev": ModelPricing(
                input_usd_per_million_tokens=0.042,
                output_usd_per_million_tokens=0,
            )
        }
        metrics_usage_events = (
            self._ai_usage.iter_usage(
                started_from=started_from,
                started_to=started_to,
            )
            if self._ai_usage is not None
            else ()
        )
        metrics = calculate_metrics(
            traces,
            model_pricing=model_pricing,
            usage_source_pricing=usage_source_pricing,
            usage_events=metrics_usage_events,
        )

        # Application spend intentionally covers the whole date range across
        # environments and does not inherit user, status, or Explorer filters.
        cost_traces = self._traces.iter_traces(
            started_from=started_from,
            started_to=started_to,
        )
        usage_events = (
            self._ai_usage.iter_usage(
                started_from=started_from,
                started_to=started_to,
            )
            if self._ai_usage is not None
            else ()
        )
        embedding_prices = {"free": 0.0, "paid": 0.20}
        application_cost = calculate_application_cost(
            cost_traces,
            usage_events,
            model_pricing=model_pricing,
            usage_source_pricing=usage_source_pricing,
            embedding_model=settings.gemini_embedding_model,
            embedding_input_usd_per_million_tokens=embedding_prices[
                settings.gemini_embedding_tier
            ],
            embedding_tier=settings.gemini_embedding_tier,
        )
        metering_started_at = (
            self._ai_usage.get_metering_started_at()
            if self._ai_usage is not None
            else None
        )
        coverage_complete = (
            metering_started_at is not None
            and started_from.astimezone(timezone.utc) >= metering_started_at
        )
        application_cost["coverage_start_at"] = metering_started_at
        application_cost["coverage_complete"] = coverage_complete
        if not coverage_complete:
            application_cost["estimated_total_usd"] = None
            application_cost["conversation_variable_cost_usd"] = None
            application_cost["operational_cost_usd"] = None
        metrics["application_cost"] = application_cost

        # Keep user-volume projections stable when the dashboard date/status
        # filters change. Use the latest 30 days with known usage coverage.
        projection_ended_at = self._utc_now()
        projection_window_started_at = projection_ended_at - timedelta(days=30)
        if metering_started_at is not None:
            projection_window_started_at = max(
                projection_window_started_at, metering_started_at
            )
        projection_window_started_at = min(
            projection_window_started_at, projection_ended_at
        )
        projection_days = round(
            max(
                0.0,
                min(
                    30.0,
                    (projection_ended_at - projection_window_started_at).total_seconds()
                    / 86_400,
                ),
            ),
            1,
        )
        projection_traces = self._traces.iter_traces(
            started_from=projection_window_started_at,
            started_to=projection_ended_at,
        )
        projection_usage_events = (
            self._ai_usage.iter_usage(
                started_from=projection_window_started_at,
                started_to=projection_ended_at,
            )
            if self._ai_usage is not None
            else ()
        )
        projection_cost = calculate_application_cost(
            projection_traces,
            projection_usage_events,
            model_pricing=model_pricing,
            usage_source_pricing=usage_source_pricing,
            embedding_model=settings.gemini_embedding_model,
            embedding_input_usd_per_million_tokens=embedding_prices[
                settings.gemini_embedding_tier
            ],
            embedding_tier=settings.gemini_embedding_tier,
        )
        if metering_started_at is None:
            projection_cost["conversation_variable_cost_usd"] = None
        projection_metrics = calculate_cost_projections(
            conversation_variable_cost_usd=projection_cost[
                "conversation_variable_cost_usd"
            ],
            conversation_count=projection_cost["conversation_count"],
            resolution_count=application_cost["resolution_count"],
        )
        selected_period_metrics = calculate_cost_projections(
            conversation_variable_cost_usd=application_cost[
                "conversation_variable_cost_usd"
            ],
            conversation_count=application_cost["conversation_count"],
            resolution_count=application_cost["resolution_count"],
        )
        metrics["board"].update(
            {
                "conversation_count": projection_cost["conversation_count"],
                "resolution_count": application_cost["resolution_count"],
                "cost_per_conversation_usd": projection_metrics[
                    "cost_per_conversation_usd"
                ],
                "cost_per_resolution_usd": selected_period_metrics[
                    "cost_per_resolution_usd"
                ],
                "projection_window_days": projection_days,
                "weekly_cost_100_users_usd": projection_metrics[
                    "weekly_cost_100_users_usd"
                ],
                "weekly_cost_1000_users_usd": projection_metrics[
                    "weekly_cost_1000_users_usd"
                ],
            }
        )

        slo_traces = self._traces.iter_traces(
            started_from=started_from,
            started_to=started_to,
            conversation_id=conversation_id,
            conversation_ids=conversation_ids,
            environment=environment,
        )
        slo_usage_events = (
            self._ai_usage.iter_usage(
                started_from=started_from,
                started_to=started_to,
            )
            if self._ai_usage is not None
            else ()
        )
        metrics["slos"] = calculate_slo_metrics(
            slo_traces,
            usage_events=slo_usage_events,
            window_started_at=started_from,
            window_ended_at=started_to,
            environment=environment,
        )
        metrics["board"]["slo_ok"] = metrics["slos"]["period_slo_ok"]
        return metrics

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    def list_traces(  # noqa: PLR0913
        self,
        *,
        started_from: datetime | None = None,
        started_to: datetime | None = None,
        conversation_id: str | None = None,
        consumer_id: str | None = None,
        environment: str | None = None,
        status: TraceStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        self._validate_period(started_from, started_to)
        conversation_ids = self._conversation_ids(consumer_id)
        return {
            "traces": self._traces.list_traces(
                started_from=started_from,
                started_to=started_to,
                conversation_id=conversation_id,
                conversation_ids=conversation_ids,
                environment=environment,
                status=status,
                limit=limit,
                offset=offset,
                include_spans=False,
            ),
            "total": self._traces.count_traces(
                started_from=started_from,
                started_to=started_to,
                conversation_id=conversation_id,
                conversation_ids=conversation_ids,
                environment=environment,
                status=status,
            ),
            "limit": limit,
            "offset": offset,
        }

    def get_trace(self, *, trace_id: str) -> dict[str, Any] | None:
        trace = self._traces.get_trace(trace_id)
        if trace is None:
            return None

        settings = config.get_settings()
        model_pricing = self._model_pricing(settings)
        usage_source_pricing = {
            "judge_jev": ModelPricing(
                input_usd_per_million_tokens=0.042,
                output_usd_per_million_tokens=0,
            )
        }
        spans = trace.get("spans")
        has_jev_span = False
        if isinstance(spans, list):
            for span in spans:
                if not isinstance(span, dict):
                    continue
                attributes = span.get("attributes")
                if (
                    isinstance(attributes, Mapping)
                    and attributes.get("usage_source") == "judge_jev"
                ):
                    has_jev_span = True
                estimated_cost = calculate_span_cost(
                    span,
                    model_pricing,
                    usage_source_pricing,
                )
                if estimated_cost is not None:
                    span["estimated_cost_usd"] = estimated_cost
        usage_events = (
            self._ai_usage.iter_trace_usage(trace_id)
            if self._ai_usage is not None and not has_jev_span
            else ()
        )
        trace["usage_events"] = []
        for event in usage_events:
            if event.get("source") != "judge_jev":
                continue
            event.pop("_id", None)
            event.pop("trace_id", None)
            event_cost = calculate_usage_event_cost(
                event,
                model_pricing=model_pricing,
                usage_source_pricing=usage_source_pricing,
            )
            if event_cost is not None:
                event["estimated_cost_usd"] = event_cost
            trace["usage_events"].append(event)
        return trace

    @staticmethod
    def _model_pricing(settings: Any) -> dict[str, ModelPricing]:
        model_pricing: dict[str, ModelPricing] = {}
        if config.OPENAI_MODEL == "gpt-6-luna":
            # Standard API rates verified 2026-10-08; input is priced as uncached.
            model_pricing[config.OPENAI_MODEL] = ModelPricing(
                input_usd_per_million_tokens=0.10,
                output_usd_per_million_tokens=0.50,
            )
        if settings.groq_chat_model == "qwen/qwen3.8-27b":
            # Groq's published rate for this exact model ID, verified 2026-11-01.
            model_pricing[settings.groq_chat_model] = ModelPricing(
                input_usd_per_million_tokens=0.80,
                output_usd_per_million_tokens=4.00,
            )
        return model_pricing

    def _conversation_ids(self, consumer_id: str | None) -> list[str] | None:
        if consumer_id is None:
            return None
        if not consumer_id.strip():
            raise ValueError("consumer_id não pode estar vazio")
        return self._conversations.list_conversation_ids_for_email(
            email=consumer_id,
        )

    @staticmethod
    def _validate_period(
        started_from: datetime | None,
        started_to: datetime | None,
    ) -> None:
        for name, value in (
            ("started_from", started_from),
            ("started_to", started_to),
        ):
            if value is not None and (
                value.tzinfo is None or value.utcoffset() is None
            ):
                raise ValueError(f"{name} precisa incluir timezone")
        if (
            started_from is not None
            and started_to is not None
            and started_from > started_to
        ):
            raise ValueError("started_from não pode ser posterior a started_to")
