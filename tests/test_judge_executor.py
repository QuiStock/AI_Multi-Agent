from __future__ import annotations

from typing import Any

from src.agents.judge.executor import JudgeExecutor
from src.agents.judge.jev_client import JevEvaluation
from src.graphs.contracts import JudgeDecision
from src.graphs.state import Evidence, ResponseDraft


class FakeJudgeModel:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.messages: list[Any] | None = None
        self.call_count = 0

    def invoke(self, messages: list[Any]) -> Any:
        self.call_count += 1
        self.messages = messages

        if isinstance(self.result, Exception):
            raise self.result

        return self.result


class FakeJevClient:
    def __init__(self, evaluation: JevEvaluation) -> None:
        self.evaluation = evaluation
        self.calls = 0

    def evaluate(self, **_: Any) -> JevEvaluation:
        self.calls += 1
        return self.evaluation


def _draft(
    *,
    citations: list[str] | None = None,
) -> ResponseDraft:
    return {
        "content": "O produto possui fluxo alto.",
        "citations": ["metric-1"] if citations is None else citations,
        "status": "draft",
    }


def _evidence() -> Evidence:
    return {
        "evidence_id": "metric-1",
        "source_type": "metric",
        "source_id": "stock_metrics:product-10",
        "content": "Classificação publicada: ALTO.",
        "metadata": {
            "product_id": "10",
        },
    }


def test_judge_approves_supported_draft_and_receives_evidence_content() -> None:
    model = FakeJudgeModel(
        JudgeDecision(
            status="approved",
            reason="Resposta sustentada pela evidência.",
            evidence_ids=["metric-1"],
        )
    )

    result = JudgeExecutor(model=model).invoke(
        response_draft=_draft(),
        evidences=[_evidence()],
    )

    assert result == {
        "status": "approved",
        "reason": "Resposta sustentada pela evidência.",
        "evidence_ids": ["metric-1"],
    }
    assert model.messages is not None
    assert "O produto possui fluxo alto." in str(model.messages[-1].content)
    assert "Classificação publicada: ALTO." in str(model.messages[-1].content)


def test_judge_fails_without_citations_without_calling_model() -> None:
    model = FakeJudgeModel(
        JudgeDecision(
            status="approved",
            reason="Não deveria ser chamado.",
            evidence_ids=["metric-1"],
        )
    )

    result = JudgeExecutor(model=model).invoke(
        response_draft=_draft(citations=[]),
        evidences=[_evidence()],
    )

    assert result["status"] == "insufficient_evidence"
    assert result["error_code"] == "JUDGE_INSUFFICIENT_EVIDENCE"
    assert model.call_count == 0


def test_judge_rejects_unknown_citation_without_calling_model() -> None:
    model = FakeJudgeModel(
        JudgeDecision(
            status="approved",
            reason="Não deveria ser chamado.",
            evidence_ids=["metric-1"],
        )
    )

    result = JudgeExecutor(model=model).invoke(
        response_draft=_draft(citations=["unknown-evidence"]),
        evidences=[_evidence()],
    )

    assert result["status"] == "invalid"
    assert result["error_code"] == "JUDGE_UNKNOWN_EVIDENCE"
    assert model.call_count == 0


def test_judge_preserves_insufficient_evidence_decision() -> None:
    model = FakeJudgeModel(
        JudgeDecision(
            status="insufficient_evidence",
            reason="A evidência não sustenta toda a resposta.",
            evidence_ids=["metric-1"],
        )
    )

    result = JudgeExecutor(model=model).invoke(
        response_draft=_draft(),
        evidences=[_evidence()],
    )

    assert result == {
        "status": "insufficient_evidence",
        "reason": "A evidência não sustenta toda a resposta.",
        "evidence_ids": ["metric-1"],
    }


def test_judge_rejects_approval_that_did_not_evaluate_all_citations() -> None:
    second_evidence: Evidence = {
        **_evidence(),
        "evidence_id": "metric-2",
        "source_id": "stock_metrics:product-11",
    }
    model = FakeJudgeModel(
        JudgeDecision(
            status="approved",
            reason="Resposta sustentada.",
            evidence_ids=["metric-1"],
        )
    )

    result = JudgeExecutor(model=model).invoke(
        response_draft=_draft(citations=["metric-1", "metric-2"]),
        evidences=[_evidence(), second_evidence],
    )

    assert result["status"] == "invalid"
    assert result["error_code"] == "JUDGE_INCOMPLETE_VALIDATION"


def test_judge_fails_closed_without_retry_when_model_is_unavailable() -> None:
    model = FakeJudgeModel(RuntimeError("model unavailable"))

    result = JudgeExecutor(model=model).invoke(
        response_draft=_draft(),
        evidences=[_evidence()],
    )

    assert result["status"] == "invalid"
    assert result["error_code"] == "JUDGE_UNAVAILABLE"
    assert model.call_count == 1


def test_judge_fails_closed_on_invalid_structured_output() -> None:
    model = FakeJudgeModel(
        {
            "status": "approved",
            "reason": "Resposta sustentada.",
        }
    )

    result = JudgeExecutor(model=model).invoke(
        response_draft=_draft(),
        evidences=[_evidence()],
    )

    assert result["status"] == "invalid"
    assert result["error_code"] == "JUDGE_INVALID_OUTPUT"


def test_jev_approves_only_with_supported_verdict_and_threshold() -> None:
    client = FakeJevClient(
        JevEvaluation(
            verdict="approved",
            reason_code="none",
            confidence=0.95,
            probabilities={"approved": 0.95, "rejected": 0.05},
            model="jev-1.13.0",
            input_tokens=100,
            output_tokens=10,
        )
    )

    result = JudgeExecutor(jev_client=client).invoke(
        response_draft=_draft(),
        evidences=[_evidence()],
    )

    assert result["status"] == "approved"
    assert result["confidence"] == 0.95
    assert result["model"] == "jev-1.13.0"
    assert client.calls == 1


def test_jev_missing_evidence_returns_specific_rejection() -> None:
    client = FakeJevClient(
        JevEvaluation(
            verdict="rejected",
            reason_code="missing_evidence",
            confidence=0.92,
            probabilities={"approved": 0.08, "rejected": 0.92},
            model="jev-1.13.0",
        )
    )

    result = JudgeExecutor(jev_client=client).invoke(
        response_draft=_draft(),
        evidences=[_evidence()],
    )

    assert result["status"] == "insufficient_evidence"
    assert result["reason_code"] == "missing_evidence"
    assert result["error_code"] == "JUDGE_MISSING_EVIDENCE"


def test_jev_rejects_low_confidence_approval() -> None:
    client = FakeJevClient(
        JevEvaluation(
            verdict="approved",
            reason_code="none",
            confidence=0.60,
            probabilities={"approved": 0.60, "rejected": 0.40},
            model="jev-1.13.0",
        )
    )

    result = JudgeExecutor(
        jev_client=client,
        jev_confidence_threshold=0.85,
    ).invoke(
        response_draft=_draft(),
        evidences=[_evidence()],
    )

    assert result["status"] == "insufficient_evidence"
    assert result["reason_code"] == "low_confidence"
