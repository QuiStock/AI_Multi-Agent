from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlsplit

import jwt

from src.auth.errors import AuthenticationConfigurationError, InvalidCredentialError


class JWTEmailDecoder:
    """Validate Auth RS256 tokens; HS256 is an explicit development option."""

    def __init__(
        self,
        secret: str | None = None,
        *,
        algorithm: str = "RS256",
        issuer: str | None = None,
        audience: str | None = None,
        jwks_uri: str | None = None,
    ) -> None:
        if algorithm not in ("RS256", "HS256"):
            raise AuthenticationConfigurationError("Unsupported JWT algorithm")
        self._algorithm = algorithm
        self._issuer = issuer
        self._audience = audience
        self._secret = secret
        self._jwks: jwt.PyJWKClient | None = None
        if algorithm == "RS256":
            if not issuer or not audience or not jwks_uri:
                raise AuthenticationConfigurationError("JWT verifier is not configured")
            url = urlsplit(jwks_uri)
            if url.scheme not in ("http", "https") or not url.hostname or url.username:
                raise AuthenticationConfigurationError("Invalid JWKS URI")
            self._jwks = jwt.PyJWKClient(jwks_uri, timeout=3, lifespan=300)
        elif not secret or not secret.strip():
            raise AuthenticationConfigurationError("JWT secret is not configured")

    def decode_email(self, compact_jwt: str) -> str:
        try:
            # Reject algorithm confusion before fetching a key from the fixed URI.
            if jwt.get_unverified_header(compact_jwt).get("alg") != self._algorithm:
                raise InvalidCredentialError
            if self._jwks is not None:
                key = self._jwks.get_signing_key_from_jwt(compact_jwt).key
                claims = jwt.decode(
                    compact_jwt,
                    key,
                    algorithms=["RS256"],
                    issuer=self._issuer,
                    audience=self._audience,
                    options={"require": ["email", "exp", "iss", "aud"]},
                )
            else:
                if self._secret is None:
                    raise AuthenticationConfigurationError("JWT secret is missing")
                claims = jwt.decode(
                    compact_jwt,
                    self._secret,
                    algorithms=["HS256"],
                    options={"require": ["email", "exp"]},
                )
        except jwt.PyJWKClientConnectionError as exc:
            raise AuthenticationConfigurationError("JWKS is unavailable") from exc
        except jwt.PyJWKClientError as exc:
            raise InvalidCredentialError from exc
        except jwt.InvalidTokenError as exc:
            raise InvalidCredentialError from exc

        if not isinstance(claims, dict):
            raise InvalidCredentialError
        email = claims.get("email")
        if not isinstance(email, str) or not email.strip():
            raise InvalidCredentialError
        return email.strip()


@dataclass(frozen=True)
class JWTVerifierSettings:
    algorithm: str
    issuer: str | None
    audience: str
    jwks_uri: str | None
    secret: str | None
    environment: str


@lru_cache(maxsize=8)
def get_jwt_decoder(settings: JWTVerifierSettings) -> JWTEmailDecoder:
    """Reuse the bounded JWKS cache instead of fetching per request."""
    if settings.algorithm == "HS256" and settings.environment != "development":
        raise AuthenticationConfigurationError("HS256 is development-only")
    return JWTEmailDecoder(
        settings.secret,
        algorithm=settings.algorithm,
        issuer=settings.issuer,
        audience=settings.audience,
        jwks_uri=settings.jwks_uri,
    )
