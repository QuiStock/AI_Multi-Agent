"""LangGraph assembly for the capabilities currently available in the app."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any, Literal

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.agents.faq.faq_node import create_faq_agent
from src.agents.router.router_node import create_router_node
from src.context.state import GraphState
from src.guardrails.input_guardrail import (
    CONTROLLED_INPUT_RESPONSE,
    input_guardrail_node,
)
from src.guardrails.output_guardrail import (
    CONTROLLED_OUTPUT_RESPONSE,
    create_output_guardrail_node,
)

GraphNode = Callable[[GraphState], dict[str, Any]]

CLARIFICATION_RESPONSE = (
    "Preciso de mais detalhes para localizar a informação documentada que você "
    "procura. Pode reformular sua pergunta?"
)
OUT_OF_SCOPE_RESPONSE = (
    "No momento, posso ajudar apenas com informações documentadas sobre os "
    "processos da organização."
)


def decide_after_input_guardrail(
    state: GraphState,
) -> Literal["router", "input_rejected"]:
    """Choose whether a validated request may reach the router."""

    guardrail = state.get("input_guardrail", {})
    if guardrail.get("status") == "passed":
        return "router"
    return "input_rejected"


def decide_after_router(
    state: GraphState,
) -> Literal["faq", "clarification", "out_of_scope"]:
    """Map the router's closed contract to graph node names.

    Unknown or inconsistent decisions fail closed as ``out_of_scope``.
    """

    decision = state.get("routing_decision", {})
    if decision.get("route") == "faq" and decision.get("outcome") == "dispatch":
        return "faq"
    if decision.get("outcome") == "clarification_required":
        return "clarification"
    return "out_of_scope"


def input_rejected_node(_: GraphState) -> dict[str, Any]:
    """Turn an input rejection into the only user-facing response for that path."""

    return {
        "final_response": {"content": CONTROLLED_INPUT_RESPONSE, "status": "rejected"},
        "status": "completed",
    }


def clarification_node(_: GraphState) -> dict[str, Any]:
    """Respond safely when the router cannot select an active capability."""

    return {
        "final_response": {
            "content": CLARIFICATION_RESPONSE,
            "status": "clarification_required",
        },
        "status": "completed",
    }


def out_of_scope_node(_: GraphState) -> dict[str, Any]:
    """Respond safely when the request is outside active capabilities."""

    return {
        "final_response": {
            "content": OUT_OF_SCOPE_RESPONSE,
            "status": "out_of_scope",
        },
        "status": "completed",
    }


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(_content_to_text(block) for block in content)
    if isinstance(content, dict):
        return str(content.get("text") or content.get("content") or "")
    return str(content or "")


def _sanitized_state(state: GraphState) -> GraphState:
    """Provide router and agents the sanitized current message when available."""

    sanitized = state.get("input_guardrail", {}).get("sanitized_message")
    if not sanitized:
        return state

    messages = list(state.get("messages", []))
    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            messages[index] = HumanMessage(content=sanitized, id=messages[index].id)
            break
    return {**state, "messages": messages}


def run_router_node(state: GraphState, *, router: GraphNode) -> dict[str, Any]:
    """Run the router with the sanitized request representation."""

    return router(_sanitized_state(state))


def run_faq_node(state: GraphState, *, agent: Any) -> dict[str, Any]:
    """Adapt the LangChain FAQ agent result to the shared graph contract."""

    try:
        result = agent.invoke({"messages": _sanitized_state(state).get("messages", [])})
        messages: list[AnyMessage] = result.get("messages", [])
        answer = next(
            (
                _content_to_text(message.content).strip()
                for message in reversed(messages)
                if isinstance(message, AIMessage)
                and _content_to_text(message.content).strip()
            ),
            "",
        )
    except Exception:
        answer = "Não foi possível consultar a base documental no momento."

    if not answer:
        answer = "Não foi possível obter uma resposta da base documental."
        response_status = "unavailable"
        agent_status = "unavailable"
    else:
        response_status = "success"
        agent_status = "success"

    return {
        "agent_outputs": [{"content": answer, "status": agent_status}],
        "final_response": {"content": answer, "status": response_status},
        "status": "in_progress",
    }


def finalize_output_node(state: GraphState) -> dict[str, Any]:
    """Ensure a blocked output is never released as the agent's original text."""

    if state.get("output_guardrail", {}).get("status") == "blocked":
        return {
            "final_response": {
                "content": CONTROLLED_OUTPUT_RESPONSE,
                "status": "rejected",
            },
            "status": "completed",
        }
    return {"status": "completed"}


def create_agent_graph(
    *,
    input_node: GraphNode = input_guardrail_node,
    router: GraphNode | None = None,
    faq_agent: Any | None = None,
    output_node: GraphNode | None = None,
) -> CompiledStateGraph:
    """Compile the current input guardrail → router → FAQ execution graph.

    Flow-agent and compiler branches are intentionally absent until that
    capability and its router contract are implemented.
    """

    router_node = router or create_router_node()
    faq = faq_agent or create_faq_agent()
    faq_node = partial(run_faq_node, agent=faq)
    routed_node = partial(run_router_node, router=router_node)
    output = output_node or create_output_guardrail_node(source="faq")

    graph = StateGraph(GraphState)
    graph.add_node("input_guardrail", input_node)
    graph.add_node("input_rejected", input_rejected_node)
    graph.add_node("router", routed_node)
    graph.add_node("faq", faq_node)
    graph.add_node("clarification", clarification_node)
    graph.add_node("out_of_scope", out_of_scope_node)
    graph.add_node("output_guardrail", output)
    graph.add_node("finalize_output", finalize_output_node)

    graph.add_edge(START, "input_guardrail")
    graph.add_conditional_edges(
        "input_guardrail",
        decide_after_input_guardrail,
        {"router": "router", "input_rejected": "input_rejected"},
    )
    graph.add_conditional_edges(
        "router",
        decide_after_router,
        {
            "faq": "faq",
            "clarification": "clarification",
            "out_of_scope": "out_of_scope",
        },
    )
    graph.add_edge("faq", "output_guardrail")
    graph.add_edge("output_guardrail", "finalize_output")
    graph.add_edge("input_rejected", END)
    graph.add_edge("clarification", END)
    graph.add_edge("out_of_scope", END)
    graph.add_edge("finalize_output", END)

    return graph.compile()


__all__ = [
    "CLARIFICATION_RESPONSE",
    "OUT_OF_SCOPE_RESPONSE",
    "create_agent_graph",
    "decide_after_input_guardrail",
    "decide_after_router",
]
