import asyncio
import sys

import pytest
from starlette.responses import JSONResponse
from starlette.types import Message, Receive, Scope, Send

from src.api.observability_cors import ObservabilityCORSMiddleware

_ORIGIN = "https://quistock-ai-observability.onrender.com"


def _request(
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str]]:
    async def run() -> tuple[int, dict[str, str]]:
        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            await JSONResponse({"ok": True})(scope, receive, send)

        middleware = ObservabilityCORSMiddleware(app, allowed_origin=_ORIGIN)
        asgi_headers = [
            (name.lower().encode("latin-1"), value.encode("latin-1"))
            for name, value in (headers or {}).items()
        ]
        scope: Scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "https",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "headers": asgi_headers,
            "server": ("api-chatbot-gdox.onrender.com", 443),
            "client": ("client", 50_000),
        }
        sent: list[Message] = []

        async def receive() -> Message:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: Message) -> None:
            sent.append(message)

        await middleware(scope, receive, send)
        status_code = next(
            int(message["status"])
            for message in sent
            if message["type"] == "http.response.start"
        )
        response_headers = {
            key.decode("latin-1"): value.decode("latin-1")
            for message in sent
            if message["type"] == "http.response.start"
            for key, value in message.get("headers", [])
        }
        return status_code, response_headers

    return asyncio.run(run())


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="O loop asyncio trava no sandbox Windows; a CI roda em Ubuntu.",
)
def test_cors_allows_only_the_configured_observability_frontend() -> None:
    allowed_status, allowed_headers = _request(
        "GET",
        "/api/v1/observability/test",
        headers={"Origin": _ORIGIN},
    )
    blocked_status, blocked_headers = _request(
        "POST",
        "/api/v1/observability/test",
        headers={"Origin": "https://untrusted.example"},
    )
    conversation_status, conversation_headers = _request(
        "GET",
        "/api/v1/conversations",
        headers={"Origin": _ORIGIN},
    )

    assert allowed_status == 200
    assert allowed_headers["access-control-allow-origin"] == _ORIGIN
    assert allowed_headers["access-control-allow-credentials"] == "true"
    assert blocked_status == 403
    assert "access-control-allow-origin" not in blocked_headers
    assert conversation_status == 200
    assert "access-control-allow-origin" not in conversation_headers


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="O loop asyncio trava no sandbox Windows; a CI roda em Ubuntu.",
)
def test_cors_preflight_is_limited_to_json_get_and_post() -> None:
    allowed_status, allowed_headers = _request(
        "OPTIONS",
        "/api/v1/observability/login",
        headers={
            "Origin": _ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    blocked_status, blocked_headers = _request(
        "OPTIONS",
        "/api/v1/observability/login",
        headers={
            "Origin": _ORIGIN,
            "Access-Control-Request-Method": "DELETE",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert allowed_status == 204
    assert allowed_headers["access-control-allow-origin"] == _ORIGIN
    assert allowed_headers["access-control-allow-credentials"] == "true"
    assert blocked_status == 403
    assert "access-control-allow-origin" not in blocked_headers
