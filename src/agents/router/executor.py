from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from langchain_core.messages import AnyMessage, SystemMessage

from src.agents.factory import create_agent_from_card
from src.agents.router.card import ROUTER_CARD
from src.agents.router.tools.search_conversation_summaries import (
    SummarySearchService,
    SummarySearchToolContext,
    build_search_conversation_summaries_tool,
)
from src.graphs.contracts import RouteDecision
from src.graphs.state import RoutingDecision
from src.llm_factory import get_structured_model, llm


class RouterExecutor:
    def __init__(
        self,
        model: Any | None = None,
        *,
        summary_search_service: SummarySearchService | None = None,
        tool_calling_model: Any | None = None,
        agent_factory: Any = create_agent_from_card,
    ) -> None:
        self.card = ROUTER_CARD
        self.model = get_structured_model(RouteDecision) if model is None else model
        self.summary_search_service = summary_search_service
        self.tool_calling_model = (
            llm if tool_calling_model is None else tool_calling_model
        )
        self.agent_factory = agent_factory

    @staticmethod
    def _normalize_decision(
        decision: RouteDecision,
    ) -> RoutingDecision:
        if decision.route == "faq":
            return {
                "route": "faq",
                "target_agent": "faq",
                "outcome": "dispatch",
                "reason": decision.reason,
            }
        if decision.route == "clarification_required":
            return {
                "route": "clarification_required",
                "target_agent": None,
                "outcome": "clarification_required",
                "reason": decision.reason,
            }
        return {
            "route": "out_of_scope",
            "target_agent": None,
            "outcome": "out_of_scope",
            "reason": decision.reason,
        }

    def invoke(
        self,
        messages: Sequence[AnyMessage],
        *,
        request_context: Mapping[str, Any] | None = None,
    ) -> RoutingDecision:
        try:
            tool_context = self._tool_context(request_context)
            if self.summary_search_service is not None and tool_context is not None:
                tool = build_search_conversation_summaries_tool(
                    service=self.summary_search_service,
                    context=SummarySearchToolContext(
                        user_id=tool_context["user_id"],
                        conversation_id=tool_context["conversation_id"],
                        query=tool_context["query"],
                        request_id=tool_context["request_id"],
                        trace_id=tool_context["trace_id"],
                    ),
                )
                agent = self.agent_factory(
                    card=self.card,
                    model=self.tool_calling_model,
                    tools=[tool],
                    response_format=RouteDecision,
                )
                agent_result = agent.invoke({"messages": list(messages)})
                decision = agent_result.get("structured_response")
            else:
                decision = self.model.invoke(
                    [
                        SystemMessage(content=self.card.system_prompt_template),
                        *messages,
                    ]
                )

            if not isinstance(decision, RouteDecision):
                decision = RouteDecision.model_validate(decision)

        except Exception:
            decision = RouteDecision(
                route="clarification_required",
                reason=("Não foi possível classificar a solicitação com segurança."),
            )
        return self._normalize_decision(decision)

    @staticmethod
    def _tool_context(
        request_context: Mapping[str, Any] | None,
    ) -> dict[str, str] | None:
        if request_context is None:
            return None
        user_id = request_context.get("user_id")
        conversation_id = request_context.get("conversation_id")
        request_id = request_context.get("request_id")
        query = request_context.get("sanitized_message")
        if not isinstance(user_id, str) or not user_id.strip():
            return None
        if not isinstance(conversation_id, str) or not conversation_id.strip():
            return None
        if not isinstance(request_id, str) or not request_id.strip():
            return None
        if not isinstance(query, str) or not query.strip():
            return None
        trace_id = request_context.get("trace_id")
        resolved_trace_id = (
            trace_id.strip()
            if isinstance(trace_id, str) and trace_id.strip()
            else request_id
        )
        return {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "request_id": request_id,
            "query": query,
            "trace_id": resolved_trace_id,
        }
