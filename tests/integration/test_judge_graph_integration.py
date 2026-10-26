from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest
from langchain_core.messages import AnyMessage, HumanMessage

from src.agents.judge.executor import JudgeExecutor
from src.agents.judge.jev_client import JevEvaluation
from src.graphs.agent_graph import create_agent_graph
from src.graphs.contracts import RouteResponse
from src.graphs.state import (
    Evidence,
    GraphState,
    ResponseDraft,
)

pytestmark = pytest.mark.integration


def _passed_input(_: GraphState) -> GraphState:
    return {
        "input_guardrail": {
            "status": "passed",
            "reason_code": "approved",
            "reason": "Aprovado.",
            "redactions": [],
        }
    }


class FakeRouter:
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


class FakeCompiler:
    def invoke(self, **_: Any) -> ResponseDraft:
        return {
            "content": "A operação é apenas uma sugestão.",
            "citations": ["faq-1"],
            "status": "success",
        }


class FakeJevClient:
    def __init__(self) -> None:
        self.calls = 0
        self.response_draft: ResponseDraft | None = None

    def evaluate(
        self,
        *,
        user_question: str,
        response_draft: ResponseDraft,
        evidences: Sequence[Evidence],
        prior_assistant_message: str | None = None,
    ) -> JevEvaluation:
        self.calls += 1
        self.response_draft = response_draft
        return JevEvaluation(
            verdict="approved",
            reason_code="none",
            model="jev-test",
            noul_probability=0.98,
        )


def _capability(_: GraphState) -> GraphState:
    return {
        "agent_results": {
            "faq": {
                "status": "success",
                "answer": "A operação é apenas uma sugestão.",
                "citation_ids": ["faq-1"],
            }
        },
        "evidences": [
            {
                "evidence_id": "faq-1",
                "source_type": "faq_document",
                "source_id": "manual.md",
                "content": "O sistema produz sugestões e não executa operações.",
                "metadata": {},
            }
        ],
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


class EmptyContextEnricher:
    def restore_messages(self, *, email: str, conversation_id: str) -> list[AnyMessage]:
        return []


def test_real_judge_executor_validates_compiler_draft_inside_graph() -> None:
    jev_client = FakeJevClient()
    graph = create_agent_graph(
        input_guardrail=_passed_input,
        router=FakeRouter(),
        capabilities={"faq": _capability},
        compiler=FakeCompiler(),
        judge=JudgeExecutor(jev_client=jev_client),
        output_guardrail=_passing_output,
        context_enricher=EmptyContextEnricher(),
    )

    result = graph.invoke(
        {
            "request": {
                "request_id": "request-1",
                "email": "user-1",
                "conversation_id": "conversation-1",
                "role_code": "EMPLOYEE",
            },
            "messages": [HumanMessage(content="Qual é a regra?", id="request-1:user")],
        }
    )

    assert result["judge"] is not None
    assert result["judge"]["status"] == "approved"
    assert result["final_response"] == {
        "content": "A operação é apenas uma sugestão.",
        "status": "success",
    }
    assert jev_client.calls == 1
    assert jev_client.response_draft is not None
    assert jev_client.response_draft["citations"] == ["faq-1"]
