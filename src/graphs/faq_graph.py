"""Initial graph: input guardrail, router and FAQ agent."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from langchain_core.messages import AnyMessage, BaseMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.agents.faq.faq_node import create_faq_agent
from src.agents.router.router_node import create_router_node
from src.context.state import GraphState, Response
from src.guardrails.input_guardrail import input_guardrail_node


def _last_message_content(messages: list[AnyMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, BaseMessage) and message.type == "ai":
            content = message.content
            return content if isinstance(content, str) else str(content)
    return ""


def _create_faq_node(faq_agent: Any) -> Callable[[GraphState], dict[str, Any]]:
    def faq_node(state: GraphState) -> dict[str, Any]:
        result = faq_agent.invoke({"messages": state.get("messages", [])})
        messages = result.get("messages", [])
        content = _last_message_content(messages)
        response: Response = {
            "content": content,
            "status": "success",
        }
        return {
            "agent_outputs": [{"content": content, "status": "success"}],
            "final_response": response,
            "status": "completed",
        }

    return faq_node


def _controlled_response_node(state: GraphState) -> dict[str, Any]:
    decision = state.get("routing_decision")
    guardrail = state.get("input_guardrail")

    if guardrail and guardrail["status"] == "blocked":
        response: Response = {
            "content": "Não foi possível processar essa mensagem.",
            "status": "rejected",
        }
    elif decision and decision["outcome"] == "clarification_required":
        response = {
            "content": "Pode reformular a pergunta com um pouco mais de detalhes?",
            "status": "clarification_required",
        }
    else:
        response = {
            "content": "Essa solicitação está fora do escopo atual.",
            "status": "out_of_scope",
        }

    return {"final_response": response, "status": "completed"}


def _after_guardrail(state: GraphState) -> str:
    return "router" if state["input_guardrail"]["status"] == "passed" else "controlled"


def _after_router(state: GraphState) -> str:
    return "faq" if state["routing_decision"]["outcome"] == "dispatch" else "controlled"


def create_faq_graph(
    *, router_model: Any | None = None, faq_agent: Any | None = None
) -> CompiledStateGraph:
    """Build the initial graph with only the active FAQ capability."""

    graph: StateGraph[GraphState] = StateGraph(GraphState)
    graph.add_node("input_guardrail", input_guardrail_node)
    graph.add_node(
        "router",
        cast(Any, create_router_node(router_model)),
        input_schema=GraphState,
    )
    graph.add_node(
        "faq",
        cast(Any, _create_faq_node(faq_agent or create_faq_agent())),
        input_schema=GraphState,
    )
    graph.add_node("controlled_response", _controlled_response_node)

    graph.add_edge(START, "input_guardrail")
    graph.add_conditional_edges(
        "input_guardrail",
        _after_guardrail,
        {"router": "router", "controlled": "controlled_response"},
    )
    graph.add_conditional_edges(
        "router",
        _after_router,
        {"faq": "faq", "controlled": "controlled_response"},
    )
    graph.add_edge("faq", END)
    graph.add_edge("controlled_response", END)
    return graph.compile()
