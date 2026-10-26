from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from src.graphs.state import Evidence, ResponseDraft

from .contracts import JudgeResponse, JudgeStatus
from .jev_client import JevJudgeClientPort


class JudgeExecutor:
    def __init__(
        self,
        *,
        jev_client: JevJudgeClientPort,
    ) -> None:
        self.jev_client = jev_client

    @staticmethod
    def _result(
        *,
        status: JudgeStatus,
        reason: str,
        evidence_count: int = 0,
        error_code: str | None = None,
        reason_code: str | None = None,
        noul_probability: float | None = None,
        model: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> JudgeResponse:
        result: JudgeResponse = {
            "status": status,
            "reason": reason,
            "evidence_count": evidence_count,
        }

        if error_code is not None:
            result["error_code"] = error_code
        if reason_code is not None:
            result["reason_code"] = reason_code
        if noul_probability is not None:
            result["noul_probability"] = noul_probability
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
    ) -> JudgeResponse | None:
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
    ) -> tuple[list[str], JudgeResponse | None]:
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
        *,
        user_question: str | None,
        response_draft: ResponseDraft | None,
        evidences: Sequence[Evidence],
    ) -> JudgeResponse | None:
        if not isinstance(user_question, str) or not user_question.strip():
            return self._result(
                status="invalid",
                reason="A pergunta atual do usuário não foi fornecida.",
                error_code="JUDGE_MISSING_QUESTION",
            )

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

        cited_evidences = [
            evidence
            for evidence in evidences
            if evidence["evidence_id"] in citation_ids
        ]
        if cited_evidences and all(
            evidence["source_type"] == "conversation_summary"
            for evidence in cited_evidences
        ):
            if current_draft.get("origin") == "exact":
                return None
            return self._result(
                status="insufficient_evidence",
                reason="Memória anterior não confirma dados atuais.",
                error_code="JUDGE_MEMORY_ONLY",
                reason_code="missing_evidence",
            )

        return None

    def _invoke_jev(
        self,
        user_question: str,
        response_draft: ResponseDraft,
        evidences: Sequence[Evidence],
        prior_assistant_message: str | None,
    ) -> JudgeResponse:
        try:
            evaluation = self.jev_client.evaluate(
                user_question=user_question,
                prior_assistant_message=prior_assistant_message,
                response_draft=response_draft,
                evidences=evidences,
            )
        except Exception as exc:
            client_code = getattr(exc, "code", "JEV_UNAVAILABLE")
            return self._result(
                status="invalid",
                reason="O JEV não conseguiu validar a resposta.",
                error_code=f"JUDGE_{client_code}",
            )

        evidence_count = len(response_draft["citations"])
        if evaluation.verdict == "approved" and evaluation.reason_code == "none":
            return self._result(
                status="approved",
                reason="Resposta aprovada pelo JEV.",
                evidence_count=evidence_count,
                reason_code=evaluation.reason_code,
                noul_probability=evaluation.noul_probability,
                model=evaluation.model,
                input_tokens=evaluation.input_tokens,
                output_tokens=evaluation.output_tokens,
            )

        reason_code = evaluation.reason_code

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
            "does_not_answer_question": (
                "A resposta não atende à pergunta atual do usuário."
            ),
            "none": "A resposta não foi aprovada pelo JEV.",
        }
        return self._result(
            status="insufficient_evidence",
            reason=reasons[reason_code],
            evidence_count=evidence_count,
            error_code=(
                "JUDGE_MISSING_EVIDENCE"
                if reason_code == "missing_evidence"
                else "JUDGE_REJECTED"
            ),
            reason_code=reason_code,
            noul_probability=evaluation.noul_probability,
            model=evaluation.model,
            input_tokens=evaluation.input_tokens,
            output_tokens=evaluation.output_tokens,
        )

    def invoke(
        self,
        *,
        user_question: str | None,
        response_draft: ResponseDraft | None,
        evidences: Sequence[Evidence],
        prior_assistant_message: str | None = None,
    ) -> JudgeResponse:
        try:
            input_failure = self._validate_input(
                user_question=user_question,
                response_draft=response_draft,
                evidences=evidences,
            )
        except KeyError, TypeError, ValueError:
            return self._result(
                status="invalid",
                reason="O payload recebido pelo agente juiz é inválido.",
                error_code="JUDGE_INVALID_INPUT",
            )

        if input_failure is not None:
            return input_failure

        return self._invoke_jev(
            cast(str, user_question),
            cast(ResponseDraft, response_draft),
            evidences,
            prior_assistant_message,
        )
