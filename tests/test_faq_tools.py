from __future__ import annotations

import json

from langgraph.graph.state import CompiledStateGraph

from src.agents.faq.faq_node import create_faq_agent
from src.agents.faq.tools.faq_tool import create_faq_search_tool


class FakeRetriever:
    def __init__(self, evidences: list[dict[str, object]]) -> None:
        self.evidences = evidences

    def search(self, query: str) -> list[dict[str, object]]:
        return self.evidences


def test_faq_search_rejects_empty_query() -> None:
    search_tool = create_faq_search_tool(FakeRetriever([]))

    assert search_tool.invoke({"query": "   "}) == "A consulta não pode estar vazia."


def test_faq_search_reports_missing_evidence() -> None:
    search_tool = create_faq_search_tool(FakeRetriever([]))

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
        )
    )

    result = json.loads(search_tool.invoke({"query": "qual é a regra?"}))

    assert result["resultados"][0]["arquivo"] == "manual.md"
    assert result["resultados"][0]["relevancia"] == 0.91


def test_faq_agent_accepts_a_tool_through_dependency_injection() -> None:
    search_tool = create_faq_search_tool(FakeRetriever([]))

    agent = create_faq_agent(tools=[search_tool])

    assert isinstance(agent, CompiledStateGraph)
