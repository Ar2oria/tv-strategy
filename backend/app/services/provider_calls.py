"""Cooperative async bounds for synchronous provider SDK calls."""

import asyncio
from collections.abc import Callable
from typing import TypeVar

from app.providers.errors import ProviderUnavailable
from app.providers.timeouts import validate_request_timeout

ResultT = TypeVar("ResultT")


async def call_provider_sync(
    function: Callable[..., ResultT],
    *args: object,
    timeout: float,
) -> ResultT:
    """Wait cooperatively; cancellation cannot force a worker socket to stop."""
    validated_timeout = validate_request_timeout(timeout)
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(function, *args),
            timeout=validated_timeout,
        )
    except TimeoutError:
        raise ProviderUnavailable(
            "Market-data provider request timed out",
            detail=(
                "Cooperative provider wait timed out; the worker thread or "
                "socket may continue, and its result will not be written"
            ),
        ) from None
