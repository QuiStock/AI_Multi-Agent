from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from src import api, config
from src.auth.errors import (
    AccountLookupError,
    AuthenticationDependencyError,
    InvalidCredentialError,
)
from src.auth.models import UserAccount, VerifiedToken
from src.main import create_app


class GraphSpy:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def invoke(self, state: dict[str, Any], config: Any = None) -> dict[str, Any]:
        self.calls.append(state)
        return {
            "final_response": {"content": "Resposta de teste.", "status": "success"}
        }


class FakeDecoder:
    fail: Exception | None = None
    identity = VerifiedToken(user_id=42, email="person@example.test")

    def decode_identity(self, token: str) -> VerifiedToken:
        if self.fail is not None:
            raise self.fail
        if token != "valid-token":
            raise InvalidCredentialError
        return self.identity


class FakeAccountRepository:
    result: UserAccount | None = None
    fail = False
    looked_up_id: int | None = None

    def __init__(self, _: object, **__: object) -> None:
        pass

    def find_by_id(self, user_id: int) -> UserAccount | None:
        type(self).looked_up_id = user_id
        if self.fail:
            raise AccountLookupError
        return self.result


def _setup(
    monkeypatch: pytest.MonkeyPatch,
    *,
    role_code: str = "MANAGER",
    missing_account: bool = False,
    database_error: bool = False,
    account_status: str = "ACTIVE",
    account_email: str = "person@example.test",
    store_ids: tuple[int, ...] = (4, 9),
    decoder_error: Exception | None = None,
) -> tuple[Any, GraphSpy]:
    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: config.Settings(
            jwt_issuer="https://auth.example.test",
            jwt_jwks_url="https://auth.example.test/jwks",
        ),
    )
    FakeDecoder.fail = decoder_error
    FakeDecoder.identity = VerifiedToken(user_id=42, email="person@example.test")
    FakeAccountRepository.result = (
        None
        if missing_account
        else UserAccount(42, account_email, role_code, account_status, store_ids)
    )
    FakeAccountRepository.fail = database_error
    FakeAccountRepository.looked_up_id = None
    monkeypatch.setattr(
        "src.api.dependencies.get_jwt_decoder", lambda *_: FakeDecoder()
    )
    monkeypatch.setattr(
        "src.api.dependencies.PostgresAccountRepository", FakeAccountRepository
    )
    monkeypatch.setattr("src.api.dependencies.get_postgres_pool", lambda _: object())
    graph = GraphSpy()
    app = create_app()
    app.state.postgres_pool = object()
    app.dependency_overrides[api.dependencies.get_graph] = lambda: graph
    return app, graph


def _post(app: Any, token: str | None = "valid-token") -> Any:
    headers = {} if token is None else {"Authorization": f"Bearer {token}"}
    with TestClient(app) as client:
        return client.post(
            "/api/v1/conversations/conversation-1/messages",
            headers=headers,
            json={"message": "hello", "sent_at": "2026-09-22T14:30:00-03:00"},
        )


def test_missing_or_invalid_bearer_returns_401_without_running_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, graph = _setup(monkeypatch)
    for token in (None, "not-a-jwt"):
        response = _post(app, token)
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
    assert graph.calls == []


@pytest.mark.parametrize(
    ("options", "expected_status"),
    [
        ({"role_code": "REGIONAL_MANAGER"}, 403),
        ({"role_code": "UNKNOWN"}, 403),
        ({"missing_account": True}, 401),
        ({"database_error": True}, 500),
        ({"account_status": "INACTIVE"}, 401),
        ({"account_email": "other@example.test"}, 401),
        ({"store_ids": ()}, 403),
        ({"decoder_error": AuthenticationDependencyError()}, 503),
    ],
)
def test_authentication_failures_do_not_enter_graph(
    monkeypatch: pytest.MonkeyPatch,
    options: dict[str, Any],
    expected_status: int,
) -> None:
    app, graph = _setup(monkeypatch, **options)
    assert _post(app).status_code == expected_status
    assert graph.calls == []


@pytest.mark.parametrize("role_code", ["MANAGER", "EMPLOYEE"])
def test_verified_sub_email_role_and_stores_enter_graph(
    monkeypatch: pytest.MonkeyPatch,
    role_code: str,
) -> None:
    app, graph = _setup(monkeypatch, role_code=role_code)
    assert _post(app).status_code == 200
    assert FakeAccountRepository.looked_up_id == 42
    assert graph.calls[0]["request"]["user_id"] == 42
    assert graph.calls[0]["request"]["email"] == "person@example.test"
    assert graph.calls[0]["request"]["role_code"] == role_code
    assert graph.calls[0]["request"]["store_ids"] == [4, 9]


def test_client_cannot_supply_identity_in_body(monkeypatch: pytest.MonkeyPatch) -> None:
    app, graph = _setup(monkeypatch)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/conversations/conversation-1/messages",
            headers={"Authorization": "Bearer valid-token"},
            json={
                "email": "attacker@example.test",
                "user_id": 99,
                "store_ids": [99],
                "message": "hello",
                "sent_at": "2026-09-22T14:30:00-03:00",
            },
        )
    assert response.status_code == 422
    assert graph.calls == []
