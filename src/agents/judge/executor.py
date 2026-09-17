from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, Literal, cast

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage

from src.graphs.contracts import JudgeDecision
from src.graphs.state import Evidence, JudgeResult, ResponseDraft
from src.llm_factory import get_structured_model

from .card import JUDGE_CARD

JudgeStatus = Literal[
    "approved",
    "insufficient_evidence",
    "invalid",
]


class JudgeExecutor:
    def __init__(self, model: Any | None = None) -> None:
        self.card = JUDGE_CARD
        self.model = (
            get_structured_model(
                JudgeDecision,
                kind="fast",
            )
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
    ) -> JudgeResult:
        result: JudgeResult = {
            "status": status,
            "reason": reason,
            "evidence_ids": list(evidence_ids),
        }

        if error_code is not None:
            result["error_code"] = error_code

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

        return None

    def _invoke_model(
        self,
        response_draft: ResponseDraft,
        evidences: Sequence[Evidence],
    ) -> JudgeResult:
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

        return self._invoke_model(
            cast(ResponseDraft, response_draft),
            evidences,
        )
