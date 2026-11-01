"""CORS handling scoped exclusively to the observability API."""

from __future__ import annotations

from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_OBSERVABILITY_PATH = "/api/v1/observability"
_ALLOWED_METHODS = {"GET", "POST"}
_ALLOWED_HEADERS = {"content-type"}


class ObservabilityCORSMiddleware:
    """Allow credentialed browser requests from one configured frontend origin."""

    def __init__(self, app: ASGIApp, *, allowed_origin: str) -> None:
        self.app = app
        self.allowed_origin = allowed_origin.rstrip("/")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._is_observability_path(scope["path"]):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        origin = headers.get(b"origin", b"").decode("latin-1")
        allowed = origin == self.allowed_origin
        method = scope["method"].upper()

        if method == "OPTIONS":
            requested_method = headers.get(b"access-control-request-method", b"")
            requested_headers = {
                item.strip().lower()
                for item in headers.get(b"access-control-request-headers", b"")
                .decode("latin-1")
                .split(",")
                if item.strip()
            }
            if (
                not allowed
                or requested_method.decode("latin-1").upper() not in _ALLOWED_METHODS
                or not requested_headers.issubset(_ALLOWED_HEADERS)
            ):
                await JSONResponse(
                    {"detail": "Origem ou solicitação CORS não permitida."},
                    status_code=403,
                )(scope, receive, send)
                return
            await Response(
                status_code=204,
                headers=self._cors_headers(),
            )(scope, receive, send)
            return

        if method not in {"GET", "HEAD"} and origin and not allowed:
            await JSONResponse({"detail": "Origem não permitida."}, status_code=403)(
                scope, receive, send
            )
            return

        async def send_with_cors(message: Message) -> None:
            if message["type"] == "http.response.start" and allowed:
                response_headers = list(message.get("headers", []))
                present = {key.lower() for key, _ in response_headers}
                for key, value in self._cors_headers().items():
                    encoded_key = key.lower().encode("latin-1")
                    if encoded_key not in present:
                        response_headers.append((encoded_key, value.encode("latin-1")))
                vary_key = b"vary"
                vary_value = next(
                    (
                        value
                        for key, value in response_headers
                        if key.lower() == vary_key
                    ),
                    None,
                )
                if vary_value is not None and b"origin" not in vary_value.lower():
                    response_headers = [
                        (key, value)
                        for key, value in response_headers
                        if key.lower() != vary_key
                    ]
                    response_headers.append((vary_key, vary_value + b", Origin"))
                message["headers"] = response_headers
            await send(message)

        await self.app(scope, receive, send_with_cors)

    @staticmethod
    def _is_observability_path(path: str) -> bool:
        return path == _OBSERVABILITY_PATH or path.startswith(f"{_OBSERVABILITY_PATH}/")

    def _cors_headers(self) -> dict[str, str]:
        return {
            "Access-Control-Allow-Origin": self.allowed_origin,
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
            "Vary": "Origin",
        }
