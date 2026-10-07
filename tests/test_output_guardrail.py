from __future__ import annotations

from typing import Any

from src.guardrails.output_guardrail import (
    CONTROLLED_OUTPUT_RESPONSE,
    create_output_guardrail_node,
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
        state["agent_results"] = {
            "faq": {
                "status": "success",
                "answer": "\n".join(agent_contents),
                "citation_ids": [],
            }
        }
    return state


def test_faq_output_only_checks_markdown() -> None:
    result = validate_output(
        "Resposta informativa sem fonte externa.",
        source="faq",
        references=["manual.md"],
    )

    assert result["status"] == "passed"
    assert result["reason_code"] == "approved"
    assert "sanitized_content" not in result


def test_faq_output_replaces_unbalanced_markdown() -> None:
    result = validate_output("Resposta com **negrito incompleto.", source="faq")

    assert result["status"] == "passed"
    assert result["reason_code"] == "invalid_markdown"
    assert "unbalanced_bold_delimiter" in result["violations"]
    assert result["sanitized_content"] == CONTROLLED_OUTPUT_RESPONSE


def test_faq_output_removes_emojis_and_passes() -> None:
    content = "Resposta com símbolo proibido " + chr(0x1F642)
    result = validate_output(
        content,
        source="faq",
        references=["manual.md"],
    )

    assert result["status"] == "passed"
    assert result["reason_code"] == "approved"
    assert result["sanitized_content"] == "Resposta com símbolo proibido "


def test_compiled_output_passes_without_semantic_evaluator() -> None:
    result = validate_output(
        "A resposta compilada está sustentada.",
        source="compiled",
        references=["Material do agente FAQ."],
    )

    assert result["status"] == "passed"


def test_output_node_replaces_missing_response() -> None:
    result = output_guardrail_node(_state(None), source="faq")

    assert result["output_guardrail"]["reason_code"] == "empty_response"
    assert result["status"] == "in_progress"
    assert result["response_draft"]["content"] == CONTROLLED_OUTPUT_RESPONSE
    assert CONTROLLED_OUTPUT_RESPONSE.startswith("Não foi possível")


def test_output_node_returns_sanitized_final_response() -> None:
    content = "Resposta final " + chr(0x1F642)
    result = output_guardrail_node(
        _state(content, agent_contents=["manual.md"]),
        source="faq",
    )

    assert result["output_guardrail"]["status"] == "passed"
    assert result["final_response"]["content"] == "Resposta final "


def test_output_node_supports_response_draft_from_graph_state() -> None:
    result = output_guardrail_node(
        {
            "status": "in_progress",
            "response_draft": {
                "content": "Resposta final " + chr(0x1F642),
                "citations": [],
                "status": "draft",
            },
            "evidences": [
                {
                    "content": "Evidência da resposta.",
                }
            ],
        },
        source="faq",
    )

    assert result["output_guardrail"]["status"] == "passed"
    assert result["response_draft"]["content"] == "Resposta final "


def test_approved_judge_allows_deterministic_validation() -> None:
    result = output_guardrail_node(
        {
            "status": "in_progress",
            "response_draft": {
                "content": "Resposta validada pelo judge.",
                "citations": [],
                "status": "draft",
            },
            "agent_results": {
                "judge": {
                    "status": "approved",
                    "reason": "Evidência suficiente.",
                    "evidence_ids": ["faq-1"],
                }
            },
        },
        source="compiled",
    )

    assert result["output_guardrail"]["status"] == "passed"


def test_output_node_replaces_when_judge_is_not_approved() -> None:
    result = output_guardrail_node(
        {
            "status": "in_progress",
            "response_draft": {
                "content": "Resposta sem confirmação.",
                "citations": [],
                "status": "draft",
            },
            "agent_results": {
                "judge": {
                    "status": "insufficient_evidence",
                    "reason": "Evidência insuficiente.",
                    "evidence_ids": [],
                }
            },
        },
        source="compiled",
    )

    assert result["output_guardrail"]["status"] == "passed"
    assert result["output_guardrail"]["reason_code"] == "judge_not_approved"
    assert result["response_draft"]["content"] == CONTROLLED_OUTPUT_RESPONSE


def test_compiled_output_node_replaces_when_judge_is_missing() -> None:
    result = output_guardrail_node(
        {
            "status": "in_progress",
            "response_draft": {
                "content": "Resposta sem julgamento.",
                "citations": ["faq-1"],
                "status": "draft",
            },
        },
        source="compiled",
    )

    assert result["output_guardrail"]["status"] == "passed"
    assert result["output_guardrail"]["reason_code"] == "judge_missing"
    assert result["response_draft"]["content"] == CONTROLLED_OUTPUT_RESPONSE


def test_created_compiled_node_uses_deterministic_validation() -> None:
    node = create_output_guardrail_node(source="compiled")
    state = _state(
        "Resposta compilada.",
        agent_contents=["Material do agente."],
    )
    state["agent_results"]["judge"] = {
        "status": "approved",
        "reason": "Resposta sustentada.",
        "evidence_ids": ["faq-1"],
    }

    result = node(state)

    assert result["output_guardrail"]["status"] == "passed"
    assert result["status"] == "in_progress"
