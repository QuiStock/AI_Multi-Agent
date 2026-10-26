from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AnyMessage, HumanMessage

from src.agents.compiler.card import COMPILER_CARD
from src.agents.compiler.contracts import CompilerResponse
from src.agents.factory import create_agent_from_card
from src.graphs.contracts import CompilerResult
from src.graphs.state import (
    AgentResults,
    Evidence,
    JudgeFeedback,
)
from src.llm_factory import llm_openai


class CompilerExecutor:
    def __init__(
        self,
        model: Any | None = None,
        *,
        agent_factory: Any | None = None,
    ) -> None:
        self.card = COMPILER_CARD
        self.model = llm_openai if model is None else model
        self.agent_factory = (
            create_agent_from_card if agent_factory is None else agent_factory
        )
        self.agent = self.agent_factory(
            card=self.card,
            model=self.model,
            tools=[],
            response_format=CompilerResult,
        )

    def _compiler_messages(
        self,
        *,
        messages: Sequence[AnyMessage],
        agent_results: AgentResults,
        evidences: Sequence[Evidence],
        judge_feedback: JudgeFeedback | None,
    ) -> list[AnyMessage]:
        payload_data: dict[str, object] = {
            "agent_results": agent_results,
            "evidences": list(evidences),
        }
        if judge_feedback is not None:
            payload_data["judge_feedback"] = judge_feedback

        payload = json.dumps(payload_data, ensure_ascii=False)

        context = (
            "Resultados dos agentes especializados e evidências "
            f"disponíveis:\n{payload}"
        )
        if judge_feedback is not None:
            context += (
                "\n\nA resposta candidata anterior foi rejeitada. Faça uma única "
                "reformulação usando somente as evidências disponíveis e "
                "corrija o problema indicado em judge_feedback. Não invente "
                "evidências nem fatos."
            )

        return [*messages, HumanMessage(content=context)]

    def invoke(
        self,
        *,
        messages: Sequence[AnyMessage],
        agent_results: AgentResults,
        evidences: Sequence[Evidence],
        judge_feedback: JudgeFeedback | None = None,
    ) -> CompilerResponse:
        if not agent_results:
            return {
                "content": "Não foi possível gerar uma resposta.",
                "citations": [],
                "status": "blocked",
                "error_code": "COMPILER_NO_AGENT_RESULTS",
            }

        try:
            raw_result = self.agent.invoke(
                {
                    "messages": self._compiler_messages(
                        messages=messages,
                        agent_results=agent_results,
                        evidences=evidences,
                        judge_feedback=judge_feedback,
                    )
                }
            )
            if not isinstance(raw_result, dict):
                raise TypeError("A saída do compiler agent deve ser um dicionário")
            result = raw_result.get("structured_response")
            if not isinstance(result, CompilerResult):
                result = CompilerResult.model_validate(result)

        except Exception:
            return {
                "content": "Não foi possível gerar uma resposta.",
                "citations": [],
                "status": "blocked",
                "error_code": "COMPILER_EXECUTION_FAILED",
            }

        return {
            "content": result.content,
            "citations": list(result.citations),
            "status": "success" if result.status == "success" else "blocked",
        }
