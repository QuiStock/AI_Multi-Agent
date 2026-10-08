from __future__ import annotations

from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient

from src import api, config
from src.api.dependencies import get_trace_repository
from src.auth.errors import AccountLookupError
from src.auth.models import UserAccount
from src.main import create_app


class FakeTraceRepository:
    def save_trace(self, trace: dict[str, Any]) -> None:
        pass


class GraphSpy:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def invoke(self, state: dict[str, Any], config: Any = None) -> dict[str, Any]:
        self.calls.append(state)
        return {
            "final_response": {
                "content": "Resposta de teste.",
                "status": "success",
            }
        }


class FakeAccountRepository:
    result: UserAccount | None = UserAccount(email="person@example.test", role_id=2)
    fail = False

    def __init__(self, _: object, **__: object) -> None:
        pass

    def find_by_email(self, email: str) -> UserAccount | None:
        if self.fail:
            raise AccountLookupError
        if self.result is None:
            return None
        return UserAccount(email=email, role_id=self.result.role_id)


JWT_SECRET = "a-long-test-only-shared-secret-for-hs256"


def _compact_jwt(email: str = "person@example.test") -> str:
    return jwt.encode({"email": email, "role_id": 1}, JWT_SECRET, algorithm="HS256")


def _setup(
    monkeypatch: pytest.MonkeyPatch,
    *,
    role_id: int = 2,
    missing_account: bool = False,
    database_error: bool = False,
) -> tuple[Any, GraphSpy]:
    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: config.Settings(jwt_secret=JWT_SECRET),
    )
    FakeAccountRepository.result = (
        None
        if missing_account
        else UserAccount(email="person@example.test", role_id=role_id)
    )
    FakeAccountRepository.fail = database_error
    monkeypatch.setattr(
        "src.api.dependencies.PostgresAccountRepository", FakeAccountRepository
    )
    graph = GraphSpy()
    app = create_app()
    app.state.postgres_pool = object()
    app.dependency_overrides[api.dependencies.get_graph] = lambda: graph
    app.dependency_overrides[get_trace_repository] = FakeTraceRepository
    return app, graph


def test_missing_bearer_returns_401_without_running_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, graph = _setup(monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/conversations/conversation-1/messages",
            json={"message": "hello", "sent_at": "2026-09-22T14:30:00-03:00"},
        )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert graph.calls == []


def test_malformed_jwt_returns_401_without_running_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, graph = _setup(monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/conversations/conversation-1/messages",
            headers={"Authorization": "Bearer not-a-jwt"},
            json={"message": "hello", "sent_at": "2026-09-22T14:30:00-03:00"},
        )

    assert response.status_code == 401
    assert graph.calls == []


@pytest.mark.parametrize(
    ("role_id", "missing_account", "database_error", "expected_status"),
    [(1, False, False, 403), (2, True, False, 401), (2, False, True, 500)],
)
def test_authentication_failures_do_not_enter_graph(
    monkeypatch: pytest.MonkeyPatch,
    role_id: int,
    missing_account: bool,
    database_error: bool,
    expected_status: int,
) -> None:
    app, graph = _setup(
        monkeypatch,
        role_id=role_id,
        missing_account=missing_account,
        database_error=database_error,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/conversations/conversation-1/messages",
            headers={"Authorization": f"Bearer {_compact_jwt()}"},
            json={"message": "hello", "sent_at": "2026-09-22T14:30:00-03:00"},
        )

    assert response.status_code == expected_status
    assert graph.calls == []


def test_valid_jwt_email_becomes_graph_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, graph = _setup(monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/conversations/conversation-1/messages",
            headers={"Authorization": f"Bearer {_compact_jwt()}"},
            json={"message": "hello", "sent_at": "2026-09-22T14:30:00-03:00"},
        )

    assert response.status_code == 200
    assert graph.calls[0]["request"]["email"] == "person@example.test"


def test_client_email_or_user_id_cannot_be_sent_as_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, graph = _setup(monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/conversations/conversation-1/messages",
            headers={"Authorization": f"Bearer {_compact_jwt()}"},
            json={
                "email": "attacker@example.test",
                "user_id": "attacker",
                "message": "hello",
                "sent_at": "2026-09-22T14:30:00-03:00",
            },
        )

    assert response.status_code == 422
    assert graph.calls == []
