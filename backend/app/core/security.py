"""Security utilities: JWT tokens, password hashing, and 2FA."""

import secrets
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any

import pyotp
import qrcode
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings
from app.core.exceptions import AuthenticationError, InvalidTwoFactorCodeError

settings = get_settings()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    expire = datetime.now(UTC) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(data: dict[str, Any]) -> str:
    """Create a JWT refresh token."""
    to_encode = data.copy()
    expire = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
    to_encode.update({"exp": expire, "type": "refresh", "jti": secrets.token_urlsafe(32)})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str, token_type: str = "access") -> dict[str, Any]:
    """Decode and validate a JWT token."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
        if payload.get("type") != token_type:
            raise AuthenticationError("Invalid token type")
        return payload
    except JWTError as e:
        raise AuthenticationError(f"Invalid token: {e}") from e


def generate_totp_secret() -> str:
    """Generate a new TOTP secret for 2FA setup."""
    return pyotp.random_base32()


def get_totp_uri(secret: str, email: str) -> str:
    """Get the TOTP provisioning URI for QR code generation."""
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=email, issuer_name=settings.totp_issuer)


def generate_totp_qr_code(secret: str, email: str) -> bytes:
    """Generate a QR code image for TOTP setup."""
    uri = get_totp_uri(secret, email)
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def verify_totp(secret: str, code: str) -> bool:
    """Verify a TOTP code."""
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)


def validate_totp_code(secret: str, code: str) -> None:
    """Validate a TOTP code, raising an exception if invalid."""
    if not verify_totp(secret, code):
        raise InvalidTwoFactorCodeError()


def generate_backup_codes(count: int = 10) -> list[str]:
    """Generate backup codes for 2FA recovery."""
    return [secrets.token_hex(4).upper() for _ in range(count)]


def hash_backup_code(code: str) -> str:
    """Hash a backup code for storage."""
    return pwd_context.hash(code.lower())


def verify_backup_code(plain_code: str, hashed_code: str) -> bool:
    """Verify a backup code against its hash."""
    return pwd_context.verify(plain_code.lower(), hashed_code)
