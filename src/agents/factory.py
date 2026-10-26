from collections.abc import Sequence
from typing import Any

from langchain.agents import create_agent
from langchain_core.tools import BaseTool
from pydantic import BaseModel

from src.agents.schemas.agent_card import AgentCard


def create_agent_from_card(
    card: AgentCard,
    model: Any,
    *,
    tools: Sequence[BaseTool],
    response_format: type[BaseModel] | None = None,
) -> Any:
    resolved_tools = list(tools)
    expected_ids = {tool_binding.id for tool_binding in card.tools}
    actual_ids = {tool.name for tool in resolved_tools}
    if actual_ids != expected_ids:
        raise ValueError("Runtime tools must match the AgentCard tool IDs")

    if response_format is None:
        return create_agent(
            model=model,
            tools=resolved_tools,
            system_prompt=card.system_prompt_template,
        )
    return create_agent(
        model=model,
        tools=resolved_tools,
        system_prompt=card.system_prompt_template,
        response_format=response_format,
    )
