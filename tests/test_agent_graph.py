from __future__ import annotations

from functools import partial
from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage

from src.graphs.adapters import run_faq_node
from src.graphs.agent_graph import create_agent_graph
from src.graphs.decisions import decide_after_input_guardrail, decide_after_router
from src.graphs.state import RoutingDecision


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


class FakeRouter:
    def __init__(self, route: str, outcome: str) -> None:
        self.route = route
        self.outcome = outcome

    def invoke(self, _: list[AnyMessage]) -> RoutingDecision:
        return {
            "route": self.route,
            "target_agent": "faq" if self.route == "faq" else None,
            "outcome": self.outcome,
            "reason": "Decisão de teste.",
        }


class FakeFAQExecutor:
    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "messages": [
                *state["messages"],
                AIMessage(content="Resposta baseada na documentação."),
            ]
        }


class FakeJudge:
    def __init__(
        self,
        status: str = "approved",
        events: list[str] | None = None,
    ) -> None:
        self.status = status
        self.events = events

    def invoke(
        self,
        *,
        response_draft: dict[str, Any] | None,
        evidences: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if self.events is not None:
            self.events.append("judge")

        return {
            "status": self.status,
            "reason": "Resultado controlado.",
            "evidence_ids": ["faq-1"] if self.status == "approved" else [],
        }


class FakeCompiler:
    def __init__(self, events: list[str] | None = None) -> None:
        self.events = events

    def invoke(self, _: dict[str, Any]) -> dict[str, Any]:
        if self.events is not None:
            self.events.append("compiler")

        return {
            "content": "Resposta compilada.",
            "citations": ["faq-1"],
            "status": "draft",
        }


class FakeBlockedCompiler:
    def invoke(self, _: dict[str, Any]) -> dict[str, Any]:
        return {
            "content": "Não foi possível gerar uma resposta.",
            "citations": [],
            "status": "blocked",
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
        router=FakeRouter("faq", "dispatch"),
        capabilities={
            "faq": partial(
                run_faq_node,
                executor=FakeFAQExecutor(),
            )
        },
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


def test_graph_dispatches_to_faq_compiler_and_judge() -> None:
    result = _graph().invoke({"messages": [HumanMessage(content="pergunta original")]})

    assert result["agent_results"]["faq"]["status"] == "success"
    assert result["agent_results"]["judge"]["status"] == "approved"
    assert result["response_draft"]["content"] == "Resposta compilada."
    assert result["final_response"] == {
        "content": "Resposta compilada.",
        "status": "success",
    }
    assert result["output_guardrail"]["status"] == "passed"
    assert result["status"] == "completed"


def test_graph_runs_compiler_before_judge() -> None:
    events: list[str] = []
    graph = create_agent_graph(
        input_guardrail=_passed_input,
        router=FakeRouter("faq", "dispatch"),
        capabilities={
            "faq": partial(
                run_faq_node,
                executor=FakeFAQExecutor(),
            )
        },
        judge=FakeJudge(events=events),
        compiler=FakeCompiler(events=events),
        output_guardrail=_passing_output,
    )

    graph.invoke({"messages": [HumanMessage(content="pergunta")]})

    assert events == ["compiler", "judge"]


def test_graph_returns_controlled_response_for_input_rejection() -> None:
    graph = create_agent_graph(
        input_guardrail=_blocked_input,
        router=FakeRouter("faq", "dispatch"),
        capabilities={
            "faq": partial(
                run_faq_node,
                executor=FakeFAQExecutor(),
            )
        },
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
            router=FakeRouter(route, outcome),
            capabilities={
                "faq": partial(
                    run_faq_node,
                    executor=FakeFAQExecutor(),
                )
            },
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
            "Não foi possível confirmar a resposta com as evidências disponíveis."
        ),
        "status": "error",
    }


def test_graph_returns_controlled_response_when_judge_is_invalid() -> None:
    result = _graph(judge_status="invalid").invoke(
        {"messages": [HumanMessage(content="pergunta")]}
    )

    assert result["final_response"] == {
        "content": "Não foi possível validar a resposta gerada.",
        "status": "error",
    }


def test_graph_returns_controlled_error_when_compiler_blocks() -> None:
    graph = create_agent_graph(
        input_guardrail=_passed_input,
        router=FakeRouter("faq", "dispatch"),
        capabilities={
            "faq": partial(
                run_faq_node,
                executor=FakeFAQExecutor(),
            )
        },
        judge=FakeJudge("invalid"),
        compiler=FakeBlockedCompiler(),
        output_guardrail=_passing_output,
    )

    result = graph.invoke({"messages": [HumanMessage(content="pergunta")]})

    assert result["final_response"] == {
        "content": "Não foi possível validar a resposta gerada.",
        "status": "error",
    }
