from typing import Any

from langchain_core.messages import HumanMessage

from src.agents.faq.executor import FAQExecutor
from src.agents.product_workflow.executor import ProductWorkflowExecutor
from src.graphs.state import GraphState


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


def test_specialists_have_only_domain_tools() -> None:
    tools_seen: list[list[str]] = []
    messages_seen: list[list[Any]] = []

    class FakeAgent:
        def invoke(
            self,
            payload: dict[str, Any],
            *,
            config: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            messages_seen.append(payload["messages"])
            return {"messages": []}

    def factory(**kwargs: Any) -> FakeAgent:
        tools_seen.append([tool.name for tool in kwargs["tools"]])
        return FakeAgent()

    state = _state()
    FAQExecutor(
        retriever=object(),  # type: ignore[arg-type]
        agent_factory=factory,
    ).invoke(state)
    ProductWorkflowExecutor(
        repository=object(),  # type: ignore[arg-type]
        agent_factory=factory,
    ).invoke(state)

    assert tools_seen == [
        ["faq_search"],
        ["get_suggestion_for_product", "get_suggestion_detail"],
    ]
    assert messages_seen == [state["messages"], state["messages"]]
