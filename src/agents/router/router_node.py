"""Router graph node: validate the executor result and update graph state."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Literal, cast, get_args

from src.agents.router.executor import RouterExecutor
from src.graphs.contracts import RouteResponse, RouterRoute
from src.graphs.state import (
    AgentError,
    Evidence,
    GraphState,
    ResponseDraft,
    RoutingDecision,
)

logger = logging.getLogger(__name__)

_ROUTER_ROUTES = frozenset(get_args(RouterRoute))
_SUMMARY_TOOL = "search_conversation_summaries"
_RETRIEVAL_SOURCES = {"temporal", "semantic", "recent_fallback", "none"}


def _is_evidence(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False

    evidence_id = value.get("evidence_id")
    source_id = value.get("source_id")
    content = value.get("content")
    metadata = value.get("metadata")
    if not (
        isinstance(evidence_id, str)
        and evidence_id.strip()
        and value.get("source_type") == "conversation_summary"
        and isinstance(source_id, str)
        and source_id.strip()
        and isinstance(content, str)
        and content.strip()
        and isinstance(metadata, Mapping)
    ):
        return False

    if metadata.get("outcome") == "not_found":
        return True
    source = metadata.get("retrieval_source")
    return isinstance(source, str) and source in _RETRIEVAL_SOURCES


def _valid_response(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    route = value.get("route")
    if not isinstance(route, str) or route not in _ROUTER_ROUTES:
        return False
    status = value.get("status")
    if status not in ("success", "error"):
        return False
    reason = value.get("reason")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 240:
        return False

    error_code = value.get("error_code")
    if error_code is not None and (
        not isinstance(error_code, str) or not error_code.strip()
    ):
        return False
    if status == "error" and error_code is None:
        return False

    tool_called = value.get("tool_called")
    if tool_called is None:
        return True
    if not isinstance(tool_called, Mapping):
        return False
    if tool_called.get("tool_name") != _SUMMARY_TOOL:
        return False
    if tool_called.get("status") not in ("success", "error"):
        return False

    tool_result = tool_called.get("toolResult")
    if not isinstance(tool_result, Mapping):
        return False
    if tool_called.get("status") == "error":
        return True
    if tool_result.get("status") not in ("success", "partial"):
        return False
    data = tool_result.get("data")
    if not isinstance(data, Mapping) or not isinstance(data.get("results"), list):
        return False

    evidence = tool_result.get("evidence")
    return isinstance(evidence, list) and all(_is_evidence(item) for item in evidence)


def _tool_evidence(response: RouteResponse) -> list[Evidence]:
    tool_called = response.get("tool_called")
    if not tool_called or tool_called.get("status") != "success":
        return []

    tool_result = tool_called.get("toolResult")
    if not isinstance(tool_result, Mapping):
        return []

    return cast(list[Evidence], tool_result.get("evidence", []))


def _tool_error(response: RouteResponse) -> tuple[str, bool] | None:
    tool_called = response.get("tool_called")
    if not tool_called:
        return None

    tool_result = tool_called.get("toolResult")
    result_status = (
        tool_result.get("status") if isinstance(tool_result, Mapping) else None
    )
    if tool_called.get("status") != "error" and result_status != "error":
        return None

    error = tool_result.get("error") if isinstance(tool_result, Mapping) else None
    code = error.get("code") if isinstance(error, Mapping) else None
    retryable = error.get("retryable") if isinstance(error, Mapping) else None
    return (
        code if isinstance(code, str) and code.strip() else "MEMORY_SEARCH_UNAVAILABLE",
        retryable if isinstance(retryable, bool) else True,
    )


def _error_update(
    *,
    code: str,
    source: Literal["model", "tool", "executor", "validation"],
    reason: str,
    content: str,
    retryable: bool,
    evidences: list[Evidence],
) -> GraphState:
    error: AgentError = {
        "agent": "router",
        "source": source,
        "code": code,
        "message": reason,
        "retryable": retryable,
    }
    update: dict[str, Any] = {
        "routing_decision": {
            "route": "clarification_required",
            "outcome": "direct_response",
            "reason": reason,
            "status": "error",
        },
        "final_response": {"content": content, "status": "error"},
        "errors": [error],
        "status": "in_progress",
    }
    if evidences:
        update["evidences"] = evidences
    return cast(GraphState, update)


def _memory_recall_response(evidences: list[Evidence]) -> dict[str, str]:
    summaries = [
        evidence
        for evidence in evidences
        if evidence["metadata"].get("outcome") != "not_found"
    ]
    topics = [
        " ".join(evidence["content"].split())[:250]
        for evidence in summaries
        if evidence["content"].strip()
    ]
    lines = "\n".join(
        f"{index}. {topic}" for index, topic in enumerate(topics[:3], start=1)
    )
    if any(
        evidence["metadata"].get("status") == "recent_fallback"
        or evidence["metadata"].get("retrieval_source") == "recent_fallback"
        for evidence in summaries
    ):
        return {
            "content": (
                "Não identifiquei esse assunto nas conversas anteriores. "
                f"Encontrei apenas:\n{lines}\nSobre o que você quer retomar?"
            ),
            "status": "clarification_required",
        }
    if lines:
        return {"content": "Conversamos sobre:\n" + lines, "status": "success"}
    return {
        "content": (
            "Não encontrei a referência que você procura. "
            "Pode me dar mais algum detalhe?"
        ),
        "status": "clarification_required",
    }


def _memory_evidence_status(evidence: Evidence) -> str:
    metadata = evidence["metadata"]
    status = metadata.get("status")
    if status in {"semantic", "temporal", "recent_fallback", "not_found"}:
        return str(status)
    if metadata.get("outcome") == "not_found":
        return "not_found"
    source = metadata.get("retrieval_source")
    if source in {"semantic", "temporal", "recent_fallback"}:
        return str(source)
    return "not_found"


def _cited_memory_evidences(evidences: list[Evidence]) -> list[Evidence]:
    statuses = {_memory_evidence_status(item) for item in evidences}
    if "recent_fallback" in statuses:
        selected = {"recent_fallback"}
    elif statuses & {"semantic", "temporal"}:
        selected = {"semantic", "temporal"}
    else:
        selected = {"not_found"}
    return [item for item in evidences if _memory_evidence_status(item) in selected]


def _memory_recall_draft(evidences: list[Evidence]) -> ResponseDraft:
    response = _memory_recall_response(evidences)
    public_status: Literal["success", "clarification_required"] = (
        "success" if response["status"] == "success" else "clarification_required"
    )
    return {
        "content": response["content"],
        "citations": [
            item["evidence_id"] for item in _cited_memory_evidences(evidences)
        ],
        "status": "draft",
        "origin": "exact",
        "public_status": public_status,
    }


def run_router_node(
    state: GraphState,
    *,
    router: RouterExecutor,
) -> GraphState:
    """Validate the router boundary and project routes and evidence to state."""

    current_state = cast(GraphState, dict(state))
    try:
        raw_response = router.invoke(
            current_state.get("messages", []),
            request_context=current_state.get("request"),
        )
    except Exception:
        return _error_update(
            code="ROUTER_MODEL_UNAVAILABLE",
            source="model",
            reason="O roteador não conseguiu classificar a solicitação.",
            content="Sistema temporariamente indisponível. Tente novamente mais tarde.",
            retryable=True,
            evidences=[],
        )

    if not _valid_response(raw_response):
        return _error_update(
            code="ROUTER_INVALID_OUTPUT",
            source="validation",
            reason="O roteador retornou uma resposta inválida.",
            content="Sistema temporariamente indisponível. Tente novamente mais tarde.",
            retryable=False,
            evidences=[],
        )

    response = cast(RouteResponse, raw_response)
    evidences = _tool_evidence(response)

    tool_error = _tool_error(response)
    if tool_error is not None:
        code, retryable = tool_error
        return _error_update(
            code=code,
            source="tool",
            reason="A busca de conversas anteriores não está disponível.",
            content=(
                "Não foi possível recuperar suas conversas anteriores agora. "
                "Sobre o que você quer retomar?"
            ),
            retryable=retryable,
            evidences=evidences,
        )

    if response["status"] == "error":
        code = response.get("error_code", "ROUTER_UNAVAILABLE")
        source: Literal["model", "tool", "executor", "validation"] = (
            "validation"
            if code == "ROUTER_INVALID_OUTPUT"
            else "executor"
            if code == "MEMORY_SEARCH_UNAVAILABLE"
            else "model"
        )
        return _error_update(
            code=code,
            source=source,
            reason="O roteador não conseguiu classificar a solicitação.",
            content="Sistema temporariamente indisponível. Tente novamente mais tarde.",
            retryable=code != "ROUTER_INVALID_OUTPUT",
            evidences=evidences,
        )

    route = response["route"]
    outcome: Literal[
        "dispatch",
        "clarification_required",
        "out_of_scope",
        "direct_response",
    ]
    if route in {"faq", "product_workflow"}:
        outcome = "dispatch"
    elif route == "clarification_required":
        outcome = "clarification_required"
    elif route == "out_of_scope":
        outcome = "out_of_scope"
    else:
        outcome = "direct_response"

    routing_decision: RoutingDecision = {
        "route": route,
        "outcome": outcome,
        "reason": response["reason"],
        "status": response["status"],
    }
    logger.info(
        "router_decision_completed",
        extra={
            "event": "router_decision_completed",
            "route": route,
            "outcome": outcome,
            "status": response["status"],
        },
    )

    update: dict[str, Any] = {
        "routing_decision": routing_decision,
        "status": "in_progress",
    }
    if evidences:
        update["evidences"] = evidences
    if route == "memory_recall":
        update["response_draft"] = _memory_recall_draft(evidences)
    return cast(GraphState, update)
