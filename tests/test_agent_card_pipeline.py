from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool

from src.agents import factory
from src.agents.faq.card import FAQ_CARD
from src.agents.faq.executor import FAQExecutor
from src.agents.registry import get_agent_card
from src.agents.router.card import ROUTER_CARD
from src.graphs.contracts import RouteDecision


class EmptyRetriever:
    def search(
        self,
        query: str,
        *,
        allowed_audiences: tuple[str, ...],
    ) -> list[dict[str, object]]:
        return []


def _fake_search(query: str) -> str:
    """Return deterministic evidence for the pipeline test."""

    return query


def test_registry_returns_the_faq_card() -> None:
    assert get_agent_card("faq_rag") is FAQ_CARD


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
        lambda **kwargs: FakeAgent(),
    )

    message = HumanMessage(content="Pergunta de teste")
    result = FAQExecutor(
        retriever=EmptyRetriever(),
        model="fake-model",
    ).invoke(
        messages=[message],
        allowed_audiences=("employee",),
        request_id="request-1",
        trace_id="trace-1",
    )

    assert captured["agent_input"] == {"messages": [message]}
    assert result == {
        "status": "error",
        "answer": "",
        "error_code": "FAQ_TOOL_NOT_CALLED",
    }


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
