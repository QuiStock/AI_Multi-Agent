from __future__ import annotations

import json
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.context.schemas import Route, RouteDecision
from src.graphs.faq_graph import create_faq_graph

pytestmark = pytest.mark.integration


class FakeRouterModel:
    def __init__(self, decision: RouteDecision) -> None:
        self.decision = decision

    def invoke(self, messages: list[Any]) -> RouteDecision:
        return self.decision


class FakeFAQAgent:
    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        evidence = {
            "resultados": [
                {
                    "arquivo": "manual.txt",
                    "conteudo": "Regra documentada.",
                    "relevancia": 0.92,
                },
                {"arquivo": "incompleto.txt"},
            ]
        }
        return {
            "messages": [
                *state["messages"],
                ToolMessage(
                    content=json.dumps(evidence),
                    tool_call_id="call-1",
                ),
                ToolMessage(content="conteudo invalido", tool_call_id="call-2"),
                AIMessage(content="A resposta veio da base documental."),
            ]
        }


class FailingFAQAgent:
    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("FAQ não deveria ser chamado")


def _state(message: str) -> dict[str, Any]:
    return {"messages": [HumanMessage(content=message)], "status": "pending"}


def test_faq_graph_dispatches_and_preserves_evidence() -> None:
    graph = create_faq_graph(
        router_model=FakeRouterModel(
            RouteDecision(route="faq", reason="Pergunta documental.")
        ),
        faq_agent=FakeFAQAgent(),
    )

    result = graph.invoke(_state("Qual é a regra documentada?"))

    assert result["response"] == {
        "content": "A resposta veio da base documental.",
        "status": "success",
    }
    assert result["evidence"] == [
        {
            "arquivo": "manual.txt",
            "conteudo": "Regra documentada.",
            "relevancia": 0.92,
        }
    ]


@pytest.mark.parametrize(
    ("route", "expected_status"),
    [
        ("clarification_required", "clarification_required"),
        ("out_of_scope", "out_of_scope"),
    ],
)
def test_graph_returns_controlled_response(route: Route, expected_status: str) -> None:
    graph = create_faq_graph(
        router_model=FakeRouterModel(
            RouteDecision(route=route, reason="Classificação controlada.")
        ),
        faq_agent=FailingFAQAgent(),
    )

    result = graph.invoke(_state("Solicitação controlada."))

    assert result["response"]["status"] == expected_status
    assert result["status"] == "completed"


def test_graph_rejects_empty_input_before_routing() -> None:
    graph = create_faq_graph(
        router_model=FailingFAQAgent(),
        faq_agent=FailingFAQAgent(),
    )

    result = graph.invoke({"messages": [], "status": "pending"})

    assert result["response"] == {
        "content": "Não foi possível processar essa mensagem.",
        "status": "rejected",
    }
