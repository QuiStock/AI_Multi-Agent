"""Contract-backed FAQ retrieval tool."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from langchain_core.tools import BaseTool, tool

from src.agents.faq.ingestion.audience import Audience
from src.agents.faq.retrieval.qdrant_retriever import QdrantRetriever
from src.agents.schemas.tool_result import (
    ResponseContent,
    ToolEvidence,
    ToolResult,
    ToolWarning,
)
from src.agents.tooling.result_adapter import serialize_for_agent
from src.agents.tooling.result_factory import (
    ToolResultExtras,
    compose_success,
    create_compose_response,
    create_tool_error,
    create_tool_metadata,
    direct_success,
    tool_error,
)

from .schemas import FAQSearchData, FAQSearchItem

FAQ_NO_RESULTS_MESSAGE = (
    "Não encontrei informação documentada sobre esse assunto. "
    "Você pode reformular a pergunta?"
)
FAQ_DEPENDENCY_MESSAGE = (
    "Não foi possível consultar a base de conhecimento agora. "
    "Tente novamente mais tarde."
)


def _normalize_item(raw: Mapping[str, Any]) -> FAQSearchItem:
    return FAQSearchItem(
        file_name=raw.get("file_name", raw.get("arquivo")),
        content=raw.get("content", raw.get("conteudo")),
        relevance=raw.get("relevance", raw.get("relevancia")),
        page=raw.get("page", raw.get("pagina")),
    )


def _evidence(item: FAQSearchItem) -> ToolEvidence:
    raw_id = f"{item.file_name}|{item.page or ''}|{item.content}"
    digest = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:16]
    metadata: dict[str, str | int | float | bool | None] = {
        "relevance": item.relevance,
    }
    if item.page is not None:
        metadata["page"] = item.page
    return ToolEvidence(
        evidence_id=f"faq:{digest}",
        source_type="faq_document",
        source_id=item.file_name,
        content=item.content,
        metadata=metadata,
    )


def create_faq_search_tool(
    retriever: QdrantRetriever,
    *,
    allowed_audiences: Sequence[Audience],
    request_id: str,
    trace_id: str | None = None,
    call_id_factory: Callable[[], str] | None = None,
) -> BaseTool:
    """Build one request-scoped FAQ tool with a single lookup budget."""

    if not request_id.strip():
        raise ValueError("request_id é obrigatório")

    effective_trace_id = (
        trace_id.strip() if trace_id and trace_id.strip() else request_id
    )
    get_call_id = call_id_factory or (lambda: str(uuid.uuid4()))
    cached_result: str | None = None

    @tool
    def faq_search(query: str) -> str:
        """Busca evidências documentais no FAQ autorizado para a requisição."""

        nonlocal cached_result
        normalized_query = query.strip()
        metadata = create_tool_metadata(
            tool_name="faq_search",
            tool_version="1.0.0",
            tool_call_id=get_call_id(),
            trace_id=effective_trace_id,
        )

        if not normalized_query:
            return serialize_for_agent(
                tool_error(
                    error=create_tool_error(
                        code="FAQ_INVALID_QUERY",
                        category="validation",
                        message="A consulta da FAQ não pode estar vazia.",
                    ),
                    meta=metadata,
                    content=ResponseContent(
                        text=(
                            "Informe uma pergunta para consultar a base de "
                            "conhecimento."
                        )
                    ),
                )
            )

        if cached_result is not None:
            return cached_result

        try:
            raw_results = retriever.search(
                normalized_query,
                allowed_audiences=allowed_audiences,
            )
            results = [
                _normalize_item(item)
                for item in raw_results
                if isinstance(item, Mapping)
            ]
            data = FAQSearchData(
                query=normalized_query,
                outcome="found" if results else "not_found",
                result_count=len(results),
                results=results,
            )

            if not results:
                result: ToolResult[Any] = direct_success(
                    content=ResponseContent(text=FAQ_NO_RESULTS_MESSAGE),
                    data=data,
                    meta=metadata,
                    extras=ToolResultExtras(
                        warnings=(
                            ToolWarning(
                                code="NO_RELEVANT_EVIDENCE",
                                message=(
                                    "Nenhum documento relevante foi encontrado "
                                    "para a consulta."
                                ),
                            ),
                        )
                    ),
                )
            else:
                result = compose_success(
                    response=create_compose_response(
                        intent="answer_documented_question",
                        must_include=(
                            "/results/0/file_name",
                            "/results/0/content",
                        ),
                        constraints=(
                            "Responder somente com base nos resultados retornados.",
                            "Indicar o arquivo e a página quando disponíveis.",
                        ),
                    ),
                    data=data,
                    meta=metadata,
                    extras=ToolResultExtras(
                        evidence=tuple(_evidence(item) for item in results),
                    ),
                )
            cached_result = serialize_for_agent(result)
            return cached_result
        except ValueError:
            result = tool_error(
                error=create_tool_error(
                    code="FAQ_INVALID_RESULT",
                    category="internal",
                    message="A base de conhecimento retornou dados inválidos.",
                ),
                meta=metadata,
                content=ResponseContent(text=FAQ_DEPENDENCY_MESSAGE),
            )
        except Exception:
            result = tool_error(
                error=create_tool_error(
                    code="FAQ_DEPENDENCY_UNAVAILABLE",
                    category="dependency",
                    message="A base de conhecimento está indisponível.",
                    retryable=True,
                ),
                meta=metadata,
                content=ResponseContent(text=FAQ_DEPENDENCY_MESSAGE),
            )

        cached_result = serialize_for_agent(result)
        return cached_result

    return faq_search
