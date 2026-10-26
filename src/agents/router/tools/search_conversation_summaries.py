"""Build a user-scoped semantic conversation-memory tool for agents."""

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from typing import Any, Protocol
from uuid import uuid4

from langchain_core.messages import AnyMessage, HumanMessage
from langchain_core.tools import BaseTool, StructuredTool

from src.agents.router.tools.schemas import (
    SearchConversationSummariesArguments,
    SearchConversationSummariesData,
)
from src.agents.schemas.tool_result import ToolEvidence
from src.agents.tooling.result_adapter import serialize_for_agent
from src.agents.tooling.result_factory import (
    ToolResultExtras,
    compose_success,
    create_tool_error,
    create_tool_metadata,
    tool_error,
)
from src.memory.contracts import SummaryContextSelection


class SummarySearchService(Protocol):
    def search_context(
        self,
        *,
        email: str,
        conversation_id: str,
        query: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> SummaryContextSelection: ...


@dataclass(frozen=True, slots=True)
class SummarySearchToolContext:
    """Authenticated and sanitized request data bound to one agent tool."""

    email: str
    conversation_id: str
    query: str
    request_id: str
    trace_id: str | None = None


def resolve_summary_tool_context(
    messages: Sequence[AnyMessage], request_context: Mapping[str, Any] | None
) -> SummarySearchToolContext | None:
    """Bind the last sanitized user message to authenticated request identity."""
    if request_context is None:
        return None
    email = request_context.get("email")
    conversation_id = request_context.get("conversation_id")
    request_id = request_context.get("request_id")
    query = next(
        (
            message.content
            for message in reversed(messages)
            if isinstance(message, HumanMessage)
            and isinstance(message.content, str)
            and message.content.strip()
        ),
        None,
    )
    if (
        not isinstance(email, str)
        or not email.strip()
        or not isinstance(conversation_id, str)
        or not conversation_id.strip()
        or not isinstance(request_id, str)
        or not request_id.strip()
        or not isinstance(query, str)
        or not query.strip()
    ):
        return None
    trace_id = request_context.get("trace_id")
    return SummarySearchToolContext(
        email=email,
        conversation_id=conversation_id,
        query=query,
        request_id=request_id,
        trace_id=trace_id if isinstance(trace_id, str) else None,
    )


def _summary_evidence(
    item: Mapping[str, Any],
    *,
    source: str,
) -> ToolEvidence:
    return ToolEvidence(
        evidence_id=(
            "conversation-summary:"
            + sha256(str(item["conversation_id"]).encode()).hexdigest()[:20]
        ),
        source_type="conversation_summary",
        source_id=str(item["conversation_id"]),
        content=str(item["summary"]),
        metadata={
            "updated_at": item["updated_at"],
            "provenance": "prior_conversation",
            "retrieval_source": source,
            "status": source,
        },
    )


def _not_found_memory_evidence(context: SummarySearchToolContext) -> ToolEvidence:
    digest = sha256(context.request_id.encode()).hexdigest()[:20]
    return ToolEvidence(
        evidence_id=f"conversation-summary-search:{digest}:no-results",
        source_type="conversation_summary",
        source_id=context.conversation_id,
        content=(
            "A busca de conversas anteriores foi concluída sem encontrar "
            "uma referência correspondente."
        ),
        metadata={
            "outcome": "not_found",
            "status": "not_found",
            "retrieval_source": "none",
            "provenance": "prior_conversation",
            "source": "memory_search",
        },
    )


def build_search_conversation_summaries_tool(
    *,
    service: SummarySearchService,
    context: SummarySearchToolContext,
    call_id_factory: Callable[[], str] | None = None,
    on_result: Callable[[dict[str, Any]], None] | None = None,
) -> BaseTool:
    """Bind authenticated request context outside the model-visible arguments."""
    if (
        not context.email.strip()
        or not context.conversation_id.strip()
        or not context.query.strip()
    ):
        raise ValueError("email, conversation_id e query são obrigatórios")
    if not context.request_id.strip():
        raise ValueError("request_id é obrigatório")

    get_call_id = call_id_factory or (lambda: str(uuid4()))
    effective_trace_id = (
        context.trace_id.strip()
        if context.trace_id and context.trace_id.strip()
        else context.request_id
    )
    cached_outputs: dict[tuple[date | None, date | None], str] = {}

    def search(
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> str:
        cache_key = (start_date, end_date)
        if cache_key in cached_outputs:
            return cached_outputs[cache_key]
        metadata = create_tool_metadata(
            tool_name="search_conversation_summaries",
            tool_version="1.0.0",
            tool_call_id=get_call_id(),
            trace_id=effective_trace_id,
        )
        try:
            selection = service.search_context(
                email=context.email,
                conversation_id=context.conversation_id,
                query=context.query,
                start_date=start_date,
                end_date=end_date,
            )
            data = SearchConversationSummariesData.model_validate(
                {
                    "results": [
                        {
                            "summary": item["summary"],
                            "updated_at": item["updated_at"],
                        }
                        for item in selection["results"]
                    ]
                }
            )
            evidence: tuple[ToolEvidence, ...]
            if selection["source"] == "none" or not selection["results"]:
                evidence = (_not_found_memory_evidence(context),)
            else:
                evidence = tuple(
                    _summary_evidence(item, source=selection["source"])
                    for item in selection["results"]
                )
            result = compose_success(
                data=data,
                meta=metadata,
                extras=ToolResultExtras(evidence=evidence),
            )
            output = serialize_for_agent(result)
            if on_result is not None:
                on_result(json.loads(output))
            cached_outputs[cache_key] = output
            return output
        except Exception:
            error_result = tool_error(
                error=create_tool_error(
                    code="MEMORY_SEARCH_UNAVAILABLE",
                    category="dependency",
                    message="A busca de contexto anterior não está disponível.",
                    retryable=True,
                ),
                meta=metadata,
            )
            output = serialize_for_agent(error_result)
            if on_result is not None:
                on_result(json.loads(output))
            cached_outputs[cache_key] = output
            return output

    return StructuredTool.from_function(
        func=search,
        name="search_conversation_summaries",
        description=(
            "Busca até três resumos de conversas encerradas do usuário autenticado "
            "que sejam próximos da mensagem atual. Aceita opcionalmente start_date "
            "e end_date inclusivos no formato YYYY-MM-DD; mensagem e identidade "
            "vêm da requisição atual."
        ),
        args_schema=SearchConversationSummariesArguments,
    )
