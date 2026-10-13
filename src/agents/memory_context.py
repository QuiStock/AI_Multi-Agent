"""Build an independently callable memory tool for a specialist agent."""

from langchain_core.tools import BaseTool

from src.agents.router.tools.search_conversation_summaries import (
    SummarySearchService,
    build_search_conversation_summaries_tool,
    resolve_summary_tool_context,
)
from src.graphs.state import GraphState


def memory_tool_for_state(
    *, service: SummarySearchService | None, state: GraphState
) -> BaseTool | None:
    """Bind the authenticated user and current message to this agent's tool."""
    if service is None:
        return None
    context = resolve_summary_tool_context(
        state.get("messages", []), state.get("request")
    )
    if context is None:
        return None
    return build_search_conversation_summaries_tool(service=service, context=context)
