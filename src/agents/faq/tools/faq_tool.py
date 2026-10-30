"""Contract-backed FAQ retrieval tool."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from src.agents.faq.ingestion.audience import Audience
from src.agents.faq.retrieval.qdrant_retriever import QdrantRetriever
from src.agents.schemas.tool_result import (
    ToolEvidence,
    ToolResult,
)
from src.agents.tooling.result_adapter import serialize_for_agent
from src.agents.tooling.result_factory import (
    ToolResultExtras,
    compose_success,
    create_tool_error,
    create_tool_metadata,
    tool_error,
)

from .schemas import FAQSearchData, FAQSearchItem


def _not_found_evidence(query: str) -> ToolEvidence:
    digest = hashlib.sha256(query.encode("utf-8")).hexdigest()[:20]
    return ToolEvidence(
        evidence_id=f"faq-search:{digest}:no-results",
        source_type="faq_document",
        source_id="faq-search",
        content=(
            "A busca documental foi concluída sem encontrar trechos sobre o assunto."
        ),
        metadata={
            "outcome": "not_found",
            "status": "not_found",
            "result_count": 0,
        },
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


@dataclass
class FAQSearchContext:
    retriever: QdrantRetriever
    allowed_audiences: Sequence[Audience]
    trace_id: str
    call_id_factory: Callable[[], str]
    on_result: Callable[[dict[str, Any]], None] | None
    cached_tool_result: str | None = None


class FAQSearchArguments(BaseModel):
    query: str


def faq_search(query: str, *, context: FAQSearchContext) -> str:
    """Busca evidências documentais no FAQ autorizado para a requisição."""

    def serialize_and_capture(
        result: ToolResult[Any],
        *,
        cache: bool = True,
    ) -> str:
        output = serialize_for_agent(result)
        if cache:
            context.cached_tool_result = output
        if context.on_result is not None:
            context.on_result(json.loads(output))
        return output

    normalized_query = query.strip()
    metadata = create_tool_metadata(
        tool_name="faq_search",
        tool_version="1.0.0",
        tool_call_id=context.call_id_factory(),
        trace_id=context.trace_id,
    )

    if not normalized_query:
        return serialize_and_capture(
            tool_error(
                error=create_tool_error(
                    code="FAQ_INVALID_QUERY",
                    category="validation",
                    message="A consulta da FAQ não pode estar vazia.",
                ),
                meta=metadata,
            ),
            cache=False,
        )

    if context.cached_tool_result is not None:
        if context.on_result is not None:
            context.on_result(json.loads(context.cached_tool_result))
        return context.cached_tool_result

    try:
        raw_results = context.retriever.search(
            normalized_query,
            allowed_audiences=context.allowed_audiences,
        )
        results = [
            _normalize_item(item) for item in raw_results if isinstance(item, Mapping)
        ]
        data = FAQSearchData(
            query=normalized_query,
            outcome="found" if results else "not_found",
            result_count=len(results),
            results=results,
        )

        if not results:
            result: ToolResult[Any] = compose_success(
                data=data,
                meta=metadata,
                extras=ToolResultExtras(
                    evidence=(_not_found_evidence(normalized_query),),
                ),
            )
        else:
            result = compose_success(
                data=data,
                meta=metadata,
                extras=ToolResultExtras(
                    evidence=tuple(_evidence(item) for item in results),
                ),
            )
        return serialize_and_capture(result)
    except ValueError:
        result = tool_error(
            error=create_tool_error(
                code="FAQ_INVALID_RESULT",
                category="internal",
                message="A base de conhecimento retornou dados inválidos.",
            ),
            meta=metadata,
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
        )

    return serialize_and_capture(result)


def create_faq_search_tool(  # noqa: PLR0913
    retriever: QdrantRetriever,
    *,
    allowed_audiences: Sequence[Audience],
    request_id: str,
    trace_id: str | None = None,
    call_id_factory: Callable[[], str] | None = None,
    on_result: Callable[[dict[str, Any]], None] | None = None,
) -> StructuredTool:
    """Build one request-scoped FAQ tool with a single lookup budget."""
    if not request_id.strip():
        raise ValueError("request_id é obrigatório")

    context = FAQSearchContext(
        retriever=retriever,
        allowed_audiences=allowed_audiences,
        trace_id=trace_id.strip() if trace_id and trace_id.strip() else request_id,
        call_id_factory=call_id_factory or (lambda: str(uuid.uuid4())),
        on_result=on_result,
    )
    return StructuredTool.from_function(
        func=partial(faq_search, context=context),
        name="faq_search",
        description="Busca evidências documentais no FAQ autorizado.",
        args_schema=FAQSearchArguments,
    )
