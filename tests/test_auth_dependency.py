from __future__ import annotations

import time
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
    result: UserAccount | None = UserAccount(
        user_id=7,
        email="person@example.test",
        role_code="MANAGER",
        store_ids=(30,),
    )
    fail = False

    def __init__(self, _: object, **__: object) -> None:
        pass

    def find_by_email(self, email: str) -> UserAccount | None:
        if self.fail:
            raise AccountLookupError
        if self.result is None or self.result.email != email:
            return None
        return self.result


JWT_SECRET = "a-long-test-only-shared-secret-for-hs256"


def _compact_jwt(email: str = "person@example.test") -> str:
    return jwt.encode(
        {"email": email, "role_id": 1, "exp": int(time.time()) + 300},
        JWT_SECRET,
        algorithm="HS256",
    )


def _account(
    role_code: str = "MANAGER",
    store_ids: tuple[int, ...] = (30,),
) -> UserAccount:
    return UserAccount(
        user_id=7,
        email="person@example.test",
        role_code=role_code,
        store_ids=store_ids,
    )


def _setup(
    monkeypatch: pytest.MonkeyPatch,
    *,
    account: UserAccount | None = None,
    missing_account: bool = False,
    database_error: bool = False,
) -> tuple[Any, GraphSpy]:
    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: config.Settings(jwt_secret=JWT_SECRET, auth_jwt_algorithm="HS256"),
    )
    if missing_account:
        FakeAccountRepository.result = None
    elif account is None:
        FakeAccountRepository.result = _account()
    else:
        FakeAccountRepository.result = account
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
    ("account", "missing_account", "database_error", "expected_status"),
    [
        (_account("REGIONAL_MANAGER"), False, False, 403),
        (_account("AUDITOR"), False, False, 403),
        (_account("MANAGER", ()), False, False, 403),
        (_account("EMPLOYEE", (30, 32)), False, False, 403),
        (None, True, False, 401),
        (_account(), False, True, 500),
    ],
)
def test_authentication_failures_do_not_enter_graph(
    monkeypatch: pytest.MonkeyPatch,
    account: UserAccount | None,
    missing_account: bool,
    database_error: bool,
    expected_status: int,
) -> None:
    app, graph = _setup(
        monkeypatch,
        account=account,
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


@pytest.mark.parametrize("role_code", ["MANAGER", "EMPLOYEE"])
def test_valid_jwt_carries_role_code_and_the_single_store(
    monkeypatch: pytest.MonkeyPatch,
    role_code: str,
) -> None:
    app, graph = _setup(monkeypatch, account=_account(role_code, (30,)))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/conversations/conversation-1/messages",
            headers={"Authorization": f"Bearer {_compact_jwt()}"},
            json={"message": "hello", "sent_at": "2026-09-22T14:30:00-03:00"},
        )

    assert response.status_code == 200
    request = graph.calls[0]["request"]
    assert request["email"] == "person@example.test"
    assert request["user_id"] == 7
    assert request["role_code"] == role_code
    assert request["store_ids"] == [30]
    assert "role_id" not in request


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
