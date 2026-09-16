from __future__ import annotations

from collections.abc import Sequence

from langchain.agents import create_agent
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph

from src.llm_factory import llm_fast

from .faq_prompt import FAQ_SYSTEM_PROMPT


def create_faq_agent(
    tools: Sequence[BaseTool] | None = None,
) -> CompiledStateGraph:
    return create_agent(
        llm_fast,
        tools=list(tools or []),
        system_prompt=FAQ_SYSTEM_PROMPT,
    )


faq_node = create_faq_agent
faq_app = create_faq_agent
