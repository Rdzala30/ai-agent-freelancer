"""Utils package for LeadHunter AI."""

from .error_handler import (
    AuthErrorException,
    DEFAULT_ERRORS_LOG_PATH,
    ERROR_AUTH_ERROR,
    ERROR_INVALID_INPUT,
    ERROR_NOT_FOUND,
    ERROR_PERMANENT,
    ERROR_QUOTA_EXCEEDED,
    ERROR_RATE_LIMIT,
    ERROR_TRANSIENT,
    ERROR_UNKNOWN,
    QuotaExceededException,
    StopPipelineException,
    classify_error,
    log_error,
    retry_with_backoff,
)

__all__ = [
    "classify_error",
    "retry_with_backoff",
    "log_error",
    "StopPipelineException",
    "AuthErrorException",
    "QuotaExceededException",
    "ERROR_TRANSIENT",
    "ERROR_RATE_LIMIT",
    "ERROR_AUTH_ERROR",
    "ERROR_QUOTA_EXCEEDED",
    "ERROR_INVALID_INPUT",
    "ERROR_NOT_FOUND",
    "ERROR_PERMANENT",
    "ERROR_UNKNOWN",
    "DEFAULT_ERRORS_LOG_PATH",
]
