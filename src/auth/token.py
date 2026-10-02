from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from jwcrypto import jwe, jwk  # type: ignore[import-untyped]

from src.auth.errors import AuthenticationConfigurationError, InvalidCredentialError

RSA_MINIMUM_KEY_BITS = 2048


class JWEEmailDecoder:
    """Decrypt compact JWE credentials and consume only their email claim."""

    def __init__(self, private_keys: dict[str, jwk.JWK]) -> None:
        if not private_keys:
            raise AuthenticationConfigurationError(
                "JWE private keys are not configured"
            )
        self._private_keys = private_keys

    def decode_email(self, compact_jwe: str) -> str:
        try:
            token = jwe.JWE(algs=["RSA-OAEP-256", "A256GCM"])
            token.deserialize(compact_jwe)
            header = token.jose_header
            if not isinstance(header, dict):
                raise InvalidCredentialError
            if header.get("alg") != "RSA-OAEP-256" or header.get("enc") != "A256GCM":
                raise InvalidCredentialError

            kid = header.get("kid")
            if kid is None and len(self._private_keys) == 1:
                kid = next(iter(self._private_keys))
            if not isinstance(kid, str) or kid not in self._private_keys:
                raise InvalidCredentialError

            token.decrypt(self._private_keys[kid])
            claims: Any = json.loads(token.payload)
            email = claims.get("email") if isinstance(claims, dict) else None
            if not isinstance(email, str) or not email.strip():
                raise InvalidCredentialError
            return email.strip()
        except InvalidCredentialError:
            raise
        except Exception as exc:
            raise InvalidCredentialError from exc


@lru_cache(maxsize=8)
def decoder_from_json_keyring(serialized_keyring: str | None) -> JWEEmailDecoder:
    if not serialized_keyring:
        raise AuthenticationConfigurationError("JWE keyring is not configured")
    try:
        raw_keys = json.loads(serialized_keyring)
        if not isinstance(raw_keys, dict) or not raw_keys:
            raise ValueError
        keys: dict[str, jwk.JWK] = {}
        for kid, pem in raw_keys.items():
            if not isinstance(kid, str) or not kid or not isinstance(pem, str):
                raise ValueError
            key = jwk.JWK.from_pem(pem.replace("\\n", "\n").encode("utf-8"))
            private_key = key.get_op_key("decrypt")
            private_key.private_numbers()
            if private_key.key_size < RSA_MINIMUM_KEY_BITS:
                raise ValueError
            keys[kid] = key
        return JWEEmailDecoder(keys)
    except Exception as exc:
        raise AuthenticationConfigurationError(
            "Invalid JWE keyring configuration"
        ) from exc
