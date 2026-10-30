from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage

from src.agents.compiler.executor import CompilerExecutor
from src.agents.router.executor import RouterExecutor
from src.graphs.contracts import CompilerResult, RouteDecision


class FakeCompilerAgent:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.input: dict[str, Any] | None = None

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        self.input = state
        return {"structured_response": self.result}


class FakeCompilerAgentFactory:
    def __init__(self, result: Any) -> None:
        self.agent = FakeCompilerAgent(result)

    def __call__(self, **_: Any) -> FakeCompilerAgent:
        return self.agent


def test_router_executor_normalizes_faq_route() -> None:
    decision = RouteDecision(
        route="faq",
        reason="Pergunta documental.",
    )
    seen: dict[str, Any] = {}

    class RecordingAgent:
        def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
            seen["messages"] = payload["messages"]
            return {"structured_response": decision}

    result = RouterExecutor(agent_factory=lambda **_: RecordingAgent()).invoke(
        [HumanMessage(content="Qual é a regra?")]
    )

    assert result == {
        "route": "faq",
        "reason": "Pergunta documental.",
        "status": "success",
    }
    assert any(
        isinstance(message, HumanMessage) and message.content == "Qual é a regra?"
        for message in seen["messages"]
    )


def test_router_executor_fails_closed_on_model_error() -> None:
    class FailingModel:
        def invoke(self, _: list[Any]) -> Any:
            raise RuntimeError("model unavailable")

    result = RouterExecutor(model=FailingModel()).invoke([])

    assert result["route"] == "clarification_required"
    assert result["status"] == "error"
    assert result["error_code"] == "ROUTER_MODEL_UNAVAILABLE"


def test_compiler_executor_returns_structured_response() -> None:
    factory = FakeCompilerAgentFactory(
        CompilerResult(
            content="Resposta consolidada.",
            citations=["faq-1"],
            status="success",
        )
    )

    result = CompilerExecutor(
        model=object(),
        agent_factory=factory,
    ).invoke(
        messages=[HumanMessage(content="Faça um resumo.")],
        agent_results={
            "faq": {
                "status": "success",
                "answer": "Resultado do FAQ.",
            },
        },
        evidences=[
            {
                "evidence_id": "faq-1",
                "source_type": "faq_document",
                "source_id": "manual.md",
                "content": "Resultado do FAQ.",
                "metadata": {},
            }
        ],
    )

    assert result == {
        "content": "Resposta consolidada.",
        "citations": ["faq-1"],
        "status": "success",
    }
    assert factory.agent.input is not None
    messages = factory.agent.input["messages"]
    assert "Resultado do FAQ." in str(messages[-1].content)


def test_compiler_executor_blocks_missing_outputs() -> None:
    factory = FakeCompilerAgentFactory(
        CompilerResult(
            content="não deveria ser chamado",
            citations=[],
            status="success",
        )
    )

    result = CompilerExecutor(
        model=object(),
        agent_factory=factory,
    ).invoke(
        messages=[HumanMessage(content="Faça um resumo.")],
        agent_results={},
        evidences=[],
    )

    assert result == {
        "content": "Não foi possível gerar uma resposta.",
        "citations": [],
        "status": "blocked",
        "error_code": "COMPILER_NO_AGENT_RESULTS",
    }
    assert factory.agent.input is None


def test_compiler_executor_blocks_invalid_output() -> None:
    result = CompilerExecutor(
        model=object(),
        agent_factory=FakeCompilerAgentFactory({"content": "sem status"}),
    ).invoke(
        messages=[HumanMessage(content="Faça um resumo.")],
        agent_results={
            "faq": {
                "status": "success",
                "answer": "Resultado do FAQ.",
            }
        },
        evidences=[],
    )

    assert result["status"] == "blocked"
    assert result["error_code"] == "COMPILER_EXECUTION_FAILED"
