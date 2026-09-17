from typing import Any, cast

from src.agents.factory import create_agent_from_card
from src.llm_factory import llm_fast

from .card import FAQ_CARD


class FAQExecutor:
    def __init__(self, model: Any | None = None) -> None:
        self.card = FAQ_CARD
        selected_model = llm_fast if model is None else model
        self.agent = create_agent_from_card(
            card=self.card,
            model=selected_model,
        )

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], self.agent.invoke(state))
