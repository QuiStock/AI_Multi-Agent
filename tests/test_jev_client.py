from __future__ import annotations

import json
from typing import Any

import pytest

from src.agents.judge.jev_client import (
    JevClientError,
    TypeSafeJevClient,
)
from src.graphs.state import Evidence, ResponseDraft


def _draft() -> ResponseDraft:
    return {
        "content": "O produto possui fluxo alto.",
        "citations": ["metric-1"],
        "status": "draft",
    }


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
                    "verdict": {
                        "type": "choice",
                        "choice": "approved",
                        "confidence": 0.96,
                        "probabilities": {"approved": 0.96, "rejected": 0.04},
                    },
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
        response_draft=_draft(),
        evidences=[_evidence()],
    )

    request = captured["request"]
    payload = json.loads(request.data.decode("utf-8"))
    assert request.full_url == "https://api.typesafe.ai/v1/systemone"
    assert request.get_header("Authorization") == "Bearer test-key"
    assert captured["timeout"] == 3.0
    assert payload["model"] == "jev-1.13.0"
    assert payload["state"]["response_draft"] == _draft()
    assert payload["state"]["evidences"] == [_evidence()]
    assert payload["questions"]["verdict"]["type"] == "choice"
    assert result.verdict == "approved"
    assert result.reason_code == "none"
    assert result.confidence == 0.96


def test_typesafe_client_fails_without_api_key() -> None:
    client = TypeSafeJevClient(api_key=None)

    with pytest.raises(JevClientError, match="não está configurada"):
        client.evaluate(
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
                        "choice": "none",
                        "confidence": 1.0,
                        "probabilities": {"none": 1.0},
                    },
                }
            }
        ),
    )

    client = TypeSafeJevClient(api_key="test-key")

    with pytest.raises(JevClientError, match="fora do contrato"):
        client.evaluate(
            response_draft=_draft(),
            evidences=[_evidence()],
        )
