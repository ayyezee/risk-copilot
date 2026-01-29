"""Custom exceptions for the application."""

from typing import Any


class AppException(Exception):
    """Base exception for application errors."""

    def __init__(
        self,
        message: str,
        status_code: int = 500,
        error_code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message
        self.status_code = status_code
        self.error_code = error_code or self.__class__.__name__
        self.details = details or {}
        super().__init__(message)


class AuthenticationError(AppException):
    """Raised when authentication fails."""

    def __init__(self, message: str = "Authentication failed", **kwargs: Any) -> None:
        super().__init__(message, status_code=401, **kwargs)


class AuthorizationError(AppException):
    """Raised when user lacks permission."""

    def __init__(self, message: str = "Permission denied", **kwargs: Any) -> None:
        super().__init__(message, status_code=403, **kwargs)


class NotFoundError(AppException):
    """Raised when a resource is not found."""

    def __init__(self, resource: str = "Resource", **kwargs: Any) -> None:
        super().__init__(f"{resource} not found", status_code=404, **kwargs)


class ValidationError(AppException):
    """Raised when validation fails."""

    def __init__(self, message: str = "Validation failed", **kwargs: Any) -> None:
        super().__init__(message, status_code=422, **kwargs)


class ConflictError(AppException):
    """Raised when there's a resource conflict."""

    def __init__(self, message: str = "Resource conflict", **kwargs: Any) -> None:
        super().__init__(message, status_code=409, **kwargs)


class RateLimitError(AppException):
    """Raised when rate limit is exceeded."""

    def __init__(self, message: str = "Rate limit exceeded", **kwargs: Any) -> None:
        super().__init__(message, status_code=429, **kwargs)


class FileProcessingError(AppException):
    """Raised when file processing fails."""

    def __init__(self, message: str = "File processing failed", **kwargs: Any) -> None:
        super().__init__(message, status_code=500, **kwargs)


class AIServiceError(AppException):
    """Raised when AI service encounters an error."""

    def __init__(self, message: str = "AI service error", **kwargs: Any) -> None:
        super().__init__(message, status_code=502, **kwargs)


class StorageError(AppException):
    """Raised when storage operations fail."""

    def __init__(self, message: str = "Storage operation failed", **kwargs: Any) -> None:
        super().__init__(message, status_code=500, **kwargs)


class TwoFactorRequiredError(AppException):
    """Raised when 2FA verification is required."""

    def __init__(self, message: str = "Two-factor authentication required", **kwargs: Any) -> None:
        super().__init__(message, status_code=403, error_code="2FA_REQUIRED", **kwargs)


class InvalidTwoFactorCodeError(AppException):
    """Raised when 2FA code is invalid."""

    def __init__(self, message: str = "Invalid two-factor code", **kwargs: Any) -> None:
        super().__init__(message, status_code=401, **kwargs)
