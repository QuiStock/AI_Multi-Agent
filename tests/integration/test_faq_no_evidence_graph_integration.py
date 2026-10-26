from __future__ import annotations

from functools import partial
from typing import Any

import pytest
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage

from src.agents.faq.executor import FAQExecutor
from src.agents.faq.faq_node import (
    FAQ_DEPENDENCY_MESSAGE,
    FAQ_NO_RESULTS_MESSAGE,
    faq_node,
)
from src.graphs.agent_graph import create_agent_graph
from src.graphs.contracts import RouteResponse
from src.graphs.state import GraphState

pytestmark = pytest.mark.integration


class EmptyRetriever:
    def search(
        self,
        query: str,
        *,
        allowed_audiences: tuple[str, ...],
    ) -> list[dict[str, object]]:
        return []


class UnavailableRetriever:
    def search(
        self,
        query: str,
        *,
        allowed_audiences: tuple[str, ...],
    ) -> list[dict[str, object]]:
        raise RuntimeError("Qdrant connection details must not reach the user")


class ToolAgent:
    def __init__(self, tool: Any) -> None:
        self.tool = tool

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        message = state["messages"][-1]
        self.tool.invoke({"query": message.content})
        return {"messages": [AIMessage(content="Resposta do modelo.")]}


class RecordingCompiler:
    def __init__(self) -> None:
        self.calls = 0
        self.evidences: list[dict[str, Any]] = []

    def invoke(self, **kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        self.evidences = list(kwargs["evidences"])
        return {
            "content": "Não há informação documentada sobre esse assunto.",
            "citations": [self.evidences[0]["evidence_id"]],
            "status": "success",
        }


class ApprovingJudge:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, **_: Any) -> dict[str, Any]:
        self.calls += 1
        return {
            "status": "approved",
            "reason": "A ausência documental está sustentada.",
            "evidence_count": 1,
        }


class JudgeMustNotRun:
    def invoke(self, **_: Any) -> dict[str, Any]:
        raise AssertionError("Erro controlado do FAQ não passa pelo judge.")


class FAQRouter:
    def invoke(
        self,
        _: list[AnyMessage],
        *,
        request_context: dict[str, Any] | None = None,
    ) -> RouteResponse:
        return {
            "route": "faq",
            "reason": "Pergunta documental.",
            "status": "success",
        }


class EmptyContextEnricher:
    def restore_messages(self, *, email: str, conversation_id: str) -> list[AnyMessage]:
        return []


class RecordingMessageService:
    def __init__(self) -> None:
        self.saved_turns: list[dict[str, Any]] = []

    def save_turn(self, **kwargs: Any) -> None:
        self.saved_turns.append(kwargs)


def _passed_input(_: GraphState) -> GraphState:
    return {
        "input_guardrail": {
            "status": "passed",
            "reason_code": "approved",
            "reason": "Aprovado.",
            "redactions": [],
        }
    }


def _passing_output(state: GraphState) -> GraphState:
    final_response = state.get("final_response")
    result: GraphState = {
        "output_guardrail": {
            "status": "passed",
            "reason_code": "approved",
            "reason": "Aprovado.",
            "violations": [],
        }
    }
    if final_response is not None:
        result["final_response"] = final_response
    return result


def _request(request_id: str) -> dict[str, Any]:
    return {
        "request": {
            "request_id": request_id,
            "email": "user@example.com",
            "conversation_id": "conversation-1",
            "role_code": "EMPLOYEE",
        },
        "messages": [
            HumanMessage(
                content="Pergunta sem suporte documental.",
                id=f"{request_id}:user",
            )
        ],
    }


def test_faq_without_documents_goes_through_compiler_and_judge() -> None:
    compiler = RecordingCompiler()
    judge = ApprovingJudge()
    message_service = RecordingMessageService()
    graph = create_agent_graph(
        input_guardrail=_passed_input,
        router=FAQRouter(),
        capabilities={
            "faq": partial(
                faq_node,
                executor=FAQExecutor(
                    retriever=EmptyRetriever(),  # type: ignore[arg-type]
                    agent_factory=lambda **kwargs: ToolAgent(kwargs["tools"][0]),
                ),
            )
        },
        compiler=compiler,  # type: ignore[arg-type]
        judge=judge,  # type: ignore[arg-type]
        output_guardrail=_passing_output,
        context_enricher=EmptyContextEnricher(),
        message_service=message_service,
    )

    result = graph.invoke(_request("request-1"))

    assert compiler.calls == 1
    assert compiler.evidences[0]["metadata"]["outcome"] == "not_found"
    assert compiler.evidences[0]["metadata"]["result_count"] == 0
    assert judge.calls == 1
    assert result["agent_results"]["faq"]["answer"] == FAQ_NO_RESULTS_MESSAGE
    assert result["response_draft"] is None
    assert result["final_response"]["content"] == (
        "Não há informação documentada sobre esse assunto."
    )
    assert result["final_response"]["status"] == "success"
    assert message_service.saved_turns[0]["assistant_content"] == (
        "Não há informação documentada sobre esse assunto."
    )


def test_faq_dependency_error_stays_off_compiler_and_judge() -> None:
    compiler = RecordingCompiler()
    message_service = RecordingMessageService()
    graph = create_agent_graph(
        input_guardrail=_passed_input,
        router=FAQRouter(),
        capabilities={
            "faq": partial(
                faq_node,
                executor=FAQExecutor(
                    retriever=UnavailableRetriever(),  # type: ignore[arg-type]
                    agent_factory=lambda **kwargs: ToolAgent(kwargs["tools"][0]),
                ),
            )
        },
        compiler=compiler,  # type: ignore[arg-type]
        judge=JudgeMustNotRun(),  # type: ignore[arg-type]
        output_guardrail=_passing_output,
        context_enricher=EmptyContextEnricher(),
        message_service=message_service,
    )

    result = graph.invoke(_request("request-failure"))

    assert compiler.calls == 0
    assert result["final_response"] == {
        "content": FAQ_DEPENDENCY_MESSAGE,
        "status": "error",
    }
    assert message_service.saved_turns[0]["assistant_content"] == (
        FAQ_DEPENDENCY_MESSAGE
    )
