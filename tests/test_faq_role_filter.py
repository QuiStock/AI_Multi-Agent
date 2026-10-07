from types import SimpleNamespace

import pytest
from qdrant_client import QdrantClient

from src.agents.faq.ingestion.processing.models import Chunk
from src.agents.faq.ingestion.vectorstore.qdrant_store import QdrantStore
from src.agents.faq.retrieval.qdrant_retriever import QdrantRetriever


class FakeEmbeddings:
    def embed_query(self, query: str) -> list[float]:
        return [0.1, 0.2, 0.3]


class CapturingVectorStore:
    def __init__(self) -> None:
        self.query_filter = None

    def search(
        self,
        *,
        query_vector: list[float],
        limit: int,
        query_filter: object,
    ) -> list[SimpleNamespace]:
        self.query_filter = query_filter
        return [
            SimpleNamespace(
                score=0.9,
                payload={
                    "source_name": "manual.md",
                    "text": "Conteúdo autorizado.",
                    "page_number": None,
                },
            )
        ]


def test_manager_search_builds_shared_and_manager_filter() -> None:
    vector_store = CapturingVectorStore()
    retriever = QdrantRetriever(
        embedding_provider=FakeEmbeddings(),
        vector_store=vector_store,
    )

    assert retriever.search(
        "qual é a regra?",
        allowed_audiences=("shared", "manager"),
    )

    query_filter = vector_store.query_filter
    assert query_filter is not None
    assert {condition.match.value for condition in query_filter.should} == {
        "shared",
        "manager",
    }


def test_retriever_rejects_an_empty_or_unknown_scope() -> None:
    retriever = QdrantRetriever(
        embedding_provider=FakeEmbeddings(),
        vector_store=CapturingVectorStore(),
    )

    with pytest.raises(ValueError):
        retriever.search("consulta", allowed_audiences=())

    with pytest.raises(ValueError):
        retriever.search(
            "consulta",
            allowed_audiences=("shared", "director"),  # type: ignore[arg-type]
        )


def test_qdrant_filter_excludes_employee_points_from_manager_search() -> None:
    store = QdrantStore(
        qdrant_client=QdrantClient(":memory:"),
        collection_name="faq_role_filter_test",
    )
    for doc_id, audience in (
        ("shared.md", "shared"),
        ("manager.md", "manager"),
        ("employee.md", "employee"),
    ):
        store.replace_document(
            doc_id=doc_id,
            source_hash="hash-1",
            pipeline_version="faq-v2",
            chunks=[
                Chunk(
                    doc_id=doc_id,
                    chunk_index=0,
                    text=doc_id,
                    audience=audience,
                    metadata={"source_name": doc_id},
                )
            ],
            vectors=[[1.0, 0.0, 0.0]],
        )

    class FixedEmbeddings:
        def embed_query(self, query: str) -> list[float]:
            return [1.0, 0.0, 0.0]

    retriever = QdrantRetriever(
        embedding_provider=FixedEmbeddings(),
        vector_store=store,
        top_k=10,
    )

    results = retriever.search(
        "regra de gerente",
        allowed_audiences=("shared", "manager"),
    )

    assert {result["arquivo"] for result in results} == {
        "shared.md",
        "manager.md",
    }
