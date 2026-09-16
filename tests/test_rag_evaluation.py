"""Regression cases for the current Qdrant-backed FAQ retriever."""

from __future__ import annotations

from types import SimpleNamespace

from src.agents.faq.retrieval.qdrant_retriever import QdrantRetriever


class FakeEmbeddings:
    def embed_query(self, query: str) -> list[float]:
        return [float(len(query)), 0.1, 0.2]


class EvaluationVectorStore:
    def __init__(self, points: list[SimpleNamespace]) -> None:
        self.points = points

    def search(self, *, query_vector: list[float], limit: int) -> list[SimpleNamespace]:
        return self.points[:limit]


def test_retriever_returns_relevant_evidence_and_citation_metadata() -> None:
    retriever = QdrantRetriever(
        embedding_provider=FakeEmbeddings(),
        vector_store=EvaluationVectorStore(
            [
                SimpleNamespace(
                    score=0.92,
                    payload={
                        "source_name": "regulamento.pdf",
                        "text": "A matrícula deve ser renovada até 15 de janeiro.",
                        "page_number": 2,
                    },
                )
            ]
        ),
    )

    result = retriever.search("Quando renovo a matrícula?")

    assert result == [
        {
            "arquivo": "regulamento.pdf",
            "conteudo": "A matrícula deve ser renovada até 15 de janeiro.",
            "relevancia": 0.92,
            "pagina": 2,
        }
    ]


def test_retriever_discards_evidence_below_minimum_relevance() -> None:
    retriever = QdrantRetriever(
        embedding_provider=FakeEmbeddings(),
        vector_store=EvaluationVectorStore(
            [
                SimpleNamespace(
                    score=0.2,
                    payload={
                        "source_name": "irrelevante.pdf",
                        "text": "Conteúdo sem relação.",
                        "page_number": 1,
                    },
                )
            ]
        ),
        min_score=0.3,
    )

    assert retriever.search("Qual é o cardápio de hoje?") == []
