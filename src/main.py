from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from psycopg_pool import ConnectionPool

from src import config
from src.api.errors import register_exception_handlers
from src.api.routes.conversation import router as conversation_router
from src.api.routes.conversation_delete import router as conversation_delete_router
from src.api.routes.conversation_end import router as conversation_end_router
from src.api.routes.conversation_list import router as conversation_list_router
from src.api.routes.health import router as health_router
from src.api.routes.observability import router as observability_router
from src.auth.postgres import create_postgres_pool


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        settings = config.get_settings()
        pool: ConnectionPool | None = None
        if settings.postgres_dsn:
            pool = create_postgres_pool(
                dsn=settings.postgres_dsn,
                timeout_seconds=settings.postgres_pool_timeout_seconds,
            )
            pool.open(wait=False)
            application.state.postgres_pool = pool
        try:
            yield
        finally:
            if pool is not None:
                pool.close()

    app = FastAPI(
        title="Quistock AI API",
        version="0.1.0",
        lifespan=lifespan,
    )
    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(conversation_router, prefix="/api/v1")
    app.include_router(conversation_delete_router, prefix="/api/v1")
    app.include_router(conversation_end_router, prefix="/api/v1")
    app.include_router(conversation_list_router, prefix="/api/v1")
    app.include_router(observability_router, prefix="/api/v1")
    return app


app = create_app()


def main() -> None:
    """Keep the original executable entry point for local smoke checks."""
    return None


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=False)
