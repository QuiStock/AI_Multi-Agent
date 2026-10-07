from src.api.schemas.health import HealthResponse
from src.api.services.health_service import HealthService


class HealthController:
    def __init__(self, service: HealthService) -> None:
        self._service = service

    def check(self) -> HealthResponse:
        return self._service.check()
