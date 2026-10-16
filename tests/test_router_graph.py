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


class CapturingRouterModel(FakeRouterModel):
    def __init__(self, decision: RouteDecision) -> None:
        super().__init__(decision)
        self.messages: list[Any] = []

    def invoke(self, messages: list[Any]) -> RouteDecision:
        self.messages = messages
        return super().invoke(messages)


def _state(message: str) -> dict[str, Any]:
    return {"messages": [HumanMessage(content=message)], "status": "pending"}


def _state_with_product_card(message: str) -> dict[str, Any]:
    return {
        "request": {
            "product_card": {
                "product_id": 42,
                "product_name": "Leite Integral",
                "category_name": "Mercearia",
                "sku": "SKU-1",
                "reference_sale_price": "12.50",
            }
        },
        "messages": [HumanMessage(content=message)],
        "status": "pending",
    }


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
    assert "memory" not in result


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


def test_router_exposes_only_safe_product_identity_to_model() -> None:
    model = CapturingRouterModel(
        RouteDecision(
            route="product_workflow",
            reason="A pergunta se refere ao produto apresentado no card.",
        )
    )
    executor = RouterExecutor(model=model)

    result = run_router_node(
        _state_with_product_card("Me explique este produto."),
        router=executor,
    )

    assert result["routing_decision"]["route"] == "product_workflow"
    context_messages = [
        str(message.content)
        for message in model.messages
        if isinstance(message, HumanMessage)
        and "Contexto estruturado de roteamento" in str(message.content)
    ]
    assert len(context_messages) == 1
    context = context_messages[0]
    assert "Leite Integral" in context
    assert "SKU-1" in context
    assert "Mercearia" in context
    assert "product_id" not in context
    assert "reference_sale_price" not in context


def test_router_preserves_faq_for_general_policy_with_product_card() -> None:
    model = CapturingRouterModel(
        RouteDecision(route="faq", reason="A pergunta é uma política geral.")
    )
    executor = RouterExecutor(model=model)

    result = run_router_node(
        _state_with_product_card("Qual é a política de promoções do aplicativo?"),
        router=executor,
    )

    assert result["routing_decision"]["route"] == "faq"


def test_router_requires_clarification_for_product_reference_without_card() -> None:
    model = CapturingRouterModel(
        RouteDecision(
            route="clarification_required",
            reason="Não há um produto identificado para a consulta.",
        )
    )
    executor = RouterExecutor(model=model)

    result = run_router_node(
        _state("Me explique este produto."),
        router=executor,
    )

    assert result["routing_decision"]["outcome"] == "clarification_required"
    assert not any(
        "Contexto estruturado de roteamento" in str(message.content)
        for message in model.messages
        if isinstance(message, HumanMessage)
    )


def test_router_keeps_ambiguous_card_question_in_clarification() -> None:
    model = CapturingRouterModel(
        RouteDecision(
            route="clarification_required",
            reason="A pergunta não identifica a informação desejada.",
        )
    )
    executor = RouterExecutor(model=model)

    result = run_router_node(
        _state_with_product_card("Pode me ajudar?"),
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
            email: str,
            conversation_id: str,
            query: str,
        ) -> dict[str, Any]:
            self.arguments = {
                "email": email,
                "conversation_id": conversation_id,
                "query": query,
            }
            return {"source": "none", "results": []}

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
                "email": "authenticated-user",
                "conversation_id": "current-conversation",
            },
            "messages": [HumanMessage(content="O que combinamos antes?")],
        },
        router=executor,
    )

    assert service.arguments == {
        "email": "authenticated-user",
        "conversation_id": "current-conversation",
        "query": "O que combinamos antes?",
    }
    assert captured["tools"][0].name == "search_conversation_summaries"
    assert captured["response_format"] is RouteDecision
    assert result["routing_decision"]["route"] == "faq"
    assert "memory" not in result


def test_router_pure_recall_captures_memory_and_answers_without_specialist() -> None:
    class FakeSummaryService:
        def search_context(self, **_: str) -> dict[str, Any]:
            return {
                "source": "temporal",
                "results": [
                    {
                        "conversation_id": "past-1",
                        "title": "Leite integral",
                        "summary": "Conversamos sobre leite integral.",
                        "updated_at": "2026-10-13T12:00:00+00:00",
                    }
                ],
            }

    class FakeToolCallingAgent:
        def __init__(self, tool: Any) -> None:
            self.tool = tool

        def invoke(self, _: dict[str, Any]) -> dict[str, Any]:
            self.tool.invoke({})
            return {
                "structured_response": RouteDecision(
                    route="clarification_required",
                    reason="A pessoa quer relembrar a conversa.",
                    memory_action="pure_recall",
                )
            }

    executor = RouterExecutor(
        summary_search_service=FakeSummaryService(),  # type: ignore[arg-type]
        tool_calling_model=object(),
        agent_factory=lambda **kwargs: FakeToolCallingAgent(kwargs["tools"][0]),
    )
    result = run_router_node(
        {
            "request": {
                "request_id": "request-1",
                "email": "authenticated-user",
                "conversation_id": "current-conversation",
            },
            "messages": [HumanMessage(content="O que falamos ontem?")],
            "pii_map": {},
        },
        router=executor,
    )

    assert result["memory_retrieval"]["source"] == "temporal"
    assert result["routing_decision"]["outcome"] == "direct_response"
    assert result["routing_decision"]["target_agent"] is None
    assert result["router_answered"] is True
    assert result["final_response"]["status"] == "success"
    assert "Leite integral" in result["final_response"]["content"]
