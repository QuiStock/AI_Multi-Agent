"""Casos de regressão para a qualidade de recuperação do FAQ RAG."""

from __future__ import annotations

import json

from langchain_core.documents import Document

from src.agents.faq.tools.faq_tool import _format_sources


class EvaluationVectorStore:
    def similarity_search_with_score(
        self, query: str, k: int = 4
    ) -> list[tuple[Document, float]]:
        if "matrícula" in query:
            return [
                (
                    Document(
                        page_content="A matrícula deve ser renovada até 15 de janeiro.",
                        metadata={"source": "regulamento.pdf", "page": 2},
                    ),
                    0.2,
                )
            ]
        return [(Document(page_content="conteúdo sem relação"), 50.0)]


def test_evaluation_returns_expected_evidence_and_citation() -> None:
    result = json.loads(
        _format_sources(EvaluationVectorStore(), "Quando renovo a matrícula?")
    )
    evidence = result["resultados"][0]

    assert evidence["arquivo"] == "regulamento.pdf"
    assert evidence["pagina"] == 3
    assert "15 de janeiro" in evidence["conteudo"]


def test_evaluation_rejects_question_without_relevant_evidence() -> None:
    result = _format_sources(EvaluationVectorStore(), "Qual é o cardápio de hoje?")
    assert result == "Nenhuma evidência relevante encontrada na base de conhecimento."
