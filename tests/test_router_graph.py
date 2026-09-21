from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage

from src.agents.router.executor import RouterExecutor
from src.graphs.adapters import run_router_node
from src.graphs.contracts import RouteDecision


class FakeRouterModel:
    def __init__(self, decision: RouteDecision) -> None:
        self.decision = decision

    def invoke(self, messages: list[Any]) -> RouteDecision:
        return self.decision


def _state(message: str) -> dict[str, Any]:
    return {"messages": [HumanMessage(content=message)], "status": "pending"}


def test_router_dispatches_only_to_active_faq_route() -> None:
    executor = RouterExecutor(
        model=FakeRouterModel(RouteDecision(route="faq", reason="Pergunta documental."))
    )

    result = run_router_node(
        _state("Qual é a regra documentada?"),
        router=executor,
    )

    assert result["routing_decision"] == {
        "route": "faq",
        "target_agent": "faq",
        "outcome": "dispatch",
        "reason": "Pergunta documental.",
    }


def test_router_keeps_clarification_as_controlled_route() -> None:
    executor = RouterExecutor(
        model=FakeRouterModel(
            RouteDecision(
                route="clarification_required",
                reason="Falta especificar a informação desejada.",
            )
        )
    )

    result = run_router_node(_state("Pode me ajudar?"), router=executor)

    assert result["routing_decision"]["outcome"] == "clarification_required"
    assert result["routing_decision"]["target_agent"] is None


def test_router_keeps_out_of_scope_as_controlled_route() -> None:
    executor = RouterExecutor(
        model=FakeRouterModel(
            RouteDecision(
                route="out_of_scope",
                reason="A solicitação não pertence à capacidade ativa.",
            )
        )
    )

    result = run_router_node(
        _state("Quais produtos devo promover?"),
        router=executor,
    )

    assert result["routing_decision"]["outcome"] == "out_of_scope"
    assert result["routing_decision"]["target_agent"] is None


def test_invalid_router_output_falls_back_to_clarification() -> None:
    class InvalidRouterModel:
        def invoke(self, messages: list[Any]) -> dict[str, str]:
            return {}

    executor = RouterExecutor(model=InvalidRouterModel())

    result = run_router_node(
        _state("Pode verificar isso?"),
        router=executor,
    )

    assert result["routing_decision"]["outcome"] == "clarification_required"


def test_router_can_call_summary_search_tool_from_authenticated_request_context() -> (
    None
):
    class FakeSummaryService:
        arguments: dict[str, str] | None = None

        def search_context(
            self,
            *,
            user_id: str,
            conversation_id: str,
            query: str,
        ) -> dict[str, Any]:
            self.arguments = {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "query": query,
            }
            return {"source": "fallback", "results": []}

    service = FakeSummaryService()
    captured: dict[str, Any] = {}

    class FakeToolCallingAgent:
        def invoke(self, agent_input: dict[str, Any]) -> dict[str, Any]:
            captured["agent_input"] = agent_input
            captured["tool_output"] = captured["tools"][0].invoke({})
            return {
                "structured_response": RouteDecision(
                    route="faq",
                    reason="A pergunta depende da conversa anterior.",
                )
            }

    def fake_agent_factory(**kwargs: Any) -> FakeToolCallingAgent:
        captured.update(kwargs)
        return FakeToolCallingAgent()

    executor = RouterExecutor(
        model=FakeRouterModel(
            RouteDecision(route="out_of_scope", reason="Fallback não usado.")
        ),
        summary_search_service=service,  # type: ignore[arg-type]
        tool_calling_model=object(),
        agent_factory=fake_agent_factory,
    )

    result = run_router_node(
        {
            "request": {
                "request_id": "request-1",
                "user_id": "authenticated-user",
                "conversation_id": "current-conversation",
                "sanitized_message": "O que combinamos antes?",
            },
            "messages": [HumanMessage(content="O que combinamos antes?")],
        },
        router=executor,
    )

    assert service.arguments == {
        "user_id": "authenticated-user",
        "conversation_id": "current-conversation",
        "query": "O que combinamos antes?",
    }
    assert captured["tools"][0].name == "search_conversation_summaries"
    assert captured["response_format"] is RouteDecision
    assert result["routing_decision"]["route"] == "faq"
