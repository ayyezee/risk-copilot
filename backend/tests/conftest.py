"""Pytest configuration and fixtures."""

import asyncio
import uuid
from collections.abc import AsyncGenerator, Generator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings, get_settings
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.database import Base, User, get_db_session


# Test settings override
def get_test_settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/docprocessor_test",
        redis_url="redis://localhost:6379/15",
        secret_key="test-secret-key-for-testing-only",
        debug=True,
        environment="development",
    )


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """Create test database engine."""
    settings = get_test_settings()
    engine = create_async_engine(str(settings.database_url), echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session."""
    async_session = async_sessionmaker(test_engine, expire_on_commit=False)

    async with async_session() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create a test HTTP client."""

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db
    app.dependency_overrides[get_settings] = get_test_settings

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    """Create a test user."""
    user = User(
        id=uuid.uuid4(),
        email="test@example.com",
        hashed_password=hash_password("TestPassword123"),
        full_name="Test User",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def auth_headers(test_user: User) -> dict[str, str]:
    """Create authentication headers for test user."""
    access_token = create_access_token({"sub": str(test_user.id)})
    return {"Authorization": f"Bearer {access_token}"}


@pytest_asyncio.fixture
async def superuser(db_session: AsyncSession) -> User:
    """Create a superuser for testing."""
    user = User(
        id=uuid.uuid4(),
        email="admin@example.com",
        hashed_password=hash_password("AdminPassword123"),
        full_name="Admin User",
        is_active=True,
        is_verified=True,
        is_superuser=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def superuser_headers(superuser: User) -> dict[str, str]:
    """Create authentication headers for superuser."""
    access_token = create_access_token({"sub": str(superuser.id)})
    return {"Authorization": f"Bearer {access_token}"}
