from typing import Any

from langchain.agents import create_agent

from src.agents.schemas.agent_card import AgentCard
from src.agents.tool_registry import get_tool


def create_agent_from_card(
    card: AgentCard,
    model: Any,
) -> Any:
    tools = [get_tool(tool_binding.id) for tool_binding in card.tools]

    return create_agent(
        model=model, tools=tools, system_prompt=card.system_prompt_template
    )
