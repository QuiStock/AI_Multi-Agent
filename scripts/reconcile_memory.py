"""Run one bounded memory reconciliation cycle."""

from __future__ import annotations

from typing import Any

from pymongo import MongoClient
from redis import Redis

from src import config
from src.agents.faq.ingestion.embedding.google_embedding_provider import (
    GoogleEmbeddingProvider,
)
from src.memory.mongo_repository import MongoConversationRepository
from src.memory.qdrant_summary_indexer import QdrantSummaryIndexer
from src.memory.summary_job_repository import MongoSummaryJobRepository
from src.memory.summary_queue import RedisSummaryQueue
from src.memory.summary_reconciler import SummaryReconciler
from src.memory.summary_scheduler import ConversationSummaryScheduler
from src.observability.ai_usage_repository import (
    AI_USAGE_COLLECTION_NAME,
    MongoAIUsageRepository,
)


def main() -> None:
    settings = config.get_settings()
    if not settings.mongodb_uri or not settings.mongodb_db:
        raise RuntimeError("MONGODB_URI e MONGODB_DB são obrigatórios")

    mongo_client: MongoClient[Any] = MongoClient(settings.mongodb_uri)
    redis_client = Redis.from_url(settings.redis_url)
    qdrant_client = config.create_qdrant_client(settings)
    try:
        database = mongo_client[settings.mongodb_db]
        ai_usage = MongoAIUsageRepository(database[AI_USAGE_COLLECTION_NAME])
        conversations = MongoConversationRepository(
            database[settings.memory_conversations_collection]
        )
        jobs = MongoSummaryJobRepository(
            database[settings.memory_summary_jobs_collection],
            max_attempts=settings.summary_job_max_attempts,
        )
        jobs.ensure_indexes()
        queue = RedisSummaryQueue(
            redis_client,
            stream_name=settings.summary_queue_stream,
            consumer_group=settings.summary_queue_group,
        )
        embeddings = GoogleEmbeddingProvider(usage_repository=ai_usage)
        indexer = QdrantSummaryIndexer(
            client=qdrant_client,
            embed_text=embeddings.embed_query,
            embed_text_with_context=lambda text, conversation_id: (
                embeddings.embed_query(
                    text,
                    source="memory_embedding_index",
                    conversation_id=conversation_id,
                )
            ),
            collection_name=settings.memory_summary_collection,
        )
        scheduler = ConversationSummaryScheduler(
            conversations=conversations,
            jobs=jobs,
            queue=queue,
        )
        report = SummaryReconciler(
            conversations=conversations,
            indexer=indexer,
            scheduler=scheduler,
        ).reconcile()
        print(report)
    finally:
        qdrant_client.close()
        redis_client.close()
        mongo_client.close()


if __name__ == "__main__":
    main()
