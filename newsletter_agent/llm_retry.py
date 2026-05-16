"""Global retry wrapper for Anthropic API calls.

Handles transient errors (529 overloaded, 529 rate-limit, 500 server error,
connection resets) with exponential back-off + jitter.

Usage:
    from newsletter_agent.llm_retry import llm_call_with_retry

    message = llm_call_with_retry(client.messages.create, **kwargs)
"""
from __future__ import annotations
import time
import random
import logging

log = logging.getLogger(__name__)

# HTTP status codes / error types that are worth retrying
_RETRYABLE_STATUS = {429, 500, 529}
_RETRYABLE_TYPES  = {"overloaded_error", "rate_limit_error", "api_error"}

_DEFAULT_RETRIES = 6
_BASE_DELAY      = 2.0   # seconds before first retry
_MAX_DELAY       = 60.0  # cap on any single sleep


def _is_retryable(exc: Exception) -> bool:
    """Return True if this Anthropic exception is worth retrying."""
    cls_name = type(exc).__name__
    # anthropic SDK raises APIStatusError subclasses
    status = getattr(exc, "status_code", None)
    if status in _RETRYABLE_STATUS:
        return True
    # Check error body for type field
    body = getattr(exc, "body", None) or {}
    if isinstance(body, dict):
        err = body.get("error", {})
        if isinstance(err, dict) and err.get("type") in _RETRYABLE_TYPES:
            return True
    # Fallback: class name heuristic
    return any(t in cls_name for t in ("Overloaded", "RateLimit", "InternalServer", "APIConnectionError"))


def llm_call_with_retry(fn, retries: int = _DEFAULT_RETRIES, **kwargs):
    """Call *fn(**kwargs)* with exponential back-off on retryable Anthropic errors.

    Args:
        fn: callable — typically client.messages.create
        retries: maximum number of attempts (default 6)
        **kwargs: forwarded to fn

    Returns:
        The successful response from fn.

    Raises:
        The last exception if all retries are exhausted.
    """
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            return fn(**kwargs)
        except Exception as exc:
            if not _is_retryable(exc):
                raise
            last_exc = exc
            delay = min(_BASE_DELAY * (2 ** attempt) + random.uniform(0, 1), _MAX_DELAY)
            print(
                f"  [llm_retry] Attempt {attempt + 1}/{retries} failed "
                f"({type(exc).__name__}: {str(exc)[:80]}). "
                f"Retrying in {delay:.1f}s..."
            )
            time.sleep(delay)
    raise last_exc
