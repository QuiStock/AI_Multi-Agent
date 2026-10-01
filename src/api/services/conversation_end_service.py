from __future__ import annotations

import logging
from typing import Protocol

from src.api.schemas.conversation_end import ConversationEndResponse
from src.memory.summary_scheduler import ConversationSummaryScheduler

logger = logging.getLogger(__name__)


class CheckpointCleanup(Protocol):
    def delete_thread(self, thread_id: str) -> None: ...


class ConversationEndService:
    def __init__(
        self,
        *,
        scheduler: ConversationSummaryScheduler,
        checkpoint_cleanup: CheckpointCleanup,
    ) -> None:
        self._scheduler = scheduler
        self._checkpoint_cleanup = checkpoint_cleanup

    def end(
        self,
        *,
        conversation_id: str,
        email: str,
    ) -> ConversationEndResponse:
        conversation_id = conversation_id.strip()
        email = email.strip()
        if not conversation_id or not email:
            raise ValueError("conversation_id e email são obrigatórios")

        job = self._scheduler.end_and_schedule(
            conversation_id=conversation_id,
            email=email,
        )
        try:
            self._checkpoint_cleanup.delete_thread(conversation_id)
        except Exception as exc:
            # Checkpoints are ephemeral; their cleanup must not undo durable close.
            logger.warning(
                "Falha ao remover checkpoint após encerramento; error_type=%s",
                type(exc).__name__,
            )
        if job.request_id is None:
            raise RuntimeError("O job persistido não tem request_id estável")
        return ConversationEndResponse(
            conversation_id=conversation_id,
            request_id=job.request_id,
            job_id=job.job_id,
            status="ended",
            summary_status=job.status,
        )
