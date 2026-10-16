from __future__ import annotations

from collections.abc import Sequence

from langchain.agents import create_agent
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph

from src.agents.faq.faq_prompt import FAQ_SYSTEM_PROMPT
from src.models import get_chat_model

SYSTEM_PROMPT = FAQ_SYSTEM_PROMPT


def create_faq_agent(
    tools: Sequence[BaseTool] | None = None,
) -> CompiledStateGraph:
    model = get_chat_model()
    return create_agent(model, tools=list(tools or []), system_prompt=SYSTEM_PROMPT)


faq_app = create_faq_agent
