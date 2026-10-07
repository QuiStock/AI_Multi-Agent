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
    @tool
    def faq_search(query: str) -> str:
        """Busca evidências na base de conhecimento da FAQ."""

        if not query.strip():
            return "A consulta não pode estar vazia."

        evidences = retriever.search(
            query,
            allowed_audiences=allowed_audiences,
        )

        if not evidences:
            return "Nenhuma evidência relevante encontrada na base de conhecimento."

        return json.dumps(
            {"resultados": evidences},
            ensure_ascii=False,
        )

    return faq_search
