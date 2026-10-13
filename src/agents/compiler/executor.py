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
        self.model = get_structured_model(CompilerResult) if model is None else model

    def _compiler_messages(
        self,
        state: GraphState,
    ) -> list[AnyMessage]:
        payload_data: dict[str, object] = {
            "agent_results": state.get("agent_results", {}),
            "evidences": state.get("evidences", []),
        }
        judge_feedback = state.get("judge_feedback")
        if judge_feedback is not None:
            payload_data["judge_feedback"] = judge_feedback

        payload = json.dumps(payload_data, ensure_ascii=False)

        context = HumanMessage(
            content=(
                "Resultados dos agentes especializados e evidências "
                f"disponíveis:\n{payload}"
            )
        )
        if judge_feedback is not None:
            context = HumanMessage(
                content=(
                    f"{context.content}\n\n"
                    "A resposta candidata anterior foi rejeitada. Faça uma única "
                    "reformulação usando somente as evidências disponíveis e "
                    "corrija o problema indicado em judge_feedback. Não invente "
                    "evidências nem fatos."
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

        return {
            "content": result.content,
            "citations": list(result.citations),
            "status": ("draft" if result.status == "success" else "blocked"),
        }
