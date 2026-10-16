from __future__ import annotations

from datetime import timezone
from functools import lru_cache, partial
from ipaddress import ip_address
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
from src.agents.judge.executor import JudgeExecutor
from src.agents.judge.jev_client import TypeSafeJevClient
from src.agents.product_workflow.executor import ProductWorkflowExecutor
from src.agents.product_workflow.repository import (
    PostgresProductWorkflowRepository,
)
from src.agents.router.executor import RouterExecutor
from src.api.controllers.conversation_controller import ConversationController
from src.api.controllers.conversation_end_controller import ConversationEndController
from src.api.controllers.conversation_history_controller import (
    ConversationHistoryController,
)
from src.api.controllers.conversation_list_controller import ConversationListController
from src.api.services.conversation_end_service import ConversationEndService
from src.api.services.conversation_history_service import ConversationHistoryService
from src.api.services.conversation_list_service import ConversationListService
from src.api.services.conversation_service import ConversationService
from src.api.services.health_service import HealthService
from src.api.services.lab_agent_config_service import LabAgentConfigService
from src.api.services.lab_run_service import LabRunService
from src.api.services.observability_service import ObservabilityService
from src.auth.account_repository import PostgresAccountRepository
from src.auth.errors import (
    AccountLookupError,
    AuthenticationConfigurationError,
    AuthenticationDependencyError,
    InvalidCredentialError,
)
from src.auth.models import AuthenticatedPrincipal
from src.auth.service import AuthenticationService
from src.auth.token import JWTIdentityDecoder
from src.graphs.adapters import GraphNode, run_faq_node, run_product_workflow_node
from src.graphs.agent_graph import create_agent_graph
from src.graphs.state import RouteName
from src.guardrails.config import GuardrailConfig
from src.guardrails.greeting import GreetingGuardrail
from src.guardrails.input_guardrail import input_guardrail_node
from src.guardrails.output_guardrail import create_output_guardrail_node
from src.llm_factory import get_configured_chat_model
from src.memory.checkpointer import create_local_checkpointer
from src.memory.enrich_context import ConversationContextEnricher
from src.memory.message_service import MemoryMessageService
from src.memory.mongo_repository import MongoConversationRepository
from src.memory.qdrant_summary_indexer import QdrantSummaryIndexer
from src.memory.service import SummaryContextService, SummarySearchConfig
from src.memory.summary_job_repository import MongoSummaryJobRepository
from src.memory.summary_lock_repository import MongoConversationSummaryLockRepository
from src.memory.summary_queue import RedisSummaryQueue
from src.memory.summary_scheduler import (
    ConversationSummaryScheduler,
)
from src.observability.ai_usage_repository import (
    AI_USAGE_COLLECTION_NAME,
    MongoAIUsageRepository,
)
from src.observability.audit import record_authentication_denial
from src.observability.trace_repository import (
    TRACE_COLLECTION_NAME,
    MongoTraceRepository,
)

_bearer_scheme = HTTPBearer(auto_error=False)


@lru_cache
def get_jwt_decoder(issuer: str | None, jwks_url: str | None) -> JWTIdentityDecoder:
    return JWTIdentityDecoder(issuer, jwks_url)


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
    settings = config.get_settings()
    client = request.client
    if (
        settings.app_environment == "development"
        and settings.auth_bypass_local_tests
        and client is not None
    ):
        try:
            is_loopback = ip_address(client.host).is_loopback
        except ValueError:
            is_loopback = False
        if is_loopback:
            return AuthenticatedPrincipal(
                user_id=settings.auth_bypass_user_id,
                email=settings.auth_bypass_email,
                role_code=settings.auth_bypass_role_code,
                store_ids=(settings.auth_bypass_store_id,),
            )

    if not isinstance(credentials, HTTPAuthorizationCredentials) or (
        credentials.scheme.lower() != "bearer"
    ):
        record_authentication_denial("credential_missing")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credencial inválida.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        identity = get_jwt_decoder(
            settings.jwt_issuer, settings.jwt_jwks_url
        ).decode_identity(credentials.credentials)
        pool = get_postgres_pool(request)
        service = AuthenticationService(
            PostgresAccountRepository(
                pool,
                statement_timeout_ms=int(settings.postgres_pool_timeout_seconds * 1000),
            ),
        )
        return service.authenticate(identity)
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
    except AuthenticationDependencyError:
        record_authentication_denial("jwks_unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
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
        tz_aware=True,
        tzinfo=timezone.utc,
    )


@lru_cache
def get_conversation_repository() -> MongoConversationRepository:
    settings = config.get_settings()
    return MongoConversationRepository(
        get_mongo_client()[_database_name()][settings.memory_conversations_collection]
    )


@lru_cache
def get_trace_repository() -> MongoTraceRepository:
    return MongoTraceRepository(
        get_mongo_client()[_database_name()][TRACE_COLLECTION_NAME]
    )


@lru_cache
def get_ai_usage_repository() -> MongoAIUsageRepository:
    return MongoAIUsageRepository(
        get_mongo_client()[_database_name()][AI_USAGE_COLLECTION_NAME]
    )


@lru_cache
def get_summary_job_repository() -> MongoSummaryJobRepository:
    settings = config.get_settings()
    repository = MongoSummaryJobRepository(
        get_mongo_client()[_database_name()][settings.memory_summary_jobs_collection],
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


def get_graph(request: Request) -> CompiledStateGraph:
    cached_graph = getattr(request.app.state, "agent_graph", None)
    if cached_graph is not None:
        return cast(CompiledStateGraph, cached_graph)

    settings = config.get_settings()
    repository = get_conversation_repository()
    postgres_pool = get_postgres_pool(request)

    qdrant_client = config.create_qdrant_client(settings)
    embedding_provider = GoogleEmbeddingProvider(
        usage_repository=get_ai_usage_repository()
    )
    summary_search_service = SummaryContextService(
        repository=repository,
        qdrant=qdrant_client,
        embed_query=embedding_provider.embed_query,
        search_config=SummarySearchConfig(
            collection_name=settings.memory_summary_collection,
            top_k=settings.memory_summary_top_k,
            min_score=settings.memory_summary_min_score,
        ),
    )
    summary_indexer = QdrantSummaryIndexer(
        client=qdrant_client,
        embed_text=embedding_provider.embed_query,
        collection_name=settings.memory_summary_collection,
    )
    summary_locks = MongoConversationSummaryLockRepository(
        get_mongo_client()[_database_name()][settings.memory_summary_locks_collection]
    )
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
    faq_executor = FAQExecutor(
        retriever=faq_retriever,
    )
    product_workflow_executor = ProductWorkflowExecutor(
        repository=PostgresProductWorkflowRepository(
            postgres_pool,
            statement_timeout_ms=int(settings.postgres_pool_timeout_seconds * 1000),
        ),
    )
    jev_client = TypeSafeJevClient(
        api_key=settings.typesafe_api_key,
        model=settings.typesafe_jev_model,
        base_url=settings.typesafe_api_base_url,
        timeout_seconds=settings.typesafe_jev_timeout_seconds,
    )
    capabilities: dict[RouteName, GraphNode] = {
        "faq": partial(
            run_faq_node,
            executor=faq_executor,
        ),
        "product_workflow": partial(
            run_product_workflow_node,
            executor=product_workflow_executor,
        ),
    }

    message_service = MemoryMessageService(repository)

    graph = create_agent_graph(
        input_guardrail=cast(
            GraphNode,
            partial(input_guardrail_node, guardrail_config=GuardrailConfig()),
        ),
        greeting_guardrail=GreetingGuardrail(),
        router=RouterExecutor(summary_search_service=summary_search_service),
        capabilities=capabilities,
        compiler=CompilerExecutor(),
        judge=JudgeExecutor(
            jev_client=jev_client,
            jev_confidence_threshold=settings.typesafe_jev_confidence_threshold,
        ),
        output_guardrail=cast(
            GraphNode,
            create_output_guardrail_node(source="compiled"),
        ),
        context_enricher=ConversationContextEnricher(
            repository,
            summary_indexer=summary_indexer,
            conversation_locks=summary_locks,
        ),
        message_service=message_service,
        checkpointer=get_checkpointer(),
    )
    request.app.state.agent_graph = graph
    return graph


def get_conversation_controller(
    graph: CompiledStateGraph = Depends(get_graph),
    trace_repository: MongoTraceRepository = Depends(get_trace_repository),
) -> ConversationController:
    return ConversationController(
        ConversationService(
            graph,
            trace_repository=trace_repository,
        )
    )


def get_observability_service() -> ObservabilityService:
    return ObservabilityService(
        traces=get_trace_repository(),
        conversations=get_conversation_repository(),
        ai_usage=get_ai_usage_repository(),
    )


def get_lab_run_service() -> LabRunService:
    return LabRunService(
        model_resolver=get_configured_chat_model,
        usage_repository=get_ai_usage_repository(),
    )


def get_lab_agent_config_service() -> LabAgentConfigService:
    return LabAgentConfigService()


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


def get_conversation_history_controller() -> ConversationHistoryController:
    return ConversationHistoryController(
        ConversationHistoryService(get_conversation_repository())
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
