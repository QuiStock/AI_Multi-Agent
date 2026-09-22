"""Redis Streams worker for asynchronous conversation summaries."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from redis import Redis
from redis.exceptions import ResponseError

from ..summary_jobs import SummaryJobRepository
from .summarizer_end_conversation import EndConversationSummaryWorker

DEFAULT_PENDING_IDLE_MS = 60_000
MAX_WORKER_BATCH = 1_000


class RedisSummaryJobWorker:
    """Consume summary jobs with at-least-once delivery and bounded retries."""

    def __init__(  # noqa: PLR0913 - explicit worker composition boundary
        self,
        *,
        client: Redis,
        stream_name: str,
        group_name: str,
        consumer_name: str,
        job_repository: SummaryJobRepository,
        summary_worker: EndConversationSummaryWorker,
        max_attempts: int = 3,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not stream_name.strip() or not group_name.strip():
            raise ValueError("stream_name e group_name são obrigatórios")
        if not consumer_name.strip():
            raise ValueError("consumer_name é obrigatório")
        if max_attempts < 1:
            raise ValueError("max_attempts deve ser positivo")
        self._client = client
        self._stream_name = stream_name
        self._group_name = group_name
        self._consumer_name = consumer_name
        self._job_repository = job_repository
        self._summary_worker = summary_worker
        self._max_attempts = max_attempts
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def ensure_group(self) -> None:
        try:
            self._client.xgroup_create(
                self._stream_name,
                self._group_name,
                id="0-0",
                mkstream=True,
            )
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def run_once(self, *, block_ms: int = 1_000) -> bool:
        """Consume at most one new stream entry."""
        if block_ms < 0:
            raise ValueError("block_ms não pode ser negativo")
        self.ensure_group()
        if self.reclaim_pending(limit=1) > 0:
            return True
        if self.republish_unpublished(limit=1) > 0:
            return True
        records: Any = self._client.xreadgroup(
            groupname=self._group_name,
            consumername=self._consumer_name,
            streams={self._stream_name: ">"},
            count=1,
            block=block_ms,
        )
        for _, entries in records:
            for entry_id, fields in entries:
                normalized_id = self._as_text(entry_id)
                self.process_entry(entry_id=normalized_id, fields=fields)
                return True
        return False

    def reclaim_pending(
        self,
        *,
        limit: int = 100,
        min_idle_ms: int = DEFAULT_PENDING_IDLE_MS,
    ) -> int:
        if not 1 <= limit <= MAX_WORKER_BATCH:
            raise ValueError("limit deve estar entre um e mil")
        if min_idle_ms < 0:
            raise ValueError("min_idle_ms não pode ser negativo")
        result: Any = self._client.xautoclaim(
            self._stream_name,
            self._group_name,
            self._consumer_name,
            min_idle_ms,
            start_id="0-0",
            count=limit,
        )
        entries = result[1] if len(result) > 1 else []
        processed = 0
        for entry_id, fields in entries:
            self.process_entry(
                entry_id=self._as_text(entry_id),
                fields=fields,
            )
            processed += 1
        return processed

    def republish_unpublished(self, *, limit: int = 100) -> int:
        """Repair jobs committed in Mongo before an API process stopped."""
        published = 0
        for job in self._job_repository.list_unpublished(limit=limit):
            if not self._job_repository.claim_publication(
                job_id=job.job_id,
                updated_at=self._clock(),
            ):
                continue
            try:
                self._client.xadd(
                    self._stream_name,
                    {
                        "job_id": job.job_id,
                        "conversation_id": job.conversation_id,
                        "user_id": job.user_id,
                        "request_id": job.request_id,
                    },
                )
                self._job_repository.mark_published(
                    job_id=job.job_id,
                    published_at=self._clock(),
                )
            except Exception:
                self._job_repository.release_publication(
                    job_id=job.job_id,
                    updated_at=self._clock(),
                )
                continue
            published += 1
        return published

    def run_forever(self, *, block_ms: int = 1_000) -> None:
        while True:
            self.run_once(block_ms=block_ms)

    def process_entry(
        self,
        *,
        entry_id: str,
        fields: Mapping[str | bytes, str | bytes],
    ) -> None:
        job_id = self._field(fields, "job_id")
        conversation_id = self._field(fields, "conversation_id")
        user_id = self._field(fields, "user_id")
        claimed = self._job_repository.mark_processing(
            job_id=job_id,
            updated_at=self._clock(),
        )
        if not claimed:
            self._client.xack(self._stream_name, self._group_name, entry_id)
            return

        try:
            self._summary_worker.run(
                conversation_id=conversation_id,
                user_id=user_id,
            )
        except Exception as exc:
            status = self._job_repository.mark_failed(
                job_id=job_id,
                updated_at=self._clock(),
                error=str(exc) or exc.__class__.__name__,
                max_attempts=self._max_attempts,
            )
            if status == "queued":
                self._client.xadd(
                    self._stream_name,
                    {
                        self._as_text(key): self._as_text(value)
                        for key, value in fields.items()
                    },
                )
            self._client.xack(self._stream_name, self._group_name, entry_id)
            return

        self._job_repository.mark_completed(
            job_id=job_id,
            updated_at=self._clock(),
        )
        self._client.xack(self._stream_name, self._group_name, entry_id)

    @staticmethod
    def _field(
        fields: Mapping[str | bytes, str | bytes],
        name: str,
    ) -> str:
        value = fields.get(name) or fields.get(name.encode())
        if value is None:
            raise ValueError(f"Campo obrigatório ausente no job: {name}")
        return value.decode() if isinstance(value, bytes) else value

    @staticmethod
    def _as_text(value: str | bytes) -> str:
        return value.decode() if isinstance(value, bytes) else value


def create_summary_job_worker() -> RedisSummaryJobWorker:
    """Build the production worker from the application settings."""
    from pymongo import MongoClient
    from qdrant_client import QdrantClient
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
    from src.memory.worker.summarizer_end_conversation import LLMSummaryUpdater

    settings = config.get_settings()
    if not settings.mongodb_uri or not settings.mongodb_db:
        raise RuntimeError("MONGODB_URI e MONGODB_DB são obrigatórios")

    mongo_client: MongoClient[Any] = MongoClient(settings.mongodb_uri)
    database = mongo_client[settings.mongodb_db]
    conversation_repository = MongoConversationRepository(
        database[CONVERSATIONS_COLLECTION_NAME]
    )
    job_repository = MongoSummaryJobRepository(database[SUMMARY_JOBS_COLLECTION_NAME])
    job_repository.ensure_indexes()

    qdrant_client = QdrantClient(path=str(settings.faq_vectorstore_dir))
    embedding_provider = GoogleEmbeddingProvider()
    summary_indexer = QdrantSummaryIndexer(
        client=qdrant_client,
        embed_text=embedding_provider.embed_query,
        collection_name=settings.memory_summary_collection,
    )
    summary_worker = EndConversationSummaryWorker(
        repository=conversation_repository,
        summary_updater=LLMSummaryUpdater(),
        summary_indexer=summary_indexer,
    )
    return RedisSummaryJobWorker(
        client=Redis.from_url(settings.redis_url),
        stream_name=settings.summary_queue_stream,
        group_name=settings.summary_queue_group,
        consumer_name=f"summary-worker-{uuid4()}",
        job_repository=job_repository,
        summary_worker=summary_worker,
        max_attempts=settings.summary_job_max_attempts,
    )


def main() -> None:
    create_summary_job_worker().run_forever()


if __name__ == "__main__":  # pragma: no cover
    main()
