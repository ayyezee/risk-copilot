"""Tests for health check endpoints."""

import pytest
from httpx import AsyncClient

from app.config import get_settings

settings = get_settings()


class TestHealthCheck:
    """Tests for health check endpoints."""

    async def test_basic_health_check(self, client: AsyncClient):
        """Test basic health check endpoint."""
        response = await client.get(f"{settings.api_prefix}/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data
        assert "environment" in data

    async def test_detailed_health_check(self, client: AsyncClient):
        """Test detailed health check endpoint."""
        response = await client.get(f"{settings.api_prefix}/health/detailed")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "database" in data
        assert "redis" in data
        assert "vector_store" in data
        assert "storage" in data


class TestRootEndpoint:
    """Tests for root endpoint."""

    async def test_root_endpoint(self, client: AsyncClient):
        """Test root endpoint returns app info."""
        response = await client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "version" in data
