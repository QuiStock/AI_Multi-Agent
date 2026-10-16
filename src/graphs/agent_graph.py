from __future__ import annotations

from collections.abc import Hashable, Mapping
from functools import partial
from typing import Literal, cast

from langchain_core.messages import AnyMessage, HumanMessage, RemoveMessage
from langchain_core.runnables import RunnableLambda
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.graph.state import CompiledStateGraph

from src.agents.registry import AGENT_ID_BY_GRAPH_NODE
from src.graphs.adapters import (
    CompilerExecutorPort,
    ConversationContextEnricherPort,
    GraphNode,
    GreetingGuardrailPort,
    JudgeExecutorPort,
    MemoryMessagePersistencePort,
    RouterExecutorPort,
    run_compiler_node,
    run_context_enrichment_node,
    run_greeting_guardrail_node,
    run_judge_node,
    run_normalize_user_message_node,
    run_persist_turn_node,
    run_router_node,
)
from src.graphs.decisions import (
    decide_after_faq,
    decide_after_input_guardrail,
    decide_after_judge,
    decide_after_router,
)
from src.graphs.state import GraphState, RouteName
from src.guardrails.greeting import GREETING_RESPONSE

CONTROLLED_INPUT_RESPONSE = (
    "Desculpe, não posso tratar desse tipo de assunto no Quistock."
)
BLOCKED_INPUT_HISTORY_MARKER = "[ENTRADA_BLOQUEADA]"
JUDGE_BLOCKED_RESPONSE = (
    "Desculpe, não foi possível te ajudar neste momento. Tente novamente mais tarde."
)
JEV_UNAVAILABLE_RESPONSE = "Desculpe, estamos com instabilidade com o fefo."
PRODUCT_WORKFLOW_UNAVAILABLE_RESPONSE = (
    "Desculpe, não foi possível consultar essas informações agora. "
    "Tente novamente mais tarde."
)
PRODUCT_WORKFLOW_AMBIGUOUS_RESPONSE = (
    "Encontrei mais de uma sugestão para esse produto. "
    "Qual opção você deseja consultar?"
)
PRODUCT_WORKFLOW_NOT_FOUND_RESPONSE = (
    "Não encontrei uma sugestão autorizada para esse produto. "
    "Você pode informar o SKU ou verificar o nome do produto?"
)
FAQ_CONTROLLED_RESPONSE = (
    "Não foi possível concluir a consulta da base de conhecimento agora. "
    "Tente novamente mais tarde."
)
OUT_OF_SCOPE_RESPONSE = (
    "Desculpe, não consigo ajudar com esse assunto. "
    "Posso ajudar com informações sobre o Quistock, produtos e sugestões."
)


def input_rejected_node(
    state: GraphState,
) -> GraphState:
    update: GraphState = {
        "final_response": {
            "content": CONTROLLED_INPUT_RESPONSE,
            "status": "rejected",
        },
        "status": "in_progress",
    }
    request = state.get("request")
    request_id = request.get("request_id") if request else None
    latest_human = next(
        (
            message
            for message in reversed(state.get("messages", []))
            if isinstance(message, HumanMessage)
        ),
    )
    if latest_human is not None:
        message_id = (
            f"{request_id}:user"
            if isinstance(request_id, str) and request_id
            else latest_human.id
        )
        if message_id is not None:
            replacement: list[AnyMessage] = []
            if latest_human.id:
                replacement.append(cast(AnyMessage, RemoveMessage(id=latest_human.id)))
            replacement.append(
                HumanMessage(content=BLOCKED_INPUT_HISTORY_MARKER, id=message_id)
            )
            update["messages"] = replacement
    elif isinstance(request_id, str) and request_id:
        update["messages"] = [
            HumanMessage(
                content=BLOCKED_INPUT_HISTORY_MARKER,
                id=f"{request_id}:user",
            )
        ]
    return update


def greeting_node(_: GraphState) -> GraphState:
    return {
        "final_response": {
            "content": GREETING_RESPONSE,
            "status": "success",
        },
        "status": "in_progress",
    }


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


def judge_blocked_node(state: GraphState) -> GraphState:
    judge_result = state.get("agent_results", {}).get("judge")
    error_code = judge_result.get("error_code") if judge_result else None
    content = "Não foi possível validar a resposta gerada."

    if isinstance(error_code, str) and error_code.startswith("JUDGE_JEV_"):
        content = JEV_UNAVAILABLE_RESPONSE
    elif judge_result and judge_result.get("reason_code") == "missing_evidence":
        content = JUDGE_BLOCKED_RESPONSE
    elif judge_result and judge_result["status"] == "insufficient_evidence":
        content = JUDGE_BLOCKED_RESPONSE

    return {
        "final_response": {
            "content": content,
            "status": "error",
        },
        "response_draft": None,
        "status": "completed",
    }


def prepare_judge_repair_node(state: GraphState) -> GraphState:
    judge_result = state.get("agent_results", {}).get("judge")
    if judge_result is None:
        return {
            "repair_attempts": state.get("repair_attempts", 0) + 1,
        }

    return {
        "judge_feedback": judge_result,
        "repair_attempts": state.get("repair_attempts", 0) + 1,
    }


def product_workflow_unavailable_node(state: GraphState) -> GraphState:
    return {
        "final_response": {
            "content": PRODUCT_WORKFLOW_UNAVAILABLE_RESPONSE,
            "status": "error",
        },
        "status": "completed",
    }


def product_workflow_ambiguous_node(state: GraphState) -> GraphState:
    return {
        "final_response": {
            "content": PRODUCT_WORKFLOW_AMBIGUOUS_RESPONSE,
            "status": "clarification_required",
        },
        "status": "completed",
    }


def product_workflow_not_found_node(state: GraphState) -> GraphState:
    result = state.get("agent_results", {}).get("product_workflow", {})
    content = (
        str(result.get("answer", "")).strip() or PRODUCT_WORKFLOW_NOT_FOUND_RESPONSE
    )
    return {
        "final_response": {
            "content": content,
            "status": "clarification_required",
        },
        "status": "completed",
    }


def faq_controlled_response_node(state: GraphState) -> GraphState:
    result = state.get("agent_results", {}).get("faq", {})
    next_step = result.get("next_step", "controlled_error")
    content = str(result.get("answer", "")).strip() or FAQ_CONTROLLED_RESPONSE
    status: Literal["error", "clarification_required"] = (
        "error" if next_step == "controlled_error" else "clarification_required"
    )
    return {
        "final_response": {
            "content": content,
            "status": status,
        },
        "status": "completed",
    }


def decide_after_product_workflow(state: GraphState) -> str:
    result = state.get("agent_results", {}).get("product_workflow", {})
    lookup_status = result.get("lookup_status")
    if lookup_status == "ambiguous":
        return "product_workflow_ambiguous"
    if lookup_status == "not_found":
        return "product_workflow_not_found"
    if result.get("status") == "success":
        return "compiler"
    return "product_workflow_unavailable"


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
    router: RouterExecutorPort,
    capabilities: Mapping[RouteName, GraphNode],
    judge: JudgeExecutorPort,
    compiler: CompilerExecutorPort,
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
        _as_runnable(input_guardrail),
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
        "greeting",
        _as_runnable(greeting_node),
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
        "normalize_user_message",
        _as_runnable(run_normalize_user_message_node),
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
                "greeting"
                if state.get("greeting_classification", {}).get("category")
                == "greeting_only"
                else "context_enrichment"
            ),
            {"greeting": "greeting", "context_enrichment": "context_enrichment"},
        )

    graph.add_edge("context_enrichment", "normalize_user_message")
    graph.add_edge("normalize_user_message", "router")

    router_targets: dict[Hashable, str] = {route: route for route in capabilities}

    router_targets.update(
        {
            "clarification_required": "clarification_required",
            "out_of_scope": "out_of_scope",
            "persist_turn": "persist_turn",
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

    graph.add_edge(
        "compiler",
        "judge",
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

    graph.add_edge("greeting", "output_guardrail")

    for terminal_node in (
        "clarification_required",
        "out_of_scope",
        "judge_blocked",
        "product_workflow_ambiguous",
        "product_workflow_not_found",
        "product_workflow_unavailable",
        "faq_controlled_response",
    ):
        graph.add_edge(terminal_node, "persist_turn")

    graph.add_edge("persist_turn", END)
    graph.add_edge("input_rejected", "persist_turn")

    return graph.compile(checkpointer=checkpointer)
