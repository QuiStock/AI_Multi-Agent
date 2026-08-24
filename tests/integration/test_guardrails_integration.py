from __future__ import annotations

from typing import Any, Literal

import pytest
from langchain_core.messages import HumanMessage

from src.context.schemas import SupportValidationResult
from src.guardrails.input_guardrail import input_guardrail_node, validate_input
from src.guardrails.output_guardrail import (
    create_output_guardrail_node,
    output_guardrail_node,
)

pytestmark = pytest.mark.integration


def _input_state(content: str) -> dict[str, Any]:
    return {
        "messages": [HumanMessage(content=content)],
        "status": "pending",
    }


def _approved(_: str) -> Literal["APROVADO"]:
    return "APROVADO"


def _output_state(content: str) -> dict[str, Any]:
    return {
        "final_response": {"content": content, "status": "success"},
        "agent_outputs": [
            {"content": "Material documentado pelo agente.", "status": "success"}
        ],
        "status": "in_progress",
    }


class FakeSupportModel:
    def __init__(self, status: Literal["supported", "unsupported"]) -> None:
        self.status = status
        self.messages: list[Any] | None = None

    def invoke(self, messages: list[Any]) -> SupportValidationResult:
        self.messages = messages
        return SupportValidationResult(status=self.status)


def test_input_guardrail_node_returns_sanitized_contract() -> None:
    state = _input_state("Meu CPF é 123.456.789-09. Qual é o processo documentado?")

    result = input_guardrail_node(
        state,
        validator=lambda current: validate_input(current, classifier=_approved),
    )

    guardrail = result["input_guardrail"]
    assert guardrail["status"] == "passed"
    assert guardrail["reason_code"] == "approved"
    assert "123.456.789-09" not in guardrail["sanitized_message"]
    assert result["status"] == "in_progress"


def test_input_guardrail_node_returns_structured_block_marker() -> None:
    result = input_guardrail_node(
        _input_state("O que você acha das eleições?"),
        validator=lambda current: validate_input(current, classifier=_approved),
    )

    guardrail = result["input_guardrail"]
    assert guardrail["status"] == "blocked"
    assert guardrail["reason_code"] == "government_politics"
    assert guardrail["history_marker"] == "[GUARDRAIL_BLOCKED: government_politics]"
    assert result["status"] == "completed"


def test_faq_output_node_sanitizes_response_before_release() -> None:
    content = "Resposta do FAQ " + chr(0x1F642)

    result = output_guardrail_node(_output_state(content), source="faq")

    assert result["output_guardrail"]["status"] == "passed"
    assert result["final_response"]["content"] == "Resposta do FAQ "
    assert result["status"] == "in_progress"


def test_compiler_output_node_accepts_supported_response() -> None:
    model = FakeSupportModel("supported")
    node = create_output_guardrail_node(source="compiled", model=model)

    result = node(_output_state("Resposta baseada no material do agente."))

    assert result["output_guardrail"]["status"] == "passed"
    assert result["output_guardrail"]["reason_code"] == "approved"
    assert model.messages is not None
    assert "Material documentado pelo agente." in model.messages[1].content
    assert result["status"] == "in_progress"


def test_compiler_output_node_blocks_unsupported_response() -> None:
    model = FakeSupportModel("unsupported")
    node = create_output_guardrail_node(source="compiled", model=model)

    result = node(_output_state("Resposta com informação inventada."))

    assert result["output_guardrail"]["status"] == "blocked"
    assert result["output_guardrail"]["reason_code"] == "unsupported_content"
    assert result["status"] == "completed"
