from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi.testclient import TestClient

from src.api.controllers.conversation_end_controller import ConversationEndController
from src.api.dependencies import get_conversation_end_controller
from src.api.services.conversation_end_service import ConversationEndService
from src.main import create_app
from src.memory.mongo_repository import ConversationNotFoundError
from src.memory.summary_jobs import SummaryJob
from src.memory.summary_queue import SummaryQueueError


class FakeConversationRepository:
    def __init__(self) -> None:
        self.status = "active"
        self.ended_at = datetime(2026, 9, 22, 17, 30, tzinfo=timezone.utc)

    def mark_ended(
        self,
        *,
        conversation_id: str,
        user_id: str,
        ended_at: datetime,
    ) -> datetime:
        assert conversation_id == "conversation-1"
        if user_id != "user-1":
            raise ConversationNotFoundError(conversation_id)
        if self.status == "active":
            self.status = "ended"
            self.ended_at = ended_at
        return self.ended_at


class FakeJobRepository:
    def __init__(self) -> None:
        self.jobs: dict[str, SummaryJob] = {}
        self.published: list[str] = []

    def create_or_get(self, **kwargs: Any) -> tuple[SummaryJob, bool]:
        existing = next(
            (
                job
                for job in self.jobs.values()
                if job.conversation_id == kwargs["conversation_id"]
                and job.closure_key == kwargs["closure_key"]
            ),
            None,
        )
        if existing is not None:
            return existing, False
        job = SummaryJob(
            job_id=kwargs["job_id"],
            conversation_id=kwargs["conversation_id"],
            user_id=kwargs["user_id"],
            closure_key=kwargs["closure_key"],
            request_id=kwargs["request_id"],
            status="queued",
            attempts=0,
            created_at=kwargs["created_at"],
            updated_at=kwargs["created_at"],
        )
        self.jobs[job.job_id] = job
        return job, True

    def mark_published(self, *, job_id: str, published_at: datetime) -> None:
        self.published.append(job_id)
        self.jobs[job_id] = self.jobs[job_id].model_copy(
            update={"published_at": published_at, "publication_claimed": False}
        )

    def claim_publication(self, *, job_id: str, updated_at: datetime) -> bool:
        job = self.jobs[job_id]
        if job.publication_claimed or job.published_at is not None:
            return False
        self.jobs[job_id] = job.model_copy(update={"publication_claimed": True})
        return True

    def release_publication(self, *, job_id: str, updated_at: datetime) -> None:
        self.jobs[job_id] = self.jobs[job_id].model_copy(
            update={"publication_claimed": False}
        )


class FakePublisher:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.jobs: list[str] = []

    def publish(self, job: SummaryJob) -> str:
        if self.fail:
            raise SummaryQueueError("redis unavailable")
        self.jobs.append(job.job_id)
        return "1-0"


class FakeCheckpoint:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete_thread(self, thread_id: str) -> None:
        self.deleted.append(thread_id)


def _controller(
    *,
    publisher: FakePublisher | None = None,
) -> tuple[
    ConversationEndController,
    FakeConversationRepository,
    FakeJobRepository,
    FakeCheckpoint,
]:
    conversation_repository = FakeConversationRepository()
    job_repository = FakeJobRepository()
    checkpoint = FakeCheckpoint()
    controller = ConversationEndController(
        ConversationEndService(
            conversation_repository=conversation_repository,  # type: ignore[arg-type]
            job_repository=job_repository,
            job_publisher=publisher or FakePublisher(),  # type: ignore[arg-type]
            checkpoint_cleanup=checkpoint,
            clock=lambda: datetime(2026, 9, 22, 17, 30, tzinfo=timezone.utc),
        )
    )
    return controller, conversation_repository, job_repository, checkpoint


def test_end_conversation_returns_202_and_queues_one_job() -> None:
    controller, repository, jobs, checkpoint = _controller()
    app = create_app()
    app.dependency_overrides[get_conversation_end_controller] = lambda: controller

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/conversations/conversation-1/end",
            json={"user_id": "user-1"},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 202
    body = response.json()
    assert body["conversation_id"] == "conversation-1"
    assert body["status"] == "ended"
    assert body["summary_status"] == "queued"
    assert repository.status == "ended"
    assert len(jobs.jobs) == 1
    assert checkpoint.deleted == ["conversation-1"]


def test_repeated_end_is_conflict_and_does_not_create_a_second_job() -> None:
    controller, _, jobs, _ = _controller()
    app = create_app()
    app.dependency_overrides[get_conversation_end_controller] = lambda: controller

    with TestClient(app) as client:
        first = client.post(
            "/api/v1/conversations/conversation-1/end",
            json={"user_id": "user-1"},
        )
        second = client.post(
            "/api/v1/conversations/conversation-1/end",
            json={"user_id": "user-1"},
        )

    app.dependency_overrides.clear()
    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "CONVERSATION_ALREADY_ENDED"
    assert len(jobs.jobs) == 1


def test_redis_failure_returns_retryable_503_without_calling_another_job() -> None:
    publisher = FakePublisher(fail=True)
    controller, _, jobs, checkpoint = _controller(publisher=publisher)
    app = create_app()
    app.dependency_overrides[get_conversation_end_controller] = lambda: controller

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/conversations/conversation-1/end",
            json={"user_id": "user-1"},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SUMMARY_QUEUE_UNAVAILABLE"
    assert len(jobs.jobs) == 1
    assert checkpoint.deleted == ["conversation-1"]


def test_end_conversation_rejects_blank_user_id() -> None:
    app = create_app()
    controller, *_ = _controller()
    app.dependency_overrides[get_conversation_end_controller] = lambda: controller

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/conversations/conversation-1/end",
            json={"user_id": " "},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 422


def test_end_conversation_does_not_cross_user_boundary() -> None:
    controller, *_ = _controller()
    app = create_app()
    app.dependency_overrides[get_conversation_end_controller] = lambda: controller

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/conversations/conversation-1/end",
            json={"user_id": "other-user"},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"
