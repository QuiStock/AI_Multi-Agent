from __future__ import annotations

import logging

from src.agents.compiler.executor import CompilerExecutor
from src.graphs.state import (
    AgentError,
    GraphState,
    ResponseDraft,
)

logger = logging.getLogger(__name__)

COMPILER_BLOCKED_RESPONSE = (
    "Não foi possível gerar uma resposta agora. Tente novamente mais tarde."
)


def run_compiler_node(
    state: GraphState,
    *,
    compiler: CompilerExecutor,
) -> GraphState:
    try:
        judge_state = state.get("judge")
        result = compiler.invoke(
            messages=state.get("messages", []),
            agent_results=state.get("agent_results", {}),
            evidences=state.get("evidences", []),
            judge_feedback=(
                judge_state.get("judge_feedback") if judge_state is not None else None
            ),
        )
    except Exception:
        result = {
            "content": "Não foi possível gerar uma resposta.",
            "citations": [],
            "status": "blocked",
            "error_code": "COMPILER_NODE_FAILURE",
        }
    logger.info(
        "response_compiler_completed",
        extra={
            "event": "agent_completed",
            "status": result["status"],
            "citation_count": len(result["citations"]),
            "error_code": result.get("error_code"),
        },
    )

    response_draft: ResponseDraft = {
        "content": result["content"],
        "citations": result["citations"],
        "status": "draft" if result["status"] == "success" else "blocked",
    }
    update: GraphState = {
        "response_draft": response_draft,
    }
    error_code = result.get("error_code")
    if error_code:
        error: AgentError = {
            "agent": "compiler",
            "source": (
                "model" if error_code == "COMPILER_EXECUTION_FAILED" else "executor"
            ),
            "code": error_code,
            "message": "O compiler não conseguiu gerar uma resposta.",
            "retryable": error_code
            in {"COMPILER_EXECUTION_FAILED", "COMPILER_NODE_FAILURE"},
        }
        update["errors"] = [error]
    return update


def compiler_blocked_node(_: GraphState) -> GraphState:
    return {
        "final_response": {
            "content": COMPILER_BLOCKED_RESPONSE,
            "status": "error",
        },
        "response_draft": None,
        "status": "completed",
    }
