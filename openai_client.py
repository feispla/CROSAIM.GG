from __future__ import annotations

import asyncio
import os
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    InternalServerError,
    RateLimitError,
)

T = TypeVar("T")

RETRYABLE_ERRORS = (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
)


def build_openai_client() -> AsyncOpenAI:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Falta OPENAI_API_KEY en las variables del servidor")

    try:
        timeout = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "30"))
    except ValueError as exc:
        raise RuntimeError("OPENAI_TIMEOUT_SECONDS debe ser numérico") from exc

    if timeout <= 0 or timeout > 300:
        raise RuntimeError("OPENAI_TIMEOUT_SECONDS debe estar entre 0 y 300")

    return AsyncOpenAI(
        api_key=api_key,
        timeout=timeout,
        max_retries=0,
    )


def _retry_after_seconds(error: Exception) -> float | None:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    value = headers.get("retry-after")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None


async def with_openai_retries(
    operation: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 4,
    base_delay_seconds: float = 0.5,
    max_delay_seconds: float = 30.0,
) -> T:
    """Ejecuta una llamada OpenAI con backoff y jitter sin reintentar errores permanentes."""
    if max_attempts < 1:
        raise ValueError("max_attempts debe ser mayor que cero")

    for attempt in range(max_attempts):
        try:
            return await operation()
        except RETRYABLE_ERRORS as error:
            if attempt == max_attempts - 1:
                raise

            cap = min(max_delay_seconds, base_delay_seconds * (2**attempt))
            delay = cap / 2 + random.random() * (cap / 2)
            retry_after = _retry_after_seconds(error)
            if retry_after is not None:
                delay = min(max_delay_seconds, max(delay, retry_after))
            await asyncio.sleep(delay)

    raise RuntimeError("La operación OpenAI terminó sin resultado")
