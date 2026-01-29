"""Health check endpoints."""

from typing import Annotated

import redis.asyncio as redis
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.database import get_db_session
from app.models.schemas import DetailedHealthResponse, HealthResponse
from app.services.vector_store import VectorStoreService, get_vector_store_service

router = APIRouter(prefix="/health", tags=["health"])
settings = get_settings()


@router.get("", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Basic health check endpoint."""
    return HealthResponse(
        status="healthy",
        version=settings.app_version,
        environment=settings.environment,
    )


@router.get("/detailed", response_model=DetailedHealthResponse)
async def detailed_health_check(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    vector_store: Annotated[VectorStoreService, Depends(get_vector_store_service)],
) -> DetailedHealthResponse:
    """Detailed health check with dependency status."""
    # Check database
    db_status = "healthy"
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        db_status = "unhealthy"

    # Check Redis
    redis_status = "healthy"
    try:
        redis_client = redis.from_url(str(settings.redis_url))
        await redis_client.ping()
        await redis_client.close()
    except Exception:
        redis_status = "unhealthy"

    # Check vector store
    vector_status = "healthy"
    try:
        if not await vector_store.health_check():
            vector_status = "unhealthy"
    except Exception:
        vector_status = "unhealthy"

    # Check storage
    storage_status = "healthy"
    try:
        from pathlib import Path
        if settings.storage_backend == "local":
            if not Path(settings.local_storage_path).exists():
                storage_status = "unhealthy"
    except Exception:
        storage_status = "unhealthy"

    overall_status = "healthy"
    if any(s == "unhealthy" for s in [db_status, redis_status, vector_status, storage_status]):
        overall_status = "degraded"

    return DetailedHealthResponse(
        status=overall_status,
        version=settings.app_version,
        environment=settings.environment,
        database=db_status,
        redis=redis_status,
        vector_store=vector_status,
        storage=storage_status,
    )
