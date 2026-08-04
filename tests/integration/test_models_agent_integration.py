import pytest
from langgraph.graph.state import CompiledStateGraph

from src import config
from src.agents.faq.agent_card import create_faq_agent
from src.models import get_chat_model, get_embeddings

pytestmark = pytest.mark.integration


def _set_fake_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "GEMINI_API_KEY", "fake-key-for-integration")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-integration")


def test_chat_model_uses_configured_model(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_fake_key(monkeypatch)
    assert get_chat_model().model == config.GEMINI_CHAT_MODEL


def test_embeddings_uses_configured_model(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_fake_key(monkeypatch)
    assert get_embeddings().model == config.GEMINI_EMBEDDING_MODEL


def test_faq_agent_builds_compiled_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_fake_key(monkeypatch)
    agent = create_faq_agent()
    assert isinstance(agent, CompiledStateGraph)
