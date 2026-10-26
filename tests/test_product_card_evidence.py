from __future__ import annotations

import json
from functools import partial
from typing import Any, Sequence

import pytest
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage

from src.agents.judge.executor import JudgeExecutor
from src.agents.judge.jev_client import JevEvaluation
from src.agents.product_workflow.executor import ProductWorkflowExecutor
from src.agents.product_workflow.product_workflow_node import (
    run_product_workflow_node,
)
from src.agents.product_workflow.product_workflow_prompt import (
    PRODUCT_WORKFLOW_SYSTEM_PROMPT,
)
from src.graphs.agent_graph import create_agent_graph
from src.graphs.contracts import RouteResponse
from src.graphs.state import Evidence, GraphState, ResponseDraft

PRODUCT_CARD: dict[str, object] = {
    "product_id": 1427,
    "suggestion_id": 87531,
    "product_name": "Café Torrado e Moído 500g",
    "category_name": "Mercearia",
    "sku": "CAF-500-TRAD",
    "suggestion_type": "PROMOTION",
    "batch_count": 3,
    "expiration_date": "2026-11-30",
    "discount_percentage": 15,
    "reference_sale_price": 29.9,
    "promotional_price": 25.42,
    "promotion_valid_from": "2026-10-14",
    "promotion_valid_until": "2026-10-31",
}


class SnapshotAgent:
    def __init__(self, answer: str) -> None:
        self.answer = answer

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "messages": [
                *state["messages"],
                AIMessage(content=self.answer),
            ]
        }


class ProductRouter:
    def invoke(
        self,
        _: Sequence[AnyMessage],
        *,
        request_context: dict[str, Any] | None = None,
    ) -> RouteResponse:
        return {
            "route": "product_workflow",
            "reason": "Consulta sobre product_card.",
            "status": "success",
        }


class EmptyContext:
    def restore_messages(
        self,
        *,
        email: str,
        conversation_id: str,
    ) -> list[AnyMessage]:
        return []


class CapturingCompiler:
    def __init__(self, content: str) -> None:
        self.content = content
        self.evidences: Sequence[Evidence] | None = None

    def invoke(
        self,
        *,
        evidences: Sequence[Evidence],
        **_: Any,
    ) -> ResponseDraft:
        self.evidences = evidences
        evidence = evidences[0]
        return {
            "content": self.content,
            "citations": [evidence["evidence_id"]],
            "status": "success",
        }


class CapturingJevClient:
    def __init__(self, *, reason_code: str = "none") -> None:
        self.reason_code = reason_code
        self.evidences: Sequence[Evidence] | None = None

    def evaluate(
        self,
        *,
        user_question: str,
        response_draft: ResponseDraft,
        evidences: Sequence[Evidence],
        prior_assistant_message: str | None = None,
    ) -> JevEvaluation:
        self.evidences = evidences
        rejected = self.reason_code != "none"
        return JevEvaluation(
            verdict="rejected" if rejected else "approved",
            reason_code=self.reason_code,  # type: ignore[arg-type]
            model="jev-test",
            noul_probability=0.95,
        )


class PassingOutputGuardrail:
    def __call__(self, state: GraphState) -> GraphState:
        final_response = state["final_response"]
        return {
            "output_guardrail": {
                "status": "passed",
                "reason_code": "approved",
                "reason": "Resposta válida.",
                "violations": [],
            },
            "final_response": {
                "content": final_response["content"],
                "status": final_response["status"],
            },
        }


def _passed_input(_: GraphState) -> GraphState:
    return {
        "input_guardrail": {
            "status": "passed",
            "reason_code": "approved",
            "reason": "Aprovado.",
            "redactions": [],
        }
    }


def _request(card: dict[str, object] | None = PRODUCT_CARD) -> dict[str, Any]:
    return {
        "request_id": "request-1",
        "email": "user@example.test",
        "role_code": "EMPLOYEE",
        "user_id": 42,
        "store_ids": [10],
        "conversation_id": "conversation-1",
        "product_card": card,
    }


def _snapshot_executor(answer: str) -> ProductWorkflowExecutor:
    return ProductWorkflowExecutor(
        repository=object(),  # type: ignore[arg-type]
        model=object(),
        agent_factory=lambda **_: SnapshotAgent(answer),
    )


def _graph(
    *,
    product_executor: ProductWorkflowExecutor,
    compiler: CapturingCompiler,
    jev_client: CapturingJevClient,
) -> Any:
    return create_agent_graph(
        input_guardrail=_passed_input,
        router=ProductRouter(),
        capabilities={
            "product_workflow": partial(
                run_product_workflow_node,
                executor=product_executor,
            )
        },
        compiler=compiler,
        judge=JudgeExecutor(jev_client=jev_client),
        output_guardrail=PassingOutputGuardrail(),
        context_enricher=EmptyContext(),
    )


@pytest.mark.parametrize(
    ("question", "answer", "expected_field"),
    [
        (
            "Qual é o preço promocional?",
            "O preço promocional é R$ 25,42.",
            '"promotional_price":"25.42"',
        ),
        (
            "Até quando a promoção é válida?",
            "A promoção é válida até 2026-10-31.",
            '"promotion_valid_until":"2026-10-31"',
        ),
    ],
)
def test_product_card_evidence_reaches_compiler_and_jev(
    question: str,
    answer: str,
    expected_field: str,
) -> None:
    compiler = CapturingCompiler(answer)
    jev_client = CapturingJevClient()
    graph = _graph(
        product_executor=_snapshot_executor(answer),
        compiler=compiler,
        jev_client=jev_client,
    )

    result = graph.invoke(
        {
            "request": _request(),
            "messages": [HumanMessage(content=question, id="request-1:user")],
        }
    )

    assert result["final_response"]["status"] == "success"
    assert result["judge"]["status"] == "approved"
    assert compiler.evidences is not None
    assert jev_client.evidences is not None
    evidence = compiler.evidences[0]
    assert evidence["source_type"] == "client_card_snapshot"
    assert evidence in jev_client.evidences
    assert expected_field in evidence["content"]
    assert evidence["evidence_id"] == "client-card:1427:87531:CAF-500-TRAD"
    assert evidence["metadata"] == {
        "origin": "conversation_request.product_card",
        "product_id": 1427,
        "suggestion_id": 87531,
        "sku": "CAF-500-TRAD",
    }
    assert "verification_status" not in evidence


def test_missing_product_card_field_is_not_invented_and_jev_blocks_claim() -> None:
    card_without_validity = {
        key: value
        for key, value in PRODUCT_CARD.items()
        if key not in {"expiration_date", "promotion_valid_until"}
    }
    compiler = CapturingCompiler("A promoção termina em 2026-12-31.")
    jev_client = CapturingJevClient(reason_code="missing_evidence")
    graph = _graph(
        product_executor=_snapshot_executor(
            "A data de validade não está disponível no card."
        ),
        compiler=compiler,
        jev_client=jev_client,
    )

    result = graph.invoke(
        {
            "request": _request(card_without_validity),
            "messages": [
                HumanMessage(
                    content="Qual é a validade da promoção?",
                    id="request-1:user",
                )
            ],
        }
    )

    assert result["judge"]["status"] == "insufficient_evidence"
    assert result["final_response"]["status"] == "clarification_required"
    assert "2026-12-31" not in result["final_response"]["content"]
    assert compiler.evidences is not None
    content = compiler.evidences[0]["content"]
    assert '"promotion_valid_until":null' in content.replace(" ", "")
    assert '"promotion_valid_until":"' not in content.replace(" ", "")


def test_product_card_snapshot_is_kept_in_the_common_evidence_list() -> None:
    result = run_product_workflow_node(
        {
            "request": _request(),
            "messages": [HumanMessage(content="Qual é o preço?")],
        },
        executor=_snapshot_executor("O preço promocional é R$ 25,42."),
    )

    assert result["evidences"][0]["source_type"] == "client_card_snapshot"
    assert result["agent_results"]["product_workflow"]["evidence_ids"] == [
        "client-card:1427:87531:CAF-500-TRAD"
    ]


def test_product_card_prompts_do_not_classify_snapshot_as_unverified() -> None:
    prompt = PRODUCT_WORKFLOW_SYSTEM_PROMPT
    assert "unverified" not in prompt.lower()
    assert "não foi verificado" not in prompt.lower()


def test_product_workflow_without_product_card_keeps_tool_flow() -> None:
    captured: dict[str, Any] = {}

    class NormalAgent:
        def invoke(
            self,
            state: dict[str, Any],
            *,
            config: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            return {
                "messages": [
                    *state["messages"],
                    ToolMessage(
                        name="get_suggestion_for_product",
                        tool_call_id="tool-1",
                        content=json.dumps(
                            {
                                "schema_version": "1.0",
                                "status": "success",
                                "data": {
                                    "product_query": "Cafe",
                                    "page": 1,
                                    "has_more": False,
                                    "status": "unique",
                                    "suggestion": {
                                        "selection_id": "candidate-1",
                                        "product_name": "Cafe",
                                        "sku": "CAF-500-TRAD",
                                        "suggestion_type": "PROMOTION",
                                        "promotional_price": 25.42,
                                        "created_at": "2026-10-03T12:00:00Z",
                                    },
                                },
                                "evidence": [
                                    {
                                        "evidence_id": "product-search:suggestion:1",
                                        "source_type": "product_workflow",
                                        "source_id": "suggestion:1",
                                        "content": "Preço publicado: R$ 25,42.",
                                        "metadata": {"sku": "CAF-500-TRAD"},
                                    }
                                ],
                                "error": None,
                                "meta": {
                                    "tool_name": "get_suggestion_for_product",
                                    "tool_version": "1.0.0",
                                    "tool_call_id": "tool-1",
                                    "trace_id": "trace-1",
                                    "timestamp": "2026-10-03T12:00:00Z",
                                },
                            }
                        ),
                    ),
                    AIMessage(content="O preço publicado é R$ 25,42."),
                ]
            }

    def factory(**kwargs: Any) -> NormalAgent:
        captured.update(kwargs)
        return NormalAgent()

    request = _request(card=None)
    executor = ProductWorkflowExecutor(
        repository=object(),  # type: ignore[arg-type]
        model=object(),
        agent_factory=factory,
    )
    result = run_product_workflow_node(
        {"request": request, "messages": []},
        executor=executor,
    )

    assert captured["tools"]
    assert result["evidences"][0]["source_type"] == "product_workflow"
