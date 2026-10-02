from __future__ import annotations

import json

import pytest
from jwcrypto import jwe, jwk

from src.auth.errors import (
    AuthenticationConfigurationError,
    InvalidCredentialError,
)
from src.auth.token import JWEEmailDecoder, decoder_from_json_keyring


@pytest.fixture
def rsa_key() -> jwk.JWK:
    return jwk.JWK.generate(kty="RSA", size=2048)


def _token(public_key: jwk.JWK, *, claims: object, kid: str = "current") -> str:
    token = jwe.JWE(
        plaintext=json.dumps(claims),
        protected={
            "alg": "RSA-OAEP-256",
            "enc": "A256GCM",
            "kid": kid,
        },
    )
    token.add_recipient(public_key)
    return token.serialize(compact=True)


def test_decoder_extracts_only_email_from_encrypted_jwt(rsa_key: jwk.JWK) -> None:
    decoder = JWEEmailDecoder({"current": rsa_key})
    compact = _token(
        rsa_key,
        claims={"email": " person@example.test ", "role_id": 1, "user_id": "ignored"},
    )

    assert decoder.decode_email(compact) == "person@example.test"


@pytest.mark.parametrize(
    "claims",
    [{}, {"email": "  "}, {"email": 5}, []],
)
def test_decoder_rejects_missing_or_invalid_email_claim(
    rsa_key: jwk.JWK, claims: object
) -> None:
    decoder = JWEEmailDecoder({"current": rsa_key})

    with pytest.raises(InvalidCredentialError):
        decoder.decode_email(_token(rsa_key, claims=claims))


def test_decoder_rejects_unknown_kid(rsa_key: jwk.JWK) -> None:
    decoder = JWEEmailDecoder({"current": rsa_key})

    with pytest.raises(InvalidCredentialError):
        decoder.decode_email(
            _token(rsa_key, claims={"email": "person@example.test"}, kid="old")
        )


def test_decoder_accepts_both_keys_during_rotation() -> None:
    old_key = jwk.JWK.generate(kty="RSA", size=2048)
    new_key = jwk.JWK.generate(kty="RSA", size=2048)
    decoder = JWEEmailDecoder({"old": old_key, "new": new_key})

    assert (
        decoder.decode_email(
            _token(old_key, claims={"email": "old@example.test"}, kid="old")
        )
        == "old@example.test"
    )
    assert (
        decoder.decode_email(
            _token(new_key, claims={"email": "new@example.test"}, kid="new")
        )
        == "new@example.test"
    )


def test_decoder_rejects_wrong_algorithms(rsa_key: jwk.JWK) -> None:
    token = jwe.JWE(
        plaintext=json.dumps({"email": "person@example.test"}),
        protected={"alg": "RSA-OAEP", "enc": "A256GCM", "kid": "current"},
    )
    token.add_recipient(rsa_key)
    decoder = JWEEmailDecoder({"current": rsa_key})

    with pytest.raises(InvalidCredentialError):
        decoder.decode_email(token.serialize(compact=True))


def test_keyring_configuration_builds_rotation_key_map(rsa_key: jwk.JWK) -> None:
    serialized = json.dumps(
        {"current": rsa_key.export_to_pem(private_key=True, password=None).decode()}
    )

    decoder = decoder_from_json_keyring(serialized)
    compact = _token(rsa_key, claims={"email": "person@example.test"})

    assert decoder.decode_email(compact) == "person@example.test"


def test_keyring_configuration_fails_closed() -> None:
    with pytest.raises(AuthenticationConfigurationError):
        decoder_from_json_keyring(None)
