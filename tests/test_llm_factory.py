from __future__ import annotations

from typing import Any

from src import config, llm_factory
from src.agents.compiler import executor as compiler_module
from src.agents.faq import executor as faq_module
from src.agents.judge import executor as judge_module
from src.agents.router import executor as router_module
from src.graphs.contracts import CompilerResult, JudgeDecision, RouteDecision
from src.memory.worker.title_generator import ConversationTitle


class FakeStructuredRunnable:
    def __init__(self, schema: type[Any]) -> None:
        self.schema = schema
        self.fallbacks: list[Any] = []

    def with_fallbacks(self, fallbacks: list[Any]) -> FakeStructuredRunnable:
        self.fallbacks = fallbacks
        return self


class FakeModel:
    def __init__(self) -> None:
        self.schemas: list[type[Any]] = []

    def with_structured_output(self, schema: type[Any]) -> FakeStructuredRunnable:
        self.schemas.append(schema)
        return FakeStructuredRunnable(schema)


def test_factory_uses_configured_provider_models() -> None:
    assert llm_factory.llm_gemini.model == config.GEMINI_CHAT_MODEL
    assert llm_factory.llm_groq.model == config.GROQ_CHAT_MODEL
    assert llm_factory.llm_huggingface.model == config.HF_TITLE_MODEL
    assert llm_factory.llm_groq.model == config.GROQ_CHAT_MODEL
    assert llm_factory.embeddings.model == config.GEMINI_EMBEDDING_MODEL


def test_default_structured_model_binds_schema_to_gemini(
    monkeypatch: Any,
) -> None:
    primary = FakeModel()
    monkeypatch.setattr(llm_factory, "llm_gemini", primary)

    result = llm_factory.get_structured_model(RouteDecision)

    assert isinstance(result, FakeStructuredRunnable)
    assert primary.schemas == [RouteDecision]
    assert result.fallbacks == []


def test_groq_structured_model_uses_selected_provider(
    monkeypatch: Any,
) -> None:
    groq_model = FakeModel()
    gemini_model = FakeModel()
    monkeypatch.setattr(llm_factory, "llm_groq", groq_model)
    monkeypatch.setattr(llm_factory, "llm_gemini", gemini_model)

    result = llm_factory.get_structured_model(CompilerResult, provider="groq")

    assert isinstance(result, FakeStructuredRunnable)
    assert groq_model.schemas == [CompilerResult]
    assert gemini_model.schemas == []


def test_title_model_uses_huggingface_model(monkeypatch: Any) -> None:
    title_model = FakeModel()
    monkeypatch.setattr(llm_factory, "llm_huggingface", title_model)

    result = llm_factory.get_title_model(ConversationTitle)

    assert isinstance(result, FakeStructuredRunnable)
    assert title_model.schemas == [ConversationTitle]


def test_faq_executor_uses_groq_model_by_default(monkeypatch: Any) -> None:
    sentinel_model = object()
    captured: dict[str, Any] = {}

    class FakeRetriever:
        def search(
            self,
            query: str,
            *,
            allowed_audiences: tuple[str, ...],
        ) -> list[dict[str, object]]:
            return []

    class FakeAgent:
        def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
            return {"messages": []}

    def fake_create_agent_from_card(
        *,
        card: Any,
        model: Any,
        tools: list[Any],
    ) -> object:
        captured["card"] = card
        captured["model"] = model
        captured["tools"] = tools
        return FakeAgent()

    monkeypatch.setattr(faq_module, "llm_groq", sentinel_model)
    monkeypatch.setattr(
        faq_module,
        "create_agent_from_card",
        fake_create_agent_from_card,
    )

    executor = faq_module.FAQExecutor(
        retriever=FakeRetriever(),
    )
    executor.invoke(
        {
            "request": {"role_id": 2},
            "messages": [],
        }
    )

    assert captured["model"] is sentinel_model
    assert captured["tools"][0].name == "faq_search"


def test_router_uses_default_structured_model(monkeypatch: Any) -> None:
    sentinel_model = object()
    captured: dict[str, Any] = {}

    def fake_structured_model(schema: type[Any]) -> object:
        captured["schema"] = schema
        return sentinel_model

    monkeypatch.setattr(router_module, "get_structured_model", fake_structured_model)

    executor = router_module.RouterExecutor()

    assert executor.model is sentinel_model
    assert captured["schema"] is RouteDecision


def test_compiler_uses_gemini_structured_model(monkeypatch: Any) -> None:
    sentinel_model = object()
    captured: dict[str, Any] = {}

    def fake_structured_model(
        schema: type[Any],
        *,
        provider: str = "gemini",
    ) -> object:
        captured["schema"] = schema
        captured["provider"] = provider
        return sentinel_model

    monkeypatch.setattr(
        compiler_module,
        "get_structured_model",
        fake_structured_model,
    )

    executor = compiler_module.CompilerExecutor()

    assert executor.model is sentinel_model
    assert captured == {"schema": CompilerResult, "provider": "gemini"}


def test_judge_uses_gemini_structured_model(monkeypatch: Any) -> None:
    sentinel_model = object()
    captured: dict[str, Any] = {}

    def fake_structured_model(
        schema: type[Any],
        *,
        provider: str = "gemini",
    ) -> object:
        captured["schema"] = schema
        captured["provider"] = provider
        return sentinel_model

    monkeypatch.setattr(
        judge_module,
        "get_structured_model",
        fake_structured_model,
    )

    executor = judge_module.JudgeExecutor()

    assert executor.model is sentinel_model
    assert captured == {"schema": JudgeDecision, "provider": "gemini"}
