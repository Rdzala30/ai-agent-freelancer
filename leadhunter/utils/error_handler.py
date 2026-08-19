"""Error handling and classification module for LeadHunter AI.

Classifies exceptions into standard error categories:
- TRANSIENT: Retry with exponential backoff (2s, 4s, 8s)
- RATE_LIMIT: Inspect Retry-After header, wait and retry once
- AUTH_ERROR: Stop immediately, print clear error message, do not retry
- QUOTA_EXCEEDED: Stop the entire batch, preserve all completed work
- INVALID_INPUT: Log, skip lead, continue
- NOT_FOUND: Log, skip lead, continue
- PERMANENT: Log, skip lead, continue
- UNKNOWN: Default fallback

Logs all errors to data/logs/errors.log with timestamps and lead_ids.
"""

from __future__ import annotations

import functools
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar

T = TypeVar("T")

# Error Classifications
ERROR_TRANSIENT = "TRANSIENT"
ERROR_RATE_LIMIT = "RATE_LIMIT"
ERROR_AUTH_ERROR = "AUTH_ERROR"
ERROR_QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
ERROR_INVALID_INPUT = "INVALID_INPUT"
ERROR_NOT_FOUND = "NOT_FOUND"
ERROR_PERMANENT = "PERMANENT"
ERROR_UNKNOWN = "UNKNOWN"

DEFAULT_ERRORS_LOG_PATH = Path("./data/logs/errors.log")


class StopPipelineException(Exception):
    """Raised when an unrecoverable batch-level error occurs (Auth / Quota)."""
    pass


class AuthErrorException(StopPipelineException):
    """Raised when API credentials / authentication fails."""
    pass


class QuotaExceededException(StopPipelineException):
    """Raised when an account quota / credit balance is completely exhausted."""
    pass


def log_error(
    exc: BaseException,
    lead_id: Optional[int] = None,
    context: str = "",
    error_type: Optional[str] = None,
    log_path: Optional[Path] = None,
) -> None:
    """Log structured error entry to local errors.log file."""
    if error_type is None:
        error_type = classify_error(exc)

    if log_path is None:
        log_path = DEFAULT_ERRORS_LOG_PATH

    log_path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lead_str = f"LeadID: {lead_id}" if lead_id is not None else "LeadID: N/A"
    context_str = f"[{context}]" if context else ""
    exc_name = exc.__class__.__name__
    exc_msg = str(exc).replace("\n", " ")

    line = f"{ts} | {error_type:<14} | {lead_str:<14} | {context_str:<24} | {exc_name}: {exc_msg}\n"

    try:
        with open(log_path, mode="a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def classify_error(exc: BaseException) -> str:
    """Classify any exception into standard LeadHunter error types."""
    exc_str = str(exc).lower()
    exc_type = type(exc).__name__.lower()

    # 1. Quota Exceeded
    quota_keywords = [
        "quota exceeded",
        "insufficient quota",
        "credit balance",
        "run out of searches",
        "out of searches",
        "plan limit exceeded",
        "exceeded your current quota",
        "billing",
    ]
    if any(k in exc_str for k in quota_keywords) or isinstance(exc, QuotaExceededException):
        return ERROR_QUOTA_EXCEEDED

    # 2. Rate Limit (HTTP 429 / Too Many Requests)
    if "429" in exc_str or "too many requests" in exc_str or "rate limit" in exc_str or "resourceexhausted" in exc_str:
        return ERROR_RATE_LIMIT

    # 3. Auth Error (HTTP 401 / 403 / Invalid key)
    auth_keywords = [
        "401",
        "403",
        "unauthorized",
        "forbidden",
        "invalid api key",
        "authentication failed",
        "permission denied",
        "invalid credentials",
        "bad credentials",
        "invalid_api_key",
        "api key is invalid",
    ]
    if any(k in exc_str for k in auth_keywords) or isinstance(exc, AuthErrorException):
        return ERROR_AUTH_ERROR

    # 4. Not Found (HTTP 404 / NotFoundError)
    if "404" in exc_str or "not found" in exc_str or "notfounderror" in exc_type:
        return ERROR_NOT_FOUND

    # 5. Invalid Input (HTTP 400 / validation error)
    if "400" in exc_str or "bad request" in exc_str or "validation" in exc_str or "valueerror" in exc_type:
        return ERROR_INVALID_INPUT

    # 6. Transient Network / Server Errors (Timeouts, DNS, 500, 502, 503, 504)
    transient_keywords = [
        "timeout",
        "timed out",
        "connection reset",
        "connection refused",
        "connectionerror",
        "connecterror",
        "readerror",
        "remotedisconnected",
        "socket",
        "500",
        "502",
        "503",
        "504",
        "service unavailable",
        "bad gateway",
        "gateway timeout",
        "server error",
    ]
    if any(k in exc_str for k in transient_keywords):
        return ERROR_TRANSIENT

    # 7. Permanent Errors (SSL error, certificate verify failed, unresolvable domain)
    permanent_keywords = [
        "ssl",
        "certificate verify failed",
        "nameresolutionerror",
        "gaierror",
        "unsupported",
    ]
    if any(k in exc_str for k in permanent_keywords):
        return ERROR_PERMANENT

    return ERROR_UNKNOWN


def extract_retry_after(exc: BaseException, default_wait: float = 60.0) -> float:
    """Extract Retry-After header seconds if available in exception response."""
    # Check if exception has response headers
    response = getattr(exc, "response", None)
    if response is not None:
        headers = getattr(response, "headers", {})
        retry_after = headers.get("retry-after") or headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass
    return default_wait


def retry_with_backoff(
    func: Callable[..., T],
    max_retries: int = 3,
    base_delay: float = 2.0,
    lead_id: Optional[int] = None,
    context: str = "",
    *args: Any,
    **kwargs: Any,
) -> T:
    """Execute function with robust classification-aware retry logic:
    - TRANSIENT: Retry with exponential backoff (2s, 4s, 8s)
    - RATE_LIMIT: Inspect Retry-After header, wait that duration, retry once
    - AUTH_ERROR: Stop immediately, print clear error message, do not retry
    - QUOTA_EXCEEDED: Stop the entire batch, preserve all completed work
    - PERMANENT / INVALID_INPUT / NOT_FOUND: Log and skip
    """
    attempt = 0
    while True:
        try:
            return func(*args, **kwargs)
        except BaseException as exc:
            attempt += 1
            err_type = classify_error(exc)
            log_error(exc, lead_id=lead_id, context=context, error_type=err_type)

            # 1. AUTH_ERROR: Stop immediately
            if err_type == ERROR_AUTH_ERROR:
                msg = f"❌ [AUTH ERROR] Authentication failed in {context or 'operation'}: {exc}. Halting execution immediately."
                print(msg, file=sys.stderr)
                raise AuthErrorException(msg) from exc

            # 2. QUOTA_EXCEEDED: Stop batch execution
            elif err_type == ERROR_QUOTA_EXCEEDED:
                msg = f"⚠️ [QUOTA EXCEEDED] Account quota/credits exhausted in {context or 'operation'}: {exc}. Preserving all completed work and stopping."
                print(msg, file=sys.stderr)
                raise QuotaExceededException(msg) from exc

            # 3. RATE_LIMIT: Retry once with Retry-After wait
            elif err_type == ERROR_RATE_LIMIT:
                if attempt <= 1:
                    wait_s = extract_retry_after(exc, default_wait=60.0)
                    print(f"⏳ [RATE LIMIT] Rate limit hit in {context or 'operation'}. Backing off for {wait_s:.1f}s before retry...", file=sys.stderr)
                    time.sleep(wait_s)
                    continue
                else:
                    print(f"❌ [RATE LIMIT] Rate limit persists after retry in {context or 'operation'}. Halting batch.", file=sys.stderr)
                    raise StopPipelineException(f"Rate limit exceeded in {context}") from exc

            # 4. TRANSIENT: Exponential backoff
            elif err_type == ERROR_TRANSIENT:
                if attempt <= max_retries:
                    delay = base_delay * (2 ** (attempt - 1))
                    print(f"🔄 [TRANSIENT] Retryable error in {context} (attempt {attempt}/{max_retries}). Retrying in {delay:.1f}s...", file=sys.stderr)
                    time.sleep(delay)
                    continue
                else:
                    print(f"❌ [TRANSIENT] Exhausted {max_retries} retries in {context}. Skipping.", file=sys.stderr)
                    raise

            # 5. PERMANENT / INVALID_INPUT / NOT_FOUND / UNKNOWN: Do not retry
            else:
                print(f"⚠️ [{err_type}] Unrecoverable error in {context}: {exc}. Skipping lead {lead_id or 'N/A'}.", file=sys.stderr)
                raise
