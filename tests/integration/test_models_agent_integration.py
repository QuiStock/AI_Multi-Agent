import pytest

from src import config, llm_factory
from src.agents.faq.executor import FAQExecutor
from src.agents.faq.tools.faq_tool import create_faq_search_tool
from src.agents.registry import get_agent_card
from src.graphs.contracts import RouteDecision
from src.models.gemini import get_chat_model, get_embeddings

pytestmark = pytest.mark.integration


class FakeRetriever:
    def search(self, query: str) -> list[dict[str, object]]:
        return []


def _set_fake_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "GEMINI_API_KEY", "fake-key-for-integration")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-integration")


def test_chat_model_uses_configured_model(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_fake_key(monkeypatch)
    assert get_chat_model().model == config.GEMINI_CHAT_MODEL


def test_embeddings_uses_configured_model(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_fake_key(monkeypatch)
    assert get_embeddings().model == config.GEMINI_EMBEDDING_MODEL


def test_faq_executor_builds_compiled_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_fake_key(monkeypatch)
    executor = FAQExecutor(retriever=FakeRetriever())
    tool = create_faq_search_tool(
        FakeRetriever(),
        allowed_audiences=("shared", "manager"),
    )

    assert executor.model is not None
    assert tool.name == "faq_search"


def test_structured_model_binds_fast_and_gemini_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRunnable:
        def __init__(self) -> None:
            self.fallbacks: list[FakeRunnable] = []

        def with_fallbacks(
            self,
            fallbacks: list[FakeRunnable],
        ) -> FakeRunnable:
            self.fallbacks = fallbacks
            return self

    class FakeProvider:
        def with_structured_output(
            self,
            _: type[RouteDecision],
        ) -> FakeRunnable:
            return FakeRunnable()

    monkeypatch.setattr(llm_factory, "llm_groq", FakeProvider())
    monkeypatch.setattr(llm_factory, "llm_gemini", FakeProvider())
    monkeypatch.setattr(llm_factory, "llm_groq", FakeProvider())

    groq = llm_factory.get_structured_model(RouteDecision, provider="groq")
    default = llm_factory.get_structured_model(RouteDecision)

    assert isinstance(groq, FakeRunnable)
    assert isinstance(default, FakeRunnable)
    assert default.fallbacks == []


def test_agent_registry_rejects_unknown_agent() -> None:
    with pytest.raises(ValueError, match="Agent not registered"):
        get_agent_card("unknown-agent")
