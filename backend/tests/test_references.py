"""Tests for reference library endpoints."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.database import ReferenceItem, User

settings = get_settings()


class TestReferenceCreate:
    """Tests for creating reference items."""

    async def test_create_reference(self, client: AsyncClient, auth_headers: dict):
        """Test creating a reference item."""
        response = await client.post(
            f"{settings.api_prefix}/references",
            headers=auth_headers,
            json={
                "title": "Test Reference",
                "content": "This is test content for the reference item.",
                "category": "testing",
                "tags": ["test", "example"],
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "Test Reference"
        assert data["category"] == "testing"
        assert "test" in data["tags"]

    async def test_create_reference_minimal(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Test creating a reference with minimal fields."""
        response = await client.post(
            f"{settings.api_prefix}/references",
            headers=auth_headers,
            json={
                "title": "Minimal Reference",
                "content": "Just the basics.",
            },
        )
        assert response.status_code == 201

    async def test_create_reference_no_auth(self, client: AsyncClient):
        """Test creating reference without authentication."""
        response = await client.post(
            f"{settings.api_prefix}/references",
            json={
                "title": "Test",
                "content": "Content",
            },
        )
        assert response.status_code == 401


class TestReferenceList:
    """Tests for listing reference items."""

    async def test_list_references_empty(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Test listing when no references exist."""
        response = await client.get(
            f"{settings.api_prefix}/references",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data

    async def test_list_references_with_filter(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_user: User,
        db_session: AsyncSession,
    ):
        """Test listing references with category filter."""
        # Create test references
        for i, category in enumerate(["work", "work", "personal"]):
            item = ReferenceItem(
                owner_id=test_user.id,
                title=f"Reference {i}",
                content=f"Content {i}",
                category=category,
            )
            db_session.add(item)
        await db_session.commit()

        response = await client.get(
            f"{settings.api_prefix}/references",
            headers=auth_headers,
            params={"category": "work"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2


class TestReferenceUpdate:
    """Tests for updating reference items."""

    async def test_update_reference(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_user: User,
        db_session: AsyncSession,
    ):
        """Test updating a reference item."""
        item = ReferenceItem(
            owner_id=test_user.id,
            title="Original Title",
            content="Original content",
        )
        db_session.add(item)
        await db_session.commit()
        await db_session.refresh(item)

        response = await client.put(
            f"{settings.api_prefix}/references/{item.id}",
            headers=auth_headers,
            json={
                "title": "Updated Title",
                "content": "Updated content",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Updated Title"

    async def test_update_nonexistent(self, client: AsyncClient, auth_headers: dict):
        """Test updating non-existent reference."""
        fake_id = uuid.uuid4()
        response = await client.put(
            f"{settings.api_prefix}/references/{fake_id}",
            headers=auth_headers,
            json={"title": "New Title"},
        )
        assert response.status_code == 404


class TestReferenceDelete:
    """Tests for deleting reference items."""

    async def test_delete_reference(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_user: User,
        db_session: AsyncSession,
    ):
        """Test deleting a reference item."""
        item = ReferenceItem(
            owner_id=test_user.id,
            title="To Delete",
            content="Will be deleted",
        )
        db_session.add(item)
        await db_session.commit()
        await db_session.refresh(item)

        response = await client.delete(
            f"{settings.api_prefix}/references/{item.id}",
            headers=auth_headers,
        )
        assert response.status_code == 204

    async def test_delete_other_users_reference(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
    ):
        """Test deleting another user's reference."""
        other_user_id = uuid.uuid4()
        item = ReferenceItem(
            owner_id=other_user_id,
            title="Other's Item",
            content="Not yours",
        )
        db_session.add(item)
        await db_session.commit()
        await db_session.refresh(item)

        response = await client.delete(
            f"{settings.api_prefix}/references/{item.id}",
            headers=auth_headers,
        )
        assert response.status_code == 404


class TestReferenceCategories:
    """Tests for reference categories endpoint."""

    async def test_list_categories(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_user: User,
        db_session: AsyncSession,
    ):
        """Test listing unique categories."""
        categories = ["work", "personal", "work", "ideas"]
        for i, cat in enumerate(categories):
            item = ReferenceItem(
                owner_id=test_user.id,
                title=f"Item {i}",
                content=f"Content {i}",
                category=cat,
            )
            db_session.add(item)
        await db_session.commit()

        response = await client.get(
            f"{settings.api_prefix}/references/categories/list",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3  # unique categories
        assert sorted(data) == ["ideas", "personal", "work"]
