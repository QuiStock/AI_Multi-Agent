from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage

from src.agents.compiler.compiler_node import create_compiler_node
from src.context.schemas import CompilerResult


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
    node = create_compiler_node(model)

    result = node(
        {
            "messages": [HumanMessage(content="Faça um resumo.")],
            "agent_outputs": [
                {
                    "content": "A primeira parte da resposta.",
                    "status": "success",
                },
                {
                    "content": "A segunda parte da resposta.",
                    "status": "success",
                },
            ],
        }
    )

    assert result["final_response"] == {
        "content": "A resposta consolidada está disponível.",
        "status": "success",
    }
    assert result["validation"]["status"] == "passed"
    assert model.messages is not None
    assert "A primeira parte da resposta." in str(model.messages[-1].content)


def test_compiler_returns_error_without_agent_outputs() -> None:
    model = FakeCompilerModel(
        CompilerResult(content="não deveria ser chamado", status="success")
    )
    node = create_compiler_node(model)

    result = node({"messages": [HumanMessage(content="Faça um resumo.")]})

    assert result["final_response"] == {
        "content": "Não foi possível gerar uma resposta.",
        "status": "error",
    }
    assert result["validation"]["status"] == "blocked"
    assert model.messages is None


def test_compiler_handles_invalid_structured_output() -> None:
    class InvalidCompilerModel:
        def invoke(self, messages: list[Any]) -> dict[str, str]:
            return {"content": "resposta sem status"}

    node = create_compiler_node(InvalidCompilerModel())

    result = node(
        {
            "messages": [HumanMessage(content="Faça um resumo.")],
            "agent_outputs": [{"content": "Resultado do agente.", "status": "success"}],
        }
    )

    assert result["final_response"]["status"] == "error"
    assert result["validation"]["status"] == "blocked"
