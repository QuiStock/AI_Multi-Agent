"""Redis Streams adapter for conversation summary jobs."""

from typing import Protocol

from redis import Redis
from redis.exceptions import RedisError

from .summary_jobs import SummaryJob


class SummaryQueueError(RuntimeError):
    """Raised when a summary job cannot be published to Redis."""


class SummaryJobPublisher(Protocol):
    def publish(self, job: SummaryJob) -> str: ...


class RedisSummaryJobPublisher:
    """Publish one validated job to a Redis Stream."""

    def __init__(
        self,
        *,
        client: Redis,
        stream_name: str,
    ) -> None:
        if not stream_name.strip():
            raise ValueError("stream_name é obrigatório")
        self._client = client
        self._stream_name = stream_name

    def publish(self, job: SummaryJob) -> str:
        try:
            entry_id = self._client.xadd(
                self._stream_name,
                {
                    "job_id": job.job_id,
                    "conversation_id": job.conversation_id,
                    "user_id": job.user_id,
                    "request_id": job.request_id,
                },
            )
        except RedisError as exc:
            raise SummaryQueueError from exc
        return entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)
