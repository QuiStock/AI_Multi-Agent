from __future__ import annotations

import jwt
import pytest

from src.auth.errors import (
    AuthenticationConfigurationError,
    InvalidCredentialError,
)
from src.auth.token import JWTEmailDecoder

SECRET = "a-long-test-only-shared-secret-for-hs256-authentication"


def _token(claims: object, *, secret: str = SECRET, algorithm: str = "HS256") -> str:
    return jwt.encode(claims, secret, algorithm=algorithm)


def test_decoder_extracts_only_email_from_signed_jwt() -> None:
    decoder = JWTEmailDecoder(SECRET)
    compact = _token(
        {"email": " person@example.test ", "role_id": 1, "user_id": "ignored"}
    )

    assert decoder.decode_email(compact) == "person@example.test"


@pytest.mark.parametrize("claims", [{}, {"email": "  "}, {"email": 5}])
def test_decoder_rejects_missing_or_invalid_email_claim(
    claims: dict[str, object],
) -> None:
    decoder = JWTEmailDecoder(SECRET)

    with pytest.raises(InvalidCredentialError):
        decoder.decode_email(_token(claims))


def test_decoder_rejects_invalid_signature() -> None:
    decoder = JWTEmailDecoder(SECRET)

    with pytest.raises(InvalidCredentialError):
        decoder.decode_email(
            _token(
                {"email": "person@example.test"},
                secret="a-different-long-test-only-shared-secret",
            )
        )


def test_decoder_rejects_wrong_algorithm() -> None:
    decoder = JWTEmailDecoder(SECRET)

    with pytest.raises(InvalidCredentialError):
        decoder.decode_email(
            _token({"email": "person@example.test"}, algorithm="HS384")
        )


def test_decoder_fails_closed_without_secret() -> None:
    with pytest.raises(AuthenticationConfigurationError):
        JWTEmailDecoder(None)
