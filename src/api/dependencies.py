from __future__ import annotations

from functools import lru_cache, partial
from typing import Any, cast

from fastapi import Depends
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.state import CompiledStateGraph
from pymongo import MongoClient
from qdrant_client import QdrantClient

from src import config
from src.agents.compiler.executor import CompilerExecutor
from src.agents.faq.executor import FAQExecutor
from src.agents.faq.ingestion.embedding.google_embedding_provider import (
    GoogleEmbeddingProvider,
)
from src.agents.faq.ingestion.vectorstore.qdrant_store import QdrantStore
from src.agents.faq.retrieval.qdrant_retriever import QdrantRetriever
from src.agents.faq.tools.faq_tool import create_faq_search_tool
from src.agents.judge.executor import JudgeExecutor
from src.agents.router.executor import RouterExecutor
from src.agents.tool_registry import TOOL_REGISTRY
from src.api.controllers.conversation_controller import ConversationController
from src.api.controllers.conversation_end_controller import ConversationEndController
from src.api.controllers.conversation_list_controller import ConversationListController
from src.api.services.conversation_end_service import ConversationEndService
from src.api.services.conversation_list_service import ConversationListService
from src.api.services.conversation_service import ConversationService
from src.graphs.adapters import GraphNode, run_faq_node
from src.graphs.agent_graph import create_agent_graph
from src.graphs.state import RouteName
from src.guardrails.input_guardrail import input_guardrail_node
from src.guardrails.output_guardrail import create_output_guardrail_node
from src.memory.checkpointer import create_local_checkpointer
from src.memory.enrich_context import ConversationContextEnricher
from src.memory.message_service import MemoryMessageService
from src.memory.mongo_repository import (
    CONVERSATIONS_COLLECTION_NAME,
    MongoConversationRepository,
)
from src.memory.summary_job_repository import (
    SUMMARY_JOBS_COLLECTION_NAME,
    MongoSummaryJobRepository,
)
from src.memory.summary_queue import RedisSummaryJobPublisher


def _database_name() -> str:
    database_name = config.get_settings().mongodb_db
    if not database_name:
        raise RuntimeError("MONGODB_DB é obrigatório")
    return database_name


@lru_cache
def get_mongo_client() -> MongoClient[Any]:
    settings = config.get_settings()
    if not settings.mongodb_uri or not settings.mongodb_db:
        raise RuntimeError("MONGODB_URI e MONGODB_DB são obrigatórios")
    return MongoClient(settings.mongodb_uri)


@lru_cache
def get_conversation_repository() -> MongoConversationRepository:
    return MongoConversationRepository(
        get_mongo_client()[_database_name()][CONVERSATIONS_COLLECTION_NAME]
    )


@lru_cache
def get_summary_job_repository() -> MongoSummaryJobRepository:
    repository = MongoSummaryJobRepository(
        get_mongo_client()[_database_name()][SUMMARY_JOBS_COLLECTION_NAME]
    )
    repository.ensure_indexes()
    return repository


@lru_cache
def get_checkpointer() -> MemorySaver:
    return create_local_checkpointer()


@lru_cache
def get_summary_job_publisher() -> RedisSummaryJobPublisher:
    settings = config.get_settings()
    from redis import Redis

    return RedisSummaryJobPublisher(
        client=Redis.from_url(settings.redis_url),
        stream_name=settings.summary_queue_stream,
    )


@lru_cache
def get_graph() -> CompiledStateGraph:
    settings = config.get_settings()
    repository = get_conversation_repository()

    qdrant_client = QdrantClient(path=str(settings.faq_vectorstore_dir))
    embedding_provider = GoogleEmbeddingProvider()
    faq_store = QdrantStore(
        qdrant_client=qdrant_client,
        collection_name=settings.faq_vectorstore_collection,
    )
    faq_retriever = QdrantRetriever(
        embedding_provider=embedding_provider,
        vector_store=faq_store,
        top_k=settings.faq_retrieval_k,
        min_score=settings.faq_retrieval_min_relevance,
    )
    TOOL_REGISTRY["faq_search"] = create_faq_search_tool(faq_retriever)

    faq_executor = FAQExecutor()
    capabilities: dict[RouteName, GraphNode] = {
        "faq": partial(
            run_faq_node,
            executor=faq_executor,
        )
    }

    return create_agent_graph(
        input_guardrail=cast(GraphNode, input_guardrail_node),
        router=RouterExecutor(),
        capabilities=capabilities,
        compiler=CompilerExecutor(),
        judge=JudgeExecutor(),
        output_guardrail=cast(
            GraphNode,
            create_output_guardrail_node(source="compiled"),
        ),
        context_enricher=ConversationContextEnricher(repository),
        message_service=MemoryMessageService(repository),
        checkpointer=get_checkpointer(),
    )


def get_conversation_controller(
    graph: CompiledStateGraph = Depends(get_graph),
) -> ConversationController:
    return ConversationController(ConversationService(graph))


def get_conversation_end_controller() -> ConversationEndController:
    return ConversationEndController(
        ConversationEndService(
            conversation_repository=get_conversation_repository(),
            job_repository=get_summary_job_repository(),
            job_publisher=get_summary_job_publisher(),
            checkpoint_cleanup=get_checkpointer(),
        )
    )


def get_conversation_list_controller() -> ConversationListController:
    return ConversationListController(
        ConversationListService(get_conversation_repository())
    )
