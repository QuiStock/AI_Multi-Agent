from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from jwcrypto import jwe, jwk

from src import api, config
from src.auth.errors import AccountLookupError
from src.auth.models import UserAccount
from src.main import create_app


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


@pytest.fixture
def rsa_key() -> jwk.JWK:
    return jwk.JWK.generate(kty="RSA", size=2048)


def _compact_jwe(key: jwk.JWK, email: str = "person@example.test") -> str:
    encrypted = jwe.JWE(
        plaintext=json.dumps({"email": email, "role_id": 1}),
        protected={"alg": "RSA-OAEP-256", "enc": "A256GCM", "kid": "current"},
    )
    encrypted.add_recipient(key)
    return encrypted.serialize(compact=True)


def _setup(
    monkeypatch: pytest.MonkeyPatch,
    key: jwk.JWK,
    *,
    role_id: int = 2,
    missing_account: bool = False,
    database_error: bool = False,
) -> tuple[Any, GraphSpy]:
    keyring = json.dumps(
        {"current": key.export_to_pem(private_key=True, password=None).decode()}
    )
    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: config.Settings(jwe_private_keys_json=keyring),
    )
    decoder_module = __import__(
        "src.auth.token", fromlist=["decoder_from_json_keyring"]
    )
    decoder_module.decoder_from_json_keyring.cache_clear()
    monkeypatch.setattr(
        FakeAccountRepository,
        "result",
        None
        if missing_account
        else UserAccount(email="person@example.test", role_id=role_id),
    )
    monkeypatch.setattr(FakeAccountRepository, "fail", database_error)
    monkeypatch.setattr(
        "src.api.dependencies.PostgresAccountRepository", FakeAccountRepository
    )
    monkeypatch.setattr(
        "src.api.dependencies.get_postgres_pool", lambda request: object()
    )
    graph = GraphSpy()
    app = create_app()
    app.dependency_overrides[api.dependencies.get_graph] = lambda: graph
    return app, graph


def test_missing_bearer_returns_401_without_running_graph(
    monkeypatch: pytest.MonkeyPatch, rsa_key: jwk.JWK
) -> None:
    app, graph = _setup(monkeypatch, rsa_key)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/conversations/conversation-1/messages",
            json={"message": "hello", "sent_at": "2026-09-22T14:30:00-03:00"},
        )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert graph.calls == []


def test_malformed_jwe_returns_401_without_running_graph(
    monkeypatch: pytest.MonkeyPatch, rsa_key: jwk.JWK
) -> None:
    app, graph = _setup(monkeypatch, rsa_key)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/conversations/conversation-1/messages",
            headers={"Authorization": "Bearer not-a-jwe"},
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
    rsa_key: jwk.JWK,
    role_id: int,
    missing_account: bool,
    database_error: bool,
    expected_status: int,
) -> None:
    app, graph = _setup(
        monkeypatch,
        rsa_key,
        role_id=role_id,
        missing_account=missing_account,
        database_error=database_error,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/conversations/conversation-1/messages",
            headers={"Authorization": f"Bearer {_compact_jwe(rsa_key)}"},
            json={"message": "hello", "sent_at": "2026-09-22T14:30:00-03:00"},
        )

    assert response.status_code == expected_status
    assert graph.calls == []


def test_valid_jwe_email_becomes_graph_identity(
    monkeypatch: pytest.MonkeyPatch, rsa_key: jwk.JWK
) -> None:
    app, graph = _setup(monkeypatch, rsa_key)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/conversations/conversation-1/messages",
            headers={"Authorization": f"Bearer {_compact_jwe(rsa_key)}"},
            json={"message": "hello", "sent_at": "2026-09-22T14:30:00-03:00"},
        )

    assert response.status_code == 200
    assert graph.calls[0]["request"]["email"] == "person@example.test"


def test_client_email_or_user_id_cannot_be_sent_as_identity(
    monkeypatch: pytest.MonkeyPatch, rsa_key: jwk.JWK
) -> None:
    app, graph = _setup(monkeypatch, rsa_key)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/conversations/conversation-1/messages",
            headers={"Authorization": f"Bearer {_compact_jwe(rsa_key)}"},
            json={
                "email": "attacker@example.test",
                "user_id": "attacker",
                "message": "hello",
                "sent_at": "2026-09-22T14:30:00-03:00",
            },
        )

    assert response.status_code == 422
    assert graph.calls == []
