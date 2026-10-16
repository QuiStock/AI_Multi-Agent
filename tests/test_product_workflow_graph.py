from __future__ import annotations

from functools import partial
from typing import Any

from langchain_core.messages import AnyMessage, HumanMessage

from src.graphs.adapters import run_product_workflow_node
from src.graphs.agent_graph import create_agent_graph
from src.graphs.state import GraphState, RoutingDecision


def _passed_input(_: GraphState) -> GraphState:
    return {
        "input_guardrail": {
            "status": "passed",
            "reason_code": "approved",
            "reason": "OK",
            "redactions": [],
        }
    }


class Router:
    def invoke(
        self, _: list[AnyMessage], *, request_context: dict[str, Any] | None = None
    ) -> RoutingDecision:
        return {
            "route": "product_workflow",
            "target_agent": "product_workflow",
            "outcome": "dispatch",
            "reason": "Consulta de produto",
        }


class FailedProductExecutor:
    def invoke(self, _: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "error",
            "answer": "Não consegui consultar os dados do produto agora.",
            "evidences": [],
        }


class NotFoundProductExecutor:
    def invoke(self, _: dict[str, Any]) -> dict[str, Any]:
        return {
            "answer": "Produto não encontrado; informe o SKU.",
            "evidences": [],
            "lookup_status": "not_found",
        }


class NoCall:
    def invoke(self, *_: Any, **__: Any) -> Any:
        raise AssertionError(
            "compiler/judge/output guardrail must not run on lookup error"
        )


def no_guardrail(_: GraphState) -> GraphState:
    raise AssertionError("output guardrail must not run on lookup error")


class EmptyContext:
    def restore_messages(self, *, email: str, conversation_id: str) -> list[AnyMessage]:
        return []


def test_lookup_error_uses_terminal_fallback_without_compiler_or_judge() -> None:
    graph = create_agent_graph(
        input_guardrail=_passed_input,
        router=Router(),
        capabilities={
            "product_workflow": partial(
                run_product_workflow_node, executor=FailedProductExecutor()
            )
        },
        judge=NoCall(),
        compiler=NoCall(),
        output_guardrail=no_guardrail,
        context_enricher=EmptyContext(),
    )
    result = graph.invoke(
        {
            "request": {
                "request_id": "req-1",
                "email": "user@example.test",
                "role_code": "EMPLOYEE",
                "conversation_id": "conv-1",
                "sanitized_message": "Consulte Leite",
            },
            "messages": [HumanMessage(content="Consulte Leite")],
        }
    )
    assert result["final_response"]["status"] == "error"
    assert result["final_response"]["content"] == (
        "Desculpe, não foi possível consultar essas informações agora. "
        "Tente novamente mais tarde."
    )
    assert "banco" not in result["final_response"]["content"].lower()
    assert "ferramenta" not in result["final_response"]["content"].lower()
    assert result["agent_results"]["product_workflow"]["answer"] == (
        "Não consegui consultar os dados do produto agora."
    )


def test_not_found_is_successful_lookup_and_direct_clarification() -> None:
    graph = create_agent_graph(
        input_guardrail=_passed_input,
        router=Router(),
        capabilities={
            "product_workflow": partial(
                run_product_workflow_node, executor=NotFoundProductExecutor()
            )
        },
        judge=NoCall(),
        compiler=NoCall(),
        output_guardrail=no_guardrail,
        context_enricher=EmptyContext(),
    )

    result = graph.invoke(
        {
            "request": {
                "request_id": "req-not-found",
                "email": "user@example.test",
                "role_code": "EMPLOYEE",
                "conversation_id": "conv-not-found",
                "sanitized_message": "Mostre o card de Arroz Branco 5kg",
            },
            "messages": [HumanMessage(content="Mostre o card de Arroz Branco 5kg")],
        }
    )

    assert result["agent_results"]["product_workflow"]["status"] == "success"
    assert result["final_response"]["status"] == "clarification_required"
    assert (
        result["final_response"]["content"] == "Produto não encontrado; informe o SKU."
    )
