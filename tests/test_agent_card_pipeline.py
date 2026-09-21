from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool

from src.agents import factory, tool_registry
from src.agents.faq.card import FAQ_CARD
from src.agents.faq.executor import FAQExecutor
from src.agents.judge.card import JUDGE_CARD
from src.agents.registry import get_agent_card
from src.agents.router.card import ROUTER_CARD
from src.graphs.contracts import RouteDecision


def _fake_search(query: str) -> str:
    """Return deterministic evidence for the pipeline test."""

    return query


def test_registry_returns_the_faq_card() -> None:
    assert get_agent_card("faq_rag") is FAQ_CARD


def test_registry_returns_the_judge_card() -> None:
    assert get_agent_card("evidence_judge") is JUDGE_CARD


def test_factory_resolves_card_tools_and_builds_agent(
    monkeypatch,
) -> None:
    fake_tool = StructuredTool.from_function(_fake_search)
    monkeypatch.setitem(
        tool_registry.TOOL_REGISTRY,
        "faq_search",
        fake_tool,
    )

    captured: dict[str, Any] = {}

    def fake_create_agent(*, model, tools, system_prompt):
        captured.update(
            model=model,
            tools=tools,
            system_prompt=system_prompt,
        )
        return "compiled-agent"

    monkeypatch.setattr(factory, "create_agent", fake_create_agent)

    result = factory.create_agent_from_card(
        card=FAQ_CARD,
        model="fake-model",
    )

    assert result == "compiled-agent"
    assert captured["model"] == "fake-model"
    assert captured["tools"] == [fake_tool]
    assert captured["system_prompt"] == FAQ_CARD.system_prompt_template


def test_executor_forwards_agent_input_to_compiled_agent(
    monkeypatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeAgent:
        def invoke(self, agent_input):
            captured["agent_input"] = agent_input
            return {"messages": agent_input["messages"]}

    monkeypatch.setattr(
        "src.agents.faq.executor.create_agent_from_card",
        lambda card, model: FakeAgent(),
    )

    agent_input = {
        "messages": [HumanMessage(content="Pergunta de teste")],
    }
    result = FAQExecutor(model="fake-model").invoke(agent_input)

    assert result == agent_input
    assert captured["agent_input"] == agent_input


def test_factory_accepts_per_request_router_tools_and_response_schema(
    monkeypatch,
) -> None:
    tool = StructuredTool.from_function(
        _fake_search,
        name="search_conversation_summaries",
    )
    captured: dict[str, Any] = {}

    def fake_create_agent(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "compiled-router"

    monkeypatch.setattr(factory, "create_agent", fake_create_agent)

    result = factory.create_agent_from_card(
        card=ROUTER_CARD,
        model="fake-model",
        tools=[tool],
        response_format=RouteDecision,
    )

    assert result == "compiled-router"
    assert captured["tools"] == [tool]
    assert captured["response_format"] is RouteDecision
