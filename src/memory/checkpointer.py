"""Local LangGraph checkpointer configuration."""

from langgraph.checkpoint.memory import MemorySaver


def create_local_checkpointer() -> MemorySaver:
    """Create the in-memory saver used by local development and tests."""
    return MemorySaver()
