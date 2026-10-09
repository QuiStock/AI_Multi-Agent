from __future__ import annotations

import logging
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from google import genai
from google.genai import types as genai_types
from openai import OpenAI
from psycopg_pool import ConnectionPool
from pymongo import MongoClient
from redis import Redis

from src import config

Probe = Callable[[], None]
logger = logging.getLogger(__name__)

_EMAIL_PATTERN = re.compile(r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+\S+")
_SECRET_PATTERN = re.compile(
    r"(?i)\b(api[_ -]?key|access[_ -]?token|password|secret)\s*[:=]\s*\S+"
)
_URL_CREDENTIALS_PATTERN = re.compile(r"(?i)(://[^/:@\s]+:)[^/@\s]+@")
_OPENAI_KEY_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b")
_GOOGLE_KEY_PATTERN = re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b")


def _safe_probe_error(error: Exception) -> str:
    """Return a bounded probe detail without common credentials or PII."""
    detail = " ".join(str(error).split())
    detail = _URL_CREDENTIALS_PATTERN.sub(r"\1[credenciais redigidas]@", detail)
    detail = _BEARER_PATTERN.sub("Bearer [segredo redigido]", detail)
    detail = _SECRET_PATTERN.sub(r"\1=[segredo redigido]", detail)
    detail = _OPENAI_KEY_PATTERN.sub("[chave OpenAI redigida]", detail)
    detail = _GOOGLE_KEY_PATTERN.sub("[chave Google redigida]", detail)
    detail = _EMAIL_PATTERN.sub("[email redigido]", detail)
    return detail[:512] or "sem mensagem de erro"


class HealthService:
    """Bounded, non-generative readiness probes for the chatbot dependencies."""

    def __init__(
        self,
        *,
        settings: config.Settings,
        postgres_pool: ConnectionPool | None,
        mongo_client: MongoClient[Any] | None,
        probes: dict[str, Probe] | None = None,
    ) -> None:
        self._settings = settings
        self._postgres_pool = postgres_pool
        self._mongo_client = mongo_client
        self._overrides = probes or {}

    def check(self) -> tuple[int, dict[str, Any]]:
        checks: dict[str, str] = {"api": "ok"}
        targets: dict[str, Probe] = {
            "postgresql": self._probe_postgresql,
            "mongodb": self._probe_mongodb,
            "redis": self._probe_redis,
            "qdrant": self._probe_qdrant,
            "gemini": self._probe_gemini,
            "openai": self._probe_openai,
        }
        executor = ThreadPoolExecutor(max_workers=len(targets))
        try:
            futures = {
                name: executor.submit(
                    self._safe_probe, self._overrides.get(name, probe)
                )
                for name, probe in targets.items()
            }
            for name, future in futures.items():
                try:
                    future.result(timeout=self._settings.health_probe_timeout_seconds)
                    checks[name] = "ok"
                except Exception as exc:
                    error_type = type(exc).__name__
                    error_message = (
                        f"timeout após {self._settings.health_probe_timeout_seconds:g}s"
                        if isinstance(exc, TimeoutError)
                        else _safe_probe_error(exc)
                    )
                    logger.warning(
                        "health_probe_failed check=%s error_type=%s error_message=%s",
                        name,
                        error_type,
                        error_message,
                        extra={
                            "event": "health_probe_failed",
                            "health_check": name,
                            "error_type": error_type,
                            "error_message": error_message,
                        },
                    )
                    checks[name] = "unavailable"
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        ready = all(value == "ok" for value in checks.values())
        return (200 if ready else 503), {
            "status": "ok" if ready else "error",
            "checks": checks,
        }

    @staticmethod
    def _safe_probe(probe: Probe) -> None:
        probe()

    def _probe_postgresql(self) -> None:
        if self._postgres_pool is None:
            raise RuntimeError("PostgreSQL pool is not configured")
        with (
            self._postgres_pool.connection(
                timeout=self._settings.health_probe_timeout_seconds
            ) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (f"{int(self._settings.health_probe_timeout_seconds * 1000)}ms",),
            )
            cursor.execute("SELECT 1")
            cursor.fetchone()

    def _probe_mongodb(self) -> None:
        if self._mongo_client is None:
            raise RuntimeError("MongoDB is not configured")
        self._mongo_client.admin.command("ping")

    def _probe_redis(self) -> None:
        client: Redis = Redis.from_url(
            self._settings.redis_url,
            socket_connect_timeout=self._settings.health_probe_timeout_seconds,
            socket_timeout=self._settings.health_probe_timeout_seconds,
        )
        try:
            if not client.ping():
                raise RuntimeError("Redis ping failed")
        finally:
            client.close()

    def _probe_qdrant(self) -> None:
        client = config.create_qdrant_client(
            self._settings,
            timeout=max(1, int(self._settings.health_probe_timeout_seconds)),
        )
        try:
            client.get_collections()
        finally:
            client.close()

    def _probe_gemini(self) -> None:
        if not self._settings.gemini_api_key:
            raise RuntimeError("Gemini credentials are not configured")
        client = genai.Client(
            api_key=self._settings.gemini_api_key,
            http_options=genai_types.HttpOptions(
                timeout=int(self._settings.health_probe_timeout_seconds * 1000),
                retry_options=genai_types.HttpRetryOptions(attempts=1),
            ),
        )
        try:
            next(iter(client.models.list()), None)
        finally:
            client.close()

    def _probe_openai(self) -> None:
        if not self._settings.openai_api_key:
            raise RuntimeError("OpenAI credentials are not configured")
        client = OpenAI(
            api_key=self._settings.openai_api_key,
            timeout=self._settings.health_probe_timeout_seconds,
            max_retries=0,
        )
        try:
            next(iter(client.models.list()), None)
        finally:
            client.close()
