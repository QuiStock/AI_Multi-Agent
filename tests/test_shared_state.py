from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph, add_messages

from src.context.state import GraphState, RoutingDecision


def test_messages_use_langgraph_message_reducer() -> None:
    current = [HumanMessage(content="Qual é a regra?")]
    update = [AIMessage(content="A regra está no documento.")]

    merged = add_messages(current, update)

    assert len(merged) == 2
    assert merged[0].content == "Qual é a regra?"
    assert merged[1].content == "A regra está no documento."


def test_evidence_is_accumulated_by_the_state_reducer() -> None:
    def retrieve_node(state: GraphState) -> dict[str, object]:
        return {
            "evidence": [
                {
                    "arquivo": "manual.txt",
                    "conteudo": "A regra está no manual.",
                    "relevancia": 0.91,
                }
            ]
        }

    def compile_node(state: GraphState) -> dict[str, object]:
        return {
            "response": {
                "content": "A regra está no manual.",
                "status": "success",
            },
            "status": "completed",
        }

    graph = (
        StateGraph(GraphState)
        .add_node("retrieve", retrieve_node)
        .add_node("compile", compile_node)
        .add_edge(START, "retrieve")
        .add_edge("retrieve", "compile")
        .add_edge("compile", END)
        .compile()
    )

    result = graph.invoke(
        {
            "session_id": "session-1",
            "turn_id": "turn-1",
            "correlation_id": "correlation-1",
            "messages": [HumanMessage(content="Qual é a regra?")],
            "evidence": [],
            "status": "pending",
        }
    )

    assert result["evidence"][0]["arquivo"] == "manual.txt"
    assert result["response"]["content"] == "A regra está no manual."
    assert result["status"] == "completed"


def test_state_keeps_execution_identifiers() -> None:
    state: GraphState = {
        "session_id": "session-1",
        "turn_id": "turn-1",
        "correlation_id": "correlation-1",
        "messages": [HumanMessage(content="Olá")],
        "status": "pending",
    }

    assert state["session_id"] == "session-1"
    assert state["turn_id"] == "turn-1"
    assert state["correlation_id"] == "correlation-1"


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
