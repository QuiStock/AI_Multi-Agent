from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage

from src.graphs.agent_graph import create_agent_graph
from src.graphs.decisions import decide_after_input_guardrail, decide_after_router


def _passed_input(_: dict[str, Any]) -> dict[str, Any]:
    return {
        "input_guardrail": {
            "status": "passed",
            "reason_code": "approved",
            "reason": "Aprovado.",
            "redactions": [],
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


def _faq(_: dict[str, Any]) -> dict[str, Any]:
    return {
        "agent_results": {
            "faq": {
                "status": "success",
                "answer": "Resposta baseada na documentação.",
                "citation_ids": ["faq-1"],
            }
        },
        "evidences": [
            {
                "evidence_id": "faq-1",
                "source_type": "faq_document",
                "source_id": "manual.md",
                "content": "Resposta baseada na documentação.",
                "metadata": {},
            }
        ],
    }


class FakeJudge:
    def __init__(self, status: str = "approved") -> None:
        self.status = status

    def invoke(self, _: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": "Resultado controlado.",
            "evidence_ids": ["faq-1"] if self.status == "approved" else [],
        }


class FakeCompiler:
    def invoke(self, _: dict[str, Any]) -> dict[str, Any]:
        return {
            "response_draft": {
                "content": "Resposta compilada.",
                "citations": ["faq-1"],
                "status": "draft",
            }
        }


def _passing_output(_: dict[str, Any]) -> dict[str, Any]:
    return {
        "output_guardrail": {
            "status": "passed",
            "reason_code": "approved",
            "reason": "Aprovado.",
            "violations": [],
        }
    }


def _graph(judge_status: str = "approved") -> Any:
    return create_agent_graph(
        input_guardrail=_passed_input,
        router=_router("faq", "dispatch"),
        capabilities={"faq": _faq},
        judge=FakeJudge(judge_status),
        compiler=FakeCompiler(),
        output_guardrail=_passing_output,
    )


def test_decision_functions_fail_closed() -> None:
    assert decide_after_input_guardrail({}) == "input_rejected"
    assert decide_after_router({}, active_routes={"faq"}) == "out_of_scope"
    assert (
        decide_after_router(
            {"routing_decision": {"route": "faq", "outcome": "dispatch"}},
            active_routes={"faq"},
        )
        == "faq"
    )


def test_graph_dispatches_to_faq_judge_and_compiler() -> None:
    result = _graph().invoke({"messages": [HumanMessage(content="pergunta original")]})

    assert result["agent_results"]["faq"]["status"] == "success"
    assert result["agent_results"]["judge"]["status"] == "approved"
    assert result["response_draft"]["content"] == "Resposta compilada."
    assert result["output_guardrail"]["status"] == "passed"
    assert result["status"] == "completed"


def test_graph_returns_controlled_response_for_input_rejection() -> None:
    graph = create_agent_graph(
        input_guardrail=_blocked_input,
        router=_router("faq", "dispatch"),
        capabilities={"faq": _faq},
        judge=FakeJudge(),
        compiler=FakeCompiler(),
        output_guardrail=_passing_output,
    )

    result = graph.invoke({"messages": [HumanMessage(content="bloqueada")]})

    assert result["final_response"] == {
        "content": "A entrada não pôde ser processada.",
        "status": "rejected",
    }


def test_graph_handles_clarification_and_out_of_scope_routes() -> None:
    for route, outcome, expected_content, expected_status in [
        (
            "clarification_required",
            "clarification_required",
            "Preciso de mais detalhes para continuar.",
            "clarification_required",
        ),
        (
            "out_of_scope",
            "out_of_scope",
            "Essa solicitação está fora do escopo atual.",
            "out_of_scope",
        ),
    ]:
        graph = create_agent_graph(
            input_guardrail=_passed_input,
            router=_router(route, outcome),
            capabilities={"faq": _faq},
            judge=FakeJudge(),
            compiler=FakeCompiler(),
            output_guardrail=_passing_output,
        )

        result = graph.invoke({"messages": [HumanMessage(content="pergunta")]})

        assert result["final_response"] == {
            "content": expected_content,
            "status": expected_status,
        }


def test_graph_returns_controlled_response_when_judge_blocks() -> None:
    result = _graph(judge_status="insufficient_evidence").invoke(
        {"messages": [HumanMessage(content="pergunta")]}
    )

    assert result["final_response"] == {
        "content": (
            "Não foi possível confirmar a resposta com evidências suficientes."
        ),
        "status": "error",
    }
