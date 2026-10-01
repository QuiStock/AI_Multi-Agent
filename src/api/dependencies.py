from __future__ import annotations

from functools import lru_cache, partial
from typing import Any, cast

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.state import CompiledStateGraph
from pymongo import MongoClient

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
from src.api.services.health_service import HealthService
from src.auth.account_repository import PostgresAccountRepository
from src.auth.errors import (
    AccountLookupError,
    AuthenticationConfigurationError,
    InvalidCredentialError,
)
from src.auth.models import AuthenticatedPrincipal
from src.auth.service import AuthenticationService
from src.auth.token import decoder_from_json_keyring
from src.graphs.adapters import GraphNode, run_faq_node
from src.graphs.agent_graph import create_agent_graph
from src.graphs.state import RouteName
from src.guardrails.config import GuardrailConfig
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
from src.memory.summary_queue import RedisSummaryQueue
from src.memory.summary_scheduler import ConversationSummaryScheduler
from src.observability.audit import record_authentication_denial

_bearer_scheme = HTTPBearer(auto_error=False)


def get_postgres_pool(request: Request) -> Any:
    pool = getattr(request.app.state, "postgres_pool", None)
    if pool is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Serviço temporariamente indisponível.",
        )
    return pool


def get_authenticated_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> AuthenticatedPrincipal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        record_authentication_denial("credential_missing")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credencial inválida.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    settings = config.get_settings()
    try:
        decoder = decoder_from_json_keyring(settings.jwe_private_keys_json)
        email = decoder.decode_email(credentials.credentials)
        pool = get_postgres_pool(request)
        service = AuthenticationService(
            decoder,
            PostgresAccountRepository(
                pool,
                statement_timeout_ms=int(settings.postgres_pool_timeout_seconds * 1000),
            ),
        )
        return service.authenticate_email(email)
    except InvalidCredentialError:
        record_authentication_denial("credential_invalid")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credencial inválida.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except AuthenticationConfigurationError:
        record_authentication_denial("authentication_misconfigured")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Serviço temporariamente indisponível.",
        ) from None
    except PermissionError:
        record_authentication_denial("role_forbidden")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso não permitido.",
        ) from None
    except AccountLookupError:
        record_authentication_denial("account_lookup_failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Serviço temporariamente indisponível.",
        ) from None


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
    timeout_ms = int(settings.health_probe_timeout_seconds * 1000)
    return MongoClient(
        settings.mongodb_uri,
        serverSelectionTimeoutMS=timeout_ms,
        connectTimeoutMS=timeout_ms,
        socketTimeoutMS=timeout_ms,
    )


@lru_cache
def get_conversation_repository() -> MongoConversationRepository:
    return MongoConversationRepository(
        get_mongo_client()[_database_name()][CONVERSATIONS_COLLECTION_NAME]
    )


@lru_cache
def get_summary_job_repository() -> MongoSummaryJobRepository:
    settings = config.get_settings()
    repository = MongoSummaryJobRepository(
        get_mongo_client()[_database_name()][SUMMARY_JOBS_COLLECTION_NAME],
        max_attempts=settings.summary_job_max_attempts,
    )
    repository.ensure_indexes()
    return repository


@lru_cache
def get_checkpointer() -> MemorySaver:
    return create_local_checkpointer()


@lru_cache
def get_summary_queue() -> RedisSummaryQueue:
    settings = config.get_settings()
    from redis import Redis

    return RedisSummaryQueue(
        client=Redis.from_url(settings.redis_url),
        stream_name=settings.summary_queue_stream,
        consumer_group=settings.summary_queue_group,
    )


@lru_cache
def get_conversation_summary_scheduler() -> ConversationSummaryScheduler:
    return ConversationSummaryScheduler(
        conversations=get_conversation_repository(),
        jobs=get_summary_job_repository(),
        queue=get_summary_queue(),
    )


@lru_cache
def get_graph() -> CompiledStateGraph:
    settings = config.get_settings()
    repository = get_conversation_repository()

    qdrant_client = config.create_qdrant_client(settings)
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
        input_guardrail=cast(
            GraphNode,
            partial(
                input_guardrail_node,
                guardrail_config=GuardrailConfig(
                    classify_semantically=False,
                ),
            ),
        ),
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
            scheduler=get_conversation_summary_scheduler(),
            checkpoint_cleanup=get_checkpointer(),
        )
    )


def get_conversation_list_controller() -> ConversationListController:
    return ConversationListController(
        ConversationListService(get_conversation_repository())
    )


def get_health_service(request: Request) -> HealthService:
    settings = config.get_settings()
    return HealthService(
        settings=settings,
        postgres_pool=getattr(request.app.state, "postgres_pool", None),
        mongo_client=get_mongo_client_if_configured(settings),
    )


def get_mongo_client_if_configured(
    settings: config.Settings,
) -> MongoClient[Any] | None:
    if not settings.mongodb_uri or not settings.mongodb_db:
        return None
    return get_mongo_client()
