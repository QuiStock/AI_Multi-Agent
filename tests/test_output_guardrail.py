from __future__ import annotations

from typing import Any

from src.context.schemas import SupportValidationResult
from src.guardrails.output_guardrail import (
    CONTROLLED_OUTPUT_RESPONSE,
    create_output_guardrail_node,
    evaluate_compiled_output,
    output_guardrail_node,
    validate_output,
)


def _state(
    content: str | None,
    *,
    agent_contents: list[str] | None = None,
) -> dict[str, Any]:
    state: dict[str, Any] = {"status": "in_progress"}
    if content is not None:
        state["final_response"] = {"content": content, "status": "success"}
    if agent_contents is not None:
        state["agent_outputs"] = [
            {"content": agent_content, "status": "success"}
            for agent_content in agent_contents
        ]
    return state


def test_faq_output_only_checks_markdown() -> None:
    def fail_evaluator(_: str, __: list[str]) -> str:
        raise AssertionError("FAQ não deve chamar o avaliador semântico")

    result = validate_output(
        "Resposta informativa sem fonte externa.",
        source="faq",
        evaluator=fail_evaluator,
    )

    assert result["status"] == "passed"
    assert result["reason_code"] == "approved"
    assert "sanitized_content" not in result


def test_faq_output_blocks_unbalanced_markdown() -> None:
    result = validate_output("Resposta com **negrito incompleto.", source="faq")

    assert result["status"] == "blocked"
    assert result["reason_code"] == "invalid_markdown"
    assert "unbalanced_bold_delimiter" in result["violations"]


def test_faq_output_removes_emojis_and_passes() -> None:
    content = "Resposta com símbolo proibido " + chr(0x1F642)
    result = validate_output(content, source="faq")

    assert result["status"] == "passed"
    assert result["reason_code"] == "approved"
    assert result["sanitized_content"] == "Resposta com símbolo proibido "


def test_compiled_output_passes_when_supported() -> None:
    received: list[tuple[str, list[str]]] = []

    def evaluator(response: str, references: list[str]) -> str:
        received.append((response, references))
        return "supported"

    result = validate_output(
        "A resposta compilada está sustentada.",
        source="compiled",
        references=["Material do agente FAQ."],
        evaluator=evaluator,
    )

    assert result["status"] == "passed"
    assert received == [
        ("A resposta compilada está sustentada.", ["Material do agente FAQ."])
    ]


def test_compiled_evaluator_receives_content_without_emojis() -> None:
    content = "Resposta compilada " + chr(0x1F642)
    received: list[str] = []

    def evaluator(response: str, _: list[str]) -> str:
        received.append(response)
        return "supported"

    result = validate_output(content, source="compiled", evaluator=evaluator)

    assert result["status"] == "passed"
    assert received == ["Resposta compilada "]
    assert result["sanitized_content"] == "Resposta compilada "


def test_compiled_output_blocks_unsupported_content() -> None:
    result = validate_output(
        "A resposta adiciona uma informação não encontrada.",
        source="compiled",
        evaluator=lambda _response, _references: "unsupported",
    )

    assert result["status"] == "blocked"
    assert result["reason_code"] == "unsupported_content"


def test_compiled_output_blocks_when_validator_is_unavailable() -> None:
    def failing_evaluator(_: str, __: list[str]) -> str:
        raise RuntimeError("modelo indisponível")

    result = validate_output(
        "Resposta sem problemas de formatação.",
        source="compiled",
        evaluator=failing_evaluator,
    )

    assert result["status"] == "blocked"
    assert result["reason_code"] == "validator_unavailable"


def test_compiled_evaluator_uses_structured_supported_contract() -> None:
    class FakeStructuredModel:
        def __init__(self) -> None:
            self.messages: Any = None

        def invoke(self, messages: Any) -> SupportValidationResult:
            self.messages = messages
            return SupportValidationResult(status="supported")

    model = FakeStructuredModel()
    result = evaluate_compiled_output(
        "Resposta compilada.",
        ["Material do agente."],
        model=model,
    )

    assert result == "supported"
    assert "Resposta compilada." in model.messages[1].content
    assert "Material do agente." in model.messages[1].content


def test_output_node_blocks_missing_response() -> None:
    result = output_guardrail_node(_state(None), source="faq")

    assert result["output_guardrail"]["reason_code"] == "empty_response"
    assert result["status"] == "completed"
    assert CONTROLLED_OUTPUT_RESPONSE.startswith("Não foi possível")


def test_output_node_returns_sanitized_final_response() -> None:
    content = "Resposta final " + chr(0x1F642)
    result = output_guardrail_node(_state(content), source="faq")

    assert result["output_guardrail"]["status"] == "passed"
    assert result["final_response"]["content"] == "Resposta final "


def test_created_compiled_node_passes_injected_model() -> None:
    class FakeStructuredModel:
        def invoke(self, _: Any) -> SupportValidationResult:
            return SupportValidationResult(status="supported")

    node = create_output_guardrail_node(
        source="compiled",
        model=FakeStructuredModel(),
    )
    result = node(
        _state(
            "Resposta compilada.",
            agent_contents=["Material do agente."],
        )
    )

    assert result["output_guardrail"]["status"] == "passed"
    assert result["status"] == "in_progress"
