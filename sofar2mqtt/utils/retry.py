"""Retry utility for handling transient failures."""

import time
import logging
from functools import wraps
from typing import TypeVar, Callable, Tuple, Any

T = TypeVar("T")

logger = logging.getLogger(__name__)


def retry_on_failure(
    max_retries: int, delay: float, exceptions: Tuple[type, ...]
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator for retrying operations on failure.

    Args:
        max_retries: Maximum number of retry attempts
        delay: Delay between retries in seconds
        exceptions: Tuple of exception types to catch and retry

    Returns:
        Decorated function with retry logic

    Example:
        @retry_on_failure(3, 0.1, (NoResponseError, SerialException))
        def read_register(addr):
            return instrument.read_register(addr)
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception: Exception | None = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        logger.debug(
                            f"{func.__name__} failed (attempt {attempt + 1}/{max_retries + 1}): {e}"
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            f"{func.__name__} failed after {max_retries + 1} attempts: {e}"
                        )

            # This should never be reached, but type checker needs it
            if last_exception:
                raise last_exception
            raise RuntimeError("Unreachable code")

        return wrapper

    return decorator
