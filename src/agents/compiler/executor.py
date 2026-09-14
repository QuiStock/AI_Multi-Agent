from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import (
    AnyMessage,
    HumanMessage,
    SystemMessage,
)

from src.agents.compiler.card import COMPILER_CARD
from src.context.schemas import CompilerResult
from src.context.state import GraphState
from src.llm_factory import get_structured_model


class CompilerExecutor:
    def __init__(self, model: Any | None = None) -> None:
        self.card = COMPILER_CARD
        self.model = model or get_structured_model(
            CompilerResult,
            kind="fast",
        )

    def _compiler_messages(
        self,
        state: GraphState,
    ) -> list[AnyMessage]:
        outputs = json.dumps(
            state.get("agent_outputs", []),
            ensure_ascii=False,
        )

        context = HumanMessage(
            content=(
                f"Resultados dos agentes especializados, já normalizados:\n{outputs}"
            )
        )

        return [
            SystemMessage(content=self.card.system_prompt_template),
            *state.get("messages", []),
            context,
        ]

    def invoke(
        self,
        state: GraphState,
    ) -> dict[str, Any]:
        if not state.get("agent_outputs"):
            return {
                "validation": {
                    "status": "blocked",
                    "reason": ("Nenhum resultado de agente foi disponibilizado."),
                },
                "final_response": {
                    "content": "Não foi possível gerar uma resposta.",
                    "status": "error",
                },
            }

        try:
            result = self.model.invoke(self._compiler_messages(state))

            if not isinstance(result, CompilerResult):
                result = CompilerResult.model_validate(result)

        except Exception:
            return {
                "validation": {
                    "status": "blocked",
                    "reason": (
                        "A saída do compilador não respeitou o contrato esperado."
                    ),
                },
                "final_response": {
                    "content": ("Não foi possível gerar uma resposta."),
                    "status": "error",
                },
            }
        return {
            "validation": {
                "status": "passed",
                "reason": ("A resposta foi compilada conforme o contrato esperado."),
            },
            "final_response": result.model_dump(),
        }
