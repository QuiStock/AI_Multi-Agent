from __future__ import annotations

from datetime import UTC, datetime
from functools import partial
from typing import Any, cast

from langchain_core.messages import AnyMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from src.agents.compiler.compiler_node import COMPILER_BLOCKED_RESPONSE
from src.agents.faq.faq_node import FAQ_NO_RESULTS_MESSAGE, faq_node
from src.agents.faq.tools.schemas import FAQSearchData, FAQSearchItem
from src.agents.judge.jev_node import JUDGE_BLOCKED_RESPONSE
from src.agents.schemas.tool_result import ToolEvidence
from src.agents.tooling.result_factory import (
    ToolResultExtras,
    compose_success,
    create_tool_metadata,
)
from src.graphs.agent_graph import (
    create_agent_graph,
    decide_after_product_workflow,
    product_workflow_ambiguous_node,
    product_workflow_not_found_node,
)
from src.graphs.contracts import RouteResponse
from src.graphs.decisions import (
    decide_after_faq,
    decide_after_input_guardrail,
    decide_after_judge,
    decide_after_router,
)
from src.graphs.state import GraphState


def _passed_input(_: dict[str, Any]) -> dict[str, Any]:
    return {
        "input_guardrail": {
            "status": "passed",
            "reason_code": "approved",
            "reason": "Aprovado.",
            "redactions": [],
        }
    }


def _blocked_input(_: dict[str, Any]) -> dict[str, Any]:
    return {
        "input_guardrail": {
            "status": "blocked",
            "reason_code": "prompt_injection",
            "reason": "Bloqueado.",
            "redactions": [],
        }
    }


class FakeRouter:
    def __init__(self, route: str, outcome: str) -> None:
        self.route = route
        self.outcome = outcome

    def invoke(
        self,
        _: list[AnyMessage],
        *,
        request_context: dict[str, Any] | None = None,
    ) -> RouteResponse:
        return {
            "route": self.route,
            "reason": "Decisão de teste.",
            "status": "success",
        }


def _faq_tool_result(*, found: bool) -> dict[str, Any]:
    data = FAQSearchData(
        query="pergunta",
        outcome="found" if found else "not_found",
        result_count=1 if found else 0,
        results=(
            [
                FAQSearchItem(
                    file_name="manual.md",
                    content="Conteúdo da documentação.",
                    relevance=0.9,
                )
            ]
            if found
            else []
        ),
    )
    if found:
        extras = ToolResultExtras(
            evidence=(
                ToolEvidence(
                    evidence_id="faq-1",
                    source_type="faq_document",
                    source_id="manual.md",
                    content="Conteúdo da documentação.",
                ),
            )
        )
    else:
        extras = ToolResultExtras(
            evidence=(
                ToolEvidence(
                    evidence_id="faq-not-found",
                    source_type="faq_document",
                    source_id="faq-search",
                    content=(
                        "A busca documental foi concluída sem encontrar "
                        "trechos sobre o assunto."
                    ),
                    metadata={
                        "outcome": "not_found",
                        "status": "not_found",
                        "result_count": 0,
                    },
                ),
            )
        )
    result = compose_success(
        data=data,
        meta=create_tool_metadata(
            tool_name="faq_search",
            tool_version="1.0.0",
            tool_call_id="call-1",
            trace_id="trace-1",
            timestamp=datetime(2026, 9, 17, 14, 0, tzinfo=UTC),
        ),
        extras=extras,
    )
    return result.model_dump(mode="json")


class FakeFAQExecutor:
    def invoke(
        self,
        *,
        messages: list[AnyMessage],
        allowed_audiences: tuple[str, ...],
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return {
            "status": "success",
            "answer": "Resposta baseada na documentação.",
            "tool_called": {"toolResult": _faq_tool_result(found=True)},
        }


class ControlledFAQExecutor:
    def invoke(
        self,
        *,
        messages: list[AnyMessage],
        allowed_audiences: tuple[str, ...],
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return {
            "status": "success",
            "answer": FAQ_NO_RESULTS_MESSAGE,
            "tool_called": {"toolResult": _faq_tool_result(found=False)},
        }


class FakeJudge:
    def __init__(
        self,
        status: str = "approved",
        events: list[str] | None = None,
        reason_code: str | None = None,
        error_code: str | None = None,
    ) -> None:
        self.status = status
        self.events = events
        self.reason_code = reason_code
        self.error_code = error_code

    def invoke(
        self,
        *,
        user_question: str | None,
        response_draft: dict[str, Any] | None,
        evidences: list[dict[str, Any]],
        prior_assistant_message: str | None = None,
    ) -> dict[str, Any]:
        if self.events is not None:
            self.events.append("judge")

        result = {
            "status": self.status,
            "reason": "Resultado controlado.",
            "evidence_count": 1 if self.status == "approved" else 0,
        }
        if self.reason_code is not None:
            result["reason_code"] = self.reason_code
        if self.error_code is not None:
            result["error_code"] = self.error_code
        return result


class RepairJudge:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(
        self,
        *,
        user_question: str | None,
        response_draft: dict[str, Any] | None,
        evidences: list[dict[str, Any]],
        prior_assistant_message: str | None = None,
    ) -> dict[str, Any]:
        self.calls += 1
        content = response_draft.get("content") if response_draft else None
        if content != "Resposta corrigida.":
            return {
                "status": "insufficient_evidence",
                "reason": "Alegação sem suporte.",
                "evidence_count": 1,
                "reason_code": "unsupported_claim",
            }
        return {
            "status": "approved",
            "reason": "Resposta corrigida.",
            "evidence_count": 1,
        }


class AlwaysRejectJudge:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(
        self,
        *,
        user_question: str | None,
        response_draft: dict[str, Any] | None,
        evidences: list[dict[str, Any]],
        prior_assistant_message: str | None = None,
    ) -> dict[str, Any]:
        self.calls += 1
        return {
            "status": "insufficient_evidence",
            "reason": "Alegação sem suporte.",
            "evidence_count": 1,
            "reason_code": "unsupported_claim",
        }


class RepairCompiler:
    def __init__(self) -> None:
        self.calls = 0
        self.saw_feedback = False

    def invoke(self, **kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        if kwargs.get("judge_feedback") is not None:
            self.saw_feedback = True
            return {
                "content": "Resposta corrigida.",
                "citations": ["faq-1"],
                "status": "success",
            }
        return {
            "content": "Resposta inicial.",
            "citations": ["faq-1"],
            "status": "success",
        }


class FakeCompiler:
    def __init__(self, events: list[str] | None = None) -> None:
        self.events = events

    def invoke(self, **_: Any) -> dict[str, Any]:
        if self.events is not None:
            self.events.append("compiler")

        return {
            "content": "Resposta compilada.",
            "citations": ["faq-1"],
            "status": "success",
        }


class FakeBlockedCompiler:
    def invoke(self, **_: Any) -> dict[str, Any]:
        return {
            "content": "Não foi possível gerar uma resposta.",
            "citations": [],
            "status": "blocked",
        }


def _passing_output(state: dict[str, Any]) -> dict[str, Any]:
    final_response = state.get("final_response")
    result: dict[str, Any] = {
        "output_guardrail": {
            "status": "passed",
            "reason_code": "approved",
            "reason": "Aprovado.",
            "violations": [],
        }
    }
    if final_response:
        result["final_response"] = final_response
    return result


class EmptyContextEnricher:
    def restore_messages(self, *, email: str, conversation_id: str) -> list[AnyMessage]:
        return []


def _graph_input(content: str) -> dict[str, Any]:
    return {
        "request": {
            "request_id": "request-1",
            "email": "user-1",
            "conversation_id": "conversation-1",
            "role_id": 3,
        },
        "messages": [HumanMessage(content=content, id="request-1:user")],
    }


def _graph(
    judge_status: str = "approved",
    *,
    judge_error_code: str | None = None,
) -> Any:
    return create_agent_graph(
        input_guardrail=_passed_input,
        router=FakeRouter("faq", "dispatch"),
        capabilities={
            "faq": partial(
                faq_node,
                executor=FakeFAQExecutor(),
            )
        },
        judge=FakeJudge(judge_status, error_code=judge_error_code),
        compiler=FakeCompiler(),
        output_guardrail=_passing_output,
        context_enricher=EmptyContextEnricher(),
    )


def test_decision_functions_fail_closed() -> None:
    assert decide_after_input_guardrail({}) == "input_rejected"
    assert decide_after_router({}, active_routes={"faq"}) == "out_of_scope"
    assert (
        decide_after_router(
            {"routing_decision": {"route": "faq", "outcome": "dispatch"}},
            active_routes={"faq"},
        )
        == "faq"
    )
    assert (
        decide_after_faq(
            {
                "agent_results": {
                    "faq": {
                        "status": "success",
                        "answer": "Sem evidência.",
                        "citation_ids": [],
                        "next_step": "direct_response",
                    }
                }
            }
        )
        == "faq_controlled_response"
    )
    assert (
        decide_after_faq(
            {
                "agent_results": {
                    "faq": {
                        "status": "success",
                        "answer": "Sem evidência.",
                        "next_step": "clarification",
                    }
                }
            }
        )
        == "compiler"
    )
    assert (
        decide_after_router(
            {
                "routing_decision": {
                    "route": "memory_recall",
                    "outcome": "direct_response",
                    "status": "success",
                }
            },
            active_routes={"faq"},
        )
        == "judge"
    )
    assert (
        decide_after_router(
            {
                "errors": [{"agent": "router", "code": "ROUTER_INVALID_OUTPUT"}],
                "routing_decision": {
                    "route": "clarification_required",
                    "outcome": "direct_response",
                    "status": "error",
                },
            },
            active_routes={"faq"},
        )
        == "router_error"
    )


def test_product_workflow_domain_outcomes_do_not_use_unavailable_node() -> None:
    base = {
        "status": "error",
        "answer": "",
        "evidence_ids": [],
    }

    assert (
        decide_after_product_workflow(
            {
                "agent_results": {
                    "product_workflow": {**base, "lookup_status": "ambiguous"}
                }
            }
        )
        == "product_workflow_ambiguous"
    )
    assert (
        decide_after_product_workflow(
            {
                "agent_results": {
                    "product_workflow": {**base, "lookup_status": "not_found"}
                }
            }
        )
        == "product_workflow_not_found"
    )
    assert (
        decide_after_product_workflow(
            {
                "agent_results": {
                    "product_workflow": {
                        **base,
                        "lookup_status": "unavailable",
                    }
                }
            }
        )
        == "product_workflow_unavailable"
    )


def test_product_workflow_ambiguous_node_preserves_candidate_page() -> None:
    candidate_page = "Sugestões 1–2:\n1. Arroz Branco\n2. Arroz Integral"
    update = product_workflow_ambiguous_node(
        {
            "agent_results": {
                "product_workflow": {
                    "answer": candidate_page,
                    "lookup_status": "ambiguous",
                    "evidence_ids": ["suggestion-list:abc"],
                }
            }
        }
    )

    assert update["response_draft"] == {
        "content": candidate_page,
        "citations": ["suggestion-list:abc"],
        "status": "draft",
        "origin": "exact",
        "public_status": "clarification_required",
    }
    assert "final_response" not in update


def test_product_workflow_not_found_node_keeps_the_controlled_sentence() -> None:
    sentence = "Não há sugestões válidas para essa busca."
    update = product_workflow_not_found_node(
        {
            "agent_results": {
                "product_workflow": {
                    "answer": sentence,
                    "lookup_status": "not_found",
                    "evidence_ids": ["product-search:abc"],
                }
            }
        }
    )

    draft = update["response_draft"]
    assert draft is not None
    assert draft["content"] == sentence
    assert draft["origin"] == "exact"
    assert draft["public_status"] == "clarification_required"
    assert draft["citations"] == ["product-search:abc"]


def test_exact_product_draft_rejection_skips_compiler_repair() -> None:
    rejected = {
        "judge": {
            "status": "insufficient_evidence",
            "reason": "A lista não foi aceita.",
            "evidence_count": 1,
            "repair_attempts": 0,
            "reason_code": "unsupported_claim",
        },
        "response_draft": {
            "content": "1. Arroz",
            "citations": ["suggestion-list:abc"],
            "status": "draft",
            "origin": "exact",
            "public_status": "clarification_required",
        },
    }
    compiled = {
        "judge": rejected["judge"],
        "response_draft": {
            "content": "Card compilado.",
            "citations": ["suggestion-detail:abc"],
            "status": "draft",
        },
    }

    assert decide_after_judge(cast(GraphState, rejected)) == "judge_blocked"
    assert decide_after_judge(cast(GraphState, compiled)) == "prepare_judge_repair"


def test_graph_dispatches_to_faq_compiler_and_judge() -> None:
    result = _graph().invoke(
        {
            "request": {
                "request_id": "request-1",
                "email": "user-1",
                "conversation_id": "conversation-1",
                "role_code": "EMPLOYEE",
                "is_new_conversation": True,
            },
            "messages": [
                HumanMessage(content="pergunta original", id="request-1:user")
            ],
        }
    )

    assert result["agent_results"]["faq"]["status"] == "success"
    assert result["judge"]["status"] == "approved"
    assert result["response_draft"] is None
    assert result["final_response"] == {
        "content": "Resposta compilada.",
        "status": "success",
    }
    assert result["output_guardrail"]["status"] == "passed"
    assert result["status"] == "completed"
    assert "memory" not in result


def test_graph_sends_faq_without_documents_to_compiler_and_judge() -> None:
    events: list[str] = []
    graph = create_agent_graph(
        input_guardrail=_passed_input,
        router=FakeRouter("faq", "dispatch"),
        capabilities={
            "faq": partial(
                faq_node,
                executor=ControlledFAQExecutor(),
            )
        },
        judge=FakeJudge(events=events),
        compiler=FakeCompiler(events=events),
        output_guardrail=_passing_output,
        context_enricher=EmptyContextEnricher(),
    )

    result = graph.invoke(_graph_input("pergunta sem evidência"))

    assert events == ["compiler", "judge"]
    assert result["evidences"][0]["metadata"]["outcome"] == "not_found"
    assert result["evidences"][0]["metadata"]["result_count"] == 0
    assert result["agent_results"]["faq"]["answer"] == FAQ_NO_RESULTS_MESSAGE
    assert result["judge"]["status"] == "approved"
    assert result["response_draft"] is None
    assert result["final_response"]["status"] == "success"
    assert result["final_response"]["content"] == "Resposta compilada."


def test_graph_sends_memory_recall_to_judge_without_compiler() -> None:
    class MemoryRouter:
        def invoke(
            self,
            _: list[AnyMessage],
            *,
            request_context: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            return {
                "route": "memory_recall",
                "reason": "A pessoa quer relembrar a conversa.",
                "status": "success",
                "tool_called": {
                    "tool_name": "search_conversation_summaries",
                    "status": "success",
                    "toolResult": {
                        "status": "success",
                        "data": {"results": []},
                        "evidence": [
                            {
                                "evidence_id": "summary-1",
                                "source_type": "conversation_summary",
                                "source_id": "past-1",
                                "content": "Conversamos sobre leite integral.",
                                "metadata": {
                                    "retrieval_source": "semantic",
                                    "status": "semantic",
                                },
                            }
                        ],
                    },
                },
            }

    class CompilerMustNotRun:
        def invoke(self, **_: Any) -> dict[str, Any]:
            raise AssertionError("O recall de memória não entra no compiler.")

    graph = create_agent_graph(
        input_guardrail=_passed_input,
        router=MemoryRouter(),
        capabilities={},
        judge=FakeJudge(),
        compiler=CompilerMustNotRun(),
        output_guardrail=_passing_output,
        context_enricher=EmptyContextEnricher(),
    )

    result = graph.invoke(_graph_input("O que falamos sobre leite?"))

    assert "leite integral" in result["final_response"]["content"]
    assert result["final_response"]["status"] == "success"
    assert result["judge"]["status"] == "approved"
    assert result["response_draft"] is None


def test_exact_memory_draft_can_cite_conversation_summaries() -> None:
    from src.agents.judge.executor import JudgeExecutor

    class IdleClient:
        def evaluate(self, **_: Any) -> Any:
            raise AssertionError("A trava local não deveria chamar o JEV.")

    executor = JudgeExecutor(jev_client=IdleClient())  # type: ignore[arg-type]
    evidence = {
        "evidence_id": "summary-1",
        "source_type": "conversation_summary",
        "source_id": "past-1",
        "content": "Conversamos sobre leite integral.",
        "metadata": {"status": "semantic"},
    }
    exact = {
        "content": "Conversamos sobre leite integral.",
        "citations": ["summary-1"],
        "status": "draft",
        "origin": "exact",
    }
    compiled = {
        "content": "Conversamos sobre leite integral.",
        "citations": ["summary-1"],
        "status": "draft",
    }

    assert (
        executor._validate_input(
            user_question="O que falamos?",
            response_draft=exact,  # type: ignore[arg-type]
            evidences=[evidence],  # type: ignore[list-item]
        )
        is None
    )
    blocked = executor._validate_input(
        user_question="O que falamos?",
        response_draft=compiled,  # type: ignore[arg-type]
        evidences=[evidence],  # type: ignore[list-item]
    )
    assert blocked is not None
    assert blocked["error_code"] == "JUDGE_MEMORY_ONLY"


def test_graph_runs_compiler_before_judge() -> None:
    events: list[str] = []
    graph = create_agent_graph(
        input_guardrail=_passed_input,
        router=FakeRouter("faq", "dispatch"),
        capabilities={
            "faq": partial(
                faq_node,
                executor=FakeFAQExecutor(),
            )
        },
        judge=FakeJudge(events=events),
        compiler=FakeCompiler(events=events),
        output_guardrail=_passing_output,
        context_enricher=EmptyContextEnricher(),
    )

    graph.invoke(_graph_input("pergunta"))

    assert events == ["compiler", "judge"]


def test_graph_returns_controlled_response_for_input_rejection() -> None:
    graph = create_agent_graph(
        input_guardrail=_blocked_input,
        router=FakeRouter("faq", "dispatch"),
        capabilities={
            "faq": partial(
                faq_node,
                executor=FakeFAQExecutor(),
            )
        },
        judge=FakeJudge(),
        compiler=FakeCompiler(),
        output_guardrail=_passing_output,
        context_enricher=EmptyContextEnricher(),
    )

    result = graph.invoke(_graph_input("bloqueada"))

    assert result["final_response"] == {
        "content": "Desculpe, não posso tratar desse tipo de assunto no Quistock.",
        "status": "rejected",
    }


def test_graph_handles_clarification_and_out_of_scope_routes() -> None:
    for route, outcome, expected_content, expected_status in [
        (
            "clarification_required",
            "clarification_required",
            "Pode me dar mais detalhes sobre o que você precisa no Quistock?",
            "clarification_required",
        ),
        (
            "out_of_scope",
            "out_of_scope",
            (
                "Desculpe, não consigo ajudar com esse assunto. "
                "Posso ajudar com informações sobre o Quistock, produtos e sugestões."
            ),
            "out_of_scope",
        ),
    ]:
        graph = create_agent_graph(
            input_guardrail=_passed_input,
            router=FakeRouter(route, outcome),
            capabilities={
                "faq": partial(
                    faq_node,
                    executor=FakeFAQExecutor(),
                )
            },
            judge=FakeJudge(),
            compiler=FakeCompiler(),
            output_guardrail=_passing_output,
            context_enricher=EmptyContextEnricher(),
        )

        result = graph.invoke(_graph_input("pergunta"))

        assert result["final_response"] == {
            "content": expected_content,
            "status": expected_status,
        }


def test_graph_returns_controlled_response_when_judge_blocks() -> None:
    result = _graph(judge_status="insufficient_evidence").invoke(
        _graph_input("pergunta")
    )

    assert result["final_response"] == {
        "content": JUDGE_BLOCKED_RESPONSE,
        "status": "clarification_required",
    }
    assert result["judge"]["status"] == "insufficient_evidence"


def test_graph_returns_jev_unavailable_message_and_keeps_diagnostic() -> None:
    result = _graph(
        judge_status="invalid",
        judge_error_code="JUDGE_JEV_UNAVAILABLE",
    ).invoke(_graph_input("pergunta"))

    assert result["errors"][-1]["code"] == "JUDGE_JEV_UNAVAILABLE"
    assert result["final_response"] == {
        "content": "Desculpe, estamos com instabilidade com o fefo.",
        "status": "error",
    }


def test_graph_returns_controlled_response_when_judge_is_invalid() -> None:
    result = _graph(judge_status="invalid").invoke(_graph_input("pergunta"))

    assert result["final_response"] == {
        "content": "Não foi possível validar a resposta gerada.",
        "status": "error",
    }


def test_graph_reforms_once_after_correctable_judge_rejection() -> None:
    judge = RepairJudge()
    compiler = RepairCompiler()
    graph = create_agent_graph(
        input_guardrail=_passed_input,
        router=FakeRouter("faq", "dispatch"),
        capabilities={
            "faq": partial(
                faq_node,
                executor=FakeFAQExecutor(),
            )
        },
        judge=judge,
        compiler=compiler,
        output_guardrail=_passing_output,
        context_enricher=EmptyContextEnricher(),
    )

    result = graph.invoke(_graph_input("pergunta"))

    assert judge.calls == 2
    assert compiler.calls == 2
    assert compiler.saw_feedback is True
    assert result["judge"]["repair_attempts"] == 1
    assert result["final_response"] == {
        "content": "Resposta corrigida.",
        "status": "success",
    }
    assert result["response_draft"] is None


def test_graph_repairs_again_on_the_next_checkpointed_turn() -> None:
    judge = RepairJudge()
    compiler = RepairCompiler()
    graph = create_agent_graph(
        input_guardrail=_passed_input,
        router=FakeRouter("faq", "dispatch"),
        capabilities={
            "faq": partial(
                faq_node,
                executor=FakeFAQExecutor(),
            )
        },
        judge=judge,
        compiler=compiler,
        output_guardrail=_passing_output,
        context_enricher=EmptyContextEnricher(),
        checkpointer=MemorySaver(),
    )
    config = {"configurable": {"thread_id": "conversation-1"}}

    graph.invoke(_graph_input("pergunta"), config)
    result = graph.invoke(
        {
            "request": {
                "request_id": "request-2",
                "email": "user-1",
                "conversation_id": "conversation-1",
                "role_code": "EMPLOYEE",
            },
            "messages": [HumanMessage(content="outra pergunta", id="request-2:user")],
        },
        config,
    )

    assert judge.calls == 4
    assert compiler.calls == 4
    assert result["judge"]["repair_attempts"] == 1
    assert result["final_response"]["content"] == "Resposta corrigida."


def test_graph_returns_controlled_response_without_repair_for_missing_evidence() -> (
    None
):
    compiler = RepairCompiler()
    graph = create_agent_graph(
        input_guardrail=_passed_input,
        router=FakeRouter("faq", "dispatch"),
        capabilities={
            "faq": partial(
                faq_node,
                executor=FakeFAQExecutor(),
            )
        },
        judge=FakeJudge(
            status="insufficient_evidence",
            reason_code="missing_evidence",
        ),
        compiler=compiler,
        output_guardrail=_passing_output,
        context_enricher=EmptyContextEnricher(),
    )

    result = graph.invoke(_graph_input("pergunta"))

    assert compiler.calls == 1
    assert result["final_response"] == {
        "content": JUDGE_BLOCKED_RESPONSE,
        "status": "clarification_required",
    }
    assert result["judge"]["reason_code"] == "missing_evidence"
    assert result["response_draft"] is None


def test_graph_allows_only_one_repair_attempt() -> None:
    judge = AlwaysRejectJudge()
    compiler = RepairCompiler()
    graph = create_agent_graph(
        input_guardrail=_passed_input,
        router=FakeRouter("faq", "dispatch"),
        capabilities={
            "faq": partial(
                faq_node,
                executor=FakeFAQExecutor(),
            )
        },
        judge=judge,
        compiler=compiler,
        output_guardrail=_passing_output,
        context_enricher=EmptyContextEnricher(),
    )

    result = graph.invoke(_graph_input("pergunta"))

    assert judge.calls == 2
    assert compiler.calls == 2
    assert result["final_response"]["status"] == "clarification_required"
    assert result["response_draft"] is None


def test_graph_returns_controlled_error_when_compiler_blocks() -> None:
    graph = create_agent_graph(
        input_guardrail=_passed_input,
        router=FakeRouter("faq", "dispatch"),
        capabilities={
            "faq": partial(
                faq_node,
                executor=FakeFAQExecutor(),
            )
        },
        judge=FakeJudge("invalid"),
        compiler=FakeBlockedCompiler(),
        output_guardrail=_passing_output,
        context_enricher=EmptyContextEnricher(),
    )

    result = graph.invoke(_graph_input("pergunta"))

    assert result["final_response"] == {
        "content": COMPILER_BLOCKED_RESPONSE,
        "status": "error",
    }
