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
from src.memory.conversation_cleanup import ConversationCleanupProcessor
from src.memory.mongo_repository import MongoConversationRepository
from src.memory.qdrant_summary_indexer import QdrantSummaryIndexer
from src.memory.summary_job_repository import MongoSummaryJobRepository
from src.memory.summary_lock_repository import MongoConversationSummaryLockRepository
from src.memory.summary_queue import RedisSummaryQueue, SummaryJobOutboxRelay
from src.memory.summary_reconciler import SummaryReconciler
from src.memory.summary_scheduler import ConversationSummaryScheduler
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
            database[settings.memory_conversations_collection]
        )
        jobs = MongoSummaryJobRepository(
            database[settings.memory_summary_jobs_collection],
            max_attempts=settings.summary_job_max_attempts,
        )
        jobs.ensure_indexes()
        locks = MongoConversationSummaryLockRepository(
            database[settings.memory_summary_locks_collection]
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
        cleanup_processor = ConversationCleanupProcessor(
            conversations=conversations,
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
            cleanup_processor=cleanup_processor,
        )
        relay = SummaryJobOutboxRelay(
            repository=jobs,
            queue=queue,
            clock=lambda: datetime.now(timezone.utc),
        )
        reconciler = SummaryReconciler(
            conversations=conversations,
            indexer=indexer,
            scheduler=ConversationSummaryScheduler(
                conversations=conversations,
                jobs=jobs,
                queue=queue,
            ),
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
        reconciliation_thread = threading.Thread(
            target=_run_reconciliation,
            kwargs={
                "reconciler": reconciler,
                "stop": stop,
                "interval_seconds": settings.summary_reconciliation_interval_seconds,
            },
            name="summary-reconciler",
            daemon=True,
        )
        reconciliation_thread.start()
        logger.info("Worker de resumos iniciado")
        try:
            worker.run_forever(stop=stop)
        finally:
            stop.set()
            relay_thread.join(timeout=5)
            reconciliation_thread.join(timeout=5)
            logger.info("Worker de resumos encerrado")
    finally:
        redis_client.close()
        qdrant_client.close()
        mongo_client.close()


def _run_reconciliation(
    *,
    reconciler: SummaryReconciler,
    stop: threading.Event,
    interval_seconds: int,
) -> None:
    if interval_seconds < 1:
        raise ValueError("interval_seconds precisa ser positivo")
    while not stop.is_set():
        try:
            report = reconciler.reconcile()
            logger.info(
                "Reconciliação de memória concluída; scanned=%s scheduled=%s "
                "orphaned=%s reset=%s",
                report.scanned_conversations,
                report.scheduled_jobs,
                report.deleted_orphan_points,
                report.invalid_points_reset,
            )
        except Exception as exc:
            logger.warning(
                "Reconciliação de memória falhou; error_type=%s",
                type(exc).__name__,
            )
        stop.wait(interval_seconds)


if __name__ == "__main__":  # pragma: no cover - exercised as a process entry point
    logging.basicConfig(level=logging.INFO)
    main()
