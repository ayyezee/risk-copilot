"""Authentication routes."""

import base64
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.middleware.auth import ActiveUser, CurrentUser
from app.config import get_settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_backup_codes,
    generate_totp_qr_code,
    generate_totp_secret,
    hash_backup_code,
    hash_password,
    validate_totp_code,
    verify_backup_code,
    verify_password,
)
from app.models.database import RefreshToken, User, get_db_session
from app.models.schemas import (
    PasswordChange,
    TokenRefresh,
    TokenResponse,
    TwoFactorBackupCode,
    TwoFactorSetupResponse,
    TwoFactorVerify,
    UserCreate,
    UserLogin,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserCreate,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> User:
    """Register a new user."""
    # Check if email already exists
    result = await db.execute(select(User).where(User.email == user_data.email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    # Create user
    user = User(
        email=user_data.email,
        hashed_password=hash_password(user_data.password),
        full_name=user_data.full_name,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)

    return user


@router.post("/login", response_model=TokenResponse)
async def login(
    credentials: UserLogin,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> TokenResponse:
    """Authenticate user and return tokens."""
    # Find user
    result = await db.execute(select(User).where(User.email == credentials.email))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )

    # Check 2FA if enabled
    if user.totp_enabled:
        if not credentials.totp_code:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Two-factor authentication code required",
                headers={"X-2FA-Required": "true"},
            )
        validate_totp_code(user.totp_secret, credentials.totp_code)

    # Create tokens
    access_token = create_access_token({"sub": str(user.id)})
    refresh_token = create_refresh_token({"sub": str(user.id)})

    # Store refresh token
    token_data = decode_token(refresh_token, token_type="refresh")
    db_token = RefreshToken(
        token_id=token_data["jti"],
        user_id=user.id,
        expires_at=datetime.fromtimestamp(token_data["exp"], tz=UTC),
    )
    db.add(db_token)

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    token_data: TokenRefresh,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> TokenResponse:
    """Refresh access token using refresh token."""
    try:
        payload = decode_token(token_data.refresh_token, token_type="refresh")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        ) from e

    # Check if token is revoked
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_id == payload["jti"],
            RefreshToken.revoked == False,
        )
    )
    db_token = result.scalar_one_or_none()

    if db_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
        )

    # Revoke old token
    db_token.revoked = True

    # Create new tokens
    access_token = create_access_token({"sub": payload["sub"]})
    new_refresh_token = create_refresh_token({"sub": payload["sub"]})

    # Store new refresh token
    new_token_data = decode_token(new_refresh_token, token_type="refresh")
    new_db_token = RefreshToken(
        token_id=new_token_data["jti"],
        user_id=uuid.UUID(payload["sub"]),
        expires_at=datetime.fromtimestamp(new_token_data["exp"], tz=UTC),
    )
    db.add(new_db_token)

    return TokenResponse(access_token=access_token, refresh_token=new_refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    token_data: TokenRefresh,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    """Logout user by revoking refresh token."""
    try:
        payload = decode_token(token_data.refresh_token, token_type="refresh")
        result = await db.execute(
            select(RefreshToken).where(RefreshToken.token_id == payload["jti"])
        )
        db_token = result.scalar_one_or_none()
        if db_token:
            db_token.revoked = True
    except Exception:
        pass  # Ignore invalid tokens during logout


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: CurrentUser) -> User:
    """Get current user information."""
    return current_user


@router.put("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    password_data: PasswordChange,
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    """Change user password."""
    if not verify_password(password_data.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    current_user.hashed_password = hash_password(password_data.new_password)


# 2FA endpoints
@router.post("/2fa/setup", response_model=TwoFactorSetupResponse)
async def setup_2fa(
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> TwoFactorSetupResponse:
    """Setup two-factor authentication."""
    if current_user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA is already enabled",
        )

    # Generate secret and backup codes
    secret = generate_totp_secret()
    backup_codes = generate_backup_codes()

    # Store secret temporarily (not enabled yet)
    current_user.totp_secret = secret
    current_user.backup_codes = [hash_backup_code(code) for code in backup_codes]

    # Generate QR code
    qr_code = generate_totp_qr_code(secret, current_user.email)
    qr_code_base64 = base64.b64encode(qr_code).decode()

    return TwoFactorSetupResponse(
        secret=secret,
        qr_code_base64=qr_code_base64,
        backup_codes=backup_codes,
    )


@router.post("/2fa/enable", status_code=status.HTTP_204_NO_CONTENT)
async def enable_2fa(
    verification: TwoFactorVerify,
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    """Enable 2FA after verifying code."""
    if current_user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA is already enabled",
        )

    if not current_user.totp_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA setup not initiated. Call /2fa/setup first",
        )

    validate_totp_code(current_user.totp_secret, verification.code)
    current_user.totp_enabled = True


@router.post("/2fa/disable", status_code=status.HTTP_204_NO_CONTENT)
async def disable_2fa(
    verification: TwoFactorVerify,
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    """Disable 2FA after verifying code."""
    if not current_user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA is not enabled",
        )

    validate_totp_code(current_user.totp_secret, verification.code)

    current_user.totp_enabled = False
    current_user.totp_secret = None
    current_user.backup_codes = None


@router.post("/2fa/backup", response_model=TokenResponse)
async def use_backup_code(
    backup_data: TwoFactorBackupCode,
    credentials: UserLogin,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> TokenResponse:
    """Login using a backup code instead of TOTP."""
    # Find user
    result = await db.execute(select(User).where(User.email == credentials.email))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.totp_enabled or not user.backup_codes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA is not enabled or no backup codes available",
        )

    # Find and verify backup code
    code_used = None
    for i, hashed_code in enumerate(user.backup_codes):
        if verify_backup_code(backup_data.backup_code, hashed_code):
            code_used = i
            break

    if code_used is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid backup code",
        )

    # Remove used backup code
    user.backup_codes = [c for i, c in enumerate(user.backup_codes) if i != code_used]

    # Create tokens
    access_token = create_access_token({"sub": str(user.id)})
    refresh_token = create_refresh_token({"sub": str(user.id)})

    # Store refresh token
    token_data = decode_token(refresh_token, token_type="refresh")
    db_token = RefreshToken(
        token_id=token_data["jti"],
        user_id=user.id,
        expires_at=datetime.fromtimestamp(token_data["exp"], tz=UTC),
    )
    db.add(db_token)

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)
