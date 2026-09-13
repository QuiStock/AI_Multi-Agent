from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from src.graphs.agent_graph import (
    CLARIFICATION_RESPONSE,
    OUT_OF_SCOPE_RESPONSE,
    create_agent_graph,
    decide_after_input_guardrail,
    decide_after_router,
)
from src.guardrails.input_guardrail import CONTROLLED_INPUT_RESPONSE
from src.guardrails.output_guardrail import CONTROLLED_OUTPUT_RESPONSE


class FakeFaqAgent:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.received: list[Any] | None = None

    def invoke(self, state: dict[str, list[Any]]) -> dict[str, list[Any]]:
        self.received = state["messages"]
        return {"messages": [*state["messages"], AIMessage(content=self.answer)]}


def _passed_input(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "input_guardrail": {
            "status": "passed",
            "reason_code": "approved",
            "reason": "Aprovado.",
            "redactions": [],
            "sanitized_message": "pergunta sanitizada",
        }
    }


def _blocked_input(_: dict[str, Any]) -> dict[str, Any]:
    return {
        "input_guardrail": {
            "status": "blocked",
            "reason_code": "prompt_injection",
            "reason": "Bloqueado.",
            "redactions": [],
        }
    }


def _router(route: str, outcome: str) -> Any:
    def node(_: dict[str, Any]) -> dict[str, Any]:
        return {
            "routing_decision": {
                "route": route,
                "target_agent": "faq" if route == "faq" else None,
                "outcome": outcome,
                "reason": "Decisão de teste.",
            }
        }

    return node


def _passing_output(_: dict[str, Any]) -> dict[str, Any]:
    return {
        "output_guardrail": {
            "status": "passed",
            "reason_code": "approved",
            "reason": "Aprovado.",
            "violations": [],
        }
    }


def test_decision_functions_fail_closed() -> None:
    assert decide_after_input_guardrail({}) == "input_rejected"
    assert decide_after_router({}) == "out_of_scope"
    assert (
        decide_after_router(
            {"routing_decision": {"route": "faq", "outcome": "dispatch"}}
        )
        == "faq"
    )


def test_graph_dispatches_sanitized_input_to_faq_and_validates_output() -> None:
    faq = FakeFaqAgent("Resposta baseada na documentação.")
    graph = create_agent_graph(
        input_node=_passed_input,
        router=_router("faq", "dispatch"),
        faq_agent=faq,
        output_node=_passing_output,
    )

    result = graph.invoke({"messages": [HumanMessage(content="pergunta original")]})

    assert faq.received is not None
    assert faq.received[-1].content == "pergunta sanitizada"
    assert result["agent_outputs"] == [
        {"content": "Resposta baseada na documentação.", "status": "success"}
    ]
    assert result["final_response"]["status"] == "success"
    assert result["status"] == "completed"


def test_graph_returns_controlled_response_for_input_rejection() -> None:
    graph = create_agent_graph(
        input_node=_blocked_input,
        router=_router("faq", "dispatch"),
        faq_agent=FakeFaqAgent("não deve executar"),
        output_node=_passing_output,
    )

    result = graph.invoke({"messages": [HumanMessage(content="entrada bloqueada")]})

    assert result["final_response"] == {
        "content": CONTROLLED_INPUT_RESPONSE,
        "status": "rejected",
    }


def test_graph_handles_controlled_router_routes() -> None:
    for route, outcome, expected_content, expected_status in [
        (
            "clarification_required",
            "clarification_required",
            CLARIFICATION_RESPONSE,
            "clarification_required",
        ),
        ("out_of_scope", "out_of_scope", OUT_OF_SCOPE_RESPONSE, "out_of_scope"),
    ]:
        graph = create_agent_graph(
            input_node=_passed_input,
            router=_router(route, outcome),
            faq_agent=FakeFaqAgent("não deve executar"),
            output_node=_passing_output,
        )

        result = graph.invoke({"messages": [HumanMessage(content="pergunta")]})

        assert result["final_response"] == {
            "content": expected_content,
            "status": expected_status,
        }


def test_graph_replaces_a_blocked_output_with_controlled_response() -> None:
    def blocked_output(_: dict[str, Any]) -> dict[str, Any]:
        return {
            "output_guardrail": {
                "status": "blocked",
                "reason_code": "invalid_markdown",
                "reason": "Formato inválido.",
                "violations": ["invalid_markdown"],
            }
        }

    graph = create_agent_graph(
        input_node=_passed_input,
        router=_router("faq", "dispatch"),
        faq_agent=FakeFaqAgent("Resposta inválida"),
        output_node=blocked_output,
    )

    result = graph.invoke({"messages": [HumanMessage(content="pergunta")]})

    assert result["final_response"] == {
        "content": CONTROLLED_OUTPUT_RESPONSE,
        "status": "rejected",
    }
