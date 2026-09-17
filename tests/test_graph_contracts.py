from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.graphs.contracts import CompilerResult, JudgeDecision, RouteDecision


def test_route_decision_accepts_graph_route_contract() -> None:
    decision = RouteDecision(
        route="faq",
        reason="A solicitação trata de conteúdo documentado.",
    )

    assert decision.route == "faq"


def test_route_decision_rejects_unknown_route() -> None:
    with pytest.raises(ValidationError):
        RouteDecision(
            route="unknown",
            reason="Rota inválida.",
        )


def test_compiler_result_requires_non_empty_content() -> None:
    with pytest.raises(ValidationError):
        CompilerResult(content="", status="success")


def test_compiler_result_rejects_duplicated_citations() -> None:
    with pytest.raises(ValidationError):
        CompilerResult(
            content="Resposta.",
            citations=["faq-1", "faq-1"],
            status="success",
        )


def test_approved_judge_requires_evidence_ids() -> None:
    with pytest.raises(ValidationError):
        JudgeDecision(
            status="approved",
            reason="Resposta sustentada.",
            evidence_ids=[],
        )


def test_judge_decision_rejects_duplicated_evidence_ids() -> None:
    with pytest.raises(ValidationError):
        JudgeDecision(
            status="approved",
            reason="Resposta sustentada.",
            evidence_ids=["faq-1", "faq-1"],
        )
