"""Redis Streams transport for summary job IDs and a Mongo outbox relay."""

import logging
import threading
from datetime import datetime
from typing import Any

from .summary_job_repository import MongoSummaryJobRepository

SUMMARY_STREAM_NAME = "conversation_summary_jobs"
SUMMARY_CONSUMER_GROUP = "conversation_summary_workers"
logger = logging.getLogger(__name__)


class RedisSummaryQueue:
    """Thin Redis Streams adapter; stream entries contain only a durable job ID."""

    def __init__(
        self,
        client: Any,
        *,
        stream_name: str = SUMMARY_STREAM_NAME,
        consumer_group: str = SUMMARY_CONSUMER_GROUP,
    ) -> None:
        if not stream_name.strip() or not consumer_group.strip():
            raise ValueError("stream_name e consumer_group são obrigatórios")
        self._client = client
        self.stream_name = stream_name
        self.consumer_group = consumer_group

    def publish(self, job_id: str) -> str:
        if not job_id.strip():
            raise ValueError("job_id é obrigatório")
        entry_id = self._client.xadd(self.stream_name, {"job_id": job_id})
        return entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)

    def ensure_consumer_group(self, group: str | None = None) -> None:
        group = group or self.consumer_group
        try:
            self._client.xgroup_create(
                name=self.stream_name,
                groupname=group,
                id="0-0",
                mkstream=True,
            )
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def read_new(
        self,
        *,
        consumer: str,
        group: str | None = None,
        count: int = 10,
        block_ms: int = 1000,
    ) -> list[tuple[str, str]]:
        group = group or self.consumer_group
        batches = self._client.xreadgroup(
            group,
            consumer,
            {self.stream_name: ">"},
            count=count,
            block=block_ms,
        )
        return self._decode_batches(batches)

    def reclaim_pending(
        self,
        *,
        consumer: str,
        min_idle_ms: int,
        group: str | None = None,
        count: int = 10,
    ) -> list[tuple[str, str]]:
        group = group or self.consumer_group
        pending = self._client.xpending_range(
            self.stream_name,
            group,
            min="-",
            max="+",
            count=count,
        )
        message_ids = []
        for item in pending or []:
            if not isinstance(item, dict):
                continue
            raw_idle = item.get("time_since_delivered")
            if raw_idle is None:
                raw_idle = item.get(b"time_since_delivered", 0)
            try:
                idle_ms = int(raw_idle)
            except TypeError, ValueError:
                continue
            if idle_ms >= min_idle_ms:
                message_id = item.get("message_id", item.get(b"message_id"))
                if message_id is not None:
                    message_ids.append(message_id)
        message_ids = [value for value in message_ids if value is not None]
        if not message_ids:
            return []
        entries = self._client.xclaim(
            self.stream_name,
            group,
            consumer,
            min_idle_ms,
            message_ids,
        )
        return self._decode_entries(entries)

    def acknowledge(self, *, entry_id: str, group: str | None = None) -> None:
        self._client.xack(self.stream_name, group or self.consumer_group, entry_id)

    def refresh_pending(
        self,
        *,
        entry_id: str,
        consumer: str,
        group: str | None = None,
    ) -> bool:
        """Reset Redis pending idle time while the Mongo leases are heartbeated."""
        group = group or self.consumer_group
        claimed = self._client.xclaim(
            self.stream_name,
            group,
            consumer,
            0,
            [entry_id],
        )
        return bool(claimed)

    @staticmethod
    def _decode_batches(batches: Any) -> list[tuple[str, str]]:
        result: list[tuple[str, str]] = []
        for _, entries in batches or []:
            result.extend(RedisSummaryQueue._decode_entries(entries))
        return result

    @staticmethod
    def _decode_entries(entries: Any) -> list[tuple[str, str]]:
        decoded: list[tuple[str, str]] = []
        for entry_id, fields in entries or []:
            raw_job_id = fields.get("job_id") or fields.get(b"job_id")
            if raw_job_id is None:
                continue
            id_text = (
                entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)
            )
            job_text = (
                raw_job_id.decode()
                if isinstance(raw_job_id, bytes)
                else str(raw_job_id)
            )
            decoded.append((id_text, job_text))
        return decoded


class SummaryJobOutboxRelay:
    def __init__(
        self,
        *,
        repository: MongoSummaryJobRepository,
        queue: RedisSummaryQueue,
        clock: Any,
    ) -> None:
        self._repository = repository
        self._queue = queue
        self._clock = clock

    def publish_due(self, *, limit: int = 100) -> int:
        now: datetime = self._clock()
        published = 0
        for job in self._repository.find_unpublished(now=now, limit=limit):
            self._queue.publish(job.job_id)
            self._repository.mark_published(job_id=job.job_id, published_at=now)
            published += 1
        return published

    def run_forever(
        self,
        *,
        stop: threading.Event,
        interval_seconds: float = 2.0,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds precisa ser positivo")
        while not stop.is_set():
            try:
                self.publish_due()
            except Exception as exc:
                logger.warning(
                    "Relay de resumo falhou; error_type=%s", type(exc).__name__
                )
            stop.wait(interval_seconds)
