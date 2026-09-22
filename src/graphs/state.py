from __future__ import annotations

from typing import Annotated, Literal, NotRequired, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages

from src.memory.contracts import ConversationSummary

RouteName = Literal[
    "faq",
    "product_workflow",
    "clarification_required",
    "out_of_scope",
]

TurnStatus = Literal[
    "pending",
    "in_progress",
    "completed",
    "failed",
]


class RequestContext(TypedDict):
    request_id: str
    user_id: str
    conversation_id: str
    sanitized_message: NotRequired[str]
    is_new_conversation: NotRequired[bool]
    is_resuming_conversation: NotRequired[bool]
    trace_id: NotRequired[str]


class MemoryContext(TypedDict):
    previous_conversation_summaries: list[ConversationSummary]
    summary_context_loaded: NotRequired[bool]


class InputGuardrailResult(TypedDict):
    status: Literal["passed", "blocked"]
    reason_code: str
    reason: str
    redactions: list[str]
    sanitized_message: NotRequired[str]
    pii_map: NotRequired[dict[str, str]]


class OutputGuardrailResult(TypedDict):
    status: Literal["passed"]
    reason_code: str
    reason: str
    violations: list[str]


class RoutingDecision(TypedDict):
    route: RouteName
    target_agent: str | None
    outcome: Literal[
        "dispatch",
        "clarification_required",
        "out_of_scope",
    ]
    reason: str


class Evidence(TypedDict):
    evidence_id: str
    source_type: Literal["metric", "faq_document"]
    source_id: str
    content: str
    metadata: dict[str, str]


class AgentResult(TypedDict):
    error_code: NotRequired[str]


class FAQResult(AgentResult):
    status: Literal["success", "unavailable", "error"]
    answer: str
    citation_ids: list[str]


class ProductWorkFlowResult(AgentResult):
    status: Literal["success", "unavailable", "error"]
    answer: str
    evidence_ids: list[str]


class JudgeResult(AgentResult):
    status: Literal[
        "approved",
        "insufficient_evidence",
        "invalid",
    ]
    reason: str
    evidence_ids: list[str]


class AgentResults(TypedDict, total=False):
    faq: FAQResult
    product_workflow: ProductWorkFlowResult
    judge: JudgeResult


class ResponseDraft(TypedDict):
    content: str
    citations: list[str]
    status: Literal["draft", "blocked"]


class FinalResponse(TypedDict):
    content: str
    status: Literal[
        "success",
        "rejected",
        "clarification_required",
        "out_of_scope",
        "error",
    ]


class AgentError(TypedDict):
    agent: str
    code: str
    message: str
    retryable: bool


def merge_agent_results(
    current: AgentResults | None, update: AgentResults | None
) -> AgentResults:
    return {**(current or {}), **(update or {})}


def merge_evidence(
    current: list[Evidence] | None,
    update: list[Evidence] | None,
) -> list[Evidence]:
    merged = {item["evidence_id"]: item for item in (current or [])}

    for item in update or []:
        merged[item["evidence_id"]] = item

    return list(merged.values())


class GraphState(TypedDict, total=False):
    request: RequestContext

    pii_map: NotRequired[dict[str, str]]

    messages: Annotated[
        list[AnyMessage],
        add_messages,
    ]

    memory: NotRequired[MemoryContext | None]

    input_guardrail: InputGuardrailResult
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
    final_response: FinalResponse | None

    status: TurnStatus
    errors: list[AgentError]
