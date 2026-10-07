from datetime import UTC, datetime

from src.api.services.conversation_delete_service import ConversationDeleteService
from src.memory.summary_job_repository import SummaryJob
from src.memory.summary_scheduler import ConversationDeletionScheduler

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)


def job(status: str = "queued") -> SummaryJob:
    return SummaryJob(
        job_id="delete-job-1",
        conversation_id="conversation-1",
        email="user@example.com",
        closure_key="delete:request-1",
        request_id="request-1",
        operation="delete",
        status=status,  # type: ignore[arg-type]
        created_at=NOW,
        updated_at=NOW,
    )


class FakeConversationRepository:
    def __init__(self, *, marked: bool = True) -> None:
        self.marked = marked
        self.calls: list[dict[str, str]] = []

    def mark_deleting(self, **kwargs: str) -> bool:
        self.calls.append(kwargs)
        return self.marked


class FakeJobRepository:
    def __init__(self, existing: SummaryJob | None = None) -> None:
        self.existing = existing
        self.created: dict[str, object] | None = None

    def find_latest_for_conversation(self, **_: object) -> SummaryJob | None:
        return self.existing

    def create_or_get(self, **kwargs: object) -> SummaryJob:
        self.created = kwargs
        return job()

    def mark_published(self, **_: object) -> bool:
        return True


class FakeQueue:
    def __init__(self) -> None:
        self.published: list[str] = []

    def publish(self, job_id: str) -> str:
        self.published.append(job_id)
        return "1-0"


class FakeCheckpoint:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete_thread(self, thread_id: str) -> None:
        self.deleted.append(thread_id)


def test_delete_marks_owned_conversation_and_enqueues_durable_cleanup() -> None:
    conversations = FakeConversationRepository()
    jobs = FakeJobRepository()
    queue = FakeQueue()
    scheduler = ConversationDeletionScheduler(
        conversations=conversations,  # type: ignore[arg-type]
        jobs=jobs,  # type: ignore[arg-type]
        queue=queue,  # type: ignore[arg-type]
        clock=lambda: NOW,
    )
    checkpoint = FakeCheckpoint()
    response = ConversationDeleteService(
        scheduler=scheduler,
        checkpoint_cleanup=checkpoint,
    ).delete(conversation_id="conversation-1", email="user@example.com")

    assert response.status == "deleting"
    assert response.cleanup_status == "queued"
    assert conversations.calls == [
        {"conversation_id": "conversation-1", "email": "user@example.com"}
    ]
    assert jobs.created is not None
    assert jobs.created["operation"] == "delete"
    assert queue.published == ["delete-job-1"]
    assert checkpoint.deleted == ["conversation-1"]


def test_delete_replays_completed_tombstone_without_requiring_document() -> None:
    conversations = FakeConversationRepository(marked=False)
    jobs = FakeJobRepository(existing=job(status="completed"))
    scheduler = ConversationDeletionScheduler(
        conversations=conversations,  # type: ignore[arg-type]
        jobs=jobs,  # type: ignore[arg-type]
        queue=FakeQueue(),  # type: ignore[arg-type]
        clock=lambda: NOW,
    )

    response = ConversationDeleteService(
        scheduler=scheduler,
        checkpoint_cleanup=FakeCheckpoint(),
    ).delete(conversation_id="conversation-1", email="user@example.com")

    assert response.job_id == "delete-job-1"
    assert response.cleanup_status == "completed"
