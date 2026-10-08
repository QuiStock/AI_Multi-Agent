"""Restartable reconciliation between ended Mongo conversations and Qdrant."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .contracts import ConversationSummarySnapshot
from .summary_job_repository import SummaryJob


class ReconciliationConversationRepository(Protocol):
    def list_ended_summary_snapshots(
        self, *, limit: int
    ) -> list[ConversationSummarySnapshot]: ...

    def list_conversation_states(self, *, limit: int) -> dict[str, str]: ...


class ReconciliationIndexer(Protocol):
    def get(self, conversation_id: str) -> dict[str, object] | None: ...

    def list_summary_payloads(self, *, limit: int) -> list[dict[str, object]]: ...

    def delete(self, conversation_id: str) -> None: ...


class ReconciliationScheduler(Protocol):
    def end_and_schedule(
        self,
        *,
        conversation_id: str,
        email: str,
    ) -> SummaryJob: ...


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    scanned_conversations: int
    scheduled_jobs: int
    deleted_orphan_points: int
    invalid_points_reset: int


class SummaryReconciler:
    def __init__(
        self,
        *,
        conversations: ReconciliationConversationRepository,
        indexer: ReconciliationIndexer,
        scheduler: ReconciliationScheduler,
        batch_size: int = 100,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size precisa ser positivo")
        self._conversations = conversations
        self._indexer = indexer
        self._scheduler = scheduler
        self._batch_size = batch_size

    def reconcile(self) -> ReconciliationReport:
        snapshots = self._conversations.list_ended_summary_snapshots(
            limit=self._batch_size
        )
        states = self._conversations.list_conversation_states(limit=self._batch_size)
        scheduled = 0
        reset = 0

        for snapshot in snapshots:
            point = self._indexer.get(snapshot.conversation_id)
            if self._needs_rebuild(snapshot, point):
                if point is not None:
                    self._indexer.delete(snapshot.conversation_id)
                    reset += 1
                self._scheduler.end_and_schedule(
                    conversation_id=snapshot.conversation_id,
                    email=snapshot.email,
                )
                scheduled += 1

        ended_ids = {snapshot.conversation_id for snapshot in snapshots}
        orphaned = 0
        for payload in self._indexer.list_summary_payloads(limit=self._batch_size):
            conversation_id = payload.get("conversation_id")
            if not isinstance(conversation_id, str):
                continue
            if (
                conversation_id not in ended_ids
                or states.get(conversation_id) != "ended"
            ):
                self._indexer.delete(conversation_id)
                orphaned += 1

        return ReconciliationReport(
            scanned_conversations=len(snapshots),
            scheduled_jobs=scheduled,
            deleted_orphan_points=orphaned,
            invalid_points_reset=reset,
        )

    @staticmethod
    def _needs_rebuild(
        snapshot: ConversationSummarySnapshot,
        point: dict[str, object] | None,
    ) -> bool:
        if point is None:
            return True
        if point.get("email") != snapshot.email:
            return True
        marker = point.get("summarized_through_message_id")
        if not isinstance(marker, str):
            return True
        positions = {
            message.message_id: index for index, message in enumerate(snapshot.messages)
        }
        current_position = positions.get(marker)
        if current_position is None:
            return True
        return current_position < len(snapshot.messages) - 1
