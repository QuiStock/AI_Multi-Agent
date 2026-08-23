from __future__ import annotations

import importlib
from typing import Any

from src import config, llm_factory
from src.context.schemas import CompilerResult, RouteDecision

compiler_module = importlib.import_module("src.agents.compiler.compiler_node")
faq_module = importlib.import_module("src.agents.faq.faq_node")
router_module = importlib.import_module("src.agents.router.router_node")


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


def test_faq_agent_uses_fast_model(monkeypatch: Any) -> None:
    sentinel_model = object()
    captured: dict[str, Any] = {}

    def fake_create_agent(model: Any, **kwargs: Any) -> object:
        captured["model"] = model
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(faq_module, "llm_fast", sentinel_model)
    monkeypatch.setattr(faq_module, "create_agent", fake_create_agent)

    faq_module.create_faq_agent()

    assert captured["model"] is sentinel_model


def test_router_uses_default_structured_model(monkeypatch: Any) -> None:
    sentinel_model = object()
    captured: dict[str, Any] = {}

    def fake_structured_model(schema: type[Any]) -> object:
        captured["schema"] = schema
        return sentinel_model

    monkeypatch.setattr(router_module, "get_structured_model", fake_structured_model)

    node = router_module.create_router_node()

    assert node is not None
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

    node = compiler_module.create_compiler_node()

    assert node is not None
    assert captured == {"schema": CompilerResult, "kind": "fast"}
