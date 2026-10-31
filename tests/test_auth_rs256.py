from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from src.auth.errors import AuthenticationConfigurationError, InvalidCredentialError
from src.auth.token import JWTEmailDecoder, JWTVerifierSettings, get_jwt_decoder

ISSUER = "https://auth.example.test"
AUDIENCE = "quistock-api"


@pytest.fixture
def signing_key() -> Any:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def jwks(signing_key: Any) -> Any:
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key()))
    public.update(kid="current", alg="RS256", use="sig")

    class Handler(BaseHTTPRequestHandler):
        calls = 0

        def do_GET(self) -> None:
            Handler.calls += 1
            body = json.dumps({"keys": [public]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/jwks", Handler
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def token(key: Any, **changes: Any) -> str:
    claims = {
        "email": "person@example.test",
        "exp": int(time.time()) + 300,
        "iss": ISSUER,
        "aud": AUDIENCE,
        **changes,
    }
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "current"})


def decoder(uri: str) -> JWTEmailDecoder:
    return JWTEmailDecoder(issuer=ISSUER, audience=AUDIENCE, jwks_uri=uri)


def test_real_rs256_jwks_lookup_and_cache(signing_key: Any, jwks: Any) -> None:
    uri, handler = jwks
    verifier = decoder(uri)
    for _ in range(2):
        assert verifier.decode_email(token(signing_key)) == "person@example.test"
    assert handler.calls == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"exp": int(time.time()) - 60},
        {"iss": "https://other.test"},
        {"aud": "other-api"},
        {"email": ""},
        {"email": 12},
    ],
)
def test_invalid_claims_are_rejected(signing_key: Any, jwks: Any, changes: Any) -> None:
    with pytest.raises(InvalidCredentialError):
        decoder(jwks[0]).decode_email(token(signing_key, **changes))


def test_different_signing_key_is_rejected(jwks: Any) -> None:
    wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(InvalidCredentialError):
        decoder(jwks[0]).decode_email(token(wrong_key))


def test_hmac_token_cannot_downgrade_rs256(jwks: Any) -> None:
    compact = jwt.encode(
        {"email": "attacker@test", "exp": int(time.time()) + 60},
        "test-secret-with-at-least-thirty-two-bytes",
        algorithm="HS256",
    )
    with pytest.raises(InvalidCredentialError):
        decoder(jwks[0]).decode_email(compact)
    assert jwks[1].calls == 0


@pytest.mark.parametrize("missing", ["exp", "iss", "aud", "email"])
def test_required_claims(signing_key: Any, jwks: Any, missing: str) -> None:
    claims = {
        "email": "person@test",
        "exp": int(time.time()) + 60,
        "iss": ISSUER,
        "aud": AUDIENCE,
    }
    del claims[missing]
    compact = jwt.encode(
        claims, signing_key, algorithm="RS256", headers={"kid": "current"}
    )
    with pytest.raises(InvalidCredentialError):
        decoder(jwks[0]).decode_email(compact)


def test_hs256_is_disabled_in_production() -> None:
    with pytest.raises(AuthenticationConfigurationError):
        get_jwt_decoder(
            JWTVerifierSettings("HS256", None, AUDIENCE, None, "secret", "production")
        )


def test_jwks_outage_fails_closed(signing_key: Any) -> None:
    with pytest.raises(AuthenticationConfigurationError):
        decoder("http://127.0.0.1:1/jwks").decode_email(token(signing_key))
