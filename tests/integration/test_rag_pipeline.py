from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.agents.faq.retrieval.qdrant_retriever import QdrantRetriever
from src.agents.faq.tools.faq_tool import create_faq_search_tool

pytestmark = pytest.mark.integration


class IntegrationEmbeddings:
    def embed_query(self, query: str) -> list[float]:
        return [float(len(query)), 0.1, 0.2]


class IntegrationVectorStore:
    def search(self, *, query_vector: list[float], limit: int) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                score=0.88,
                payload={
                    "source_name": "manual.md",
                    "text": "A regra está no manual.",
                    "page_number": None,
                },
            )
        ][:limit]


def test_faq_tool_connects_retriever_to_serialized_evidence() -> None:
    retriever = QdrantRetriever(
        embedding_provider=IntegrationEmbeddings(),
        vector_store=IntegrationVectorStore(),
    )
    search_tool = create_faq_search_tool(retriever)

    result = search_tool.invoke({"query": "Qual é a regra?"})

    assert "manual.md" in result
    assert "A regra está no manual." in result
