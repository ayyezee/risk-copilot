"""Tests for authentication endpoints."""

import pytest
from httpx import AsyncClient

from app.config import get_settings
from app.models.database import User

settings = get_settings()


class TestRegistration:
    """Tests for user registration."""

    async def test_register_success(self, client: AsyncClient):
        """Test successful user registration."""
        response = await client.post(
            f"{settings.api_prefix}/auth/register",
            json={
                "email": "newuser@example.com",
                "password": "ValidPass123",
                "full_name": "New User",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "newuser@example.com"
        assert data["full_name"] == "New User"
        assert "id" in data

    async def test_register_duplicate_email(self, client: AsyncClient, test_user: User):
        """Test registration with existing email."""
        response = await client.post(
            f"{settings.api_prefix}/auth/register",
            json={
                "email": test_user.email,
                "password": "ValidPass123",
            },
        )
        assert response.status_code == 409

    async def test_register_weak_password(self, client: AsyncClient):
        """Test registration with weak password."""
        response = await client.post(
            f"{settings.api_prefix}/auth/register",
            json={
                "email": "weak@example.com",
                "password": "weak",
            },
        )
        assert response.status_code == 422


class TestLogin:
    """Tests for user login."""

    async def test_login_success(self, client: AsyncClient, test_user: User):
        """Test successful login."""
        response = await client.post(
            f"{settings.api_prefix}/auth/login",
            json={
                "email": test_user.email,
                "password": "TestPassword123",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    async def test_login_wrong_password(self, client: AsyncClient, test_user: User):
        """Test login with wrong password."""
        response = await client.post(
            f"{settings.api_prefix}/auth/login",
            json={
                "email": test_user.email,
                "password": "WrongPassword123",
            },
        )
        assert response.status_code == 401

    async def test_login_nonexistent_user(self, client: AsyncClient):
        """Test login with non-existent user."""
        response = await client.post(
            f"{settings.api_prefix}/auth/login",
            json={
                "email": "nonexistent@example.com",
                "password": "SomePassword123",
            },
        )
        assert response.status_code == 401


class TestTokenRefresh:
    """Tests for token refresh."""

    async def test_refresh_token_success(self, client: AsyncClient, test_user: User):
        """Test successful token refresh."""
        # First login to get tokens
        login_response = await client.post(
            f"{settings.api_prefix}/auth/login",
            json={
                "email": test_user.email,
                "password": "TestPassword123",
            },
        )
        tokens = login_response.json()

        # Refresh the token
        response = await client.post(
            f"{settings.api_prefix}/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data

    async def test_refresh_invalid_token(self, client: AsyncClient):
        """Test refresh with invalid token."""
        response = await client.post(
            f"{settings.api_prefix}/auth/refresh",
            json={"refresh_token": "invalid-token"},
        )
        assert response.status_code == 401


class TestCurrentUser:
    """Tests for current user endpoint."""

    async def test_get_current_user(
        self, client: AsyncClient, test_user: User, auth_headers: dict
    ):
        """Test getting current user info."""
        response = await client.get(
            f"{settings.api_prefix}/auth/me",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == test_user.email
        assert data["id"] == str(test_user.id)

    async def test_get_current_user_no_auth(self, client: AsyncClient):
        """Test getting current user without authentication."""
        response = await client.get(f"{settings.api_prefix}/auth/me")
        assert response.status_code == 401


class TestPasswordChange:
    """Tests for password change."""

    async def test_change_password_success(
        self, client: AsyncClient, test_user: User, auth_headers: dict
    ):
        """Test successful password change."""
        response = await client.put(
            f"{settings.api_prefix}/auth/password",
            headers=auth_headers,
            json={
                "current_password": "TestPassword123",
                "new_password": "NewPassword456",
            },
        )
        assert response.status_code == 204

    async def test_change_password_wrong_current(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Test password change with wrong current password."""
        response = await client.put(
            f"{settings.api_prefix}/auth/password",
            headers=auth_headers,
            json={
                "current_password": "WrongPassword",
                "new_password": "NewPassword456",
            },
        )
        assert response.status_code == 400
