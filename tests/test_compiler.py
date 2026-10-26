from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage

from src.agents.compiler.compiler_node import run_compiler_node
from src.agents.compiler.compiler_prompt import COMPILER_SYSTEM_PROMPT
from src.agents.compiler.executor import CompilerExecutor
from src.graphs.contracts import CompilerResult


class FakeCompilerAgent:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.input: dict[str, Any] | None = None
        self.call_count = 0

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        self.call_count += 1
        self.input = state
        if isinstance(self.result, Exception):
            raise self.result
        return {"structured_response": self.result}


class FakeCompilerAgentFactory:
    def __init__(self, result: Any) -> None:
        self.agent = FakeCompilerAgent(result)
        self.call: dict[str, Any] | None = None

    def __call__(self, **kwargs: Any) -> FakeCompilerAgent:
        self.call = kwargs
        return self.agent


def _executor(result: Any) -> tuple[CompilerExecutor, FakeCompilerAgentFactory]:
    factory = FakeCompilerAgentFactory(result)
    executor = CompilerExecutor(
        model=object(),
        agent_factory=factory,
    )
    return executor, factory


def test_compiler_prompt_explains_numbered_detail_card() -> None:
    prompt = " ".join(COMPILER_SYSTEM_PROMPT.split())

    assert "escolha numerada" in prompt
    assert "Não repita selection_id" in prompt
    assert "outcome" in prompt and "not_found" in prompt


def test_compiler_prompt_only_allows_exact_current_turn_pii_markers() -> None:
    assert "aparecer literalmente na mensagem atual" in COMPILER_SYSTEM_PROMPT
    assert "Nunca crie, complete, altere ou reutilize um marcador" in (
        COMPILER_SYSTEM_PROMPT
    )
    assert "copie exatamente o marcador correspondente" in COMPILER_SYSTEM_PROMPT


def test_compiler_returns_structured_final_response() -> None:
    executor, factory = _executor(
        CompilerResult(
            content="A resposta consolidada está disponível.",
            citations=["faq-1"],
            status="success",
        )
    )

    result = run_compiler_node(
        {
            "messages": [HumanMessage(content="Faça um resumo.")],
            "agent_results": {
                "faq": {
                    "status": "success",
                    "answer": "A primeira parte da resposta.",
                },
            },
            "evidences": [
                {
                    "evidence_id": "faq-1",
                    "source_type": "faq_document",
                    "source_id": "manual.md",
                    "content": "A primeira parte da resposta.",
                    "metadata": {},
                }
            ],
        },
        compiler=executor,
    )

    assert result["response_draft"] == {
        "content": "A resposta consolidada está disponível.",
        "citations": ["faq-1"],
        "status": "draft",
    }
    assert factory.call is not None
    assert factory.call["card"] is executor.card
    assert factory.call["tools"] == []
    assert factory.call["response_format"] is CompilerResult
    assert factory.agent.call_count == 1
    assert factory.agent.input is not None
    messages = factory.agent.input["messages"]
    assert "A primeira parte da resposta." in str(messages[-1].content)


def test_compiler_returns_blocked_draft_without_agent_results() -> None:
    executor, factory = _executor(
        CompilerResult(
            content="não deveria ser chamado",
            citations=[],
            status="success",
        )
    )

    result = run_compiler_node(
        {"messages": [HumanMessage(content="Faça um resumo.")]},
        compiler=executor,
    )

    assert result["response_draft"] == {
        "content": "Não foi possível gerar uma resposta.",
        "citations": [],
        "status": "blocked",
    }
    assert factory.agent.call_count == 0
    assert factory.agent.input is None


def test_compiler_handles_invalid_structured_output() -> None:
    executor, factory = _executor({"content": "resposta sem status"})

    result = run_compiler_node(
        {
            "messages": [HumanMessage(content="Faça um resumo.")],
            "agent_results": {
                "faq": {
                    "status": "success",
                    "answer": "Resultado do agente.",
                }
            },
        },
        compiler=executor,
    )

    assert result["response_draft"]["status"] == "blocked"
    assert factory.agent.call_count == 1


def test_compiler_fails_closed_when_agent_is_unavailable() -> None:
    executor, factory = _executor(RuntimeError("agent unavailable"))

    result = run_compiler_node(
        {
            "messages": [HumanMessage(content="Faça um resumo.")],
            "agent_results": {
                "faq": {
                    "status": "success",
                    "answer": "Resultado do agente.",
                }
            },
        },
        compiler=executor,
    )

    assert result["response_draft"] == {
        "content": "Não foi possível gerar uma resposta.",
        "citations": [],
        "status": "blocked",
    }
    assert factory.agent.call_count == 1


def test_compiler_forwards_judge_feedback_for_single_reformulation() -> None:
    executor, factory = _executor(
        CompilerResult(
            content="Resposta reformulada.",
            citations=["faq-1"],
            status="success",
        )
    )

    result = run_compiler_node(
        {
            "messages": [HumanMessage(content="Faça um resumo.")],
            "agent_results": {
                "faq": {
                    "status": "success",
                    "answer": "Resultado do agente.",
                }
            },
            "evidences": [
                {
                    "evidence_id": "faq-1",
                    "source_type": "faq_document",
                    "source_id": "manual.md",
                    "content": "Resultado do agente.",
                    "metadata": {},
                }
            ],
            "judge": {
                "status": "insufficient_evidence",
                "reason": "Alegação sem suporte.",
                "evidence_count": 1,
                "reason_code": "unsupported_claim",
                "repair_attempts": 1,
                "judge_feedback": {
                    "status": "insufficient_evidence",
                    "reason": "Alegação sem suporte.",
                    "evidence_count": 1,
                    "reason_code": "unsupported_claim",
                },
            },
        },
        compiler=executor,
    )

    assert result["response_draft"]["content"] == "Resposta reformulada."
    assert factory.agent.call_count == 1
    assert factory.agent.input is not None
    context = str(factory.agent.input["messages"][-1].content)
    assert "judge_feedback" in context
    assert "unsupported_claim" in context
