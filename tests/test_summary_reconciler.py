from datetime import UTC, datetime

from src.memory.contracts import ConversationSummarySnapshot, StoredMessage
from src.memory.summary_job_repository import SummaryJob
from src.memory.summary_reconciler import SummaryReconciler

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)


def snapshot(
    conversation_id: str, *, email: str = "user@example.com"
) -> ConversationSummarySnapshot:
    return ConversationSummarySnapshot(
        conversation_id=conversation_id,
        email=email,
        title=None,
        status="ended",
        summary=None,
        summary_version=0,
        summarized_through_message_id=None,
        messages=[
            StoredMessage(
                message_id="message-1",
                role="user",
                content="Olá",
                created_at=NOW,
            )
        ],
        updated_at=NOW,
    )


class FakeConversations:
    def __init__(self) -> None:
        self.snapshots = [snapshot("conversation-1")]

    def list_ended_summary_snapshots(
        self, *, limit: int
    ) -> list[ConversationSummarySnapshot]:
        return self.snapshots[:limit]

    def list_conversation_states(self, *, limit: int) -> dict[str, str]:
        return {"conversation-1": "ended", "conversation-2": "active"}


class FakeIndexer:
    def __init__(self) -> None:
        self.points = {
            "conversation-1": {
                "conversation_id": "conversation-1",
                "email": "user@example.com",
                "summarized_through_message_id": "message-1",
            },
            "conversation-2": {
                "conversation_id": "conversation-2",
                "email": "user@example.com",
                "summarized_through_message_id": "message-1",
            },
        }
        self.deleted: list[str] = []

    def get(self, conversation_id: str) -> dict[str, object] | None:
        return self.points.get(conversation_id)

    def list_summary_payloads(self, *, limit: int) -> list[dict[str, object]]:
        return list(self.points.values())[:limit]

    def delete(self, conversation_id: str) -> None:
        self.deleted.append(conversation_id)
        self.points.pop(conversation_id, None)


class FakeScheduler:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def end_and_schedule(self, *, conversation_id: str, email: str) -> SummaryJob:
        self.calls.append((conversation_id, email))
        return SummaryJob(
            job_id="job-1",
            conversation_id=conversation_id,
            email=email,
            closure_key="closure-1",
            created_at=NOW,
            updated_at=NOW,
        )


def test_reconciler_removes_points_for_active_conversations() -> None:
    indexer = FakeIndexer()
    reconciler = SummaryReconciler(
        conversations=FakeConversations(),  # type: ignore[arg-type]
        indexer=indexer,  # type: ignore[arg-type]
        scheduler=FakeScheduler(),  # type: ignore[arg-type]
    )

    report = reconciler.reconcile()

    assert report.scanned_conversations == 1
    assert report.scheduled_jobs == 0
    assert report.deleted_orphan_points == 1
    assert indexer.deleted == ["conversation-2"]


def test_reconciler_schedules_missing_point() -> None:
    conversations = FakeConversations()
    indexer = FakeIndexer()
    indexer.points.pop("conversation-1")
    scheduler = FakeScheduler()
    report = SummaryReconciler(
        conversations=conversations,  # type: ignore[arg-type]
        indexer=indexer,  # type: ignore[arg-type]
        scheduler=scheduler,  # type: ignore[arg-type]
    ).reconcile()

    assert report.scheduled_jobs == 1
    assert scheduler.calls == [("conversation-1", "user@example.com")]
