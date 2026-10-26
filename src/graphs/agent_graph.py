from __future__ import annotations

from collections.abc import Mapping
from functools import partial

from langchain_core.messages import RemoveMessage
from langchain_core.runnables import RunnableLambda
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.graph.state import CompiledStateGraph

from src.agents.compiler.compiler_node import compiler_blocked_node, run_compiler_node
from src.agents.compiler.executor import CompilerExecutor
from src.agents.faq.faq_node import faq_controlled_response_node
from src.agents.judge.executor import JudgeExecutor
from src.agents.judge.jev_node import judge_blocked_node, run_judge_node
from src.agents.product_workflow.product_workflow_node import (
    decide_after_product_workflow,
    product_workflow_ambiguous_node,
    product_workflow_not_found_node,
    product_workflow_unavailable_node,
)
from src.agents.registry import AGENT_ID_BY_GRAPH_NODE
from src.agents.router.executor import RouterExecutor
from src.agents.router.router_node import run_router_node
from src.graphs.adapters import (
    ConversationContextEnricherPort,
    GraphNode,
    MemoryMessagePersistencePort,
    run_context_enrichment_node,
    run_persist_turn_node,
)
from src.graphs.decisions import (
    decide_after_compiler,
    decide_after_faq,
    decide_after_input_guardrail,
    decide_after_judge,
    decide_after_router,
)
from src.graphs.state import GraphState, JudgeFeedback, JudgeState, RouteName
from src.guardrails.guardrails_node import (
    GreetingGuardrailPort,
    input_rejected_node,
    run_greeting_guardrail_node,
)

OUT_OF_SCOPE_RESPONSE = (
    "Desculpe, não consigo ajudar com esse assunto. "
    "Posso ajudar com informações sobre o Quistock, produtos e sugestões."
)


def clarification_node(_: GraphState) -> GraphState:
    return {
        "final_response": {
            "content": (
                "Pode me dar mais detalhes sobre o que você precisa no Quistock?"
            ),
            "status": "clarification_required",
        },
        "status": "completed",
    }


def out_of_scope_node(_: GraphState) -> GraphState:
    return {
        "final_response": {
            "content": OUT_OF_SCOPE_RESPONSE,
            "status": "out_of_scope",
        },
        "status": "completed",
    }


def _run_input_guardrail_for_graph(
    state: GraphState,
    *,
    guardrail: GraphNode,
) -> GraphState:
    """Start each turn with an empty error list and no judge carryover."""
    return {
        **guardrail(state),
        "errors": [],
        "judge": None,
    }


def _judge_feedback(judge_state: JudgeState) -> JudgeFeedback:
    feedback: JudgeFeedback = {
        "status": judge_state["status"],
        "reason": judge_state["reason"],
        "evidence_count": judge_state["evidence_count"],
    }
    if "reason_code" in judge_state:
        feedback["reason_code"] = judge_state["reason_code"]
    if "noul_probability" in judge_state:
        feedback["noul_probability"] = judge_state["noul_probability"]
    if "model" in judge_state:
        feedback["model"] = judge_state["model"]
    if "input_tokens" in judge_state:
        feedback["input_tokens"] = judge_state["input_tokens"]
    if "output_tokens" in judge_state:
        feedback["output_tokens"] = judge_state["output_tokens"]
    return feedback


def prepare_judge_repair_node(state: GraphState) -> GraphState:
    current = state.get("judge")
    if current is None:
        return {}

    updated: JudgeState = {
        **_judge_feedback(current),
        "repair_attempts": current["repair_attempts"] + 1,
        "judge_feedback": _judge_feedback(current),
    }
    return {"judge": updated}


def _as_runnable(
    node: GraphNode,
) -> RunnableLambda[GraphState, GraphState]:
    return RunnableLambda(node)


def _run_context_enrichment_for_graph(
    state: GraphState,
    *,
    context_enricher: ConversationContextEnricherPort,
) -> GraphState:
    """Apply the context adapter with reducer-safe message replacement."""
    update = run_context_enrichment_node(
        state,
        context_enricher=context_enricher,
    )
    messages = update.get("messages")
    if messages and isinstance(messages[0], RemoveMessage):
        return {
            **update,
            "messages": [
                RemoveMessage(id=REMOVE_ALL_MESSAGES),
                *messages[1:],
            ],
        }
    return update


def create_agent_graph(  # noqa: PLR0913 - explicit graph-composition boundary
    *,
    input_guardrail: GraphNode,
    router: RouterExecutor,
    capabilities: Mapping[RouteName, GraphNode],
    judge: JudgeExecutor,
    compiler: CompilerExecutor,
    output_guardrail: GraphNode,
    context_enricher: ConversationContextEnricherPort,
    greeting_guardrail: GreetingGuardrailPort | None = None,
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
        _as_runnable(
            partial(
                _run_input_guardrail_for_graph,
                guardrail=input_guardrail,
            )
        ),
        input_schema=GraphState,
    )

    if greeting_guardrail is not None:
        graph.add_node(
            "greeting_guardrail",
            _as_runnable(
                partial(
                    run_greeting_guardrail_node,
                    guardrail=greeting_guardrail,
                )
            ),
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
                _run_context_enrichment_for_graph,
                context_enricher=context_enricher,
            )
        ),
        input_schema=GraphState,
    )

    graph.add_node(
        "router",
        _as_runnable(partial(run_router_node, router=router)),
        metadata={"agent_id": AGENT_ID_BY_GRAPH_NODE["router"]},
        input_schema=GraphState,
    )

    for route, node in capabilities.items():
        agent_id = AGENT_ID_BY_GRAPH_NODE.get(route)
        graph.add_node(
            route,
            _as_runnable(node),
            metadata={"agent_id": agent_id} if agent_id is not None else None,
            input_schema=GraphState,
        )

    graph.add_node(
        "judge",
        _as_runnable(partial(run_judge_node, judge=judge)),
        metadata={"agent_id": AGENT_ID_BY_GRAPH_NODE["judge"]},
        input_schema=GraphState,
    )

    graph.add_node(
        "compiler",
        _as_runnable(partial(run_compiler_node, compiler=compiler)),
        metadata={"agent_id": AGENT_ID_BY_GRAPH_NODE["compiler"]},
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
        "compiler_blocked",
        _as_runnable(compiler_blocked_node),
        input_schema=GraphState,
    )

    graph.add_node(
        "prepare_judge_repair",
        _as_runnable(prepare_judge_repair_node),
        input_schema=GraphState,
    )

    graph.add_node(
        "product_workflow_unavailable",
        _as_runnable(product_workflow_unavailable_node),
        input_schema=GraphState,
    )

    graph.add_node(
        "product_workflow_ambiguous",
        _as_runnable(product_workflow_ambiguous_node),
        input_schema=GraphState,
    )

    graph.add_node(
        "product_workflow_not_found",
        _as_runnable(product_workflow_not_found_node),
        input_schema=GraphState,
    )

    graph.add_node(
        "faq_controlled_response",
        _as_runnable(faq_controlled_response_node),
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
            "context_enrichment": (
                "greeting_guardrail"
                if greeting_guardrail is not None
                else "context_enrichment"
            ),
            "input_rejected": "input_rejected",
        },
    )

    if greeting_guardrail is not None:
        graph.add_conditional_edges(
            "greeting_guardrail",
            lambda state: (
                "persist_turn"
                if state.get("greeting_classification", {}).get("category")
                == "greeting_only"
                else "context_enrichment"
            ),
            {
                "persist_turn": "persist_turn",
                "context_enrichment": "context_enrichment",
            },
        )

    graph.add_edge("context_enrichment", "router")

    router_targets: dict[str, str] = {route: route for route in capabilities}
    router_targets.update(
        {
            "clarification_required": "clarification_required",
            "out_of_scope": "out_of_scope",
            "judge": "judge",
            "router_error": "persist_turn",
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
        if route == "product_workflow":
            graph.add_conditional_edges(
                route,
                decide_after_product_workflow,
                {
                    "compiler": "compiler",
                    "product_workflow_ambiguous": "product_workflow_ambiguous",
                    "product_workflow_not_found": "product_workflow_not_found",
                    "product_workflow_unavailable": "product_workflow_unavailable",
                },
            )
        elif route == "faq":
            graph.add_conditional_edges(
                route,
                decide_after_faq,
                {
                    "compiler": "compiler",
                    "faq_controlled_response": "faq_controlled_response",
                },
            )
        else:
            graph.add_edge(route, "compiler")

    graph.add_conditional_edges(
        "compiler",
        decide_after_compiler,
        {
            "judge": "judge",
            "compiler_blocked": "compiler_blocked",
        },
    )

    graph.add_conditional_edges(
        "judge",
        decide_after_judge,
        {
            "output_guardrail": "output_guardrail",
            "prepare_judge_repair": "prepare_judge_repair",
            "judge_blocked": "judge_blocked",
        },
    )

    graph.add_edge("prepare_judge_repair", "compiler")

    graph.add_edge(
        "output_guardrail",
        "persist_turn",
    )

    graph.add_edge("product_workflow_ambiguous", "judge")
    graph.add_edge("product_workflow_not_found", "judge")

    for terminal_node in (
        "clarification_required",
        "out_of_scope",
        "judge_blocked",
        "compiler_blocked",
        "product_workflow_unavailable",
        "faq_controlled_response",
    ):
        graph.add_edge(terminal_node, "persist_turn")

    graph.add_edge("persist_turn", END)
    graph.add_edge("input_rejected", "persist_turn")

    return graph.compile(checkpointer=checkpointer)
