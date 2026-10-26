from __future__ import annotations

import json
from datetime import date
from typing import Any

from src.agents.router.tools.search_conversation_summaries import (
    SummarySearchToolContext,
    build_search_conversation_summaries_tool,
)
from src.memory.contracts import SummaryContextSelection


class FakeSummarySearchService:
    def __init__(self, result: SummaryContextSelection | None = None) -> None:
        self.result = result or {"source": "none", "results": []}
        self.arguments: dict[str, Any] | None = None

    def search_context(
        self,
        *,
        email: str,
        conversation_id: str,
        query: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> SummaryContextSelection:
        self.arguments = {
            "email": email,
            "conversation_id": conversation_id,
            "query": query,
            "start_date": start_date,
            "end_date": end_date,
        }
        return self.result


def _tool(service: FakeSummarySearchService):
    return build_search_conversation_summaries_tool(
        service=service,
        context=SummarySearchToolContext(
            email="authenticated-user",
            conversation_id="current-conversation",
            query="O que combinamos na conversa anterior?",
            request_id="request-1",
        ),
        call_id_factory=lambda: "tool-call-1",
    )


def test_router_memory_tool_uses_bound_identity_and_returns_typed_results() -> None:
    service = FakeSummarySearchService(
        {
            "source": "semantic",
            "results": [
                {
                    "conversation_id": "past-conversation",
                    "title": "Plano anterior",
                    "summary": "O usuário discutiu um plano.",
                    "updated_at": "2026-09-20T10:00:00+00:00",
                }
            ],
        }
    )
    tool = _tool(service)

    start_date = date(2026, 9, 20)
    end_date = date(2026, 9, 22)
    result = json.loads(tool.invoke({"start_date": start_date, "end_date": end_date}))

    assert "start_date" in tool.args
    assert "end_date" in tool.args
    assert service.arguments == {
        "email": "authenticated-user",
        "conversation_id": "current-conversation",
        "query": "O que combinamos na conversa anterior?",
        "start_date": start_date,
        "end_date": end_date,
    }
    assert result["status"] == "success"
    assert len(result["evidence"]) == 1
    evidence = result["evidence"][0]
    assert evidence["evidence_id"].startswith("conversation-summary:")
    assert evidence["source_type"] == "conversation_summary"
    assert evidence["source_id"] == "past-conversation"
    assert evidence["content"] == "O usuário discutiu um plano."
    assert evidence["metadata"]["provenance"] == "prior_conversation"
    assert evidence["metadata"]["retrieval_source"] == "semantic"
    assert evidence["metadata"]["status"] == "semantic"
    assert result["meta"]["tool_name"] == "search_conversation_summaries"


def test_router_memory_tool_returns_safe_error_when_search_is_unavailable() -> None:
    class FailingService(FakeSummarySearchService):
        def search_context(self, **_: Any) -> SummaryContextSelection:
            raise RuntimeError("private database details")

    result = json.loads(_tool(FailingService()).invoke({}))

    assert result["status"] == "error"
    assert result["data"] is None
    assert result["error"]["code"] == "MEMORY_SEARCH_UNAVAILABLE"
    assert result["error"]["message"] == (
        "A busca de contexto anterior não está disponível."
    )
    assert "private database details" not in json.dumps(result)


def test_router_memory_tool_reports_no_match_without_recent_fallback() -> None:
    result = json.loads(_tool(FakeSummarySearchService()).invoke({}))

    assert result["status"] == "success"
    assert result["data"]["results"] == []
    evidence = result["evidence"][0]
    assert evidence["metadata"]["status"] == "not_found"
    assert evidence["metadata"]["retrieval_source"] == "none"
    assert evidence["metadata"]["status"] != "recent_fallback"


def test_router_memory_tool_keeps_recent_fallback_distinct_from_not_found() -> None:
    service = FakeSummarySearchService(
        {
            "source": "recent_fallback",
            "results": [
                {
                    "conversation_id": "past-conversation",
                    "title": "Conversa recente",
                    "summary": "Um resumo recente.",
                    "updated_at": "2026-09-20T10:00:00+00:00",
                }
            ],
        }
    )

    result = json.loads(_tool(service).invoke({}))
    evidence = result["evidence"][0]

    assert evidence["metadata"]["status"] == "recent_fallback"
    assert evidence["metadata"]["retrieval_source"] == "recent_fallback"
    assert evidence["metadata"].get("outcome") != "not_found"
