from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.graphs.contracts import CompilerResult, RouteDecision


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
