from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage

from src.agents.compiler.executor import CompilerExecutor
from src.graphs.adapters import run_compiler_node
from src.graphs.contracts import CompilerResult


class FakeCompilerModel:
    def __init__(self, result: CompilerResult) -> None:
        self.result = result
        self.messages: list[Any] | None = None

    def invoke(self, messages: list[Any]) -> CompilerResult:
        self.messages = messages
        return self.result


def test_compiler_returns_structured_final_response() -> None:
    model = FakeCompilerModel(
        CompilerResult(
            content="A resposta consolidada está disponível.",
            status="success",
        )
    )
    executor = CompilerExecutor(model=model)

    result = run_compiler_node(
        {
            "messages": [HumanMessage(content="Faça um resumo.")],
            "agent_results": {
                "faq": {
                    "status": "success",
                    "answer": "A primeira parte da resposta.",
                    "citation_ids": ["faq-1"],
                },
                "judge": {
                    "status": "approved",
                    "reason": "Evidência suficiente.",
                    "evidence_ids": ["faq-1"],
                },
            },
        },
        compiler=executor,
    )

    assert result["response_draft"] == {
        "content": "A resposta consolidada está disponível.",
        "citations": ["faq-1"],
        "status": "draft",
    }
    assert model.messages is not None
    assert "A primeira parte da resposta." in str(model.messages[-1].content)


def test_compiler_returns_blocked_draft_without_agent_results() -> None:
    model = FakeCompilerModel(
        CompilerResult(content="não deveria ser chamado", status="success")
    )
    executor = CompilerExecutor(model=model)

    result = run_compiler_node(
        {"messages": [HumanMessage(content="Faça um resumo.")]},
        compiler=executor,
    )

    assert result["response_draft"] == {
        "content": "Não foi possível gerar uma resposta.",
        "citations": [],
        "status": "blocked",
    }
    assert model.messages is None


def test_compiler_handles_invalid_structured_output() -> None:
    class InvalidCompilerModel:
        def invoke(self, messages: list[Any]) -> dict[str, str]:
            return {"content": "resposta sem status"}

    executor = CompilerExecutor(model=InvalidCompilerModel())

    result = run_compiler_node(
        {
            "messages": [HumanMessage(content="Faça um resumo.")],
            "agent_results": {
                "faq": {
                    "status": "success",
                    "answer": "Resultado do agente.",
                    "citation_ids": [],
                }
            },
        },
        compiler=executor,
    )

    assert result["response_draft"]["status"] == "blocked"
