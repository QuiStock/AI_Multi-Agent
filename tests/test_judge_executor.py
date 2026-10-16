from collections.abc import Sequence

from src.agents.judge.executor import JudgeExecutor
from src.agents.judge.jev_client import JevClientError, JevEvaluation
from src.graphs.state import Evidence, ResponseDraft


class FakeJevClient:
    def __init__(self, result: JevEvaluation | Exception) -> None:
        self.result = result
        self.calls = 0
        self.response_draft: ResponseDraft | None = None
        self.evidences: list[Evidence] | None = None

    def evaluate(
        self,
        *,
        response_draft: ResponseDraft,
        evidences: Sequence[Evidence],
    ) -> JevEvaluation:
        self.calls += 1
        self.response_draft = response_draft
        self.evidences = list(evidences)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _draft(*, citations: list[str] | None = None) -> ResponseDraft:
    return {
        "content": "O produto possui fluxo alto.",
        "citations": ["metric-1"] if citations is None else citations,
        "status": "draft",
    }


def _evidence(evidence_id: str = "metric-1") -> Evidence:
    return {
        "evidence_id": evidence_id,
        "source_type": "metric",
        "source_id": f"stock_metrics:{evidence_id}",
        "content": "Classificação publicada: ALTO.",
        "metadata": {"product_id": "10"},
    }


def _approved_evaluation(*, confidence: float = 0.95) -> JevEvaluation:
    return JevEvaluation(
        verdict="approved",
        reason_code="none",
        confidence=confidence,
        probabilities={"approved": confidence, "rejected": 1 - confidence},
        model="jev-1.13.0",
        input_tokens=100,
        output_tokens=10,
    )


def test_judge_uses_jev_and_passes_the_draft_and_cited_evidence() -> None:
    client = FakeJevClient(_approved_evaluation())
    second_evidence = _evidence("metric-2")

    result = JudgeExecutor(jev_client=client).invoke(
        response_draft=_draft(citations=["metric-1", "metric-2"]),
        evidences=[_evidence(), second_evidence],
    )

    assert result["status"] == "approved"
    assert result["evidence_ids"] == ["metric-1", "metric-2"]
    assert result["confidence"] == 0.95
    assert result["model"] == "jev-1.13.0"
    assert client.calls == 1
    assert client.response_draft is not None
    assert client.evidences is not None
    assert [item["evidence_id"] for item in client.evidences] == [
        "metric-1",
        "metric-2",
    ]


def test_judge_fails_without_citations_without_calling_jev() -> None:
    client = FakeJevClient(_approved_evaluation())

    result = JudgeExecutor(jev_client=client).invoke(
        response_draft=_draft(citations=[]),
        evidences=[_evidence()],
    )

    assert result["status"] == "insufficient_evidence"
    assert result["error_code"] == "JUDGE_INSUFFICIENT_EVIDENCE"
    assert client.calls == 0


def test_judge_rejects_unknown_citation_without_calling_jev() -> None:
    client = FakeJevClient(_approved_evaluation())

    result = JudgeExecutor(jev_client=client).invoke(
        response_draft=_draft(citations=["unknown-evidence"]),
        evidences=[_evidence()],
    )

    assert result["status"] == "invalid"
    assert result["error_code"] == "JUDGE_UNKNOWN_EVIDENCE"
    assert client.calls == 0


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
    client = FakeJevClient(_approved_evaluation(confidence=0.60))

    result = JudgeExecutor(
        jev_client=client,
        jev_confidence_threshold=0.85,
    ).invoke(response_draft=_draft(), evidences=[_evidence()])

    assert result["status"] == "insufficient_evidence"
    assert result["reason_code"] == "low_confidence"


def test_jev_approves_at_the_configured_confidence_threshold() -> None:
    client = FakeJevClient(_approved_evaluation(confidence=0.85))

    result = JudgeExecutor(
        jev_client=client,
        jev_confidence_threshold=0.85,
    ).invoke(response_draft=_draft(), evidences=[_evidence()])

    assert result["status"] == "approved"
    assert result["confidence"] == 0.85


def test_jev_unavailable_preserves_internal_error_code() -> None:
    client = FakeJevClient(JevClientError("JEV_UNAVAILABLE", "private diagnostic"))

    result = JudgeExecutor(jev_client=client).invoke(
        response_draft=_draft(),
        evidences=[_evidence()],
    )

    assert result["status"] == "invalid"
    assert result["error_code"] == "JUDGE_JEV_UNAVAILABLE"
    assert "private diagnostic" not in result["reason"]


def test_jev_invalid_output_keeps_jev_error_classification() -> None:
    client = FakeJevClient(JevClientError("JEV_INVALID_OUTPUT", "private diagnostic"))

    result = JudgeExecutor(jev_client=client).invoke(
        response_draft=_draft(),
        evidences=[_evidence()],
    )

    assert result["status"] == "invalid"
    assert result["error_code"] == "JUDGE_JEV_INVALID_OUTPUT"
