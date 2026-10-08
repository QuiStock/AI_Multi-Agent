from __future__ import annotations

import json

from src.agents.faq.executor import FAQExecutor
from src.agents.faq.tools.faq_tool import create_faq_search_tool


class FakeRetriever:
    def __init__(self, evidences: list[dict[str, object]]) -> None:
        self.evidences = evidences
        self.allowed_audiences: tuple[str, ...] | None = None

    def search(
        self,
        query: str,
        *,
        allowed_audiences: tuple[str, ...],
    ) -> list[dict[str, object]]:
        self.allowed_audiences = allowed_audiences
        return self.evidences


def test_faq_search_rejects_empty_query() -> None:
    search_tool = create_faq_search_tool(
        FakeRetriever([]),
        allowed_audiences=("shared", "employee"),
    )

    assert search_tool.invoke({"query": "   "}) == "A consulta não pode estar vazia."


def test_faq_search_reports_missing_evidence() -> None:
    search_tool = create_faq_search_tool(
        FakeRetriever([]),
        allowed_audiences=("shared", "employee"),
    )

    result = search_tool.invoke({"query": "qual é a regra?"})

    assert result == ("Nenhuma evidência relevante encontrada na base de conhecimento.")


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
    )

    result = json.loads(search_tool.invoke({"query": "qual é a regra?"}))

    assert result["resultados"][0]["arquivo"] == "manual.md"
    assert result["resultados"][0]["relevancia"] == 0.91


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
            "request": {"role_id": 2},
            "messages": [],
        }
    )

    assert result["evidences"] == []
    assert captured["tools"][0].name == "faq_search"  # type: ignore[index]
    captured["tools"][0].invoke({"query": "consulta"})  # type: ignore[index]
    assert retriever.allowed_audiences == ("shared", "manager")
