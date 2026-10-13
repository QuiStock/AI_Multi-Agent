from __future__ import annotations

import re
from typing import Any

import jwt
from jwt import PyJWKClient
from jwt.exceptions import (
    PyJWKClientConnectionError,
    PyJWKClientError,
    PyJWKSetError,
)

from src.auth.errors import (
    AuthenticationConfigurationError,
    AuthenticationDependencyError,
    InvalidCredentialError,
)
from src.auth.models import VerifiedToken

AUDIENCE = "quistock-api"
REQUIRED_CLAIMS = ("sub", "email", "iss", "aud", "iat", "exp", "jti")
MAX_BIGINT = 2**63 - 1


class JWTIdentityDecoder:
    """Verify an Auth RS256 token with a trusted, configured JWKS."""

    def __init__(
        self,
        issuer: str | None,
        jwks_url: str | None,
        *,
        jwks_client: Any | None = None,
    ) -> None:
        if not issuer or not issuer.strip() or not jwks_url or not jwks_url.strip():
            raise AuthenticationConfigurationError
        self._issuer = issuer
        self._jwks = jwks_client or PyJWKClient(jwks_url, timeout=3, lifespan=300)

    def decode_identity(self, compact_jwt: str) -> VerifiedToken:
        try:
            header = jwt.get_unverified_header(compact_jwt)
            if (
                header.get("alg") != "RS256"
                or not isinstance(header.get("kid"), str)
                or not header["kid"]
            ):
                raise InvalidCredentialError
            key = self._jwks.get_signing_key_from_jwt(compact_jwt).key
            claims = jwt.decode(
                compact_jwt,
                key,
                algorithms=["RS256"],
                issuer=self._issuer,
                audience=AUDIENCE,
                options={"require": list(REQUIRED_CLAIMS)},
            )
        except (PyJWKClientConnectionError, PyJWKSetError) as exc:
            raise AuthenticationDependencyError from exc
        except (PyJWKClientError, jwt.InvalidTokenError) as exc:
            raise InvalidCredentialError from exc

        if claims.get("aud") != [AUDIENCE]:
            raise InvalidCredentialError
        iat, exp = claims["iat"], claims["exp"]
        if type(iat) is not int or type(exp) is not int or exp - iat != 300:
            raise InvalidCredentialError
        sub, email, jti = claims["sub"], claims["email"], claims["jti"]
        if (
            not isinstance(sub, str)
            or len(sub) > 19
            or re.fullmatch(r"[0-9]+", sub) is None
        ):
            raise InvalidCredentialError
        user_id = int(sub)
        if not 1 <= user_id <= MAX_BIGINT:
            raise InvalidCredentialError
        if not isinstance(email, str) or not email.strip():
            raise InvalidCredentialError
        if not isinstance(jti, str) or not jti.strip():
            raise InvalidCredentialError
        return VerifiedToken(user_id=user_id, email=email)
