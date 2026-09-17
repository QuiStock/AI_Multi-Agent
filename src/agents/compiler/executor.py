from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import (
    AnyMessage,
    HumanMessage,
    SystemMessage,
)

from src.agents.compiler.card import COMPILER_CARD
from src.graphs.contracts import CompilerResult
from src.graphs.state import GraphState, ResponseDraft
from src.llm_factory import get_structured_model


class CompilerExecutor:
    def __init__(self, model: Any | None = None) -> None:
        self.card = COMPILER_CARD
        self.model = (
            get_structured_model(
                CompilerResult,
                kind="fast",
            )
            if model is None
            else model
        )

    def _compiler_messages(
        self,
        state: GraphState,
    ) -> list[AnyMessage]:
        payload = json.dumps(
            {
                "agent_results": state.get("agent_results", {}),
                "evidences": state.get("evidences", []),
            },
            ensure_ascii=False,
        )

        context = HumanMessage(
            content=(
                f"Resultados dos agentes especializados, já normalizados:\n{payload}"
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
    ) -> ResponseDraft:
        if not state.get("agent_results"):
            return {
                "content": "Não foi possível gerar uma resposta.",
                "citations": [],
                "status": "blocked",
            }

        try:
            result = self.model.invoke(self._compiler_messages(state))

            if not isinstance(result, CompilerResult):
                result = CompilerResult.model_validate(result)

        except Exception:
            return {
                "content": "Não foi possível gerar uma resposta.",
                "citations": [],
                "status": "blocked",
            }

        judge_result = state.get("agent_results", {}).get("judge")
        citations = (
            list(judge_result.get("evidence_ids", []))
            if judge_result is not None
            else []
        )

        return {
            "content": result.content,
            "citations": citations,
            "status": "draft" if result.status == "success" else "blocked",
        }
