from __future__ import annotations

from langchain.agents import create_agent
from langgraph.graph.state import CompiledStateGraph

from src.llm_factory import llm_fast

from .faq_prompt import FAQ_SYSTEM_PROMPT
from .tools.faq_tool import faq_search


def create_faq_agent() -> CompiledStateGraph:
    return create_agent(
        llm_fast,
        tools=[faq_search],
        system_prompt=FAQ_SYSTEM_PROMPT,
    )


faq_node = create_faq_agent
faq_app = create_faq_agent
