"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from typing import Any

import sentry_sdk
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.middleware.logging import RequestLoggingMiddleware, configure_logging
from app.api.routes import analytics, auth, batch, documents, document_processing, health, reference_examples, reference_library
from app.config import get_settings
from app.core.exceptions import AppException
from app.models.schemas import ErrorResponse, ValidationErrorResponse

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    configure_logging()

    # Initialize Sentry if configured
    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.environment,
            traces_sample_rate=0.1 if settings.environment == "production" else 1.0,
        )

    # Create upload directory
    if settings.storage_backend == "local":
        from pathlib import Path
        Path(settings.local_storage_path).mkdir(parents=True, exist_ok=True)

    # Create ChromaDB directory
    from pathlib import Path
    Path(settings.chroma_persist_directory).mkdir(parents=True, exist_ok=True)

    yield

    # Shutdown
    pass


def create_application() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="A modern document processing backend with AI capabilities",
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        openapi_url="/openapi.json" if settings.debug else None,
        lifespan=lifespan,
    )

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Add request logging middleware
    app.add_middleware(RequestLoggingMiddleware)

    # Register exception handlers
    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(
                error_code=exc.error_code,
                message=exc.message,
                details=exc.details,
            ).model_dump(),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=ValidationErrorResponse(
                details=[
                    {"loc": list(err["loc"]), "msg": err["msg"], "type": err["type"]}
                    for err in exc.errors()
                ]
            ).model_dump(),
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        # Log the error
        import structlog
        logger = structlog.get_logger()
        logger.error("Unhandled exception", error=str(exc), exc_info=True)

        # Report to Sentry
        if settings.sentry_dsn:
            sentry_sdk.capture_exception(exc)

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=ErrorResponse(
                error_code="InternalServerError",
                message="An unexpected error occurred",
            ).model_dump(),
        )

    # Register routers
    app.include_router(health.router, prefix=settings.api_prefix)
    app.include_router(auth.router, prefix=settings.api_prefix)
    app.include_router(documents.router, prefix=settings.api_prefix)
    app.include_router(reference_library.router, prefix=settings.api_prefix)
    app.include_router(reference_examples.router, prefix=settings.api_prefix)
    app.include_router(document_processing.router, prefix=settings.api_prefix)
    app.include_router(analytics.router, prefix=settings.api_prefix)
    app.include_router(batch.router, prefix=settings.api_prefix)

    return app


app = create_application()


@app.get("/")
async def root() -> dict[str, Any]:
    """Root endpoint."""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": f"{settings.api_prefix}/docs" if settings.debug else None,
    }
