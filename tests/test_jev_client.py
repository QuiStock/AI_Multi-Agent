from __future__ import annotations

import json
from typing import Any

import pytest

from src.agents.judge.jev_client import (
    JevClientError,
    TypeSafeJevClient,
)
from src.graphs.state import Evidence, ResponseDraft
from src.observability.traces.traces import TraceRecorder, bind_trace_recorder


def _draft() -> ResponseDraft:
    return {
        "content": "O produto possui fluxo alto.",
        "citations": ["metric-1"],
        "status": "draft",
    }


def _section(regras: str, name: str) -> str:
    start = regras.index(f"<{name}>")
    end = regras.index(f"</{name}>")
    return regras[start:end]


def _evidence() -> Evidence:
    return {
        "evidence_id": "metric-1",
        "source_type": "metric",
        "source_id": "metrics:product-10",
        "content": "Classificação publicada: ALTO.",
        "metadata": {},
    }


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_typesafe_client_sends_typed_judge_questions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(request: Any, *, timeout: float) -> FakeResponse:
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse(
            {
                "model": "jev-1.13.0",
                "answers": {
                    "verdict": {"type": "noul", "noul": 0.96},
                    "reason_code": {
                        "type": "choice",
                        "choice": "none",
                        "confidence": 1.0,
                        "probabilities": {"none": 1.0},
                    },
                },
                "usage": {"input_tokens": 100, "output_tokens": 12},
            }
        )

    monkeypatch.setattr(
        "src.agents.judge.jev_client.urlopen",
        fake_urlopen,
    )

    client = TypeSafeJevClient(
        api_key="test-key",
        timeout_seconds=3.0,
    )
    result = client.evaluate(
        user_question="2",
        response_draft=_draft(),
        evidences=[_evidence()],
    )

    request = captured["request"]
    payload = json.loads(request.data.decode("utf-8"))
    assert request.full_url == "https://api.typesafe.ai/v1/systemone"
    assert request.get_header("Authorization") == "Bearer test-key"
    assert captured["timeout"] == 3.0
    assert payload["model"] == "jev-1.13.0"
    assert payload["state"]["user_question"] == "2"
    assert "prior_assistant_message" not in payload["state"]
    regras = payload["state"]["regras"]
    memory = _section(regras, "sobre memória")
    product = _section(regras, "sobre produtos ou sugestão")
    policy = _section(regras, "sobre políticas")
    assert "apenas contexto" in regras
    assert payload["state"]["response_draft"] == _draft()
    assert payload["state"]["evidences"] == [_evidence()]
    assert "o que falamos tal dia" in memory
    assert "outro dia" in memory
    assert "conversation_summary" in memory
    assert "recent_fallback" in memory
    assert "página_n" in product
    assert "não é o item de mesmo número" in product
    assert "product-search" in product
    assert "lista que reproduz a posição e o nome" in product
    assert "status not_found" in product
    assert "outcome not_found" in policy
    assert "result_count 0" in policy
    assert (
        "página_n"
        in payload["questions"]["reason_code"]["criteria"]["does_not_answer_question"]
    )
    assert (
        "outro dia"
        in payload["questions"]["reason_code"]["criteria"]["does_not_answer_question"]
    )
    assert (
        "card unique"
        in payload["questions"]["reason_code"]["criteria"]["ambiguous_evidence"]
    )
    assert "página_n" in payload["questions"]["verdict"]["instructions"]
    assert "Aplique o campo regras" in payload["questions"]["verdict"]["instructions"]
    assert payload["questions"]["verdict"]["type"] == "noul"
    assert result.verdict == "approved"
    assert result.reason_code == "none"
    assert result.noul_probability == 0.96


def test_typesafe_client_records_invalid_judgment_as_trace_span(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.agents.judge.jev_client.urlopen",
        lambda *_args, **_kwargs: FakeResponse(
            {
                "model": "jev-1.13.0",
                "answers": {},
                "usage": {"input_tokens": 1200, "output_tokens": 8},
            }
        ),
    )
    client = TypeSafeJevClient(api_key="test-key")
    trace = TraceRecorder(
        trace_id="trace-1",
        conversation_id="conversation-1",
        environment="test",
    )

    with bind_trace_recorder(trace):
        with pytest.raises(JevClientError, match="verdict"):
            client.evaluate(
                user_question="2",
                response_draft=_draft(),
                evidences=[_evidence()],
            )

    trace.finish_trace(status="error")
    jev_span = next(
        span for span in trace.to_document()["spans"] if span["kind"] == "llm"
    )
    assert jev_span["name"] == "Judge JEV"
    assert jev_span["model"] == "jev-1.13.0"
    assert jev_span["attributes"]["usage_source"] == "judge_jev"
    assert jev_span["input_tokens"] == 1200
    assert jev_span["output_tokens"] == 8
    assert jev_span["status"] == "error"
    assert jev_span["duration_ms"] >= 0


def test_typesafe_client_sends_prior_assistant_message_as_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(request: Any, *, timeout: float) -> FakeResponse:
        captured["request"] = request
        return FakeResponse(
            {
                "answers": {
                    "verdict": {"type": "noul", "noul": 0.91},
                    "reason_code": {"type": "choice", "choice": "none"},
                }
            }
        )

    monkeypatch.setattr("src.agents.judge.jev_client.urlopen", fake_urlopen)
    client = TypeSafeJevClient(api_key="test-key")

    client.evaluate(
        user_question="página 2",
        prior_assistant_message="As promoções vigentes são:\n1. Agua",
        response_draft=_draft(),
        evidences=[_evidence()],
    )

    payload = json.loads(captured["request"].data.decode("utf-8"))
    assert payload["state"]["user_question"] == "página 2"
    assert payload["state"]["prior_assistant_message"] == (
        "As promoções vigentes são:\n1. Agua"
    )


def test_typesafe_client_fails_without_api_key() -> None:
    client = TypeSafeJevClient(api_key=None)

    with pytest.raises(JevClientError, match="não está configurada"):
        client.evaluate(
            user_question="2",
            response_draft=_draft(),
            evidences=[_evidence()],
        )


def test_typesafe_client_rejects_unknown_choice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.agents.judge.jev_client.urlopen",
        lambda *_args, **_kwargs: FakeResponse(
            {
                "answers": {
                    "verdict": {
                        "choice": "maybe",
                        "confidence": 0.5,
                        "probabilities": {"maybe": 1.0},
                    },
                    "reason_code": {
                        "choice": "talvez",
                        "confidence": 1.0,
                        "probabilities": {"talvez": 1.0},
                    },
                }
            }
        ),
    )

    client = TypeSafeJevClient(api_key="test-key")

    with pytest.raises(JevClientError, match="fora do contrato"):
        client.evaluate(
            user_question="2",
            response_draft=_draft(),
            evidences=[_evidence()],
        )
