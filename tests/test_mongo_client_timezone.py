from datetime import timezone
from types import SimpleNamespace
from typing import Any

from src.api import dependencies


def test_api_mongo_client_preserves_timezone_aware_datetimes(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}

    def fake_mongo_client(uri: str, **kwargs: Any) -> object:
        captured["uri"] = uri
        captured.update(kwargs)
        return object()

    settings = SimpleNamespace(
        mongodb_uri="mongodb://localhost:27017",
        mongodb_db="test",
        health_probe_timeout_seconds=2.0,
    )
    monkeypatch.setattr(dependencies, "MongoClient", fake_mongo_client)
    monkeypatch.setattr(dependencies.config, "get_settings", lambda: settings)
    dependencies.get_mongo_client.cache_clear()

    try:
        dependencies.get_mongo_client()
    finally:
        dependencies.get_mongo_client.cache_clear()

    assert captured["tz_aware"] is True
    assert captured["tzinfo"] is timezone.utc
