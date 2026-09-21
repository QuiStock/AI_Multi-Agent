from __future__ import annotations

import json
from typing import Any

from src.agents.router.tools.search_conversation_summaries import (
    SummarySearchToolContext,
    build_search_conversation_summaries_tool,
)
from src.memory.contracts import SummaryContextSelection


class FakeSummarySearchService:
    def __init__(self, result: SummaryContextSelection | None = None) -> None:
        self.result = result or {"source": "fallback", "results": []}
        self.arguments: dict[str, str] | None = None

    def search_context(
        self,
        *,
        user_id: str,
        conversation_id: str,
        query: str,
    ) -> SummaryContextSelection:
        self.arguments = {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "query": query,
        }
        return self.result


def _tool(service: FakeSummarySearchService):
    return build_search_conversation_summaries_tool(
        service=service,
        context=SummarySearchToolContext(
            user_id="authenticated-user",
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

    result = json.loads(tool.invoke({}))

    assert tool.args == {}
    assert service.arguments == {
        "user_id": "authenticated-user",
        "conversation_id": "current-conversation",
        "query": "O que combinamos na conversa anterior?",
    }
    assert result["status"] == "success"
    assert result["data"]["source"] == "semantic"
    assert result["data"]["results"][0]["conversation_id"] == "past-conversation"
    assert "meta" not in result


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
