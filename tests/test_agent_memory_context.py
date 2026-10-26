from typing import Any

from langchain_core.messages import HumanMessage

from src.agents.faq.executor import FAQExecutor
from src.agents.faq.faq_node import faq_node
from src.agents.product_workflow.executor import ProductWorkflowExecutor
from src.agents.product_workflow.product_workflow_node import (
    run_product_workflow_node,
)
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
        "evidences": [
            {
                "evidence_id": "conversation-summary:past",
                "source_type": "conversation_summary",
                "source_id": "past",
                "content": "Conversamos sobre arroz integral.",
                "metadata": {"retrieval_source": "recent_fallback"},
            }
        ],
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
    faq_node(
        state,
        executor=FAQExecutor(
            retriever=object(),  # type: ignore[arg-type]
            agent_factory=factory,
        ),
    )
    run_product_workflow_node(
        state,
        executor=ProductWorkflowExecutor(
            repository=object(),  # type: ignore[arg-type]
            agent_factory=factory,
        ),
    )

    assert tools_seen == [
        ["faq_search"],
        [
            "get_suggestion_for_product",
            "get_suggestion_detail",
            "list_suggestions",
            "get_promotion_by_expiration",
        ],
    ]
    faq_messages, product_messages = messages_seen
    assert faq_messages[0] == state["messages"][0]
    assert len(faq_messages) == 2
    assert product_messages[0].content.startswith("Data local atual:")
    assert product_messages[1] == state["messages"][0]
    assert len(product_messages) == 3
    assert all(
        "recent_fallback" in str(messages[-1].content) for messages in messages_seen
    )
