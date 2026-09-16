from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import add_messages

from src.graphs.state import (
    FAQResult,
    GraphState,
    MemoryContext,
    RoutingDecision,
    merge_agent_results,
    merge_evidence,
)


def test_messages_use_langgraph_message_reducer() -> None:
    current = [HumanMessage(content="Qual é a regra?")]
    update = [AIMessage(content="A regra está no documento.")]

    merged = add_messages(current, update)

    assert len(merged) == 2
    assert merged[0].content == "Qual é a regra?"
    assert merged[1].content == "A regra está no documento."


def test_agent_results_are_merged_by_agent_name() -> None:
    faq_result: FAQResult = {
        "status": "success",
        "answer": "A regra está no manual.",
        "citation_ids": ["faq-1"],
    }

    merged = merge_agent_results(
        {"faq": faq_result},
        {
            "judge": {
                "status": "approved",
                "reason": "Evidência suficiente.",
                "evidence_ids": ["faq-1"],
            }
        },
    )

    assert merged["faq"] == faq_result
    assert merged["judge"]["status"] == "approved"


def test_evidence_reducer_replaces_duplicate_ids_instead_of_appending() -> None:
    first = {
        "evidence_id": "faq-1",
        "source_type": "faq_document",
        "source_id": "manual.md",
        "content": "Versão inicial.",
        "metadata": {},
    }
    retry = {
        **first,
        "content": "Versão confirmada.",
    }

    merged = merge_evidence([first], [retry])

    assert merged == [retry]


def test_memory_is_optional_in_shared_state() -> None:
    memory: MemoryContext = {
        "recent_messages": [],
        "previous_conversation_summaries": [],
    }
    state_without_memory: GraphState = {
        "request": {
            "request_id": "request-1",
            "user_id": "user-1",
            "conversation_id": "conversation-1",
        },
        "messages": [HumanMessage(content="Olá")],
    }
    state_with_memory: GraphState = {
        **state_without_memory,
        "memory": memory,
    }

    assert "memory" not in state_without_memory
    assert state_with_memory["memory"] == memory


def test_routing_decision_is_separate_from_turn_status() -> None:
    decision: RoutingDecision = {
        "route": "faq",
        "target_agent": "faq",
        "outcome": "dispatch",
        "reason": "A pergunta trata de uma regra documentada.",
    }
    state: GraphState = {
        "routing_decision": decision,
        "status": "in_progress",
    }

    assert state["routing_decision"]["target_agent"] == "faq"
    assert state["routing_decision"]["outcome"] == "dispatch"
    assert state["status"] == "in_progress"
