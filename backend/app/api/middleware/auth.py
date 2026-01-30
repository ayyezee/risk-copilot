"""Authentication middleware and dependencies."""

import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationError, AuthorizationError
from app.core.security import decode_token
from app.models.database import User, get_db_session

security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> User:
    """Get the current authenticated user from JWT token."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_token(credentials.credentials, token_type="access")
        user_id = payload.get("sub")
        if user_id is None:
            raise AuthenticationError("Invalid token payload")

        result = await db.execute(
            select(User).where(User.id == uuid.UUID(user_id))
        )
        user = result.scalar_one_or_none()

        if user is None:
            raise AuthenticationError("User not found")

        if not user.is_active:
            raise AuthenticationError("User account is disabled")

        return user
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Get current user and verify they are active."""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )
    return current_user


async def get_current_verified_user(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> User:
    """Get current user and verify they are verified."""
    if not current_user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email verification required",
        )
    return current_user


async def get_current_superuser(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> User:
    """Get current user and verify they are a superuser."""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Superuser privileges required",
        )
    return current_user


def require_2fa_if_enabled(
    current_user: Annotated[User, Depends(get_current_active_user)],
    x_2fa_verified: Annotated[str | None, Header()] = None,
) -> User:
    """Verify 2FA if enabled for the user."""
    if current_user.totp_enabled and x_2fa_verified != "true":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Two-factor authentication required",
            headers={"X-2FA-Required": "true"},
        )
    return current_user


async def get_current_user_ws(
    token: str,
    db: AsyncSession,
) -> User:
    """Get current user from a token string (for WebSocket authentication).

    Unlike the regular get_current_user, this takes the token directly
    rather than from HTTP headers, since WebSocket connections pass
    auth tokens via query params.

    Args:
        token: The JWT access token
        db: Database session

    Returns:
        The authenticated User

    Raises:
        AuthenticationError: If authentication fails
    """
    try:
        payload = decode_token(token, token_type="access")
        user_id = payload.get("sub")
        if user_id is None:
            raise AuthenticationError("Invalid token payload")

        result = await db.execute(
            select(User).where(User.id == uuid.UUID(user_id))
        )
        user = result.scalar_one_or_none()

        if user is None:
            raise AuthenticationError("User not found")

        if not user.is_active:
            raise AuthenticationError("User account is disabled")

        return user
    except ValueError as e:
        raise AuthenticationError(str(e)) from e


# Type aliases for dependency injection
CurrentUser = Annotated[User, Depends(get_current_user)]
ActiveUser = Annotated[User, Depends(get_current_active_user)]
VerifiedUser = Annotated[User, Depends(get_current_verified_user)]
SuperUser = Annotated[User, Depends(get_current_superuser)]
