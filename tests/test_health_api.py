import time

from fastapi.testclient import TestClient

from src.api.dependencies import get_health_service
from src.api.services.health_service import HealthService
from src.config import Settings
from src.main import create_app


def test_health_endpoint_returns_ok() -> None:
    app = create_app()
    ready_probes = {
        name: lambda: None
        for name in ("postgresql", "mongodb", "redis", "qdrant", "gemini", "groq")
    }
    app.dependency_overrides[get_health_service] = lambda: HealthService(
        settings=Settings(),
        postgres_pool=None,
        mongo_client=None,
        probes=ready_probes,
    )
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {
            "api": "ok",
            "postgresql": "ok",
            "mongodb": "ok",
            "redis": "ok",
            "qdrant": "ok",
            "gemini": "ok",
            "groq": "ok",
        },
    }
    app.dependency_overrides.clear()


def test_health_reports_failed_dependency_without_leaking_errors() -> None:
    app = create_app()

    def fail_with_secret() -> None:
        raise RuntimeError("password=do-not-return")

    probes = {
        name: lambda: None
        for name in ("postgresql", "mongodb", "redis", "qdrant", "gemini", "groq")
    }
    probes["mongodb"] = fail_with_secret
    app.dependency_overrides[get_health_service] = lambda: HealthService(
        settings=Settings(),
        postgres_pool=None,
        mongo_client=None,
        probes=probes,
    )

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 500
    assert response.json()["status"] == "error"
    assert response.json()["checks"]["mongodb"] == "unavailable"
    assert "do-not-return" not in response.text
    app.dependency_overrides.clear()


def test_provider_probes_use_model_catalog_without_generation(
    monkeypatch,
) -> None:
    from src.api.services import health_service

    calls = {"gemini_list": 0, "groq_list": 0, "generated": 0}

    class Models:
        def __init__(self, key: str) -> None:
            self.key = key

        def list(self):
            calls[self.key] += 1
            return ["model"]

    class ProviderClient:
        def __init__(self, key: str) -> None:
            self.models = Models(key)

        def close(self) -> None:
            pass

    settings = Settings(
        gemini_api_key="test-key",
        groq_api_key="test-key",
    )
    service = HealthService(
        settings=settings,
        postgres_pool=None,
        mongo_client=None,
    )
    monkeypatch.setattr(
        health_service.genai,
        "Client",
        lambda **_: ProviderClient("gemini_list"),
    )
    monkeypatch.setattr(
        health_service,
        "Groq",
        lambda **_: ProviderClient("groq_list"),
    )

    service._probe_gemini()
    service._probe_groq()

    assert calls == {"gemini_list": 1, "groq_list": 1, "generated": 0}


def test_health_marks_probe_timeout_unavailable() -> None:
    settings = Settings(health_probe_timeout_seconds=0.02)
    probes = {
        name: lambda: None
        for name in ("postgresql", "mongodb", "redis", "qdrant", "gemini", "groq")
    }

    def slow_probe() -> None:
        time.sleep(0.15)

    probes["gemini"] = slow_probe
    service = HealthService(
        settings=settings,
        postgres_pool=None,
        mongo_client=None,
        probes=probes,
    )

    status_code, result = service.check()

    assert status_code == 500
    assert result["checks"]["gemini"] == "unavailable"
