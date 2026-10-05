from __future__ import annotations

import jwt

from src.auth.errors import AuthenticationConfigurationError, InvalidCredentialError


class JWTEmailDecoder:
    """Validate an HS256 JWT and return its email claim."""

    def __init__(self, secret: str | None) -> None:
        if not secret or not secret.strip():
            raise AuthenticationConfigurationError("JWT secret is not configured")
        self._secret = secret

    def decode_email(self, compact_jwt: str) -> str:
        try:
            claims = jwt.decode(
                compact_jwt,
                self._secret,
                algorithms=["HS256"],
                options={"verify_exp": False, "require": ["email"]},
            )
        except jwt.InvalidTokenError as exc:
            raise InvalidCredentialError from exc

        if not isinstance(claims, dict):
            raise InvalidCredentialError
        email = claims.get("email")
        if not isinstance(email, str) or not email.strip():
            raise InvalidCredentialError
        return email.strip()
