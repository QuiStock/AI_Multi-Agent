import json
from typing import Any

from langchain_core.messages import HumanMessage

from src.agents.faq.executor import FAQExecutor
from src.agents.memory_context import memory_tool_for_state
from src.agents.product_workflow.executor import ProductWorkflowExecutor
from src.agents.router.executor import RouterExecutor
from src.graphs.contracts import RouteDecision
from src.graphs.state import GraphState
from src.memory.contracts import SummaryContextSelection


class FakeSummaryService:
    def __init__(self, result: SummaryContextSelection | None = None) -> None:
        self.calls = 0
        self.result = result or {"source": "none", "results": []}

    def search_context(self, **_: str) -> SummaryContextSelection:
        self.calls += 1
        return self.result


def _state() -> GraphState:
    return {
        "request": {
            "request_id": "request-1",
            "email": "owner@example.com",
            "conversation_id": "current",
            "role_code": "MANAGER",
            "user_id": 7,
            "store_ids": [3],
        },
        "messages": [HumanMessage(content="E o produto que discutimos antes?")],
    }


def test_specialist_search_does_not_reuse_router_tool_result() -> None:
    service = FakeSummaryService(
        {
            "source": "semantic",
            "results": [
                {
                    "conversation_id": "previous",
                    "title": "Produto",
                    "summary": "Conversamos sobre leite integral.",
                    "updated_at": "2026-10-01T12:00:00+00:00",
                }
            ],
        }
    )
    state = _state()

    class RouterAgent:
        def __init__(self, tool: Any) -> None:
            self.tool = tool

        def invoke(self, _: dict[str, Any]) -> dict[str, Any]:
            self.tool.invoke({})
            return {
                "structured_response": RouteDecision(
                    route="product_workflow", reason="Produto mencionado."
                )
            }

    router = RouterExecutor(
        summary_search_service=service,
        tool_calling_model=object(),
        agent_factory=lambda **kwargs: RouterAgent(kwargs["tools"][0]),
    )
    decision = router.invoke(state["messages"], request_context=state["request"])
    specialist_tool = memory_tool_for_state(service=service, state=state)

    assert specialist_tool is not None
    result = json.loads(specialist_tool.invoke({}))
    assert "memory" not in decision
    assert "memory" not in state
    assert service.calls == 2
    assert result["evidence"][0]["source_type"] == "conversation_summary"
    assert result["evidence"][0]["source_id"] == "previous"


def test_specialists_receive_tool_without_preloaded_memory() -> None:
    service = FakeSummaryService()
    tools_seen: list[list[str]] = []
    messages_seen: list[list[Any]] = []

    class FakeAgent:
        def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
            messages_seen.append(payload["messages"])
            return {"messages": []}

    def factory(**kwargs: Any) -> FakeAgent:
        tools_seen.append([tool.name for tool in kwargs["tools"]])
        return FakeAgent()

    state = _state()
    FAQExecutor(
        retriever=object(),  # type: ignore[arg-type]
        summary_search_service=service,
        agent_factory=factory,
    ).invoke(state)
    ProductWorkflowExecutor(
        repository=object(),  # type: ignore[arg-type]
        summary_search_service=service,
        agent_factory=factory,
    ).invoke(state)

    assert tools_seen == [
        ["faq_search", "search_conversation_summaries"],
        [
            "get_suggestion_for_product",
            "get_suggestion_detail",
            "search_conversation_summaries",
        ],
    ]
    assert messages_seen == [state["messages"], state["messages"]]
    assert service.calls == 0


def test_empty_memory_search_has_no_evidence() -> None:
    service = FakeSummaryService()
    tool = memory_tool_for_state(service=service, state=_state())

    assert tool is not None
    result = json.loads(tool.invoke({}))

    assert result["data"] == {"source": "none", "results": []}
    assert result["evidence"] == []
    assert result["warnings"][0]["code"] == "NO_RELEVANT_MEMORY"
