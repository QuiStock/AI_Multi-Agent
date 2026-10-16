"""LLM-backed greeting gate used by the input guardrail flow."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage

from src.graphs.contracts import GreetingDecision
from src.llm_factory import get_structured_model

GREETING_RESPONSE = "Oi, tudo bem! Qual é a sua necessidade dentro do Quistock?"
MAX_GREETING_CLASSIFIER_CHARS = 160

GREETING_CLASSIFIER_SYSTEM_PROMPT = """Você é um classificador de saudações.

Classifique somente a mensagem atual e retorne uma saída estruturada com uma
das categorias abaixo:
- greeting_only: a mensagem contém apenas uma saudação;
- normal_request: a mensagem contém uma pergunta, pedido ou assunto além da
  saudação.

Não responda ao usuário, não use ferramentas e não invente categorias.
"""


def _latest_human_text(messages: Sequence[AnyMessage]) -> str:
    for message in reversed(messages):
        if getattr(message, "type", None) != "human":
            continue
        content = getattr(message, "content", "")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            return " ".join(
                str(item.get("text", ""))
                for item in content
                if isinstance(item, dict) and item.get("text")
            ).strip()
    return ""


class GreetingGuardrail:
    """Classify short greeting candidates before memory and routing."""

    def __init__(self, model: Any | None = None) -> None:
        self.model = get_structured_model(GreetingDecision) if model is None else model

    @staticmethod
    def _normal_request() -> GreetingDecision:
        return GreetingDecision(category="normal_request")

    def invoke(
        self,
        messages: Sequence[AnyMessage],
        *,
        request_context: Mapping[str, Any] | None = None,
    ) -> GreetingDecision:
        del request_context
        text = _latest_human_text(messages)
        if not text or len(text) > MAX_GREETING_CLASSIFIER_CHARS:
            return self._normal_request()

        try:
            raw_decision = self.model.invoke(
                [
                    SystemMessage(content=GREETING_CLASSIFIER_SYSTEM_PROMPT),
                    HumanMessage(content=text),
                ]
            )
            if isinstance(raw_decision, GreetingDecision):
                return raw_decision
            return GreetingDecision.model_validate(raw_decision)
        except Exception:
            # The gate is an optimization; failures must reach the normal router.
            return self._normal_request()
