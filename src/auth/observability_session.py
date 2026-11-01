"""Short-lived cookie sessions for the isolated observability API."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import HTTPException, Request, status
from jwt import InvalidTokenError
from starlette.responses import Response

from src import config
from src.config import Settings

OBSERVABILITY_COOKIE_NAME = "observability_session"
OBSERVABILITY_COOKIE_PATH = "/api/v1/observability"
OBSERVABILITY_SESSION_TTL_SECONDS = 60 * 60
OBSERVABILITY_SESSION_SECRET_MIN_LENGTH = 32
OBSERVABILITY_PASSWORD_MAX_BYTES = 72
_SESSION_ISSUER = "quistock-observability"
_SESSION_AUDIENCE = "quistock-observability"


def get_observability_session_secret(settings: Settings) -> str:
    secret = settings.observability_session_secret
    if secret is None or len(secret) < OBSERVABILITY_SESSION_SECRET_MIN_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sessão de observabilidade não configurada.",
        )
    return secret


def create_observability_session_token(
    email: str,
    secret: str,
    *,
    now: datetime | None = None,
) -> str:
    issued_at = now or datetime.now(UTC)
    expires_at = issued_at + timedelta(seconds=OBSERVABILITY_SESSION_TTL_SECONDS)
    token = jwt.encode(
        {
            "sub": email.strip().lower(),
            "iat": issued_at,
            "exp": expires_at,
            "iss": _SESSION_ISSUER,
            "aud": _SESSION_AUDIENCE,
        },
        secret,
        algorithm="HS256",
    )
    if not isinstance(token, str):
        raise TypeError("JWT encoder returned a non-string token")
    return token


def verify_observability_session(token: str, secret: str) -> str | None:
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            issuer=_SESSION_ISSUER,
            audience=_SESSION_AUDIENCE,
            options={"require": ["sub", "iat", "exp"]},
        )
    except InvalidTokenError, TypeError, ValueError:
        return None

    subject = claims.get("sub")
    return (
        subject.strip().lower()
        if isinstance(subject, str) and subject.strip()
        else None
    )


def require_observability_session(request: Request) -> str:
    """Authenticate a request using only the observability cookie."""
    secret = get_observability_session_secret(config.get_settings())
    token = request.cookies.get(OBSERVABILITY_COOKIE_NAME)
    email = verify_observability_session(token, secret) if token else None
    if email is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sessão de observabilidade ausente ou expirada.",
        )
    return email


def set_observability_session_cookie(
    response: Response,
    token: str,
    *,
    production: bool,
) -> None:
    response.set_cookie(
        key=OBSERVABILITY_COOKIE_NAME,
        value=token,
        max_age=OBSERVABILITY_SESSION_TTL_SECONDS,
        httponly=True,
        secure=production,
        samesite="none" if production else "lax",
        path=OBSERVABILITY_COOKIE_PATH,
    )


def clear_observability_session_cookie(
    response: Response,
    *,
    production: bool,
) -> None:
    response.delete_cookie(
        key=OBSERVABILITY_COOKIE_NAME,
        path=OBSERVABILITY_COOKIE_PATH,
        secure=production,
        httponly=True,
        samesite="none" if production else "lax",
    )


def verify_observability_password(password: str, stored_hash: str) -> bool:
    """Compare a plain password to a bcrypt hash without exposing failures."""
    try:
        password_bytes = password.encode("utf-8")
    except UnicodeEncodeError:
        return False
    if len(
        password_bytes
    ) > OBSERVABILITY_PASSWORD_MAX_BYTES or not stored_hash.startswith(
        ("$2a$", "$2b$", "$2y$")
    ):
        return False
    normalized_hash = (
        "$2b$" + stored_hash[4:] if stored_hash.startswith("$2y$") else stored_hash
    )
    try:
        return bcrypt.checkpw(password_bytes, normalized_hash.encode("ascii"))
    except UnicodeEncodeError, ValueError:
        return False
