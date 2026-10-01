from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from uuid import NAMESPACE_URL, uuid5

from src.memory.summary_job_repository import MongoSummaryJobRepository
from src.memory.summary_jobs import SummaryJob, retry_delay_seconds
from src.memory.summary_queue import RedisSummaryQueue, SummaryJobOutboxRelay
from src.memory.summary_scheduler import ConversationSummaryScheduler

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _job_document() -> dict[str, object]:
    return {
        "_id": str(uuid5(NAMESPACE_URL, 'summary-job:["conversation-1","close-1"]')),
        "conversation_id": "conversation-1",
        "user_id": "user-1",
        "closure_key": "close-1",
        "request_id": "request-1",
        "status": "queued",
        "attempts": 0,
        "max_attempts": 5,
        "created_at": NOW,
        "updated_at": NOW,
        "published_at": None,
        "next_attempt_at": NOW,
        "lease_owner": None,
        "lease_until": None,
        "last_error": None,
    }


def test_retry_delay_grows_exponentially_and_is_bounded() -> None:
    assert [retry_delay_seconds(n) for n in range(1, 7)] == [2, 4, 8, 16, 32, 64]
    assert retry_delay_seconds(20, max_seconds=60) == 60


def test_job_contract_rejects_summary_content() -> None:
    document = _job_document()
    document["summary"] = "private conversation summary"

    try:
        SummaryJob.model_validate({**document, "job_id": document.pop("_id")})
    except ValueError:
        pass
    else:
        raise AssertionError("Job must reject summary content")


def test_create_or_get_uses_the_stable_conversation_closure_key() -> None:
    collection = Mock()
    collection.find_one.return_value = _job_document()
    repository = MongoSummaryJobRepository(collection)

    first = repository.create_or_get(
        conversation_id="conversation-1",
        user_id="user-1",
        closure_key="close-1",
        request_id="request-1",
        now=NOW,
    )
    second = repository.create_or_get(
        conversation_id="conversation-1",
        user_id="user-1",
        closure_key="close-1",
        request_id="request-1",
        now=NOW,
    )

    expected_id = _job_document()["_id"]
    assert first.job_id == second.job_id == expected_id
    assert collection.update_one.call_args.args[0] == {
        "conversation_id": "conversation-1",
        "closure_key": "close-1",
    }
    assert collection.update_one.call_args.kwargs["upsert"] is True
    assert "summary" not in collection.update_one.call_args.args[1]["$setOnInsert"]


def test_claim_sets_a_bounded_lease_and_increments_attempts() -> None:
    collection = Mock()
    collection.find_one_and_update.return_value = _job_document()
    repository = MongoSummaryJobRepository(collection)

    job = repository.claim(
        job_id=str(_job_document()["_id"]),
        worker_id="worker-1",
        now=NOW,
        lease_seconds=60,
    )

    assert job is not None
    query, update = collection.find_one_and_update.call_args.args[:2]
    assert query["_id"] == job.job_id
    assert update["$inc"] == {"attempts": 1}
    assert update["$set"]["lease_until"] == NOW + timedelta(seconds=60)


def test_retry_persists_only_safe_error_code_and_republishes_when_due() -> None:
    collection = Mock()
    collection.update_one.return_value = Mock(modified_count=1)
    repository = MongoSummaryJobRepository(collection)
    data = _job_document()
    job_id = data.pop("_id")
    job = SummaryJob.model_validate({**data, "job_id": job_id, "attempts": 1})

    state = repository.schedule_retry(
        job=job,
        worker_id="worker-1",
        now=NOW,
        delay_seconds=4,
        safe_error_code="TemporaryFailure",
    )

    update = collection.update_one.call_args.args[1]
    assert state == "queued"
    assert update["$set"]["last_error"] == "TemporaryFailure"
    assert update["$set"]["next_attempt_at"] == NOW + timedelta(seconds=4)
    assert update["$set"]["published_at"] is None
    assert "summary" not in update["$set"]


def test_exhausted_job_becomes_terminal_and_can_be_explicitly_requeued() -> None:
    collection = Mock()
    collection.update_one.return_value = Mock(modified_count=1)
    repository = MongoSummaryJobRepository(collection)
    values = _job_document()
    job_id = values.pop("_id")
    job = SummaryJob.model_validate(
        {**values, "job_id": job_id, "status": "processing", "attempts": 5}
    )

    state = repository.schedule_retry(
        job=job,
        worker_id="worker-1",
        now=NOW,
        delay_seconds=32,
        safe_error_code="TemporaryFailure",
    )
    terminal_update = collection.update_one.call_args.args[1]
    requeued = repository.requeue_failed(job_id=job.job_id, now=NOW)
    requeue_update = collection.update_one.call_args.args[1]

    assert state == "failed"
    assert terminal_update["$set"]["status"] == "failed"
    assert "next_attempt_at" not in terminal_update["$set"]
    assert requeued
    assert requeue_update["$set"]["status"] == "queued"
    assert requeue_update["$set"]["attempts"] == 0
    assert requeue_update["$set"]["published_at"] is None


class FakeStreamClient:
    def __init__(self) -> None:
        self.entries: list[tuple[str, dict[str, str]]] = []
        self.pending: list[dict[str, object]] = []
        self.claimed: list[tuple[str, dict[str, str]]] = []

    def xadd(self, stream: str, fields: dict[str, str]) -> str:
        self.entries.append((stream, fields))
        return f"{len(self.entries)}-0"

    def xpending_range(self, *_: object, **__: object) -> list[dict[str, object]]:
        return self.pending

    def xclaim(self, *_: object) -> list[tuple[str, dict[str, str]]]:
        return self.claimed


def test_redis_stream_carries_only_the_durable_job_id() -> None:
    client = FakeStreamClient()
    queue = RedisSummaryQueue(client, stream_name="summary-jobs")

    queue.publish("job-123")

    assert client.entries == [("summary-jobs", {"job_id": "job-123"})]


def test_redis_reclaims_only_pending_entries_past_the_idle_threshold() -> None:
    client = FakeStreamClient()
    client.pending = [
        {"message_id": "1-0", "time_since_delivered": 5_000},
        {"message_id": "2-0", "time_since_delivered": 500},
    ]
    client.claimed = [("1-0", {"job_id": "job-123"})]
    queue = RedisSummaryQueue(client, stream_name="summary-jobs")

    entries = queue.reclaim_pending(consumer="worker-1", min_idle_ms=1_000)

    assert entries == [("1-0", "job-123")]


def test_backend_closure_key_is_deterministic_for_the_same_request() -> None:
    make_key = ConversationSummaryScheduler.closure_key_for_request

    first = make_key(conversation_id="conversation-1", request_id="request-1")
    retry = make_key(conversation_id="conversation-1", request_id="request-1")
    next_close = make_key(conversation_id="conversation-1", request_id="request-2")

    assert first == retry
    assert first != next_close


def test_scheduler_derives_stable_backend_request_and_closure_ids() -> None:
    class Conversations:
        def mark_ended(self, **_: object) -> datetime:
            return NOW

    class Jobs:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def create_or_get(self, **kwargs: object) -> SummaryJob:
            self.calls.append(kwargs)
            job_data = _job_document()
            job_data.pop("_id")
            return SummaryJob.model_validate(
                {
                    **job_data,
                    "job_id": "stable-job",
                    "request_id": kwargs["request_id"],
                    "closure_key": kwargs["closure_key"],
                }
            )

        def mark_published(self, **_: object) -> bool:
            return True

    class Queue:
        def publish(self, _: str) -> str:
            return "1-0"

    jobs = Jobs()
    scheduler = ConversationSummaryScheduler(
        conversations=Conversations(),  # type: ignore[arg-type]
        jobs=jobs,  # type: ignore[arg-type]
        queue=Queue(),  # type: ignore[arg-type]
        clock=lambda: NOW,
    )

    first = scheduler.end_and_schedule(
        conversation_id="conversation-1", user_id="user-1"
    )
    retry = scheduler.end_and_schedule(
        conversation_id="conversation-1", user_id="user-1"
    )

    assert first.request_id == retry.request_id
    assert first.closure_key == retry.closure_key
    assert jobs.calls[0]["request_id"] == jobs.calls[1]["request_id"]
    assert jobs.calls[0]["closure_key"] == jobs.calls[1]["closure_key"]


def test_outbox_republishes_jobs_not_recorded_as_published() -> None:
    job_data = _job_document()
    job_data.pop("_id")
    job = SummaryJob.model_validate({**job_data, "job_id": "job-123"})

    class OutboxRepository:
        def __init__(self) -> None:
            self.marked: list[str] = []

        def find_unpublished(self, **_: object) -> list[SummaryJob]:
            return [job]

        def mark_published(self, *, job_id: str, published_at: datetime) -> bool:
            self.marked.append(job_id)
            return True

    repository = OutboxRepository()
    client = FakeStreamClient()
    relay = SummaryJobOutboxRelay(
        repository=repository,  # type: ignore[arg-type]
        queue=RedisSummaryQueue(client, stream_name="summary-jobs"),
        clock=lambda: NOW,
    )

    assert relay.publish_due() == 1
    assert client.entries == [("summary-jobs", {"job_id": "job-123"})]
    assert repository.marked == ["job-123"]


def test_scheduler_keeps_job_durable_when_redis_publish_fails() -> None:
    job_data = _job_document()
    job_data.pop("_id")
    job = SummaryJob.model_validate({**job_data, "job_id": "job-123"})

    class Conversations:
        ended: bool = False

        def mark_ended(self, **_: object) -> None:
            self.ended = True

    class Jobs:
        created: bool = False
        created_args: dict[str, object] = {}

        def create_or_get(self, **_: object) -> SummaryJob:
            self.created = True
            self.created_args = _
            return job

        def mark_published(self, **_: object) -> bool:
            return True

    class FailedQueue:
        def publish(self, _: str) -> str:
            raise ConnectionError("no connection")

    conversations = Conversations()
    jobs = Jobs()
    scheduler = ConversationSummaryScheduler(
        conversations=conversations,  # type: ignore[arg-type]
        jobs=jobs,  # type: ignore[arg-type]
        queue=FailedQueue(),  # type: ignore[arg-type]
        clock=lambda: NOW,
    )

    result = scheduler.end_and_schedule(
        conversation_id="conversation-1",
        user_id="user-1",
        request_id="request-1",
    )

    assert result.job_id == "job-123"
    assert conversations.ended
    assert jobs.created
    assert jobs.created_args["closure_key"] == (
        ConversationSummaryScheduler.closure_key_for_request(
            conversation_id="conversation-1", request_id="request-1"
        )
    )
