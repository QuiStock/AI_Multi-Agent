from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    RemoveMessage,
)

from src.agents.compiler.compiler_node import run_compiler_node
from src.agents.faq.faq_node import faq_node
from src.agents.judge.jev_node import run_judge_node
from src.agents.product_workflow.product_workflow_node import (
    run_product_workflow_node,
)
from src.agents.router.executor import RouterExecutor
from src.agents.router.router_node import run_router_node
from src.graphs.adapters import (
    run_context_enrichment_node,
)
from src.graphs.contracts import RouteResponse
from src.graphs.state import (
    Evidence,
    GraphState,
    ResponseDraft,
)


class FakeRouterExecutor:
    def __init__(self) -> None:
        self.messages: Sequence[AnyMessage] | None = None
        self.request_context: dict[str, Any] | None = None

    def invoke(
        self,
        messages: Sequence[AnyMessage],
        *,
        request_context: dict[str, Any] | None = None,
    ) -> RouteResponse:
        self.messages = messages
        self.request_context = request_context
        return {
            "route": "faq",
            "reason": "Pergunta documental.",
            "status": "success",
        }


class FakeFAQExecutor:
    def __init__(self) -> None:
        self.state: dict[str, Any] | None = None

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        self.state = state
        return {
            "answer": "Resposta baseada na documentação.",
            "evidences": [
                {
                    "evidence_id": "faq-1",
                    "source_type": "faq_document",
                    "source_id": "manual.md",
                    "content": "Conteúdo da documentação.",
                    "metadata": {},
                }
            ],
        }


class FakeProductWorkflowExecutor:
    def invoke(
        self,
        *,
        messages: list[AnyMessage],
        request_context: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "status": "success",
            "answer": "1. Arroz Branco\n2. Arroz Integral",
            "tools_called": [
                {
                    "tool_name": "get_suggestion_for_product",
                    "status": "success",
                    "toolResult": {
                        "status": "success",
                        "data": {
                            "status": "ambiguous",
                            "candidates": [
                                {"position": 1, "product_name": "Arroz Branco"},
                                {"position": 2, "product_name": "Arroz Integral"},
                            ],
                        },
                        "evidence": [
                            {
                                "evidence_id": "candidate-1",
                                "source_type": "product_workflow",
                                "source_id": "postgresql:suggestion:1",
                                "content": '{"product_name":"Arroz Branco"}',
                                "metadata": {"suggestion_id": "1"},
                            },
                            {
                                "evidence_id": "candidate-2",
                                "source_type": "product_workflow",
                                "source_id": "postgresql:suggestion:2",
                                "content": '{"product_name":"Arroz Integral"}',
                                "metadata": {"suggestion_id": "2"},
                            },
                        ],
                    },
                }
            ],
        }


class FakeCompilerExecutor:
    def __init__(self) -> None:
        self.arguments: dict[str, Any] | None = None

    def invoke(self, **kwargs: Any) -> ResponseDraft:
        self.arguments = kwargs
        return {
            "content": "Resposta compilada.",
            "citations": ["faq-1"],
            "status": "success",
        }


class FakeJudgeExecutor:
    def __init__(self) -> None:
        self.response_draft: ResponseDraft | None = None
        self.evidences: Sequence[Evidence] | None = None

    def invoke(
        self,
        *,
        user_question: str | None,
        response_draft: ResponseDraft | None,
        evidences: Sequence[Evidence],
        prior_assistant_message: str | None = None,
    ) -> dict[str, Any]:
        self.response_draft = response_draft
        self.evidences = evidences
        return {
            "status": "approved",
            "reason": "Resposta sustentada.",
            "evidence_count": 1,
        }


def test_router_adapter_forwards_the_sanitized_message_from_shared_state() -> None:
    executor = FakeRouterExecutor()
    state: GraphState = {
        "request": {
            "request_id": "req-1",
            "email": "user-1",
            "conversation_id": "conversation-1",
        },
        "messages": [HumanMessage(content="Mensagem sanitizada.")],
    }

    result = run_router_node(state, router=cast(RouterExecutor, executor))

    assert executor.messages is not None
    assert executor.messages[-1].content == "Mensagem sanitizada."
    assert executor.request_context == state["request"]
    assert result["routing_decision"]["route"] == "faq"
    assert result["status"] == "in_progress"


def test_product_workflow_adapter_keeps_ambiguous_page_evidence() -> None:
    evidence = [
        {
            "evidence_id": "candidate-1",
            "source_type": "product_workflow",
            "source_id": "postgresql:suggestion:1",
            "content": '{"product_name":"Arroz Branco"}',
            "metadata": {"suggestion_id": "1"},
        },
        {
            "evidence_id": "candidate-2",
            "source_type": "product_workflow",
            "source_id": "postgresql:suggestion:2",
            "content": '{"product_name":"Arroz Integral"}',
            "metadata": {"suggestion_id": "2"},
        },
    ]

    result = run_product_workflow_node(
        {
            "request": {},
            "messages": [HumanMessage(content="Busque arroz")],
        },
        executor=FakeProductWorkflowExecutor(),
    )

    assert result["agent_results"]["product_workflow"]["lookup_status"] == ("ambiguous")
    assert result["agent_results"]["product_workflow"]["evidence_ids"] == [
        "candidate-1",
        "candidate-2",
    ]
    assert result["evidences"] == evidence


class FakeConversationEnricher:
    def __init__(self, messages: list[AnyMessage]) -> None:
        self.messages = messages
        self.calls: list[tuple[str, str]] = []

    def restore_messages(
        self,
        *,
        email: str,
        conversation_id: str,
    ) -> list[AnyMessage]:
        self.calls.append((email, conversation_id))
        return self.messages


def test_context_enrichment_does_not_load_history_for_new_conversation() -> None:
    enricher = FakeConversationEnricher([])
    state: GraphState = {
        "request": {
            "request_id": "request-1",
            "email": "user-1",
            "conversation_id": "conversation-1",
            "is_new_conversation": True,
        },
        "messages": [HumanMessage(content="O que comprei?")],
    }

    result = run_context_enrichment_node(state, context_enricher=enricher)

    assert result == {}
    assert enricher.calls == []


def test_context_enrichment_does_not_reopen_an_active_continuing_conversation() -> None:
    enricher = FakeConversationEnricher([])
    state: GraphState = {
        "request": {
            "request_id": "request-2",
            "email": "user-1",
            "conversation_id": "conversation-1",
            "is_new_conversation": False,
            "is_resuming_conversation": False,
        },
        "messages": [HumanMessage(content="Próxima mensagem.")],
    }

    result = run_context_enrichment_node(state, context_enricher=enricher)

    assert result == {}
    assert enricher.calls == []


def test_context_enrichment_restores_history_before_current_sanitized_message() -> None:
    current_id = "request-1:user"
    enricher = FakeConversationEnricher(
        [
            HumanMessage(id="message-1", content="Primeira pergunta."),
            AIMessage(id="message-2", content="Primeira resposta."),
            HumanMessage(id=current_id, content="Mensagem atual sanitizada."),
        ]
    )
    state: GraphState = {
        "request": {
            "request_id": "request-1",
            "email": "user-1",
            "conversation_id": "conversation-1",
            "is_resuming_conversation": True,
        },
        "messages": [HumanMessage(id=current_id, content="Mensagem atual sanitizada.")],
    }

    result = run_context_enrichment_node(state, context_enricher=enricher)
    messages = result["messages"]

    assert enricher.calls == [("user-1", "conversation-1")]
    assert isinstance(messages[0], RemoveMessage)
    assert messages[0].id == current_id
    assert [message.id for message in messages[1:]] == [
        "message-1",
        "message-2",
        current_id,
    ]
    assert messages[-1].content == "Mensagem atual sanitizada."


def test_faq_adapter_calls_executor_and_normalizes_answer() -> None:
    executor = FakeFAQExecutor()
    state: GraphState = {
        "request": {
            "request_id": "request-1",
            "email": "manager@example.com",
            "conversation_id": "conversation-1",
            "role_id": 2,
        },
        "messages": [HumanMessage(content="Qual é a regra?")],
    }

    result = faq_node(state, executor=executor)

    assert executor.state is not None
    assert executor.state["messages"] == state["messages"]
    assert executor.state["request"] == state["request"]
    assert result["agent_results"]["faq"] == {
        "status": "success",
        "answer": "Resposta baseada na documentação.",
        "next_step": "continue",
    }


def test_compiler_node_passes_only_compiler_inputs_to_executor() -> None:
    executor = FakeCompilerExecutor()
    state: GraphState = {
        "agent_results": {
            "faq": {
                "status": "success",
                "answer": "Resposta do FAQ.",
            }
        },
    }

    result = run_compiler_node(state, compiler=executor)

    assert executor.arguments is not None
    assert executor.arguments["agent_results"] == state["agent_results"]
    assert executor.arguments["evidences"] == []
    assert "state" not in executor.arguments
    assert result["response_draft"] == {
        "content": "Resposta compilada.",
        "citations": ["faq-1"],
        "status": "draft",
    }


def test_judge_adapter_forwards_draft_and_full_evidence_content() -> None:
    executor = FakeJudgeExecutor()
    evidence: Evidence = {
        "evidence_id": "faq-1",
        "source_type": "faq_document",
        "source_id": "manual.md",
        "content": "Conteúdo usado para sustentar a resposta.",
        "metadata": {},
    }
    draft: ResponseDraft = {
        "content": "Resposta compilada.",
        "citations": ["faq-1"],
        "status": "draft",
    }

    result = run_judge_node(
        {
            "response_draft": draft,
            "evidences": [evidence],
        },
        judge=executor,
    )

    assert executor.response_draft is draft
    assert executor.evidences == [evidence]
    assert executor.evidences[0]["content"] == evidence["content"]
    assert result["judge"]["status"] == "approved"
    assert result["judge"]["repair_attempts"] == 0
    assert result["final_response"] == {
        "content": "Resposta compilada.",
        "status": "success",
    }
    assert result["response_draft"] is None


def test_judge_adapter_keeps_exact_draft_status_on_approval() -> None:
    executor = FakeJudgeExecutor()
    result = run_judge_node(
        {
            "response_draft": {
                "content": "1. Arroz Branco",
                "citations": ["suggestion-list:abc"],
                "status": "draft",
                "origin": "exact",
                "public_status": "clarification_required",
            },
            "evidences": [],
        },
        judge=executor,
    )

    assert result["final_response"] == {
        "content": "1. Arroz Branco",
        "status": "clarification_required",
    }
    assert result["response_draft"] is None


def test_judge_adapter_preserves_draft_when_approval_is_rejected() -> None:
    class RejectingJudgeExecutor:
        def invoke(
            self,
            *,
            user_question: str | None,
            response_draft: ResponseDraft | None,
            evidences: Sequence[Evidence],
            prior_assistant_message: str | None = None,
        ) -> dict[str, Any]:
            return {
                "status": "insufficient_evidence",
                "reason": "Evidência insuficiente.",
                "evidence_count": 0,
            }

    draft: ResponseDraft = {
        "content": "Resposta compilada.",
        "citations": ["faq-1"],
        "status": "draft",
    }
    result = run_judge_node(
        {"response_draft": draft, "evidences": []},
        judge=RejectingJudgeExecutor(),
    )

    assert result["judge"]["status"] == "insufficient_evidence"
    assert "response_draft" not in result
    assert "final_response" not in result


def test_judge_adapter_fails_closed_on_unexpected_executor_error() -> None:
    class FailingJudgeExecutor:
        def invoke(
            self,
            *,
            user_question: str | None,
            response_draft: ResponseDraft | None,
            evidences: Sequence[Evidence],
            prior_assistant_message: str | None = None,
        ) -> dict[str, Any]:
            raise RuntimeError("unexpected failure")

    result = run_judge_node(
        {
            "response_draft": {
                "content": "Resposta compilada.",
                "citations": ["faq-1"],
                "status": "draft",
            },
            "evidences": [],
        },
        judge=FailingJudgeExecutor(),
    )

    judge_result = result["judge"]
    assert judge_result is not None
    assert judge_result["status"] == "invalid"
    assert result["errors"][0]["code"] == "JUDGE_ADAPTER_FAILURE"


def test_judge_uses_only_the_user_message_without_a_prior_assistant_reply() -> None:
    class CapturingJudge:
        def __init__(self) -> None:
            self.prior: str | None = "unset"
            self.question: str | None = None

        def invoke(
            self,
            *,
            user_question: str | None,
            response_draft: ResponseDraft | None,
            evidences: Sequence[Evidence],
            prior_assistant_message: str | None = None,
        ) -> dict[str, Any]:
            self.question = user_question
            self.prior = prior_assistant_message
            return {
                "status": "approved",
                "reason": "Controlado.",
                "evidence_count": 0,
            }

    judge = CapturingJudge()
    run_judge_node(
        {
            "request": {"request_id": "request-1"},
            "messages": [HumanMessage(content="página 2", id="request-1:user")],
            "response_draft": {
                "content": "Lista da página.",
                "citations": [],
                "status": "draft",
            },
        },
        judge=judge,  # type: ignore[arg-type]
    )

    assert judge.question == "página 2"
    assert judge.prior is None


def test_judge_sends_the_previous_assistant_message_as_context() -> None:
    class CapturingJudge:
        def __init__(self) -> None:
            self.prior: str | None = None

        def invoke(
            self,
            *,
            user_question: str | None,
            response_draft: ResponseDraft | None,
            evidences: Sequence[Evidence],
            prior_assistant_message: str | None = None,
        ) -> dict[str, Any]:
            self.prior = prior_assistant_message
            return {
                "status": "approved",
                "reason": "Controlado.",
                "evidence_count": 0,
            }

    judge = CapturingJudge()
    run_judge_node(
        {
            "request": {"request_id": "request-2"},
            "messages": [
                HumanMessage(content="Quais promoções vigentes?", id="request-1:user"),
                AIMessage(content="As promoções vigentes são:\n1. Agua", id="a-1"),
                HumanMessage(content="página 2", id="request-2:user"),
                AIMessage(content="Esta resposta ainda não existe.", id="a-2"),
            ],
            "response_draft": {
                "content": "7. Leite",
                "citations": [],
                "status": "draft",
            },
        },
        judge=judge,  # type: ignore[arg-type]
    )

    assert judge.prior == "As promoções vigentes são:\n1. Agua"
