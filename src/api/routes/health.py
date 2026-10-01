from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from src.api.dependencies import get_health_service
from src.api.services.health_service import HealthService

router = APIRouter(tags=["health"])


@router.get("/health")
def health(service: HealthService = Depends(get_health_service)) -> JSONResponse:
    status_code, result = service.check()
    return JSONResponse(status_code=status_code, content=result)
