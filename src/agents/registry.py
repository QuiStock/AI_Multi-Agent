from src.agents.compiler.card import COMPILER_CARD
from src.agents.faq.card import FAQ_CARD
from src.agents.judge.card import JUDGE_CARD
from src.agents.router.card import ROUTER_CARD
from src.agents.schemas.agent_card import AgentCard

AGENT_CARDS = {
    FAQ_CARD.id: FAQ_CARD,
    COMPILER_CARD.id: COMPILER_CARD,
    JUDGE_CARD.id: JUDGE_CARD,
    ROUTER_CARD.id: ROUTER_CARD,
}


def get_agent_card(agent_id: str) -> AgentCard:
    try:
        return AGENT_CARDS[agent_id]
    except KeyError as exc:
        raise ValueError(f"Agent not registered: {agent_id}") from exc
