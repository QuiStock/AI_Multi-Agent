from fastapi import FastAPI

from src.api.errors import register_exception_handlers
from src.api.routes.conversation import router as conversation_router
from src.api.routes.conversation_end import router as conversation_end_router
from src.api.routes.conversation_list import router as conversation_list_router
from src.api.routes.health import router as health_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Quistock AI API",
        version="0.1.0",
    )
    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(conversation_router, prefix="/api/v1")
    app.include_router(conversation_end_router, prefix="/api/v1")
    app.include_router(conversation_list_router, prefix="/api/v1")
    return app


app = create_app()


def main() -> None:
    """Keep the original executable entry point for local smoke checks."""
    return None


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=False)
