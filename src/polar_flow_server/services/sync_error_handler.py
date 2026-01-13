"""Sync error handler for consistent error classification and retry strategies.

This module provides centralized error handling for all sync operations, ensuring:
- Consistent error classification into SyncErrorType categories
- Appropriate retry strategies based on error type
- Comprehensive error details for debugging
- Clear separation between transient and permanent failures

Error Classification:

    TRANSIENT (can retry):
    - TOKEN_EXPIRED: OAuth token needs refresh, retry with new token
    - RATE_LIMITED_15M: Hit 15-min limit, backoff ~15 minutes
    - RATE_LIMITED_24H: Hit 24-hour limit, backoff ~24 hours
    - API_UNAVAILABLE: Polar API down, exponential backoff
    - API_TIMEOUT: Request timed out, retry with longer timeout
    - DATABASE_ERROR: DB connection issue, retry after reconnect

    PERMANENT (don't retry automatically):
    - TOKEN_INVALID: Token is malformed, user needs to re-auth
    - TOKEN_REVOKED: User revoked access, user needs to re-auth
    - API_ERROR: Polar API returned error response
    - INVALID_RESPONSE: Response schema mismatch
    - TRANSFORM_ERROR: Data transformation failed
    - INTERNAL_ERROR: Unexpected internal error
"""

from dataclasses import dataclass
from typing import Any

import httpx
import structlog
from polar_flow.exceptions import (
    AuthenticationError,
    PolarFlowError,
    RateLimitError,
)
from sqlalchemy.exc import SQLAlchemyError

from polar_flow_server.models.sync_log import SyncErrorType

logger = structlog.get_logger()


@dataclass
class SyncError:
    """Structured sync error with classification and retry info.

    Attributes:
        error_type: Categorized error type for consistent handling
        message: Human-readable error message
        details: Additional error context as dict
        retry_after_seconds: Seconds to wait before retry (None if no retry)
        is_transient: Whether error is temporary and can be retried
        original_exception: The original exception that caused this error
    """

    error_type: SyncErrorType
    message: str
    details: dict[str, Any]
    retry_after_seconds: int | None
    is_transient: bool
    original_exception: Exception | None = None

    def to_log_dict(self) -> dict[str, Any]:
        """Convert to dict for structured logging.

        Returns:
            Dict suitable for structlog context
        """
        return {
            "error_type": self.error_type.value,
            "message": self.message,
            "is_transient": self.is_transient,
            "retry_after_seconds": self.retry_after_seconds,
            **self.details,
        }


class SyncErrorHandler:
    """Centralized error handler for sync operations.

    Classifies exceptions into SyncErrorType categories and provides
    consistent retry strategies across all sync operations.

    Usage:
        handler = SyncErrorHandler()

        try:
            await sync_user(user_id, token)
        except Exception as e:
            sync_error = handler.classify(e, context={"user_id": user_id})
            sync_log.complete_failed(
                error_type=sync_error.error_type,
                message=sync_error.message,
                details=sync_error.details,
            )
            if sync_error.is_transient:
                schedule_retry(user_id, delay=sync_error.retry_after_seconds)
    """

    def __init__(self) -> None:
        """Initialize error handler."""
        self.logger = logger.bind(component="sync_error_handler")

    def classify(
        self,
        exception: Exception,
        context: dict[str, Any] | None = None,
    ) -> SyncError:
        """Classify an exception into a SyncError.

        Examines the exception type and attributes to determine:
        - The appropriate SyncErrorType category
        - Whether the error is transient (retryable)
        - How long to wait before retrying

        Args:
            exception: The exception to classify
            context: Additional context (user_id, endpoint, etc.)

        Returns:
            SyncError with classification and retry info
        """
        context = context or {}

        # Polar SDK exceptions
        if isinstance(exception, RateLimitError):
            return self._handle_rate_limit(exception, context)
        if isinstance(exception, AuthenticationError):
            return self._handle_auth_error(exception, context)
        if isinstance(exception, PolarFlowError):
            return self._handle_polar_error(exception, context)

        # HTTP client exceptions
        if isinstance(exception, httpx.TimeoutException):
            return self._handle_timeout(exception, context)
        if isinstance(exception, httpx.ConnectError):
            return self._handle_connect_error(exception, context)
        if isinstance(exception, httpx.HTTPStatusError):
            return self._handle_http_status(exception, context)

        # Database exceptions
        if isinstance(exception, SQLAlchemyError):
            return self._handle_database_error(exception, context)

        # Transformation errors (ValueError, KeyError, TypeError in transforms)
        if isinstance(exception, (ValueError, KeyError, TypeError)):
            return self._handle_transform_error(exception, context)

        # Unknown exceptions
        return self._handle_unknown_error(exception, context)

    def _handle_rate_limit(
        self,
        exception: RateLimitError,
        context: dict[str, Any],
    ) -> SyncError:
        """Handle rate limit errors from Polar API.

        Polar has two rate limits:
        - 15-minute: 500 + (users × 20) requests
        - 24-hour: 5000 + (users × 100) requests

        We determine which limit was hit based on retry_after:
        - retry_after <= 900 (15 min): 15-minute limit
        - retry_after > 900: 24-hour limit
        """
        retry_after = exception.retry_after

        # Classify based on retry duration
        if retry_after <= 900:  # 15 minutes
            error_type = SyncErrorType.RATE_LIMITED_15M
            message = f"Rate limited by Polar API (15-min window). Retry after {retry_after}s."
        else:
            error_type = SyncErrorType.RATE_LIMITED_24H
            message = f"Rate limited by Polar API (24-hour window). Retry after {retry_after}s."

        self.logger.warning(
            "Rate limit hit",
            error_type=error_type.value,
            retry_after=retry_after,
            endpoint=exception.endpoint,
            **context,
        )

        return SyncError(
            error_type=error_type,
            message=message,
            details={
                "endpoint": exception.endpoint,
                "retry_after": retry_after,
                **context,
            },
            retry_after_seconds=retry_after,
            is_transient=True,
            original_exception=exception,
        )

    def _handle_auth_error(
        self,
        exception: AuthenticationError,
        context: dict[str, Any],
    ) -> SyncError:
        """Handle authentication errors.

        We classify based on status code and message:
        - 401 with "expired": Token expired, might be refreshable
        - 401 with "invalid": Token malformed or unrecognized
        - 401 with "revoked": User revoked access in Polar settings
        """
        message_lower = str(exception).lower()
        response_body = (exception.response_body or "").lower()

        # Try to determine specific auth failure type
        if "expired" in message_lower or "expired" in response_body:
            error_type = SyncErrorType.TOKEN_EXPIRED
            message = "Polar access token has expired. Token refresh required."
            is_transient = True  # Can retry with new token
            retry_after = 0  # Retry immediately with refreshed token
        elif "revoked" in message_lower or "revoked" in response_body:
            error_type = SyncErrorType.TOKEN_REVOKED
            message = "User revoked Polar access. Re-authentication required."
            is_transient = False  # User action required
            retry_after = None
        else:
            error_type = SyncErrorType.TOKEN_INVALID
            message = "Polar access token is invalid. Re-authentication required."
            is_transient = False  # User action required
            retry_after = None

        self.logger.error(
            "Authentication error",
            error_type=error_type.value,
            endpoint=exception.endpoint,
            **context,
        )

        return SyncError(
            error_type=error_type,
            message=message,
            details={
                "endpoint": exception.endpoint,
                "status_code": exception.status_code,
                **context,
            },
            retry_after_seconds=retry_after,
            is_transient=is_transient,
            original_exception=exception,
        )

    def _handle_polar_error(
        self,
        exception: PolarFlowError,
        context: dict[str, Any],
    ) -> SyncError:
        """Handle generic Polar API errors."""
        self.logger.error(
            "Polar API error",
            endpoint=exception.endpoint,
            status_code=exception.status_code,
            response=exception.response_body[:200] if exception.response_body else None,
            **context,
        )

        return SyncError(
            error_type=SyncErrorType.API_ERROR,
            message=f"Polar API error: {exception}",
            details={
                "endpoint": exception.endpoint,
                "status_code": exception.status_code,
                "response_body": exception.response_body[:500] if exception.response_body else None,
                **context,
            },
            retry_after_seconds=300,  # Retry in 5 minutes
            is_transient=True,  # API errors might be temporary
            original_exception=exception,
        )

    def _handle_timeout(
        self,
        exception: httpx.TimeoutException,
        context: dict[str, Any],
    ) -> SyncError:
        """Handle HTTP timeout errors."""
        self.logger.warning("API request timeout", error=str(exception), **context)

        return SyncError(
            error_type=SyncErrorType.API_TIMEOUT,
            message=f"Request timed out: {exception}",
            details={
                "error": str(exception),
                **context,
            },
            retry_after_seconds=60,  # Retry in 1 minute
            is_transient=True,
            original_exception=exception,
        )

    def _handle_connect_error(
        self,
        exception: httpx.ConnectError,
        context: dict[str, Any],
    ) -> SyncError:
        """Handle connection errors (API unreachable)."""
        self.logger.error("API connection failed", error=str(exception), **context)

        return SyncError(
            error_type=SyncErrorType.API_UNAVAILABLE,
            message=f"Failed to connect to Polar API: {exception}",
            details={
                "error": str(exception),
                **context,
            },
            retry_after_seconds=300,  # Retry in 5 minutes
            is_transient=True,
            original_exception=exception,
        )

    def _handle_http_status(
        self,
        exception: httpx.HTTPStatusError,
        context: dict[str, Any],
    ) -> SyncError:
        """Handle HTTP status errors not caught by SDK."""
        status_code = exception.response.status_code

        # Map status codes to error types
        if status_code == 401:
            error_type = SyncErrorType.TOKEN_INVALID
            is_transient = False
        elif status_code == 429:
            error_type = SyncErrorType.RATE_LIMITED_15M
            is_transient = True
        elif status_code >= 500:
            error_type = SyncErrorType.API_UNAVAILABLE
            is_transient = True
        else:
            error_type = SyncErrorType.API_ERROR
            is_transient = False

        self.logger.error(
            "HTTP status error",
            status_code=status_code,
            error_type=error_type.value,
            **context,
        )

        return SyncError(
            error_type=error_type,
            message=f"HTTP {status_code}: {exception}",
            details={
                "status_code": status_code,
                "url": str(exception.request.url),
                **context,
            },
            retry_after_seconds=300 if is_transient else None,
            is_transient=is_transient,
            original_exception=exception,
        )

    def _handle_database_error(
        self,
        exception: SQLAlchemyError,
        context: dict[str, Any],
    ) -> SyncError:
        """Handle database errors."""
        self.logger.error("Database error", error=str(exception), **context)

        return SyncError(
            error_type=SyncErrorType.DATABASE_ERROR,
            message=f"Database error: {exception}",
            details={
                "error_type": type(exception).__name__,
                "error": str(exception)[:500],
                **context,
            },
            retry_after_seconds=60,  # Retry in 1 minute
            is_transient=True,  # DB errors often transient
            original_exception=exception,
        )

    def _handle_transform_error(
        self,
        exception: ValueError | KeyError | TypeError,
        context: dict[str, Any],
    ) -> SyncError:
        """Handle data transformation errors."""
        self.logger.error(
            "Transform error",
            error_type=type(exception).__name__,
            error=str(exception),
            **context,
        )

        return SyncError(
            error_type=SyncErrorType.TRANSFORM_ERROR,
            message=f"Data transformation failed: {exception}",
            details={
                "error_type": type(exception).__name__,
                "error": str(exception),
                **context,
            },
            retry_after_seconds=None,  # Don't auto-retry data errors
            is_transient=False,  # Data errors need investigation
            original_exception=exception,
        )

    def _handle_unknown_error(
        self,
        exception: Exception,
        context: dict[str, Any],
    ) -> SyncError:
        """Handle unknown/unexpected errors."""
        self.logger.exception(
            "Unexpected sync error",
            error_type=type(exception).__name__,
            error=str(exception),
            **context,
        )

        return SyncError(
            error_type=SyncErrorType.INTERNAL_ERROR,
            message=f"Unexpected error: {type(exception).__name__}: {exception}",
            details={
                "error_type": type(exception).__name__,
                "error": str(exception)[:500],
                **context,
            },
            retry_after_seconds=300,  # Retry in 5 minutes cautiously
            is_transient=True,  # Assume transient, investigate logs
            original_exception=exception,
        )


# Default retry delays for each error type (seconds)
RETRY_DELAYS: dict[SyncErrorType, int | None] = {
    # Transient - will retry
    SyncErrorType.TOKEN_EXPIRED: 0,  # Retry immediately with refreshed token
    SyncErrorType.RATE_LIMITED_15M: 900,  # 15 minutes
    SyncErrorType.RATE_LIMITED_24H: 86400,  # 24 hours
    SyncErrorType.API_UNAVAILABLE: 300,  # 5 minutes
    SyncErrorType.API_TIMEOUT: 60,  # 1 minute
    SyncErrorType.DATABASE_ERROR: 60,  # 1 minute
    # Permanent - won't auto-retry
    SyncErrorType.TOKEN_INVALID: None,
    SyncErrorType.TOKEN_REVOKED: None,
    SyncErrorType.API_ERROR: None,
    SyncErrorType.INVALID_RESPONSE: None,
    SyncErrorType.TRANSFORM_ERROR: None,
    SyncErrorType.INTERNAL_ERROR: None,
}


def get_retry_delay(error_type: SyncErrorType) -> int | None:
    """Get the default retry delay for an error type.

    Args:
        error_type: The categorized error type

    Returns:
        Seconds to wait before retry, or None if no retry
    """
    return RETRY_DELAYS.get(error_type)


def is_retryable(error_type: SyncErrorType) -> bool:
    """Check if an error type is retryable.

    Args:
        error_type: The categorized error type

    Returns:
        True if the error can be retried automatically
    """
    return RETRY_DELAYS.get(error_type) is not None
