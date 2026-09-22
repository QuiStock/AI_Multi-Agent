from __future__ import annotations

from collections.abc import Hashable, Mapping
from functools import partial
from typing import cast

from langchain_core.messages import AnyMessage, HumanMessage, RemoveMessage
from langchain_core.runnables import RunnableLambda
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.graphs.adapters import (
    CompilerExecutorPort,
    ConversationContextEnricherPort,
    GraphNode,
    JudgeExecutorPort,
    MemoryMessagePersistencePort,
    RouterExecutorPort,
    run_compiler_node,
    run_context_enrichment_node,
    run_judge_node,
    run_normalize_user_message_node,
    run_persist_turn_node,
    run_router_node,
)
from src.graphs.decisions import (
    decide_after_input_guardrail,
    decide_after_judge,
    decide_after_router,
)
from src.graphs.state import GraphState, RouteName


def input_rejected_node(state: GraphState) -> GraphState:
    update: GraphState = {
        "final_response": {
            "content": "A entrada não pôde ser processada.",
            "status": "rejected",
        },
        "status": "completed",
    }
    latest_human = next(
        (
            message
            for message in reversed(state.get("messages", []))
            if isinstance(message, HumanMessage)
        ),
    )
    if latest_human is not None and latest_human.id:
        update["messages"] = [cast(AnyMessage, RemoveMessage(id=latest_human.id))]
    return update


def clarification_node(_: GraphState) -> GraphState:
    return {
        "final_response": {
            "content": "Preciso de mais detalhes para continuar.",
            "status": "clarification_required",
        },
        "status": "completed",
    }


def out_of_scope_node(_: GraphState) -> GraphState:
    return {
        "final_response": {
            "content": "Essa solicitação está fora do escopo atual.",
            "status": "out_of_scope",
        },
        "status": "completed",
    }


def judge_blocked_node(state: GraphState) -> GraphState:
    judge_result = state.get("agent_results", {}).get("judge")
    content = "Não foi possível validar a resposta gerada."

    if judge_result and judge_result["status"] == "insufficient_evidence":
        content = "Não foi possível confirmar a resposta com as evidências disponíveis."

    return {
        "final_response": {
            "content": content,
            "status": "error",
        },
        "status": "completed",
    }


def _as_runnable(
    node: GraphNode,
) -> RunnableLambda[GraphState, GraphState]:
    return RunnableLambda(node)


def create_agent_graph(  # noqa: PLR0913 - explicit graph-composition boundary
    *,
    input_guardrail: GraphNode,
    router: RouterExecutorPort,
    capabilities: Mapping[RouteName, GraphNode],
    judge: JudgeExecutorPort,
    compiler: CompilerExecutorPort,
    output_guardrail: GraphNode,
    context_enricher: ConversationContextEnricherPort,
    message_service: MemoryMessagePersistencePort | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    graph: StateGraph[
        GraphState,
        None,
        GraphState,
        GraphState,
    ] = StateGraph(GraphState)

    graph.add_node(
        "input_guardrail",
        _as_runnable(input_guardrail),
        input_schema=GraphState,
    )

    graph.add_node(
        "clarification_required",
        _as_runnable(clarification_node),
        input_schema=GraphState,
    )

    graph.add_node(
        "context_enrichment",
        _as_runnable(
            partial(
                run_context_enrichment_node,
                context_enricher=context_enricher,
            )
        ),
        input_schema=GraphState,
    )

    graph.add_node(
        "normalize_user_message",
        _as_runnable(run_normalize_user_message_node),
        input_schema=GraphState,
    )

    graph.add_node(
        "router",
        _as_runnable(partial(run_router_node, router=router)),
        input_schema=GraphState,
    )

    for route, node in capabilities.items():
        graph.add_node(
            route,
            _as_runnable(node),
            input_schema=GraphState,
        )

    graph.add_node(
        "judge",
        _as_runnable(partial(run_judge_node, judge=judge)),
        input_schema=GraphState,
    )

    graph.add_node(
        "compiler",
        _as_runnable(partial(run_compiler_node, compiler=compiler)),
        input_schema=GraphState,
    )

    graph.add_node(
        "output_guardrail",
        _as_runnable(output_guardrail),
        input_schema=GraphState,
    )

    graph.add_node(
        "input_rejected",
        _as_runnable(input_rejected_node),
        input_schema=GraphState,
    )

    graph.add_node(
        "clarification",
        _as_runnable(clarification_node),
        input_schema=GraphState,
    )

    graph.add_node(
        "out_of_scope",
        _as_runnable(out_of_scope_node),
        input_schema=GraphState,
    )

    graph.add_node(
        "judge_blocked",
        _as_runnable(judge_blocked_node),
        input_schema=GraphState,
    )

    graph.add_node(
        "persist_turn",
        _as_runnable(
            partial(
                run_persist_turn_node,
                message_service=message_service,
            )
        ),
        input_schema=GraphState,
    )

    graph.add_edge(
        START,
        "input_guardrail",
    )

    graph.add_conditional_edges(
        "input_guardrail",
        decide_after_input_guardrail,
        {
            "context_enrichment": "context_enrichment",
            "input_rejected": "input_rejected",
        },
    )

    graph.add_edge("context_enrichment", "normalize_user_message")
    graph.add_edge("normalize_user_message", "router")

    router_targets: dict[Hashable, str] = {route: route for route in capabilities}

    router_targets.update(
        {
            "clarification_required": "clarification_required",
            "out_of_scope": "out_of_scope",
        }
    )

    graph.add_conditional_edges(
        "router",
        partial(
            decide_after_router,
            active_routes=capabilities.keys(),
        ),
        router_targets,
    )

    for route in capabilities:
        graph.add_edge(route, "compiler")

    graph.add_edge(
        "compiler",
        "judge",
    )

    graph.add_conditional_edges(
        "judge",
        decide_after_judge,
        {
            "output_guardrail": "output_guardrail",
            "judge_blocked": "judge_blocked",
        },
    )

    graph.add_edge(
        "output_guardrail",
        "persist_turn",
    )

    for terminal_node in (
        "clarification_required",
        "out_of_scope",
        "judge_blocked",
    ):
        graph.add_edge(terminal_node, "persist_turn")

    graph.add_edge("persist_turn", END)
    graph.add_edge("input_rejected", END)

    return graph.compile(checkpointer=checkpointer)
