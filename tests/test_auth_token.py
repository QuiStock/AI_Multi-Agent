from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError
from jwt.utils import base64url_encode

from src.auth.errors import (
    AuthenticationConfigurationError,
    AuthenticationDependencyError,
    InvalidCredentialError,
)
from src.auth.models import VerifiedToken
from src.auth.token import JWTIdentityDecoder

ISSUER = "https://auth.example.test"
JWKS_URL = f"{ISSUER}/.well-known/jwks.json"


def _b64(number: int) -> str:
    raw = number.to_bytes((number.bit_length() + 7) // 8, "big")
    return base64url_encode(raw).decode()


def _jwk(key: rsa.RSAPrivateKey, kid: str) -> dict[str, str]:
    numbers = key.public_key().public_numbers()
    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": kid,
        "n": _b64(numbers.n),
        "e": _b64(numbers.e),
    }


class LocalJWKS(PyJWKClient):
    def __init__(self, keys: list[dict[str, str]]) -> None:
        super().__init__(JWKS_URL, cooldown_duration=0)
        self.keys = keys

    def fetch_data(self) -> dict[str, Any]:
        return {"keys": self.keys}


@pytest.fixture
def signing_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _claims(**changes: Any) -> dict[str, Any]:
    issued = int(datetime.now(timezone.utc).timestamp())
    claims: dict[str, Any] = {
        "sub": "42",
        "email": "person@example.test",
        "iss": ISSUER,
        "aud": ["quistock-api"],
        "iat": issued,
        "exp": issued + 300,
        "jti": "token-1",
    }
    claims.update(changes)
    return claims


def _token(key: rsa.RSAPrivateKey, claims: dict[str, Any], kid: str = "key-1") -> str:
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


def _decoder(key: rsa.RSAPrivateKey) -> JWTIdentityDecoder:
    return JWTIdentityDecoder(
        ISSUER, JWKS_URL, jwks_client=LocalJWKS([_jwk(key, "key-1")])
    )


def test_decoder_resolves_jwks_key_and_validates_identity(
    signing_key: rsa.RSAPrivateKey,
) -> None:
    assert _decoder(signing_key).decode_identity(
        _token(signing_key, _claims())
    ) == VerifiedToken(user_id=42, email="person@example.test")


@pytest.mark.parametrize(
    "missing",
    ["sub", "email", "iss", "aud", "iat", "exp", "jti"],
)
def test_decoder_requires_all_claims(
    signing_key: rsa.RSAPrivateKey, missing: str
) -> None:
    claims = _claims()
    del claims[missing]
    with pytest.raises(InvalidCredentialError):
        _decoder(signing_key).decode_identity(_token(signing_key, claims))


@pytest.mark.parametrize(
    "changes",
    [
        {"iss": "https://other.example.test"},
        {"aud": ["other-api"]},
        {"aud": "quistock-api"},
        {"aud": ["quistock-api", "other-api"]},
        {"sub": "not-an-id"},
        {"sub": "0"},
        {"sub": str(2**63)},
        {"sub": "9" * 5000},
        {"email": ""},
        {"jti": ""},
    ],
)
def test_decoder_rejects_invalid_claims(
    signing_key: rsa.RSAPrivateKey, changes: dict[str, Any]
) -> None:
    with pytest.raises(InvalidCredentialError):
        _decoder(signing_key).decode_identity(_token(signing_key, _claims(**changes)))


def test_decoder_rejects_expired_and_overlong_tokens(
    signing_key: rsa.RSAPrivateKey,
) -> None:
    now = int(datetime.now(timezone.utc).timestamp())
    for claims in (
        _claims(iat=now - 301, exp=now - 1),
        _claims(exp=now + 301),
        _claims(iat=now + 30, exp=now + 330),
    ):
        with pytest.raises(InvalidCredentialError):
            _decoder(signing_key).decode_identity(_token(signing_key, claims))


def test_decoder_rejects_wrong_signature_algorithm_and_kid(
    signing_key: rsa.RSAPrivateKey,
) -> None:
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    tokens = (
        _token(other_key, _claims()),
        jwt.encode(
            _claims(),
            "a-long-test-only-hs256-secret-123456",
            algorithm="HS256",
            headers={"kid": "key-1"},
        ),
        _token(signing_key, _claims(), kid="unknown"),
    )
    for compact in tokens:
        with pytest.raises(InvalidCredentialError):
            _decoder(signing_key).decode_identity(compact)


def test_decoder_accepts_new_key_after_jwks_rotation(
    signing_key: rsa.RSAPrivateKey,
) -> None:
    new_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwks = LocalJWKS([_jwk(signing_key, "key-1")])
    decoder = JWTIdentityDecoder(ISSUER, JWKS_URL, jwks_client=jwks)
    assert decoder.decode_identity(_token(signing_key, _claims())).user_id == 42
    jwks.keys.append(_jwk(new_key, "key-2"))
    assert (
        decoder.decode_identity(_token(new_key, _claims(), kid="key-2")).user_id == 42
    )


def test_decoder_distinguishes_jwks_outage_from_invalid_token() -> None:
    class OfflineJWKS:
        def get_signing_key_from_jwt(self, _: str) -> None:
            raise PyJWKClientConnectionError("unavailable")

    decoder = JWTIdentityDecoder(ISSUER, JWKS_URL, jwks_client=OfflineJWKS())
    token = jwt.encode(
        _claims(),
        "a-long-test-only-hs256-secret-123456",
        algorithm="HS256",
        headers={"kid": "key-1"},
    )
    # The fixed algorithm check denies HS256 without calling the network.
    with pytest.raises(InvalidCredentialError):
        decoder.decode_identity(token)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(AuthenticationDependencyError):
        decoder.decode_identity(_token(key, _claims()))


def test_decoder_fails_closed_without_issuer_or_jwks() -> None:
    with pytest.raises(AuthenticationConfigurationError):
        JWTIdentityDecoder(None, JWKS_URL)
    with pytest.raises(AuthenticationConfigurationError):
        JWTIdentityDecoder(ISSUER, None)
