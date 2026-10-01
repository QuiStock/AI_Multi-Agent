from datetime import datetime, timedelta, timezone

from src.memory.mongo_repository import ConversationNotEndedError
from src.memory.summary_jobs import SummaryJob
from src.memory.summary_lock_repository import ConversationSummaryLease
from src.memory.worker.summary_job_worker import (
    SummaryJobWorker,
    SummaryJobWorkerSettings,
)

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _job() -> SummaryJob:
    return SummaryJob(
        job_id="conversation-1:close-1",
        conversation_id="conversation-1",
        email="user-1",
        closure_key="close-1",
        status="processing",
        attempts=1,
        created_at=NOW,
        updated_at=NOW,
        lease_owner="worker-1",
        lease_until=NOW + timedelta(minutes=5),
    )


class FakeJobRepository:
    def __init__(self) -> None:
        self.events: list[str] = []

    def claim(self, **_: object) -> SummaryJob:
        self.events.append("claim")
        return _job()

    def renew_lease(self, **_: object) -> bool:
        self.events.append("renew")
        return True

    def complete(self, **_: object) -> bool:
        self.events.append("complete")
        return True

    def mark_superseded(self, **_: object) -> bool:
        self.events.append("superseded")
        return True

    def schedule_retry(self, **_: object) -> str:
        self.events.append("retry")
        return "queued"

    def mark_expired_jobs_failed(self, **_: object) -> int:
        return 0


class FakeQueue:
    def __init__(self) -> None:
        self.acks: list[str] = []

    def ensure_consumer_group(self) -> None:
        pass

    def reclaim_pending(self, **_: object) -> list[tuple[str, str]]:
        return []

    def read_new(self, **_: object) -> list[tuple[str, str]]:
        return [("1-0", "conversation-1:close-1")]

    def acknowledge(self, *, entry_id: str) -> None:
        self.acks.append(entry_id)

    def refresh_pending(self, **_: object) -> bool:
        return True


class FakeLockRepository:
    def acquire(self, **kwargs: object) -> ConversationSummaryLease:
        return ConversationSummaryLease(
            conversation_id="conversation-1",
            owner="worker-1",
            expires_at=NOW + timedelta(seconds=30),
            fencing_token=1,
        )

    def renew(self, **_: object) -> bool:
        return True

    def release(self, **_: object) -> bool:
        return True


class BusyLockRepository(FakeLockRepository):
    def acquire(self, **_: object) -> None:
        return None


class FakeProcessor:
    def __init__(self, *, fail_after_upsert: bool = False) -> None:
        self.fail_after_upsert = fail_after_upsert
        self.upserted = False

    def run(self, *, before_upsert: object, **_: object) -> None:
        before_upsert()  # type: ignore[operator]
        self.upserted = True
        if self.fail_after_upsert:
            raise RuntimeError("failure after Qdrant upsert")


class ResumedConversationProcessor:
    def run(self, **_: object) -> None:
        raise ConversationNotEndedError("conversation resumed")


def _worker(
    repository: FakeJobRepository, queue: FakeQueue, processor: FakeProcessor
) -> SummaryJobWorker:
    return SummaryJobWorker(
        repository=repository,  # type: ignore[arg-type]
        conversation_locks=FakeLockRepository(),  # type: ignore[arg-type]
        queue=queue,  # type: ignore[arg-type]
        processor=processor,  # type: ignore[arg-type]
        settings=SummaryJobWorkerSettings(
            worker_id="worker-1", clock=lambda: NOW, lease_seconds=30
        ),
    )


def test_worker_completes_only_after_processor_and_then_acks_stream_entry() -> None:
    repository = FakeJobRepository()
    queue = FakeQueue()
    processor = FakeProcessor()

    assert _worker(repository, queue, processor).run_once(block_ms=0) == 1

    assert processor.upserted
    assert repository.events.index("complete") > repository.events.index("renew")
    assert queue.acks == ["1-0"]


def test_failure_after_qdrant_write_schedules_durable_retry_before_ack() -> None:
    repository = FakeJobRepository()
    queue = FakeQueue()
    processor = FakeProcessor(fail_after_upsert=True)

    _worker(repository, queue, processor).run_once(block_ms=0)

    assert processor.upserted
    assert repository.events.index("retry") > repository.events.index("renew")
    assert queue.acks == ["1-0"]


def test_worker_does_not_process_two_jobs_for_same_conversation_concurrently() -> None:
    repository = FakeJobRepository()
    queue = FakeQueue()
    processor = FakeProcessor()
    worker = SummaryJobWorker(
        repository=repository,  # type: ignore[arg-type]
        conversation_locks=BusyLockRepository(),  # type: ignore[arg-type]
        queue=queue,  # type: ignore[arg-type]
        processor=processor,  # type: ignore[arg-type]
        settings=SummaryJobWorkerSettings(
            worker_id="worker-1", clock=lambda: NOW, lease_seconds=30
        ),
    )

    worker.run_once(block_ms=0)

    assert not processor.upserted
    assert "retry" in repository.events
    assert queue.acks == ["1-0"]


def test_job_is_superseded_if_the_conversation_was_resumed() -> None:
    repository = FakeJobRepository()
    queue = FakeQueue()
    worker = _worker(
        repository,
        queue,
        ResumedConversationProcessor(),  # type: ignore[arg-type]
    )

    worker.run_once(block_ms=0)

    assert "superseded" in repository.events
    assert "retry" not in repository.events
    assert queue.acks == ["1-0"]
