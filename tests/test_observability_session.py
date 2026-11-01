from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from types import SimpleNamespace

import bcrypt
import pytest
from fastapi import HTTPException, Request, Response
from fastapi.routing import APIRoute

from src import config
from src.api.routes.observability import login, logout
from src.api.routes.observability import router as observability_router
from src.api.schemas.observability import ObservabilityLoginRequest
from src.auth.observability_session import (
    OBSERVABILITY_COOKIE_NAME,
    create_observability_session_token,
    get_observability_session_secret,
    require_observability_session,
    verify_observability_password,
    verify_observability_session,
)
from src.config import Settings

_SECRET = "observability-session-test-secret-32"
_EMAIL = "observer@example.com"
_PASSWORD = "safe-test-password"


class FakeCursor:
    def __init__(self, rows: list[tuple[str, str]]) -> None:
        self.rows = rows
        self.queries: list[tuple[str, tuple[str, ...] | None]] = []

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, parameters: tuple[str, ...] | None = None) -> None:
        self.queries.append((query, parameters))

    def fetchall(self) -> list[tuple[str, str]]:
        return self.rows


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    @contextmanager
    def cursor(self) -> Iterator[FakeCursor]:
        yield self._cursor


class FakePool:
    def __init__(self, rows: list[tuple[str, str]]) -> None:
        self.cursor = FakeCursor(rows)
        self._connection = FakeConnection(self.cursor)

    @contextmanager
    def connection(self, *, timeout: float) -> Iterator[FakeConnection]:
        assert timeout > 0
        yield self._connection


def _settings() -> Settings:
    return Settings(
        app_environment="production",
        observability_session_secret=_SECRET,
    )


def _request(
    *,
    pool: FakePool | None = None,
    cookie: str | None = None,
    path: str = "/api/v1/observability/lab/models",
) -> Request:
    headers = []
    if cookie is not None:
        headers.append(
            (b"cookie", f"{OBSERVABILITY_COOKIE_NAME}={cookie}".encode("ascii"))
        )
    app = SimpleNamespace(state=SimpleNamespace())
    if pool is not None:
        app.state.postgres_pool = pool
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "headers": headers,
            "server": ("testserver", 443),
            "client": ("testclient", 50000),
            "app": app,
        }
    )


def test_observability_session_token_expiration_and_secret_validation() -> None:
    now = datetime.now(UTC)
    token = create_observability_session_token("ADMIN@example.com", _SECRET, now=now)

    assert verify_observability_session(token, _SECRET) == "admin@example.com"
    assert (
        verify_observability_session(token, "another-observability-secret-32x") is None
    )
    expired = create_observability_session_token(
        _EMAIL,
        _SECRET,
        now=now - timedelta(hours=2),
    )
    assert verify_observability_session(expired, _SECRET) is None
    with pytest.raises(HTTPException) as error:
        get_observability_session_secret(Settings(observability_session_secret="short"))
    assert error.value.status_code == 503


def test_bcrypt_password_validation() -> None:
    stored_hash = bcrypt.hashpw(_PASSWORD.encode(), bcrypt.gensalt()).decode()

    assert verify_observability_password(_PASSWORD, stored_hash)
    assert verify_observability_password(_PASSWORD, "$2y$" + stored_hash[4:])
    assert not verify_observability_password("wrong-password", stored_hash)
    assert not verify_observability_password(_PASSWORD, "not-a-bcrypt-hash")
    assert not verify_observability_password("x" * 73, stored_hash)
    assert not verify_observability_password("\ud800", stored_hash)


def test_every_observability_route_requires_a_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "get_settings", _settings)
    protected_routes = [
        route
        for route in observability_router.routes
        if isinstance(route, APIRoute) and not route.path.endswith("/login")
    ]

    assert protected_routes
    assert all(
        any(
            dependency.call is require_observability_session
            for dependency in route.dependant.dependencies
        )
        for route in protected_routes
    )
    with pytest.raises(HTTPException) as error:
        require_observability_session(_request())
    assert error.value.status_code == 401


def test_login_cookie_grants_and_logout_revokes_observability_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "get_settings", _settings)
    stored_hash = bcrypt.hashpw(_PASSWORD.encode(), bcrypt.gensalt()).decode()
    pool = FakePool([(_EMAIL, stored_hash)])
    response = Response()

    result = login(
        ObservabilityLoginRequest(
            email=f" {_EMAIL.upper()} ",
            password=_PASSWORD,
        ),
        _request(pool=pool, path="/api/v1/observability/login"),
        response,
    )

    assert result.authenticated is True
    cookie_header = response.headers["set-cookie"]
    assert "HttpOnly" in cookie_header
    assert "Secure" in cookie_header
    assert "SameSite=none" in cookie_header
    assert "Path=/api/v1/observability" in cookie_header
    cookie = SimpleCookie()
    cookie.load(cookie_header)
    token = cookie[OBSERVABILITY_COOKIE_NAME].value
    assert require_observability_session(_request(cookie=token)) == _EMAIL

    logged_out = Response()
    assert logout(logged_out).authenticated is False
    assert "Max-Age=0" in logged_out.headers["set-cookie"]
    with pytest.raises(HTTPException) as error:
        require_observability_session(_request())
    assert error.value.status_code == 401
    assert pool.cursor.queries[-1][1] == (_EMAIL,)


@pytest.mark.parametrize(
    ("rows", "password"),
    [
        ([], _PASSWORD),
        ([("observer@example.com", "$2b$invalid")], _PASSWORD),
    ],
)
def test_login_rejects_unknown_or_invalid_credentials(
    monkeypatch: pytest.MonkeyPatch,
    rows: list[tuple[str, str]],
    password: str,
) -> None:
    monkeypatch.setattr(config, "get_settings", _settings)

    with pytest.raises(HTTPException) as error:
        login(
            ObservabilityLoginRequest(email=_EMAIL, password=password),
            _request(pool=FakePool(rows), path="/api/v1/observability/login"),
            Response(),
        )

    assert error.value.status_code == 401
    assert error.value.detail == "Credenciais inválidas."


def test_login_fails_closed_without_database_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "get_settings", _settings)

    with pytest.raises(HTTPException) as error:
        login(
            ObservabilityLoginRequest(email=_EMAIL, password=_PASSWORD),
            _request(path="/api/v1/observability/login"),
            Response(),
        )

    assert error.value.status_code == 503
