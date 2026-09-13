import json

from langchain_core.tools import tool

from src.agents.faq.retrieval.qdrant_retriever import (
    QdrantRetriever,
)


def create_faq_search_tool(
    retriever: QdrantRetriever,
):
    @tool
    def faq_search(query: str) -> str:
        """Busca evidências na base de conhecimento da FAQ."""

        if not query.strip():
            return "A consulta não pode estar vazia."

        evidences = retriever.search(query)

        if not evidences:
            return (
                "Nenhuma evidência relevante encontrada "
                "na base de conhecimento."
            )

        return json.dumps(
            {"resultados": evidences},
            ensure_ascii=False,
        )

    return faq_search