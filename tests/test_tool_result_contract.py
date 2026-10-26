from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.agents.faq.tools.schemas import FAQSearchData, FAQSearchItem
from src.agents.schemas.tool_result import (
    ToolError,
    ToolEvidence,
    ToolMetadata,
    ToolResult,
    ToolStatus,
)
from src.agents.tooling.result_adapter import serialize_for_agent
from src.agents.tooling.result_factory import (
    ToolResultExtras,
    compose_success,
    create_tool_error,
    create_tool_metadata,
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
        outcome="found",
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


def _evidence() -> ToolEvidence:
    return ToolEvidence(
        evidence_id="faq_01",
        source_type="faq_document",
        source_id="manual.md",
        content="Validade próxima significa até 15 dias.",
    )


def _dependency_error() -> ToolError:
    return create_tool_error(
        code="FAQ_DEPENDENCY_UNAVAILABLE",
        category="dependency",
        message="A base de conhecimento está indisponível.",
        retryable=True,
        details={"provider": "qdrant"},
    )


def test_compose_success_builds_the_live_envelope() -> None:
    result = compose_success(
        data=_faq_data(),
        meta=_metadata(),
        extras=ToolResultExtras(evidence=(_evidence(),)),
    )

    assert result.status is ToolStatus.SUCCESS
    assert result.schema_version == "1.0"
    assert result.error is None
    assert result.data is not None
    assert result.data.result_count == 1
    assert result.evidence[0].source_id == "manual.md"
    assert result.meta.trace_id == "trace_01"


def test_success_result_rejects_error() -> None:
    with pytest.raises(ValidationError, match="cannot contain an error"):
        ToolResult[FAQSearchData](
            status=ToolStatus.SUCCESS,
            data=_faq_data(),
            error=_dependency_error(),
            meta=_metadata(),
        )


def test_partial_result_requires_data() -> None:
    with pytest.raises(ValidationError, match="partial data"):
        ToolResult[FAQSearchData](
            status=ToolStatus.PARTIAL,
            data=None,
            meta=_metadata(),
        )


def test_error_result_requires_error_without_data_or_evidence() -> None:
    with pytest.raises(ValidationError, match="must contain an error"):
        ToolResult[None](
            status=ToolStatus.ERROR,
            data=None,
            error=None,
            meta=_metadata(),
        )

    with pytest.raises(ValidationError, match="cannot contain data or evidence"):
        ToolResult[FAQSearchData](
            status=ToolStatus.ERROR,
            data=_faq_data(),
            error=_dependency_error(),
            meta=_metadata(),
        )

    with pytest.raises(ValidationError, match="cannot contain data or evidence"):
        ToolResult[None](
            status=ToolStatus.ERROR,
            evidence=[_evidence()],
            error=_dependency_error(),
            meta=_metadata(),
        )


def test_metadata_requires_timezone() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        ToolMetadata(
            tool_name="faq_search",
            tool_version="1.0.0",
            tool_call_id="call_01",
            trace_id="trace_01",
            timestamp=datetime(2026, 9, 17, 14, 0),
        )


def test_tool_error_builds_a_safe_error_result() -> None:
    result = tool_error(
        error=_dependency_error(),
        meta=_metadata(),
    )

    assert result.status is ToolStatus.ERROR
    assert result.data is None
    assert result.evidence == []
    assert result.error is not None
    assert result.error.retryable is True
    assert result.error.details == {"provider": "qdrant"}


def test_agent_serialization_includes_the_full_envelope() -> None:
    result = tool_error(
        error=_dependency_error(),
        meta=_metadata(),
    )

    agent_payload = json.loads(serialize_for_agent(result))

    assert agent_payload["status"] == "error"
    assert agent_payload["meta"]["trace_id"] == "trace_01"
    assert agent_payload["error"]["details"]["provider"] == "qdrant"


def test_faq_data_rejects_inconsistent_result_count() -> None:
    with pytest.raises(ValidationError, match="result_count must match"):
        FAQSearchData(
            query="Pergunta",
            outcome="not_found",
            result_count=1,
            results=[],
        )
