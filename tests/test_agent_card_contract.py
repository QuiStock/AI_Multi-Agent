import pytest
from pydantic import ValidationError

from src.agents.faq.card import FAQ_CARD
from src.agents.judge.card import JUDGE_CARD
from src.agents.router.card import ROUTER_CARD
from src.agents.schemas.agent_card import AgentCard, AgentRole
from src.agents.schemas.tool_binding import ToolBinding, ToolProperty


def _card_payload() -> dict:
    return {
        "id": "test_agent",
        "name": "Test agent",
        "description": "Agent used by the contract tests.",
        "role": AgentRole.FAQ_RAG,
        "version": "1.0.0",
        "system_prompt_template": "Answer using the available evidence.",
        "tools": [
            ToolBinding(
                id="search",
                name="search",
                description="Searches the knowledge base.",
                properties=[
                    ToolProperty(
                        name="query",
                        type="string",
                        description="Search query.",
                        required=True,
                    )
                ],
            )
        ],
    }


def test_faq_card_has_the_expected_contract() -> None:
    assert FAQ_CARD.id == "faq_rag"
    assert FAQ_CARD.role is AgentRole.FAQ_RAG
    assert FAQ_CARD.tools[0].id == "faq_search"
    assert FAQ_CARD.tools[0].properties[0].name == "query"
    assert FAQ_CARD.routing_intents == ["faq", "politicas", "processos"]


def test_judge_card_has_no_tools_and_uses_failure_policy() -> None:
    assert JUDGE_CARD.id == "evidence_judge"
    assert JUDGE_CARD.role is AgentRole.EVIDENCE_JUDGE
    assert JUDGE_CARD.tools == []
    assert JUDGE_CARD.failure_policy is not None
    assert JUDGE_CARD.failure_policy.max_retries == 0
    assert JUDGE_CARD.routing_intents == []


def test_router_card_declares_optional_memory_tool() -> None:
    assert [tool.id for tool in ROUTER_CARD.tools] == ["search_conversation_summaries"]


def test_agent_card_does_not_declare_memory_or_evidence_policies() -> None:
    assert "memory_policy" not in AgentCard.model_fields
    assert "evidence_policy" not in AgentCard.model_fields


def test_agent_card_accepts_optional_failure_policy() -> None:
    card = AgentCard(**_card_payload())

    assert card.failure_policy is None


def test_agent_card_does_not_require_model_profile_id() -> None:
    assert "model_profile_id" not in AgentCard.model_fields
    AgentCard(**_card_payload())


def test_agent_card_rejects_invalid_version() -> None:
    payload = _card_payload()
    payload["version"] = "v1"

    with pytest.raises(ValidationError):
        AgentCard(**payload)


def test_agent_card_rejects_duplicate_tools() -> None:
    payload = _card_payload()
    payload["tools"] = [
        payload["tools"][0],
        payload["tools"][0],
    ]

    with pytest.raises(ValidationError, match="duplicated tools"):
        AgentCard(**payload)


def test_agent_card_rejects_unknown_fields() -> None:
    payload = _card_payload()
    payload["unexpected"] = True

    with pytest.raises(ValidationError):
        AgentCard(**payload)


def test_tool_binding_requires_a_valid_property_type() -> None:
    with pytest.raises(ValidationError):
        ToolProperty(
            name="query",
            type="date",
            description="Invalid property type.",
        )


def test_tool_binding_rejects_removed_skip_compilation_flag() -> None:
    with pytest.raises(ValidationError):
        ToolBinding(
            id="internal_lookup",
            name="internal_lookup",
            description="Internal lookup.",
            skip_compilation=True,
        )
