"""Compiler node for normalizing responses from specialized agents."""

from __future__ import annotations

import json
from collections.abc import Callable
from functools import partial
from typing import Any

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage
from pydantic import ValidationError

from src.context.schemas import CompilerResult
from src.context.state import GraphState
from src.llm_factory import get_structured_model

from .compiler_prompt import COMPILER_SYSTEM_PROMPT


def _compiler_messages(state: GraphState) -> list[AnyMessage]:
    outputs = json.dumps(
        state.get("agent_outputs", []),
        ensure_ascii=False,
    )
    context = HumanMessage(
        content=(f"Resultados dos agentes especializados, já normalizados:\n{outputs}")
    )
    return [
        SystemMessage(content=COMPILER_SYSTEM_PROMPT),
        *state.get("messages", []),
        context,
    ]


def compile_response_state(
    state: GraphState,
    *,
    structured_model: Any,
) -> dict[str, Any]:
    """Compile specialized-agent outputs into the final response contract."""

    if not state.get("agent_outputs"):
        return {
            "validation": {
                "status": "blocked",
                "reason": "Nenhum resultado de agente foi disponibilizado.",
            },
            "final_response": {
                "content": "Não foi possível gerar uma resposta.",
                "status": "error",
            },
        }

    try:
        result = structured_model.invoke(_compiler_messages(state))
        if not isinstance(result, CompilerResult):
            result = CompilerResult.model_validate(result)
    except ValidationError:
        return {
            "validation": {
                "status": "blocked",
                "reason": "A saída do compilador não respeitou o contrato esperado.",
            },
            "final_response": {
                "content": "Não foi possível gerar uma resposta.",
                "status": "error",
            },
        }

    return {
        "validation": {
            "status": "passed",
            "reason": "A resposta foi compilada conforme o contrato esperado.",
        },
        "final_response": result.model_dump(),
    }


def create_compiler_node(
    model: Any | None = None,
) -> Callable[[GraphState], dict[str, Any]]:
    """Create a compiler node with optional structured-model injection."""

    structured_model = model or get_structured_model(CompilerResult, kind="fast")
    return partial(compile_response_state, structured_model=structured_model)


compiler_node = create_compiler_node
