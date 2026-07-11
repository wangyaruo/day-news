from __future__ import annotations

import asyncio

import httpx
import pytest

from day_news.fetchers.http import FetchError, get_with_retry


@pytest.mark.asyncio
async def test_retries_two_503_responses_then_returns_success() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(503, request=request)
        return httpx.Response(200, content=b"ok", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await get_with_retry(
            client,
            "https://example.com/feed.xml",
            delays=(0.0, 0.0),
        )

    assert attempts == 3
    assert response.content == b"ok"


@pytest.mark.parametrize("status_code", [408, 429, 500, 502, 503, 599])
@pytest.mark.asyncio
async def test_retryable_statuses_use_all_attempts_before_failing(status_code: int) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(status_code, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(FetchError) as exc_info:
            await get_with_retry(
                client,
                "https://example.com/feed.xml",
                delays=(0.0, 0.0),
            )

    assert attempts == 3
    assert str(status_code) in str(exc_info.value)


@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout])
@pytest.mark.asyncio
async def test_transport_errors_and_timeouts_can_succeed_on_third_attempt(
    error_type: type[httpx.TransportError],
) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise error_type("temporary network failure", request=request)
        return httpx.Response(200, content=b"recovered", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await get_with_retry(
            client,
            "https://example.com/feed.xml",
            delays=(0.0, 0.0),
        )

    assert attempts == 3
    assert response.content == b"recovered"


@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout])
@pytest.mark.asyncio
async def test_persistent_transport_errors_and_timeouts_stop_after_three_attempts(
    error_type: type[httpx.TransportError],
) -> None:
    attempts = 0
    url = "https://example.com/feed.xml"

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise error_type("network unavailable", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(FetchError) as exc_info:
            await get_with_retry(client, url, delays=(0.0, 0.0))

    assert attempts == 3
    assert url in str(exc_info.value)
    assert "network unavailable" in str(exc_info.value)


@pytest.mark.asyncio
async def test_404_fails_without_retry() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(404, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(FetchError) as exc_info:
            await get_with_retry(
                client,
                "https://example.com/missing.xml",
                delays=(0.0, 0.0),
            )

    assert attempts == 1
    assert "404" in str(exc_info.value)


@pytest.mark.asyncio
async def test_redirect_is_returned_without_retry() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            302,
            headers={"location": "https://example.com/new-feed.xml"},
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await get_with_retry(
            client,
            "https://example.com/feed.xml",
            delays=(0.0, 0.0),
        )

    assert attempts == 1
    assert response.status_code == 302


@pytest.mark.parametrize("status_code", [200, 204, 299])
@pytest.mark.asyncio
async def test_successful_response_is_not_retried_and_receives_timeout(status_code: int) -> None:
    attempts = 0
    timeout_extensions: list[dict[str, float]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        timeout_extensions.append(request.extensions["timeout"])
        return httpx.Response(status_code, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await get_with_retry(
            client,
            "https://example.com/feed.xml",
            timeout=3.25,
            delays=(0.0, 0.0),
        )

    assert attempts == 1
    assert response.status_code == status_code
    assert timeout_extensions == [{"connect": 3.25, "read": 3.25, "write": 3.25, "pool": 3.25}]


@pytest.mark.asyncio
async def test_final_retryable_failure_does_not_sleep_after_last_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0
    sleep_delays: list[float] = []
    real_sleep = asyncio.sleep

    async def recording_sleep(delay: float) -> None:
        sleep_delays.append(delay)
        await real_sleep(0)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503, request=request)

    monkeypatch.setattr(asyncio, "sleep", recording_sleep)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(FetchError):
            await get_with_retry(
                client,
                "https://example.com/feed.xml",
                delays=(0.0, 0.0),
            )

    assert attempts == 3
    assert sleep_delays == [0.0, 0.0]
