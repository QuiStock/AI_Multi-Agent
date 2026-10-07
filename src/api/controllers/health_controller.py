from typing import Any

from src.api.services.health_service import HealthService


class HealthController:
    def __init__(self, service: HealthService) -> None:
        self._service = service

    def check(self) -> tuple[int, dict[str, Any]]:
        return self._service.check()
