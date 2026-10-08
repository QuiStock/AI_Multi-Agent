from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

MAX_LAB_CONTENT_CHARACTERS = 100_000


class ObservabilityConversationMessageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(min_length=1)
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)
    created_at: AwareDatetime
    consulted_agents: list[str] | None = None


class ObservabilityConversationSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str = Field(min_length=1)
    title: str | None = None
    status: Literal["active", "ended"]
    started_at: AwareDatetime
    updated_at: AwareDatetime
    ended_at: AwareDatetime | None = None


class ObservabilityConversationListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversations: list[ObservabilityConversationSummaryResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)


class ObservabilityConversationDetailResponse(ObservabilityConversationSummaryResponse):
    messages: list[ObservabilityConversationMessageResponse]
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)
    has_more: bool
    next_offset: int | None = Field(default=None, ge=0)


class LabRunMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20_000)


class LabRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1, max_length=30_000)
    messages: list[LabRunMessage] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_content_budget(self) -> "LabRunRequest":
        if not self.prompt.strip():
            raise ValueError("prompt não pode estar vazio")
        total_characters = len(self.prompt) + sum(
            len(message.content) for message in self.messages
        )
        if total_characters > MAX_LAB_CONTENT_CHARACTERS:
            raise ValueError("O prompt e as mensagens excedem 100000 caracteres")
        if not any(message.role == "user" for message in self.messages):
            raise ValueError("messages precisa conter ao menos uma mensagem user")
        return self


class LabRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: str


class LabModelOptionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(min_length=1)
    label: str = Field(min_length=1)


class LabModelCatalogResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    models: list[LabModelOptionResponse]
    default_model_id: str = Field(min_length=1)


class LabAgentConfigResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    role: str = Field(min_length=1)
    version: str = Field(min_length=1)
    system_prompt: str = Field(min_length=1)


class TraceSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    trace_id: str
    conversation_id: str
    environment: str
    started_at: datetime
    status: str
    ended_at: datetime | None = None
    duration_ms: float | None = None


class TraceSpanResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    span_id: str
    parent_span_id: str | None = None
    name: str
    kind: str
    started_at: datetime
    status: str
    ended_at: datetime | None = None
    duration_ms: float | None = None
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    error_type: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class TraceLogResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    log_id: str = Field(min_length=1)
    timestamp: AwareDatetime
    level: Literal["INFO", "WARNING", "ERROR", "CRITICAL"]
    logger: str = Field(min_length=1)
    message: str = Field(min_length=1)
    span_id: str = Field(min_length=1)
    agent_id: str | None = None
    event: str | None = None
    error_type: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class TraceDetailResponse(TraceSummaryResponse):
    spans: list[TraceSpanResponse]
    logs: list[TraceLogResponse] = Field(default_factory=list)


class TraceListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    traces: list[TraceSummaryResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class LiveTraceEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=1)
    event_type: Literal["trace", "span", "log"]
    phase: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    timestamp: AwareDatetime
    data: dict[str, Any] = Field(default_factory=dict)


class LiveTraceActiveResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    environment: str = Field(min_length=1)
    started_at: AwareDatetime


class LiveTraceFeedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[LiveTraceEventResponse]
    active_traces: list[LiveTraceActiveResponse]
    next_cursor: int = Field(ge=0)
    has_more: bool
    reset_required: bool


class LatencyMetricsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_count: int = Field(ge=0)
    average_ms: float | None = None
    p95_ms: float | None = None
    max_ms: float | None = None


class TraceMetricsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    error_rate: float | None = None
    latency: LatencyMetricsResponse


class SpanMetricsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    error_rate: float | None = None


class TokenMetricsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    llm_calls: int = Field(ge=0)
    input_tokens: int | None = None
    output_tokens: int | None = None
    calls_with_complete_usage: int = Field(ge=0)
    calls_with_partial_usage: int = Field(ge=0)
    calls_without_usage: int = Field(ge=0)


class CostMetricsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: str
    estimated_total_usd: float | None = None
    priced_subtotal_usd: float = Field(ge=0)
    priced_calls: int = Field(ge=0)
    unpriced_calls: int = Field(ge=0)
    completed_trace_count: int = Field(ge=0)
    completed_trace_unpriced_calls: int = Field(ge=0)
    cost_per_completed_trace_usd: float | None = Field(default=None, ge=0)


class CostOriginResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    label: str
    model: str
    calls: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    calls_with_usage: int = Field(ge=0)
    calls_without_usage: int = Field(ge=0)
    priced_calls: int = Field(ge=0)
    unpriced_calls: int = Field(ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    priced_subtotal_usd: float = Field(ge=0)


class ApplicationCostMetricsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: str
    estimated_total_usd: float | None = Field(default=None, ge=0)
    priced_subtotal_usd: float = Field(ge=0)
    priced_calls: int = Field(ge=0)
    unpriced_calls: int = Field(ge=0)
    embedding_model: str
    embedding_tier: Literal["free", "paid"]
    embedding_input_usd_per_million_tokens: float = Field(ge=0)
    coverage_start_at: AwareDatetime | None = None
    coverage_complete: bool
    origins: list[CostOriginResponse]


class FallbackMetricsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_trace_count: int = Field(ge=0)
    trace_signal_count: int = Field(ge=0)
    signal_coverage: float | None = None
    rate: float | None = None


class ComponentMetricsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calls: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    error_rate: float | None = None
    latency: LatencyMetricsResponse


class ModelMetricsResponse(ComponentMetricsResponse):
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    calls_with_complete_usage: int = Field(ge=0)
    calls_with_partial_usage: int = Field(ge=0)
    calls_without_usage: int = Field(ge=0)
    estimated_cost_usd: float | None = None
    priced_subtotal_usd: float = Field(ge=0)
    priced_calls: int = Field(ge=0)
    unpriced_calls: int = Field(ge=0)


class SLOMetricResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_rate: float = Field(ge=0, le=1)
    actual_rate: float | None = Field(default=None, ge=0, le=1)
    good_count: int = Field(ge=0)
    bad_count: int = Field(ge=0)
    total_count: int = Field(ge=0)
    error_budget_consumed_pct: float | None = Field(default=None, ge=0)
    error_budget_remaining_pct: float | None = Field(default=None, ge=0, le=100)
    status: Literal["met", "breached", "no_data"]


class SLOLatencyResponse(SLOMetricResponse):
    p95_ms: float | None = Field(default=None, ge=0)
    duration_sample_count: int = Field(ge=0)
    target_p95_ms: float = Field(gt=0)


class SLOModelResponse(SLOMetricResponse):
    model: str = Field(min_length=1)


class SLOWindowResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    started_at: AwareDatetime
    ended_at: AwareDatetime
    duration_days: int = Field(ge=1)
    environment: str | None = None


class ObservabilitySLOResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window: SLOWindowResponse
    turn_completion: SLOMetricResponse
    turn_latency: SLOLatencyResponse
    models: dict[str, SLOModelResponse]


class ObservabilityMetricsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    traces: TraceMetricsResponse
    spans: SpanMetricsResponse
    tokens: TokenMetricsResponse
    cost: CostMetricsResponse
    application_cost: ApplicationCostMetricsResponse
    fallback: FallbackMetricsResponse
    components: dict[str, ComponentMetricsResponse]
    models: dict[str, ModelMetricsResponse]
    slos: ObservabilitySLOResponse
