from typing import Any, cast

from src.agents.factory import create_agent_from_card

from .card import FAQ_CARD


class FAQExecutor:
    def __init__(self, model: Any) -> None:
        self.card = FAQ_CARD
        self.agent = create_agent_from_card(
            card=self.card,
            model=model,
        )

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], self.agent.invoke(state))
