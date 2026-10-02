from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi.testclient import TestClient

from src.api.controllers.conversation_end_controller import ConversationEndController
from src.api.dependencies import (
    get_authenticated_principal,
    get_conversation_end_controller,
)
from src.api.services.conversation_end_service import ConversationEndService
from src.auth.models import AuthenticatedPrincipal
from src.main import create_app
from src.memory.mongo_repository import ConversationNotFoundError
from src.memory.summary_jobs import SummaryJob

NOW = datetime(2026, 9, 22, 17, 30, tzinfo=timezone.utc)


class FakeScheduler:
    def __init__(self, *, status: str = "queued") -> None:
        self.calls: list[dict[str, str]] = []
        self.job = SummaryJob(
            job_id="job-1",
            conversation_id="conversation-1",
            email="user-1",
            closure_key="closure-1",
            request_id="stable-request-1",
            status=status,  # type: ignore[arg-type]
            attempts=0,
            created_at=NOW,
            updated_at=NOW,
        )

    def end_and_schedule(self, **kwargs: str) -> SummaryJob:
        self.calls.append(kwargs)
        if kwargs["email"] != "user-1":
            raise ConversationNotFoundError(kwargs["conversation_id"])
        return self.job


class FakeCheckpoint:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete_thread(self, thread_id: str) -> None:
        self.deleted.append(thread_id)


def _controller(
    *, status: str = "queued"
) -> tuple[ConversationEndController, FakeScheduler, FakeCheckpoint]:
    scheduler = FakeScheduler(status=status)
    checkpoint = FakeCheckpoint()
    controller = ConversationEndController(
        ConversationEndService(
            scheduler=scheduler,  # type: ignore[arg-type]
            checkpoint_cleanup=checkpoint,
        )
    )
    return controller, scheduler, checkpoint


def _post_end(app: Any, *, body: dict[str, str] | None = None) -> Any:
    with TestClient(app) as client:
        return client.post("/api/v1/conversations/conversation-1/end", json=body)


def _override_principal(app: Any, email: str = "user-1") -> None:
    app.dependency_overrides[get_authenticated_principal] = lambda: (
        AuthenticatedPrincipal(email=email, role_id=2)
    )


def test_end_conversation_returns_202_after_durable_scheduling() -> None:
    controller, scheduler, checkpoint = _controller()
    app = create_app()
    app.dependency_overrides[get_conversation_end_controller] = lambda: controller
    _override_principal(app)

    response = _post_end(app)

    app.dependency_overrides.clear()
    assert response.status_code == 202
    assert response.json() == {
        "conversation_id": "conversation-1",
        "request_id": "stable-request-1",
        "job_id": "job-1",
        "status": "ended",
        "summary_status": "queued",
    }
    assert scheduler.calls == [{"conversation_id": "conversation-1", "email": "user-1"}]
    assert checkpoint.deleted == ["conversation-1"]


def test_repeated_end_returns_the_same_durable_job_idempotently() -> None:
    controller, scheduler, _ = _controller()
    app = create_app()
    app.dependency_overrides[get_conversation_end_controller] = lambda: controller
    _override_principal(app)

    first = _post_end(app)
    second = _post_end(app)

    app.dependency_overrides.clear()
    assert first.status_code == second.status_code == 202
    assert first.json()["job_id"] == second.json()["job_id"] == "job-1"
    assert first.json()["request_id"] == second.json()["request_id"]
    assert len(scheduler.calls) == 2


def test_end_response_reports_current_durable_job_state() -> None:
    controller, _, _ = _controller(status="completed")
    app = create_app()
    app.dependency_overrides[get_conversation_end_controller] = lambda: controller
    _override_principal(app)

    response = _post_end(app)

    app.dependency_overrides.clear()
    assert response.status_code == 202
    assert response.json()["summary_status"] == "completed"


def test_end_conversation_does_not_need_identity_in_body() -> None:
    app = create_app()
    controller, _, _ = _controller()
    app.dependency_overrides[get_conversation_end_controller] = lambda: controller
    _override_principal(app)

    response = _post_end(app)

    app.dependency_overrides.clear()
    assert response.status_code == 202


def test_end_conversation_does_not_cross_user_boundary() -> None:
    app = create_app()
    controller, _, _ = _controller()
    app.dependency_overrides[get_conversation_end_controller] = lambda: controller

    _override_principal(app, email="other-user")
    response = _post_end(app)

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"
