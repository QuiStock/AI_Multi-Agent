"""Compose and run the durable conversation-summary worker process."""

from __future__ import annotations

import logging
import signal
import socket
import threading
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo import MongoClient
from redis import Redis

from src import config
from src.agents.faq.ingestion.embedding.google_embedding_provider import (
    GoogleEmbeddingProvider,
)
from src.memory.mongo_repository import (
    CONVERSATIONS_COLLECTION_NAME,
    MongoConversationRepository,
)
from src.memory.qdrant_summary_indexer import QdrantSummaryIndexer
from src.memory.summary_job_repository import (
    SUMMARY_JOBS_COLLECTION_NAME,
    MongoSummaryJobRepository,
)
from src.memory.summary_lock_repository import MongoConversationSummaryLockRepository
from src.memory.summary_queue import RedisSummaryQueue, SummaryJobOutboxRelay
from src.memory.worker.summarizer_end_conversation import (
    EndConversationSummaryWorker,
    LLMSummaryUpdater,
)
from src.memory.worker.summary_job_worker import (
    SummaryJobWorker,
    SummaryJobWorkerSettings,
)

logger = logging.getLogger(__name__)


def main() -> None:
    """Run the Redis consumer and Mongo outbox relay until process shutdown."""
    settings = config.get_settings()
    if not settings.mongodb_uri or not settings.mongodb_db:
        raise RuntimeError("MONGODB_URI e MONGODB_DB são obrigatórios para o worker")

    mongo_client: MongoClient[Any] = MongoClient(settings.mongodb_uri)
    redis_client = Redis.from_url(settings.redis_url)
    qdrant_client = config.create_qdrant_client(settings)
    try:
        database = mongo_client[settings.mongodb_db]
        conversations = MongoConversationRepository(
            database[CONVERSATIONS_COLLECTION_NAME]
        )
        jobs = MongoSummaryJobRepository(
            database[SUMMARY_JOBS_COLLECTION_NAME],
            max_attempts=settings.summary_job_max_attempts,
        )
        jobs.ensure_indexes()
        locks = MongoConversationSummaryLockRepository(
            database["conversation_summary_locks"]
        )
        queue = RedisSummaryQueue(
            redis_client,
            stream_name=settings.summary_queue_stream,
            consumer_group=settings.summary_queue_group,
        )
        embeddings = GoogleEmbeddingProvider()
        indexer = QdrantSummaryIndexer(
            client=qdrant_client,
            embed_text=embeddings.embed_query,
            collection_name=settings.memory_summary_collection,
        )
        processor = EndConversationSummaryWorker(
            repository=conversations,
            summary_updater=LLMSummaryUpdater(),
            summary_indexer=indexer,
        )
        worker = SummaryJobWorker(
            repository=jobs,
            conversation_locks=locks,
            queue=queue,
            processor=processor,
            settings=SummaryJobWorkerSettings(
                worker_id=f"{socket.gethostname()}-{uuid4().hex}"
            ),
        )
        relay = SummaryJobOutboxRelay(
            repository=jobs,
            queue=queue,
            clock=lambda: datetime.now(timezone.utc),
        )
        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        relay_thread = threading.Thread(
            target=relay.run_forever,
            kwargs={"stop": stop},
            name="summary-outbox-relay",
            daemon=True,
        )
        relay_thread.start()
        logger.info("Worker de resumos iniciado")
        try:
            worker.run_forever(stop=stop)
        finally:
            stop.set()
            relay_thread.join(timeout=5)
            logger.info("Worker de resumos encerrado")
    finally:
        redis_client.close()
        qdrant_client.close()
        mongo_client.close()


if __name__ == "__main__":  # pragma: no cover - exercised as a process entry point
    logging.basicConfig(level=logging.INFO)
    main()
