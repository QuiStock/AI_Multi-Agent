from __future__ import annotations

import json

from src.agents.faq.executor import FAQExecutor
from src.agents.faq.tools.faq_tool import create_faq_search_tool


class FakeRetriever:
    def __init__(self, evidences: list[dict[str, object]]) -> None:
        self.evidences = evidences
        self.allowed_audiences: tuple[str, ...] | None = None
        self.calls = 0

    def search(
        self,
        query: str,
        *,
        allowed_audiences: tuple[str, ...],
    ) -> list[dict[str, object]]:
        self.calls += 1
        self.allowed_audiences = allowed_audiences
        return self.evidences


def test_faq_search_rejects_empty_query() -> None:
    search_tool = create_faq_search_tool(
        FakeRetriever([]),
        allowed_audiences=("shared", "employee"),
        request_id="request-1",
        trace_id="trace-1",
        call_id_factory=lambda: "call-1",
    )

    result = json.loads(search_tool.invoke({"query": "   "}))

    assert result["status"] == "error"
    assert result["next_step"] == "controlled_error"
    assert result["error"]["code"] == "FAQ_INVALID_QUERY"


def test_faq_search_reports_missing_evidence() -> None:
    search_tool = create_faq_search_tool(
        FakeRetriever([]),
        allowed_audiences=("shared", "employee"),
        request_id="request-1",
        trace_id="trace-1",
        call_id_factory=lambda: "call-1",
    )

    result = json.loads(search_tool.invoke({"query": "qual é a regra?"}))

    assert result["status"] == "success"
    assert result["next_step"] == "direct_response"
    assert result["data"] == {
        "query": "qual é a regra?",
        "outcome": "not_found",
        "result_count": 0,
        "results": [],
    }
    assert result["warnings"][0]["code"] == "NO_RELEVANT_EVIDENCE"


def test_faq_search_serializes_retrieved_evidence() -> None:
    search_tool = create_faq_search_tool(
        FakeRetriever(
            [
                {
                    "arquivo": "manual.md",
                    "conteudo": "A regra está no manual.",
                    "relevancia": 0.91,
                }
            ]
        ),
        allowed_audiences=("shared", "manager"),
        request_id="request-1",
        trace_id="trace-1",
        call_id_factory=lambda: "call-1",
    )

    result = json.loads(search_tool.invoke({"query": "qual é a regra?"}))

    assert result["status"] == "success"
    assert result["next_step"] == "continue"
    assert result["data"]["outcome"] == "found"
    assert result["data"]["result_count"] == 1
    assert result["data"]["results"][0]["file_name"] == "manual.md"
    assert result["data"]["results"][0]["relevance"] == 0.91
    assert result["evidence"][0]["source_type"] == "faq_document"


def test_faq_search_executes_only_one_lookup_per_turn() -> None:
    retriever = FakeRetriever([])
    search_tool = create_faq_search_tool(
        retriever,
        allowed_audiences=("shared", "employee"),
        request_id="request-1",
        trace_id="trace-1",
        call_id_factory=lambda: "call-1",
    )

    first = search_tool.invoke({"query": "Primeira pergunta"})
    second = search_tool.invoke({"query": "Outra pergunta"})

    assert second == first
    assert retriever.calls == 1


def test_faq_executor_binds_manager_scope_per_request(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeAgent:
        def invoke(self, state: dict[str, object]) -> dict[str, object]:
            captured["state"] = state
            return {"messages": []}

    def fake_agent_factory(**kwargs: object) -> FakeAgent:
        captured.update(kwargs)
        return FakeAgent()

    retriever = FakeRetriever([])
    monkeypatch.setattr(
        "src.agents.faq.executor.create_agent_from_card",
        fake_agent_factory,
    )

    executor = FAQExecutor(retriever=retriever)

    result = executor.invoke(
        {
            "request": {
                "request_id": "request-1",
                "trace_id": "trace-1",
                "role_code": "MANAGER",
            },
            "messages": [],
        }
    )

    assert result["evidences"] == []
    assert captured["tools"][0].name == "faq_search"  # type: ignore[index]
    captured["tools"][0].invoke({"query": "consulta"})  # type: ignore[index]
    assert retriever.allowed_audiences == ("shared", "manager")
