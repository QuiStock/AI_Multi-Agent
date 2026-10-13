from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, Literal, cast

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage

from src.graphs.contracts import JudgeDecision
from src.graphs.state import Evidence, JudgeResult, ResponseDraft
from src.llm_factory import get_structured_model

from .card import JUDGE_CARD
from .jev_client import JevJudgeClientPort

JudgeStatus = Literal[
    "approved",
    "insufficient_evidence",
    "invalid",
]


class JudgeExecutor:
    def __init__(
        self,
        model: Any | None = None,
        *,
        jev_client: JevJudgeClientPort | None = None,
        jev_confidence_threshold: float = 0.85,
    ) -> None:
        self.card = JUDGE_CARD
        if not 0 <= jev_confidence_threshold <= 1:
            raise ValueError("O limiar de confiança do JEV deve estar entre zero e um")
        self.jev_client = jev_client
        self.jev_confidence_threshold = jev_confidence_threshold
        self.model = (
            None
            if jev_client is not None and model is None
            else get_structured_model(JudgeDecision)
            if model is None
            else model
        )

    @staticmethod
    def _result(
        *,
        status: JudgeStatus,
        reason: str,
        evidence_ids: Sequence[str] = (),
        error_code: str | None = None,
        reason_code: str | None = None,
        confidence: float | None = None,
        probabilities: dict[str, float] | None = None,
        model: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> JudgeResult:
        result: JudgeResult = {
            "status": status,
            "reason": reason,
            "evidence_ids": list(evidence_ids),
        }

        if error_code is not None:
            result["error_code"] = error_code
        if reason_code is not None:
            result["reason_code"] = reason_code
        if confidence is not None:
            result["confidence"] = confidence
        if probabilities is not None:
            result["probabilities"] = probabilities
        if model is not None:
            result["model"] = model
        if input_tokens is not None:
            result["input_tokens"] = input_tokens
        if output_tokens is not None:
            result["output_tokens"] = output_tokens

        return result

    def _validate_draft(
        self,
        response_draft: ResponseDraft | None,
    ) -> JudgeResult | None:
        if response_draft is None:
            return self._result(
                status="invalid",
                reason="A resposta compilada não foi fornecida.",
                error_code="JUDGE_MISSING_DRAFT",
            )

        if response_draft.get("status") != "draft":
            return self._result(
                status="invalid",
                reason="A resposta compilada não está disponível para julgamento.",
                error_code="JUDGE_INVALID_DRAFT_STATUS",
            )

        content = response_draft.get("content")

        if not isinstance(content, str) or not content.strip():
            return self._result(
                status="invalid",
                reason="A resposta compilada não possui conteúdo válido.",
                error_code="JUDGE_INVALID_DRAFT_CONTENT",
            )

        citation_ids = response_draft.get("citations")

        if not isinstance(citation_ids, list) or any(
            not isinstance(evidence_id, str) or not evidence_id.strip()
            for evidence_id in citation_ids
        ):
            return self._result(
                status="invalid",
                reason="As citações da resposta possuem formato inválido.",
                error_code="JUDGE_INVALID_CITATIONS",
            )

        if len(citation_ids) != len(set(citation_ids)):
            return self._result(
                status="invalid",
                reason="A resposta contém citações duplicadas.",
                error_code="JUDGE_DUPLICATED_CITATIONS",
            )

        return None

    def _validated_evidence_ids(
        self,
        evidences: Sequence[Evidence],
    ) -> tuple[list[str], JudgeResult | None]:
        try:
            evidence_ids = [evidence["evidence_id"] for evidence in evidences]
        except KeyError, TypeError:
            return [], self._result(
                status="invalid",
                reason="As evidências possuem estrutura inválida.",
                error_code="JUDGE_INVALID_EVIDENCE",
            )

        if any(
            not isinstance(evidence_id, str) or not evidence_id.strip()
            for evidence_id in evidence_ids
        ):
            return [], self._result(
                status="invalid",
                reason="As evidências possuem identificadores inválidos.",
                error_code="JUDGE_INVALID_EVIDENCE",
            )

        if len(evidence_ids) != len(set(evidence_ids)):
            return [], self._result(
                status="invalid",
                reason="Foram recebidas evidências com identificadores duplicados.",
                error_code="JUDGE_DUPLICATED_EVIDENCE",
            )

        return evidence_ids, None

    def _validate_input(
        self,
        response_draft: ResponseDraft | None,
        evidences: Sequence[Evidence],
    ) -> JudgeResult | None:
        draft_failure = self._validate_draft(response_draft)

        if draft_failure is not None:
            return draft_failure

        evidence_ids, evidence_failure = self._validated_evidence_ids(evidences)

        if evidence_failure is not None:
            return evidence_failure

        current_draft = cast(ResponseDraft, response_draft)
        citation_ids = current_draft["citations"]

        available_ids = set(evidence_ids)
        unknown_ids = [
            evidence_id
            for evidence_id in citation_ids
            if evidence_id not in available_ids
        ]

        if unknown_ids:
            return self._result(
                status="invalid",
                reason="A resposta referencia evidências inexistentes.",
                error_code="JUDGE_UNKNOWN_EVIDENCE",
            )

        if not citation_ids or not evidences:
            return self._result(
                status="insufficient_evidence",
                reason="Não há evidências suficientes para validar a resposta.",
                error_code="JUDGE_INSUFFICIENT_EVIDENCE",
            )

        external_evidences = [
            evidence
            for evidence in evidences
            if evidence.get("source_type") == "a2a_agent"
            and evidence["evidence_id"] in citation_ids
        ]
        if external_evidences:
            content = current_draft["content"].casefold()
            if "segundo o sistema externo de caminhões" not in content:
                return self._result(
                    status="invalid",
                    reason="Resposta A2A sem atribuição ao sistema externo.",
                    error_code="JUDGE_A2A_ATTRIBUTION_MISSING",
                )
            if (
                any(
                    item.get("metadata", {}).get("mock") == "true"
                    for item in external_evidences
                )
                and "simulad" not in content
            ):
                return self._result(
                    status="invalid",
                    reason="Resposta A2A simulada sem indicação de simulação.",
                    error_code="JUDGE_A2A_MOCK_LABEL_MISSING",
                )

        return None

    def _invoke_jev(
        self,
        response_draft: ResponseDraft,
        evidences: Sequence[Evidence],
    ) -> JudgeResult:
        try:
            if self.jev_client is None:
                raise RuntimeError("Cliente JEV não configurado")
            evaluation = self.jev_client.evaluate(
                response_draft=response_draft,
                evidences=evidences,
            )
        except Exception as exc:
            client_code = getattr(exc, "code", "JEV_UNAVAILABLE")
            error_code = (
                "JUDGE_INVALID_OUTPUT"
                if client_code == "JEV_INVALID_OUTPUT"
                else f"JUDGE_{client_code}"
            )
            return self._result(
                status="invalid",
                reason="O agente juiz não conseguiu validar a resposta.",
                error_code=error_code,
            )

        evidence_ids = list(response_draft["citations"])
        if (
            evaluation.verdict == "approved"
            and evaluation.reason_code == "none"
            and evaluation.confidence >= self.jev_confidence_threshold
        ):
            return self._result(
                status="approved",
                reason="Resposta aprovada pelo JEV.",
                evidence_ids=evidence_ids,
                reason_code=evaluation.reason_code,
                confidence=evaluation.confidence,
                probabilities=evaluation.probabilities,
                model=evaluation.model,
                input_tokens=evaluation.input_tokens,
                output_tokens=evaluation.output_tokens,
            )

        reason_code = evaluation.reason_code
        if evaluation.verdict == "approved":
            reason_code = "low_confidence"

        reasons = {
            "missing_evidence": (
                "Não foi encontrada evidência suficiente para confirmar a resposta."
            ),
            "unsupported_claim": (
                "A resposta contém alegações não sustentadas pelas evidências."
            ),
            "contradiction": "A resposta contradiz as evidências disponíveis.",
            "invalid_citation": "As citações não sustentam a resposta.",
            "ambiguous_evidence": (
                "As evidências não permitem confirmar a resposta com segurança."
            ),
            "low_confidence": (
                "A confiança do julgamento não é suficiente para liberar a resposta."
            ),
            "none": "A resposta não foi aprovada pelo JEV.",
        }
        return self._result(
            status="insufficient_evidence",
            reason=reasons[reason_code],
            evidence_ids=evidence_ids,
            error_code=(
                "JUDGE_MISSING_EVIDENCE"
                if reason_code == "missing_evidence"
                else "JUDGE_REJECTED"
            ),
            reason_code=reason_code,
            confidence=evaluation.confidence,
            probabilities=evaluation.probabilities,
            model=evaluation.model,
            input_tokens=evaluation.input_tokens,
            output_tokens=evaluation.output_tokens,
        )

    def _invoke_model(
        self,
        response_draft: ResponseDraft,
        evidences: Sequence[Evidence],
    ) -> JudgeResult:
        if self.model is None:
            return self._result(
                status="invalid",
                reason="O agente juiz não conseguiu validar a resposta.",
                error_code="JUDGE_UNAVAILABLE",
            )

        try:
            raw_decision = self.model.invoke(
                self._messages(
                    response_draft,
                    evidences,
                )
            )
        except Exception:
            return self._result(
                status="invalid",
                reason="O agente juiz não conseguiu validar a resposta.",
                error_code="JUDGE_UNAVAILABLE",
            )

        try:
            decision = (
                raw_decision
                if isinstance(raw_decision, JudgeDecision)
                else JudgeDecision.model_validate(raw_decision)
            )
        except Exception:
            return self._result(
                status="invalid",
                reason="O agente juiz retornou uma saída inválida.",
                error_code="JUDGE_INVALID_OUTPUT",
            )

        available_ids = {evidence["evidence_id"] for evidence in evidences}
        unknown_decision_ids = set(decision.evidence_ids) - available_ids

        if unknown_decision_ids:
            return self._result(
                status="invalid",
                reason="O julgamento referenciou evidências inexistentes.",
                error_code="JUDGE_INVALID_OUTPUT_REFERENCES",
            )

        cited_ids = set(response_draft["citations"])
        evaluated_ids = set(decision.evidence_ids)

        if decision.status == "approved" and evaluated_ids != cited_ids:
            return self._result(
                status="invalid",
                reason=(
                    "O julgamento não avaliou todas as evidências citadas "
                    "pela resposta."
                ),
                error_code="JUDGE_INCOMPLETE_VALIDATION",
            )

        return self._result(
            status=decision.status,
            reason=decision.reason,
            evidence_ids=decision.evidence_ids,
        )

    def _messages(
        self,
        response_draft: ResponseDraft,
        evidences: Sequence[Evidence],
    ) -> list[AnyMessage]:
        payload = json.dumps(
            {
                "response_draft": response_draft,
                "evidences": list(evidences),
            },
            ensure_ascii=False,
        )

        return [
            SystemMessage(content=self.card.system_prompt_template),
            HumanMessage(
                content=(
                    "Avalie a resposta compilada usando exclusivamente o "
                    f"payload a seguir:\n{payload}"
                )
            ),
        ]

    def invoke(
        self,
        *,
        response_draft: ResponseDraft | None,
        evidences: Sequence[Evidence],
    ) -> JudgeResult:
        try:
            input_failure = self._validate_input(
                response_draft,
                evidences,
            )
        except KeyError, TypeError, ValueError:
            return self._result(
                status="invalid",
                reason="O payload recebido pelo agente juiz é inválido.",
                error_code="JUDGE_INVALID_INPUT",
            )

        if input_failure is not None:
            return input_failure

        if self.jev_client is not None:
            return self._invoke_jev(
                cast(ResponseDraft, response_draft),
                evidences,
            )

        return self._invoke_model(
            cast(ResponseDraft, response_draft),
            evidences,
        )
