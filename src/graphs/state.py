from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, NotRequired, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages

from src.agents.product_workflow.contracts import SuggestionLookupStatus
from src.agents.schemas.tool_result import JsonScalar, ToolNextStep
from src.graphs.contracts import RouterRoute

RouteName = RouterRoute
TurnStatus = Literal[
    "pending",
    "in_progress",
    "completed",
    "failed",
]


class RequestContext(TypedDict):
    request_id: str
    email: str
    role_code: str
    user_id: NotRequired[int]
    store_ids: NotRequired[list[int]]
    role_id: NotRequired[int]
    conversation_id: str
    sent_at: datetime
    is_new_conversation: NotRequired[bool]
    is_resuming_conversation: NotRequired[bool]
    pii_redacted_before_graph: NotRequired[bool]
    original_message_length: NotRequired[int]
    trace_id: NotRequired[str]
    product_card: NotRequired[dict[str, object] | None]


class GreetingClassification(TypedDict):
    """Classification produced by the greeting gate before the router."""

    category: Literal["greeting_only", "normal_request"]


class InputGuardrailResult(TypedDict):
    status: Literal["passed", "blocked"]
    reason_code: str
    reason: str
    redactions: list[str]


class OutputGuardrailResult(TypedDict):
    status: Literal["passed"]
    reason_code: str
    reason: str
    violations: list[str]


class RoutingDecision(TypedDict):
    route: RouteName
    outcome: Literal[
        "dispatch",
        "clarification_required",
        "out_of_scope",
        "direct_response",
    ]
    reason: str
    status: NotRequired[Literal["success", "error"]]


class Evidence(TypedDict):
    evidence_id: str
    source_type: Literal[
        "metric",
        "faq_document",
        "product_workflow",
        "client_card_snapshot",
        "conversation_summary",
    ]
    source_id: str
    content: str
    metadata: dict[str, JsonScalar]


class FAQResult(TypedDict):
    status: Literal["success", "unavailable", "error"]
    answer: str
    next_step: NotRequired[ToolNextStep]


class ProductWorkFlowResult(TypedDict):
    status: Literal["success", "unavailable", "error"]
    answer: str
    evidence_ids: list[str]
    lookup_status: NotRequired[SuggestionLookupStatus]
    error_code: NotRequired[str]


class JudgeFeedback(TypedDict):
    status: Literal[
        "approved",
        "insufficient_evidence",
        "invalid",
    ]
    reason: str
    evidence_count: int
    reason_code: NotRequired[str]
    noul_probability: NotRequired[float]
    model: NotRequired[str]
    input_tokens: NotRequired[int | None]
    output_tokens: NotRequired[int | None]


class JudgeState(JudgeFeedback):
    repair_attempts: int
    judge_feedback: NotRequired[JudgeFeedback]


class AgentResults(TypedDict, total=False):
    faq: FAQResult
    product_workflow: ProductWorkFlowResult


FinalResponseStatus = Literal[
    "success",
    "rejected",
    "clarification_required",
    "out_of_scope",
    "error",
]


class ResponseDraft(TypedDict):
    content: str
    citations: list[str]
    status: Literal["draft", "blocked"]
    origin: NotRequired[Literal["exact"]]
    public_status: NotRequired[FinalResponseStatus]


class FinalResponse(TypedDict):
    content: str
    status: FinalResponseStatus


class AgentError(TypedDict):
    agent: str
    source: Literal["model", "tool", "executor", "validation"]
    code: str
    message: str
    retryable: bool


def merge_errors(
    current: list[AgentError] | None,
    update: list[AgentError] | None,
) -> list[AgentError]:
    # An explicit empty update starts a clean error list for a new turn.
    if update == []:
        return []
    return [*(current or []), *(update or [])]


def merge_agent_results(
    current: AgentResults | None, update: AgentResults | None
) -> AgentResults:
    return {**(current or {}), **(update or {})}


def merge_evidence(
    current: list[Evidence] | None,
    update: list[Evidence] | None,
) -> list[Evidence]:
    retained = list(current or [])
    incoming = list(update or [])
    if any(item["source_type"] == "product_workflow" for item in incoming):
        retained = [
            item for item in retained if item["source_type"] != "product_workflow"
        ]
    merged = {item["evidence_id"]: item for item in retained}

    for item in incoming:
        merged[item["evidence_id"]] = item

    return list(merged.values())


class GraphState(TypedDict, total=False):
    request: RequestContext

    messages: Annotated[
        list[AnyMessage],
        add_messages,
    ]

    input_guardrail: InputGuardrailResult
    greeting_classification: GreetingClassification
    output_guardrail: OutputGuardrailResult
    routing_decision: RoutingDecision

    agent_results: Annotated[
        AgentResults,
        merge_agent_results,
    ]

    evidences: Annotated[
        list[Evidence],
        merge_evidence,
    ]

    response_draft: ResponseDraft | None
    judge: JudgeState | None
    final_response: FinalResponse | None

    status: TurnStatus
    errors: Annotated[
        list[AgentError],
        merge_errors,
    ]
