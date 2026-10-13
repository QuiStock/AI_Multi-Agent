from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.graphs.state import Evidence, ResponseDraft

JevVerdict = Literal["approved", "rejected"]
JevReasonCode = Literal[
    "none",
    "missing_evidence",
    "unsupported_claim",
    "contradiction",
    "invalid_citation",
    "ambiguous_evidence",
    "low_confidence",
]

_VERDICTS = {"approved", "rejected"}
_REASON_CODES = {
    "none",
    "missing_evidence",
    "unsupported_claim",
    "contradiction",
    "invalid_citation",
    "ambiguous_evidence",
    "low_confidence",
}


@dataclass(frozen=True)
class JevEvaluation:
    verdict: JevVerdict
    reason_code: JevReasonCode
    confidence: float
    probabilities: dict[str, float]
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class JevJudgeClientPort(Protocol):
    def evaluate(
        self,
        *,
        response_draft: ResponseDraft,
        evidences: Sequence[Evidence],
    ) -> JevEvaluation: ...


class JevClientError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class TypeSafeJevClient:
    """Small synchronous adapter for TypeSafe's System One API."""

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str = "jev-1.13.0",
        base_url: str = "https://api.typesafe.ai",
        timeout_seconds: float = 5.0,
    ) -> None:
        self.api_key = api_key.strip() if api_key else None
        self.model = model.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

        if not self.model:
            raise ValueError("O modelo JEV é obrigatório")
        if not self.base_url:
            raise ValueError("A URL da API TypeSafe é obrigatória")
        if timeout_seconds <= 0:
            raise ValueError("O timeout do JEV deve ser maior que zero")

    @staticmethod
    def _questions() -> dict[str, dict[str, Any]]:
        return {
            "verdict": {
                "type": "choice",
                "instructions": (
                    "A resposta candidata está completamente sustentada "
                    "pelas evidências fornecidas?"
                ),
                "criteria": {
                    "approved": (
                        "Todas as alegações factuais são sustentadas pelas "
                        "evidências e não há contradições."
                    ),
                    "rejected": (
                        "Existe alegação sem suporte, evidência ausente, "
                        "citação inválida ou contradição."
                    ),
                },
            },
            "reason_code": {
                "type": "choice",
                "instructions": (
                    "Qual é o principal motivo para o veredito? Use none "
                    "quando a resposta estiver aprovada."
                ),
                "criteria": {
                    "none": "A resposta está integralmente sustentada.",
                    "missing_evidence": (
                        "A evidência necessária não foi fornecida ou não existe "
                        "entre as evidências disponíveis."
                    ),
                    "unsupported_claim": (
                        "Uma ou mais alegações não são sustentadas pelas evidências."
                    ),
                    "contradiction": ("A resposta contradiz uma evidência disponível."),
                    "invalid_citation": (
                        "A resposta usa uma citação que não sustenta o conteúdo."
                    ),
                    "ambiguous_evidence": (
                        "As evidências são ambíguas para confirmar a resposta."
                    ),
                    "low_confidence": (
                        "O julgamento não tem confiança suficiente para "
                        "liberar a resposta."
                    ),
                },
            },
        }

    @staticmethod
    def _choice(
        answers: Mapping[str, Any],
        question_id: str,
    ) -> tuple[str, Mapping[str, Any]]:
        answer = answers.get(question_id)
        if not isinstance(answer, Mapping):
            raise JevClientError(
                "JEV_INVALID_OUTPUT",
                f"A resposta {question_id} do JEV é inválida.",
            )

        choice = answer.get("choice")
        if not isinstance(choice, str) or not choice:
            raise JevClientError(
                "JEV_INVALID_OUTPUT",
                f"A escolha {question_id} do JEV é inválida.",
            )
        return choice, answer

    @staticmethod
    def _probabilities(answer: Mapping[str, Any]) -> dict[str, float]:
        probabilities = answer.get("probabilities")
        if not isinstance(probabilities, Mapping):
            raise JevClientError(
                "JEV_INVALID_OUTPUT",
                "O JEV não retornou probabilidades válidas.",
            )

        normalized: dict[str, float] = {}
        for key, value in probabilities.items():
            if not isinstance(key, str) or not isinstance(value, (int, float)):
                raise JevClientError(
                    "JEV_INVALID_OUTPUT",
                    "As probabilidades retornadas pelo JEV são inválidas.",
                )
            probability = float(value)
            if not 0 <= probability <= 1:
                raise JevClientError(
                    "JEV_INVALID_OUTPUT",
                    "As probabilidades retornadas pelo JEV estão fora do intervalo.",
                )
            normalized[key] = probability

        if not normalized:
            raise JevClientError(
                "JEV_INVALID_OUTPUT",
                "O JEV não retornou probabilidades.",
            )
        return normalized

    @staticmethod
    def _confidence(answer: Mapping[str, Any]) -> float:
        confidence = answer.get("confidence")
        if not isinstance(confidence, (int, float)):
            raise JevClientError(
                "JEV_INVALID_OUTPUT",
                "O JEV não retornou confiança válida.",
            )
        normalized = float(confidence)
        if not 0 <= normalized <= 1:
            raise JevClientError(
                "JEV_INVALID_OUTPUT",
                "A confiança retornada pelo JEV está fora do intervalo.",
            )
        return normalized

    def _payload(
        self,
        *,
        response_draft: ResponseDraft,
        evidences: Sequence[Evidence],
    ) -> dict[str, Any]:
        return {
            "model": self.model,
            "state": {
                "response_draft": response_draft,
                "evidences": list(evidences),
            },
            "questions": self._questions(),
        }

    def _request(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        if not self.api_key:
            raise JevClientError(
                "JEV_API_KEY_MISSING",
                "A chave da API TypeSafe não está configurada.",
            )

        request = Request(
            f"{self.base_url}/v1/systemone",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw_response = response.read()
        except HTTPError as exc:
            if exc.code == 401:
                code = "JEV_AUTHENTICATION_FAILED"
            elif exc.code == 429:
                code = "JEV_RATE_LIMITED"
            elif exc.code == 529:
                code = "JEV_OVERLOADED"
            else:
                code = "JEV_HTTP_ERROR"
            raise JevClientError(
                code, "A API TypeSafe não respondeu com sucesso."
            ) from exc
        except (TimeoutError, URLError, OSError) as exc:
            raise JevClientError(
                "JEV_UNAVAILABLE",
                "A API TypeSafe está indisponível.",
            ) from exc

        try:
            decoded = json.loads(raw_response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise JevClientError(
                "JEV_INVALID_OUTPUT",
                "A API TypeSafe retornou JSON inválido.",
            ) from exc

        if not isinstance(decoded, Mapping):
            raise JevClientError(
                "JEV_INVALID_OUTPUT",
                "A API TypeSafe retornou uma estrutura inválida.",
            )
        return decoded

    def evaluate(
        self,
        *,
        response_draft: ResponseDraft,
        evidences: Sequence[Evidence],
    ) -> JevEvaluation:
        payload = self._payload(
            response_draft=response_draft,
            evidences=evidences,
        )
        response = self._request(payload)
        answers = response.get("answers")
        if not isinstance(answers, Mapping):
            raise JevClientError(
                "JEV_INVALID_OUTPUT",
                "A API TypeSafe não retornou answers.",
            )

        verdict, verdict_answer = self._choice(answers, "verdict")
        reason_code, _ = self._choice(answers, "reason_code")
        if verdict not in _VERDICTS or reason_code not in _REASON_CODES:
            raise JevClientError(
                "JEV_INVALID_OUTPUT",
                "O JEV retornou uma opção fora do contrato.",
            )

        usage = response.get("usage")
        if not isinstance(usage, Mapping):
            usage = {}

        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        if input_tokens is not None and not isinstance(input_tokens, int):
            raise JevClientError(
                "JEV_INVALID_OUTPUT",
                "O uso de tokens de entrada do JEV é inválido.",
            )
        if output_tokens is not None and not isinstance(output_tokens, int):
            raise JevClientError(
                "JEV_INVALID_OUTPUT",
                "O uso de tokens de saída do JEV é inválido.",
            )

        model = response.get("model", self.model)
        if not isinstance(model, str) or not model:
            raise JevClientError(
                "JEV_INVALID_OUTPUT",
                "A versão do modelo JEV é inválida.",
            )

        return JevEvaluation(
            verdict=cast(JevVerdict, verdict),
            reason_code=cast(JevReasonCode, reason_code),
            confidence=self._confidence(verdict_answer),
            probabilities=self._probabilities(verdict_answer),
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
