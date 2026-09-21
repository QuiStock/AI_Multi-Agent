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
    assert llm_factory.llm_gemini_title.model == config.GEMINI_TITLE_MODEL
    assert llm_factory.llm_fast.model == config.GROQ_FAST_MODEL
    assert llm_factory.embeddings.model == config.GEMINI_EMBEDDING_MODEL


def test_default_structured_model_binds_schema_before_fallback(
    monkeypatch: Any,
) -> None:
    primary = FakeModel()
    fallback = FakeModel()
    monkeypatch.setattr(llm_factory, "llm_gemini", primary)
    monkeypatch.setattr(llm_factory, "llm_groq", fallback)

    result = llm_factory.get_structured_model(RouteDecision)

    assert isinstance(result, FakeStructuredRunnable)
    assert primary.schemas == [RouteDecision]
    assert fallback.schemas == [RouteDecision]
    assert result.fallbacks
    assert result.fallbacks[0].schema is RouteDecision


def test_fast_structured_model_does_not_create_default_fallback(
    monkeypatch: Any,
) -> None:
    fast = FakeModel()
    primary = FakeModel()
    fallback = FakeModel()
    monkeypatch.setattr(llm_factory, "llm_fast", fast)
    monkeypatch.setattr(llm_factory, "llm_gemini", primary)
    monkeypatch.setattr(llm_factory, "llm_groq", fallback)

    result = llm_factory.get_structured_model(CompilerResult, kind="fast")

    assert isinstance(result, FakeStructuredRunnable)
    assert fast.schemas == [CompilerResult]
    assert primary.schemas == []
    assert fallback.schemas == []


def test_title_model_uses_dedicated_gemini_model(monkeypatch: Any) -> None:
    title_model = FakeModel()
    monkeypatch.setattr(llm_factory, "llm_gemini_title", title_model)

    result = llm_factory.get_title_model(ConversationTitle)

    assert isinstance(result, FakeStructuredRunnable)
    assert title_model.schemas == [ConversationTitle]


def test_faq_executor_uses_fast_model_by_default(monkeypatch: Any) -> None:
    sentinel_model = object()
    captured: dict[str, Any] = {}

    def fake_create_agent_from_card(*, card: Any, model: Any) -> object:
        captured["card"] = card
        captured["model"] = model
        return object()

    monkeypatch.setattr(faq_module, "llm_fast", sentinel_model)
    monkeypatch.setattr(
        faq_module,
        "create_agent_from_card",
        fake_create_agent_from_card,
    )

    executor = faq_module.FAQExecutor()

    assert executor.agent is not None
    assert captured["model"] is sentinel_model


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


def test_compiler_uses_fast_structured_model(monkeypatch: Any) -> None:
    sentinel_model = object()
    captured: dict[str, Any] = {}

    def fake_structured_model(schema: type[Any], *, kind: str) -> object:
        captured["schema"] = schema
        captured["kind"] = kind
        return sentinel_model

    monkeypatch.setattr(
        compiler_module,
        "get_structured_model",
        fake_structured_model,
    )

    executor = compiler_module.CompilerExecutor()

    assert executor.model is sentinel_model
    assert captured == {"schema": CompilerResult, "kind": "fast"}


def test_judge_uses_fast_structured_model(monkeypatch: Any) -> None:
    sentinel_model = object()
    captured: dict[str, Any] = {}

    def fake_structured_model(schema: type[Any], *, kind: str) -> object:
        captured["schema"] = schema
        captured["kind"] = kind
        return sentinel_model

    monkeypatch.setattr(
        judge_module,
        "get_structured_model",
        fake_structured_model,
    )

    executor = judge_module.JudgeExecutor()

    assert executor.model is sentinel_model
    assert captured == {"schema": JudgeDecision, "kind": "fast"}
