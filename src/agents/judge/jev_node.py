from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Literal, cast

from langchain_core.messages import AIMessage, HumanMessage

from src.agents.judge.contracts import JudgeResponse
from src.agents.judge.executor import JudgeExecutor
from src.graphs.state import (
    AgentError,
    FinalResponseStatus,
    GraphState,
    JudgeState,
)

logger = logging.getLogger(__name__)

JUDGE_BLOCKED_RESPONSE = (
    "Não encontrei informação documentada suficiente no Quistock para responder "
    "a essa pergunta. Posso ajudar com outra dúvida sobre o Quistock?"
)
JEV_UNAVAILABLE_RESPONSE = "Desculpe, estamos com instabilidade com o fefo."
_FINAL_RESPONSE_STATUSES = frozenset(
    {
        "success",
        "rejected",
        "clarification_required",
        "out_of_scope",
        "error",
    }
)


def _public_status(response_draft: object) -> FinalResponseStatus:
    if isinstance(response_draft, Mapping):
        candidate = response_draft.get("public_status")
        if candidate in _FINAL_RESPONSE_STATUSES:
            return cast(FinalResponseStatus, candidate)
    return "success"


def _project_judge_state(
    response: JudgeResponse,
    *,
    current: JudgeState | None,
) -> JudgeState:
    judge_state: JudgeState = {
        "status": response["status"],
        "reason": response["reason"],
        "evidence_count": response["evidence_count"],
        "repair_attempts": current["repair_attempts"] if current else 0,
    }
    if "reason_code" in response:
        judge_state["reason_code"] = response["reason_code"]
    if "noul_probability" in response:
        judge_state["noul_probability"] = response["noul_probability"]
    if "model" in response:
        judge_state["model"] = response["model"]
    if "input_tokens" in response:
        judge_state["input_tokens"] = response["input_tokens"]
    if "output_tokens" in response:
        judge_state["output_tokens"] = response["output_tokens"]
    if current is not None and "judge_feedback" in current:
        judge_state["judge_feedback"] = current["judge_feedback"]
    return judge_state


def _prior_assistant_message(
    messages: Sequence[object],
    user_message_id: str | None,
) -> str | None:
    if user_message_id is None:
        return None
    current_index = next(
        (
            index
            for index, message in enumerate(messages)
            if isinstance(message, HumanMessage) and message.id == user_message_id
        ),
        None,
    )
    if current_index is None:
        return None
    for message in reversed(messages[:current_index]):
        if isinstance(message, AIMessage) and isinstance(message.content, str):
            text = message.content.strip()
            if text:
                return text
    return None


def run_judge_node(
    state: GraphState,
    *,
    judge: JudgeExecutor,
) -> GraphState:
    request = state.get("request")
    request_id = request.get("request_id") if request else None
    user_message_id = (
        f"{request_id}:user"
        if isinstance(request_id, str) and request_id.strip()
        else None
    )
    messages = state.get("messages", [])
    user_question = next(
        (
            message.content
            for message in messages
            if (
                user_message_id is not None
                and isinstance(message, HumanMessage)
                and message.id == user_message_id
                and isinstance(message.content, str)
            )
        ),
        None,
    )
    response_draft = state.get("response_draft")
    response: JudgeResponse
    try:
        response = judge.invoke(
            user_question=user_question,
            prior_assistant_message=_prior_assistant_message(messages, user_message_id),
            response_draft=response_draft,
            evidences=state.get("evidences", []),
        )
    except Exception:
        response = {
            "status": "invalid",
            "reason": "O agente juiz não conseguiu validar a resposta.",
            "evidence_count": 0,
            "error_code": "JUDGE_ADAPTER_FAILURE",
        }

    draft_content = (
        response_draft.get("content") if isinstance(response_draft, Mapping) else None
    )
    approved_content: str | None = None
    if response["status"] == "approved":
        if isinstance(draft_content, str) and draft_content.strip():
            approved_content = draft_content
        else:
            response = {
                "status": "invalid",
                "reason": "O judge aprovou uma resposta sem draft válido.",
                "evidence_count": 0,
                "error_code": "JUDGE_MISSING_DRAFT",
            }

    error_code = response.get("error_code")
    judge_result = _project_judge_state(response, current=state.get("judge"))

    errors: list[AgentError] = []
    if error_code:
        source: Literal["model", "tool", "executor", "validation"] = (
            "model"
            if error_code.startswith("JUDGE_JEV_")
            or error_code in {"JUDGE_REJECTED", "JUDGE_MISSING_EVIDENCE"}
            else "validation"
            if error_code.startswith("JUDGE_INVALID_")
            or error_code
            in {
                "JUDGE_MISSING_QUESTION",
                "JUDGE_UNKNOWN_EVIDENCE",
                "JUDGE_DUPLICATED_EVIDENCE",
                "JUDGE_INSUFFICIENT_EVIDENCE",
                "JUDGE_MEMORY_ONLY",
            }
            else "executor"
        )
        errors.append(
            {
                "agent": "judge",
                "source": source,
                "code": error_code,
                "message": response["reason"],
                "retryable": error_code.startswith("JUDGE_JEV_")
                and error_code != "JUDGE_JEV_INVALID_OUTPUT",
            }
        )

    logger.info(
        "judge_evaluation_completed",
        extra={
            "event": "judge_evaluation_completed",
            "judge_status": judge_result["status"],
            "evidence_count": judge_result["evidence_count"],
            "judge_error_code": error_code,
            "judge_reason_code": judge_result.get("reason_code"),
            "judge_noul_probability": judge_result.get("noul_probability"),
            "judge_model": judge_result.get("model"),
            "judge_input_tokens": judge_result.get("input_tokens"),
            "judge_output_tokens": judge_result.get("output_tokens"),
        },
    )

    update: GraphState = {
        "judge": judge_result,
    }
    if errors:
        update["errors"] = errors
    if approved_content is not None:
        update["final_response"] = {
            "content": approved_content,
            "status": _public_status(response_draft),
        }
        update["response_draft"] = None

    return update


def judge_blocked_node(state: GraphState) -> GraphState:
    judge_result = state.get("judge")
    judge_error = next(
        (
            error
            for error in reversed(state.get("errors", []))
            if error.get("agent") == "judge"
        ),
        None,
    )
    error_code = judge_error.get("code") if judge_error else None
    content = "Não foi possível validar a resposta gerada."
    response_status: Literal["error", "clarification_required"] = "error"

    if isinstance(error_code, str) and error_code.startswith("JUDGE_JEV_"):
        content = JEV_UNAVAILABLE_RESPONSE
    elif judge_result and judge_result.get("reason_code") == "missing_evidence":
        content = JUDGE_BLOCKED_RESPONSE
        response_status = "clarification_required"
    elif judge_result and judge_result["status"] == "insufficient_evidence":
        content = JUDGE_BLOCKED_RESPONSE
        response_status = "clarification_required"

    return {
        "final_response": {
            "content": content,
            "status": response_status,
        },
        "response_draft": None,
        "status": "completed",
    }
