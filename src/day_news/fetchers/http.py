from __future__ import annotations

import asyncio
from collections.abc import Sequence

import httpx


class FetchError(RuntimeError):
    pass


RETRYABLE_STATUSES = {408, 429}


async def get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    timeout: float = 10.0,
    delays: Sequence[float] = (1.0, 2.0),
) -> httpx.Response:
    last_error: Exception | None = None

    for attempt in range(len(delays) + 1):
        try:
            response = await client.get(url, timeout=timeout)
        except httpx.TransportError as exc:
            last_error = exc
        else:
            if response.status_code in RETRYABLE_STATUSES or response.status_code >= 500:
                last_error = FetchError(f"retryable HTTP status {response.status_code}")
            elif response.status_code >= 400:
                last_error = FetchError(f"HTTP status {response.status_code}")
                break
            else:
                return response

        if attempt == len(delays):
            break
        await asyncio.sleep(delays[attempt])

    raise FetchError(f"request failed for {url}: {last_error}") from last_error
