from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import add_messages

from src.graphs.state import (
    FAQResult,
    GraphState,
    ProductWorkFlowResult,
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
    }

    product_result: ProductWorkFlowResult = {
        "status": "success",
        "answer": "Sugestão vigente.",
        "evidence_ids": ["suggestion-1"],
    }
    merged = merge_agent_results(
        {"faq": faq_result},
        {"product_workflow": product_result},
    )

    assert merged["faq"] == faq_result
    assert merged["product_workflow"] == product_result


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


def test_product_workflow_evidence_replaces_the_previous_commercial_page() -> None:
    summary = {
        "evidence_id": "summary-1",
        "source_type": "conversation_summary",
        "source_id": "summary-1",
        "content": "Resumo anterior.",
        "metadata": {},
    }
    page = {
        "evidence_id": "product-search:1",
        "source_type": "product_workflow",
        "source_id": "product-search:1",
        "content": '{"status":"ambiguous"}',
        "metadata": {},
    }
    detail = {
        "evidence_id": "suggestion-detail:1",
        "source_type": "product_workflow",
        "source_id": "suggestion-detail:1",
        "content": '{"status":"unique"}',
        "metadata": {},
    }

    merged = merge_evidence([summary, page], [detail])

    assert merged == [summary, detail]


def test_routing_decision_is_separate_from_turn_status() -> None:
    decision: RoutingDecision = {
        "route": "faq",
        "outcome": "dispatch",
        "reason": "A pergunta trata de uma regra documentada.",
    }
    state: GraphState = {
        "routing_decision": decision,
        "status": "in_progress",
    }

    assert state["routing_decision"]["route"] == "faq"
    assert state["routing_decision"]["outcome"] == "dispatch"
    assert state["status"] == "in_progress"
