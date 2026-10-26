from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage

from src.guardrails.output import (
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


def test_output_passes_without_faq_references() -> None:
    result = validate_output(
        "Resposta informativa sem fonte externa.",
    )

    assert result["status"] == "passed"
    assert result["reason_code"] == "approved"
    assert "sanitized_content" not in result


def test_output_replaces_unbalanced_markdown() -> None:
    result = validate_output("Resposta com **negrito incompleto.")

    assert result["status"] == "passed"
    assert result["reason_code"] == "invalid_markdown"
    assert "unbalanced_bold_delimiter" in result["violations"]
    assert result["sanitized_content"] == CONTROLLED_OUTPUT_RESPONSE


def test_output_removes_emojis_and_passes() -> None:
    content = "Resposta com símbolo proibido " + chr(0x1F642)
    result = validate_output(
        content,
    )

    assert result["status"] == "passed"
    assert result["reason_code"] == "approved"
    assert result["sanitized_content"] == "Resposta com símbolo proibido "


def test_compiled_output_passes_without_semantic_evaluator() -> None:
    result = validate_output(
        "A resposta compilada está sustentada.",
    )

    assert result["status"] == "passed"


def test_output_node_replaces_missing_response() -> None:
    result = output_guardrail_node(_state(None))

    assert result["output_guardrail"]["reason_code"] == "empty_response"
    assert result["status"] == "in_progress"
    assert result["response_draft"] is None
    assert result["final_response"]["content"] == CONTROLLED_OUTPUT_RESPONSE
    assert CONTROLLED_OUTPUT_RESPONSE.startswith("Não foi possível")


def test_output_guardrail_keeps_pii_placeholder_for_http_boundary() -> None:
    request_id = "request-1"
    marker = f"[DADO_SENSIVEL_EMAIL_{request_id}_1]"
    result = output_guardrail_node(
        {
            "request": {"request_id": request_id},
            "messages": [
                HumanMessage(
                    content=f"Meu e-mail é {marker}.",
                    id=f"{request_id}:user",
                )
            ],
            "final_response": {
                "content": f"Seu e-mail é {marker}.",
                "status": "success",
            },
        },
    )

    assert result["final_response"]["content"] == f"Seu e-mail é {marker}."


def test_output_guardrail_replaces_unrecognized_pii_marker_response() -> None:
    request_id = "request-1"
    allowed_marker = f"[DADO_SENSIVEL_EMAIL_{request_id}_1]"
    invented_marker = "[DADO_SENSIVEL_CPF_fake_2]"
    result = output_guardrail_node(
        {
            "request": {"request_id": request_id},
            "messages": [
                HumanMessage(
                    content=f"Meu e-mail é {allowed_marker}.",
                    id=f"{request_id}:user",
                )
            ],
            "final_response": {
                "content": f"Sobre seu e-mail {allowed_marker}: {invented_marker}",
                "status": "success",
            },
        },
    )

    assert result["output_guardrail"]["reason_code"] == "unexpected_pii_marker"
    assert result["final_response"]["content"] == CONTROLLED_OUTPUT_RESPONSE
    assert result["final_response"]["status"] == "success"


def test_output_guardrail_preserves_evidence_supported_email() -> None:
    result = output_guardrail_node(
        {
            "evidences": [{"content": "Contato de suporte: pessoa@example.com"}],
            "final_response": {
                "content": "O e-mail é pessoa@example.com.",
                "status": "success",
            }
        },
    )

    assert result["output_guardrail"]["reason_code"] == "approved"
    assert result["final_response"]["content"] == "O e-mail é pessoa@example.com."
    assert result["final_response"]["status"] == "success"


def test_output_node_returns_sanitized_final_response() -> None:
    content = "Resposta final " + chr(0x1F642)
    result = output_guardrail_node(
        _state(content, agent_contents=["manual.md"]),
    )

    assert result["output_guardrail"]["status"] == "passed"
    assert result["final_response"]["content"] == "Resposta final "


def test_output_node_ignores_stale_response_draft() -> None:
    result = output_guardrail_node(
        {
            "status": "in_progress",
            "final_response": {"content": "Olá!", "status": "success"},
            "greeting_classification": {"category": "greeting_only"},
            "response_draft": {
                "content": "Resposta antiga do FAQ.",
                "citations": [],
                "status": "draft",
            },
            "evidences": [
                {
                    "content": "Evidência da resposta.",
                }
            ],
        },
    )

    assert result["output_guardrail"]["status"] == "passed"
    assert result["final_response"] == {"content": "Olá!", "status": "success"}
    assert result["response_draft"] is None


def test_output_node_does_not_fallback_to_response_draft() -> None:
    result = output_guardrail_node(
        {
            "response_draft": {
                "content": "Resposta antiga do FAQ.",
                "citations": [],
                "status": "draft",
            }
        },
    )

    assert result["output_guardrail"]["reason_code"] == "empty_response"
    assert result["final_response"]["content"] == CONTROLLED_OUTPUT_RESPONSE
    assert result["response_draft"] is None


def test_approved_judge_allows_deterministic_validation() -> None:
    result = output_guardrail_node(
        {
            "status": "in_progress",
            "final_response": {
                "content": "Resposta validada pelo judge.",
                "status": "success",
            },
            "response_draft": {"content": "Rascunho obsoleto."},
            "agent_results": {
                "judge": {
                    "status": "approved",
                    "reason": "Evidência suficiente.",
                    "evidence_ids": ["faq-1"],
                }
            },
        },
    )

    assert result["output_guardrail"]["status"] == "passed"
    assert result["final_response"]["content"] == "Resposta validada pelo judge."
    assert result["response_draft"] is None


def test_output_node_does_not_recheck_judge_approval() -> None:
    result = output_guardrail_node(
        {
            "status": "in_progress",
            "final_response": {
                "content": "Resposta sem confirmação.",
                "status": "success",
            },
            "agent_results": {
                "judge": {
                    "status": "insufficient_evidence",
                    "reason": "Evidência insuficiente.",
                    "evidence_ids": [],
                }
            },
        },
    )

    assert result["output_guardrail"]["status"] == "passed"
    assert result["output_guardrail"]["reason_code"] == "approved"
    assert result["final_response"]["content"] == "Resposta sem confirmação."
    assert result["response_draft"] is None


def test_compiled_output_node_does_not_require_judge() -> None:
    result = output_guardrail_node(
        {
            "status": "in_progress",
            "final_response": {
                "content": "Resposta sem julgamento.",
                "status": "success",
            },
        },
    )

    assert result["output_guardrail"]["status"] == "passed"
    assert result["output_guardrail"]["reason_code"] == "approved"
    assert result["final_response"]["content"] == "Resposta sem julgamento."
    assert result["response_draft"] is None


def test_created_compiled_node_uses_deterministic_validation() -> None:
    node = create_output_guardrail_node()
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
