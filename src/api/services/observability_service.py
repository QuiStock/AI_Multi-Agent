from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from src import config
from src.memory.mongo_repository import MongoConversationRepository
from src.observability.ai_usage_repository import MongoAIUsageRepository
from src.observability.metrics import (
    ModelPricing,
    calculate_application_cost,
    calculate_metrics,
    calculate_slo_metrics,
)
from src.observability.trace_repository import MongoTraceRepository, TraceStatus


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
        model_pricing: dict[str, ModelPricing] = {}
        if config.OPENAI_MODEL == "gpt-6-luna":
            # Standard API rates verified 2026-10-08; input is priced as uncached.
            model_pricing[config.OPENAI_MODEL] = ModelPricing(
                input_usd_per_million_tokens=0.10,
                output_usd_per_million_tokens=0.50,
            )
        metrics = calculate_metrics(traces, model_pricing=model_pricing)

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
        settings = config.get_settings()
        embedding_prices = {"free": 0.0, "paid": 0.20}
        application_cost = calculate_application_cost(
            cost_traces,
            usage_events,
            model_pricing=model_pricing,
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
        metrics["application_cost"] = application_cost

        slo_window_ended_at = datetime.now(timezone.utc)
        slo_window_started_at = slo_window_ended_at - timedelta(days=28)
        slo_traces = self._traces.iter_traces(
            started_from=slo_window_started_at,
            started_to=slo_window_ended_at,
            environment=environment,
        )
        metrics["slos"] = calculate_slo_metrics(
            slo_traces,
            window_started_at=slo_window_started_at,
            window_ended_at=slo_window_ended_at,
            environment=environment,
        )
        return metrics

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
        return self._traces.get_trace(trace_id)

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
