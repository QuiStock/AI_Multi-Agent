from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.agents.faq.tools.schemas import FAQSearchData, FAQSearchItem
from src.agents.schemas.tool_result import (
    ComposeResponse,
    DirectResponse,
    NavigateAction,
    NoResponse,
    ResponseContent,
    ToolEvidence,
    ToolMetadata,
    ToolResult,
    ToolStatus,
    ToolWarning,
)
from src.agents.tooling.result_adapter import (
    deserialize_tool_result,
    project_tool_result,
    serialize_for_agent,
    serialize_for_state,
)
from src.agents.tooling.result_factory import (
    ToolResultExtras,
    compose_success,
    create_compose_response,
    create_tool_error,
    create_tool_metadata,
    direct_success,
    partial_result,
    tool_error,
)


def _metadata() -> ToolMetadata:
    return create_tool_metadata(
        tool_name="faq_search",
        tool_version="1.0.0",
        tool_call_id="call_01",
        trace_id="trace_01",
        timestamp=datetime(2026, 9, 17, 14, 0, tzinfo=UTC),
    )


def _faq_data() -> FAQSearchData:
    return FAQSearchData(
        query="Qual é a regra de validade?",
        result_count=1,
        results=[
            FAQSearchItem(
                file_name="manual.md",
                content="Validade próxima significa até 15 dias.",
                relevance=0.91,
                page=None,
            )
        ],
    )


def _compose_result() -> ToolResult[FAQSearchData]:
    return compose_success(
        response=create_compose_response(
            intent="answer_documented_question",
            must_include=[
                "/results/0/content",
                "/results/0/file_name",
            ],
            constraints=[
                "Responder somente com base nos resultados",
                "Citar o arquivo utilizado",
            ],
        ),
        data=_faq_data(),
        meta=_metadata(),
        extras=ToolResultExtras(
            evidence=(
                ToolEvidence(
                    evidence_id="faq_01",
                    source_type="faq_document",
                    source_id="manual.md",
                    content="Validade próxima significa até 15 dias.",
                ),
            ),
        ),
    )


def test_compose_result_accepts_existing_json_pointers() -> None:
    result = _compose_result()

    assert result.status is ToolStatus.SUCCESS
    assert result.response.mode == "compose"
    assert result.data is not None
    assert result.data.result_count == 1


@pytest.mark.parametrize(
    "pointer",
    [
        "/results/1/content",
        "/results/not-an-index/content",
        "/unknown",
        "/query/value",
    ],
)
def test_compose_result_rejects_missing_json_pointer(
    pointer: str,
) -> None:
    with pytest.raises(
        ValidationError,
        match="must_include references missing data",
    ):
        compose_success(
            response=create_compose_response(
                intent="answer_documented_question",
                must_include=[pointer],
            ),
            data=_faq_data(),
            meta=_metadata(),
        )


def test_compose_result_supports_escaped_json_pointer() -> None:
    result = compose_success(
        response=create_compose_response(
            intent="answer_documented_question",
            must_include=["/document~1name/~0section"],
        ),
        data={"document/name": {"~section": "Conteúdo"}},
        meta=_metadata(),
    )

    assert result.data["document/name"]["~section"] == "Conteúdo"


def test_compose_response_rejects_duplicated_items() -> None:
    with pytest.raises(ValidationError):
        ComposeResponse(
            intent="answer_documented_question",
            must_include=["/query", "/query"],
        )


def test_success_result_rejects_error_and_empty_response() -> None:
    error = create_tool_error(
        code="UNEXPECTED_ERROR",
        category="internal",
        message="Falha inesperada.",
    )

    with pytest.raises(ValidationError):
        ToolResult[None](
            status=ToolStatus.SUCCESS,
            response=NoResponse(),
            data=None,
            error=error,
            meta=_metadata(),
        )


def test_error_result_requires_error_without_data_or_actions() -> None:
    with pytest.raises(ValidationError):
        ToolResult[dict[str, str]](
            status=ToolStatus.ERROR,
            response=NoResponse(),
            data={"unexpected": "data"},
            actions=[
                NavigateAction(
                    target="faq_document",
                    label="Abrir documento",
                )
            ],
            error=None,
            meta=_metadata(),
        )


def test_error_result_rejects_composition() -> None:
    error = create_tool_error(
        code="DEPENDENCY_UNAVAILABLE",
        category="dependency",
        message="Dependência indisponível.",
    )

    with pytest.raises(ValidationError):
        ToolResult[dict[str, str]](
            status=ToolStatus.ERROR,
            response=ComposeResponse(
                intent="answer_documented_question",
            ),
            data=None,
            error=error,
            meta=_metadata(),
        )


def test_partial_result_requires_data_and_explanation() -> None:
    with pytest.raises(ValidationError):
        ToolResult[dict[str, bool]](
            status=ToolStatus.PARTIAL,
            response=DirectResponse(
                content=ResponseContent(text="Resultado parcial."),
            ),
            data={"available": True},
            warnings=[],
            error=None,
            meta=_metadata(),
        )


def test_partial_result_rejects_empty_response() -> None:
    with pytest.raises(ValidationError):
        ToolResult[dict[str, bool]](
            status=ToolStatus.PARTIAL,
            response=NoResponse(),
            data={"available": True},
            warnings=[
                ToolWarning(
                    code="PARTIAL_DATA",
                    message="Uma fonte não respondeu.",
                )
            ],
            meta=_metadata(),
        )


def test_metadata_requires_timezone() -> None:
    with pytest.raises(ValidationError):
        ToolMetadata(
            tool_name="faq_search",
            tool_version="1.0.0",
            tool_call_id="call_01",
            trace_id="trace_01",
            timestamp=datetime(2026, 9, 17, 14, 0),
        )


def test_factory_builds_direct_and_partial_results() -> None:
    direct = direct_success(
        content=ResponseContent(
            text="Resposta pronta.",
            format="plain",
        ),
        meta=_metadata(),
    )

    partial = partial_result(
        response=DirectResponse(
            content=ResponseContent(
                text="Encontrei somente parte dos dados.",
            ),
        ),
        data={"available": True},
        meta=_metadata(),
        extras=ToolResultExtras(
            warnings=(
                ToolWarning(
                    code="PARTIAL_DATA",
                    message="Uma das fontes não respondeu.",
                ),
            ),
        ),
    )

    assert direct.status is ToolStatus.SUCCESS
    assert partial.status is ToolStatus.PARTIAL


def test_factory_builds_safe_error_results() -> None:
    error = create_tool_error(
        code="FAQ_DEPENDENCY_UNAVAILABLE",
        category="dependency",
        message="A base de conhecimento está indisponível.",
        retryable=True,
        details={"provider": "qdrant"},
    )

    hidden = tool_error(
        error=error,
        meta=_metadata(),
    )
    visible = tool_error(
        error=error,
        meta=_metadata(),
        content=ResponseContent(
            text="Não foi possível consultar a base de conhecimento.",
        ),
    )

    assert hidden.response.mode == "none"
    assert visible.response.mode == "direct"
    assert visible.error is not None
    assert visible.error.retryable is True


def test_agent_serialization_hides_internal_metadata() -> None:
    error = create_tool_error(
        code="FAQ_DEPENDENCY_UNAVAILABLE",
        category="dependency",
        message="A base de conhecimento está indisponível.",
        details={"provider": "qdrant"},
    )
    result = tool_error(
        error=error,
        meta=_metadata(),
    )

    agent_payload = json.loads(serialize_for_agent(result))
    state_payload = serialize_for_state(result)

    assert "meta" not in agent_payload
    assert "details" not in agent_payload["error"]
    assert state_payload["meta"]["trace_id"] == "trace_01"
    assert state_payload["error"]["details"]["provider"] == "qdrant"


def test_projection_exposes_agent_and_state_views() -> None:
    projection = project_tool_result(_compose_result())

    assert projection.metadata.trace_id == "trace_01"
    assert projection.state_record["meta"]["tool_name"] == "faq_search"
    assert projection.evidence[0].source_id == "manual.md"
    assert "answer_documented_question" in projection.agent_content


def test_deserialize_tool_result_validates_typed_data() -> None:
    expected = _compose_result()

    restored = deserialize_tool_result(
        expected.model_dump_json(),
        result_model=ToolResult[FAQSearchData],
    )

    assert restored.data is not None
    assert restored.data.results[0].file_name == "manual.md"


def test_faq_data_rejects_inconsistent_result_count() -> None:
    with pytest.raises(
        ValidationError,
        match="result_count must match",
    ):
        FAQSearchData(
            query="Pergunta",
            result_count=1,
            results=[],
        )
