from __future__ import annotations

from typing import Protocol

from src.api.schemas.conversation_delete import ConversationDeleteResponse
from src.memory.summary_job_repository import SummaryJob
from src.memory.summary_scheduler import ConversationDeletionScheduler


class CheckpointCleanup(Protocol):
    def delete_thread(self, thread_id: str) -> None: ...


class ConversationDeleteService:
    def __init__(
        self,
        *,
        scheduler: ConversationDeletionScheduler,
        checkpoint_cleanup: CheckpointCleanup,
    ) -> None:
        self._scheduler = scheduler
        self._checkpoint_cleanup = checkpoint_cleanup

    def delete(
        self,
        *,
        conversation_id: str,
        email: str,
        request_id: str | None = None,
    ) -> ConversationDeleteResponse:
        conversation_id = conversation_id.strip()
        email = email.strip()
        if not conversation_id or not email:
            raise ValueError("conversation_id e email são obrigatórios")

        job = self._scheduler.delete_and_schedule(
            conversation_id=conversation_id,
            email=email,
            request_id=request_id,
        )
        try:
            self._checkpoint_cleanup.delete_thread(conversation_id)
        except Exception:
            # Checkpoints are ephemeral; cleanup must not undo the durable job.
            pass
        return self._response(conversation_id=conversation_id, job=job)

    @staticmethod
    def _response(
        *, conversation_id: str, job: SummaryJob
    ) -> ConversationDeleteResponse:
        if job.request_id is None:
            raise RuntimeError("O job de exclusão não tem request_id estável")
        return ConversationDeleteResponse(
            conversation_id=conversation_id,
            request_id=job.request_id,
            job_id=job.job_id,
            status="deleting",
            cleanup_status=job.status,
        )
