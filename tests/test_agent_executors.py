from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage

from src.agents.compiler.executor import CompilerExecutor
from src.agents.router.executor import RouterExecutor
from src.graphs.contracts import CompilerResult, RouteDecision


class FakeRouterModel:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.messages: list[Any] | None = None

    def invoke(self, messages: list[Any]) -> Any:
        self.messages = messages
        return self.result


class FakeCompilerModel:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.messages: list[Any] | None = None

    def invoke(self, messages: list[Any]) -> Any:
        self.messages = messages
        return self.result


def test_router_executor_normalizes_faq_route() -> None:
    model = FakeRouterModel(
        RouteDecision(
            route="faq",
            reason="Pergunta documental.",
        )
    )

    result = RouterExecutor(model=model).invoke(
        [HumanMessage(content="Qual é a regra?")]
    )

    assert result == {
        "route": "faq",
        "target_agent": "faq",
        "outcome": "dispatch",
        "reason": "Pergunta documental.",
    }
    assert model.messages is not None


def test_router_executor_fails_closed_on_model_error() -> None:
    class FailingModel:
        def invoke(self, _: list[Any]) -> Any:
            raise RuntimeError("model unavailable")

    result = RouterExecutor(model=FailingModel()).invoke([])

    assert result["route"] == "clarification_required"
    assert result["outcome"] == "clarification_required"


def test_compiler_executor_returns_structured_response() -> None:
    model = FakeCompilerModel(
        CompilerResult(
            content="Resposta consolidada.",
            status="success",
        )
    )

    result = CompilerExecutor(model=model).invoke(
        {
            "messages": [HumanMessage(content="Faça um resumo.")],
            "agent_outputs": [
                {
                    "content": "Resultado do FAQ.",
                    "status": "success",
                }
            ],
        }
    )

    assert result["validation"]["status"] == "passed"
    assert result["final_response"] == {
        "content": "Resposta consolidada.",
        "status": "success",
    }
    assert model.messages is not None
    assert "Resultado do FAQ." in str(model.messages[-1].content)


def test_compiler_executor_blocks_missing_outputs() -> None:
    model = FakeCompilerModel(
        CompilerResult(
            content="não deveria ser chamado",
            status="success",
        )
    )

    result = CompilerExecutor(model=model).invoke(
        {"messages": [HumanMessage(content="Faça um resumo.")]}
    )

    assert result["validation"]["status"] == "blocked"
    assert result["final_response"]["status"] == "error"
    assert model.messages is None


def test_compiler_executor_blocks_invalid_output() -> None:
    result = CompilerExecutor(
        model=FakeCompilerModel({"content": "sem status"})
    ).invoke(
        {
            "messages": [HumanMessage(content="Faça um resumo.")],
            "agent_outputs": [
                {
                    "content": "Resultado do FAQ.",
                    "status": "success",
                }
            ],
        }
    )

    assert result["validation"]["status"] == "blocked"
    assert result["final_response"]["status"] == "error"
