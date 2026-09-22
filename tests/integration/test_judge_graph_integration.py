from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import AnyMessage, HumanMessage

from src.agents.judge.executor import JudgeExecutor
from src.graphs.agent_graph import create_agent_graph
from src.graphs.contracts import JudgeDecision
from src.graphs.state import (
    GraphState,
    ResponseDraft,
    RoutingDecision,
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
    ) -> RoutingDecision:
        return {
            "route": "faq",
            "target_agent": "faq",
            "outcome": "dispatch",
            "reason": "Pergunta documental.",
        }


class FakeCompiler:
    def invoke(self, _: GraphState) -> ResponseDraft:
        return {
            "content": "A operação é apenas uma sugestão.",
            "citations": ["faq-1"],
            "status": "draft",
        }


class FakeJudgeModel:
    def __init__(self) -> None:
        self.messages: list[Any] | None = None

    def invoke(self, messages: list[Any]) -> JudgeDecision:
        self.messages = messages
        return JudgeDecision(
            status="approved",
            reason="Resposta sustentada pela evidência.",
            evidence_ids=["faq-1"],
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
    response_draft = state.get("response_draft")
    result: GraphState = {
        "output_guardrail": {
            "status": "passed",
            "reason_code": "approved",
            "reason": "Aprovado.",
            "violations": [],
        }
    }
    if response_draft is not None:
        result["final_response"] = {
            "content": response_draft["content"],
            "status": "success",
        }
    return result


class EmptyContextEnricher:
    def restore_messages(
        self, *, user_id: str, conversation_id: str
    ) -> list[AnyMessage]:
        return []


def test_real_judge_executor_validates_compiler_draft_inside_graph() -> None:
    model = FakeJudgeModel()
    graph = create_agent_graph(
        input_guardrail=_passed_input,
        router=FakeRouter(),
        capabilities={"faq": _capability},
        compiler=FakeCompiler(),
        judge=JudgeExecutor(model=model),
        output_guardrail=_passing_output,
        context_enricher=EmptyContextEnricher(),
    )

    result = graph.invoke(
        {
            "messages": [HumanMessage(content="Qual é a regra?")],
        }
    )

    assert result["agent_results"]["judge"]["status"] == "approved"
    assert result["final_response"] == {
        "content": "A operação é apenas uma sugestão.",
        "status": "success",
    }
    assert model.messages is not None
    assert "manual.md" in str(model.messages[-1].content)
