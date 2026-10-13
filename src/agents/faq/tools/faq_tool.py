import json
from collections.abc import Sequence

from langchain_core.tools import BaseTool, tool

from src.agents.faq.ingestion.audience import Audience
from src.agents.faq.retrieval.qdrant_retriever import (
    QdrantRetriever,
)


def create_faq_search_tool(
    retriever: QdrantRetriever,
    *,
    allowed_audiences: Sequence[Audience],
) -> BaseTool:
    cached_result: str | None = None

    @tool
    def faq_search(query: str) -> str:
        """Busca evidências na base de conhecimento da FAQ."""
        nonlocal cached_result

        if not query.strip():
            return "A consulta não pode estar vazia."
        if cached_result is not None:
            return cached_result

        evidences = retriever.search(
            query,
            allowed_audiences=allowed_audiences,
        )

        if not evidences:
            cached_result = (
                "Nenhuma evidência relevante encontrada na base de conhecimento."
            )
            return cached_result

        cached_result = json.dumps(
            {"resultados": evidences},
            ensure_ascii=False,
        )
        return cached_result

    return faq_search
