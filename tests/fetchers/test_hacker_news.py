from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from day_news.fetchers.hacker_news import fetch_hacker_news
from day_news.fetchers.http import FetchError
from day_news.models import Category, SourceConfig, SourceKind

FIXTURE_DIR = Path("tests/fixtures/hn")
SOURCE = SourceConfig(
    id="hacker-news",
    publisher_id="hacker-news",
    name="Hacker News",
    kind=SourceKind.HACKER_NEWS,
    url="https://hacker-news.example/v0/",
    category=Category.TECHNOLOGY,
    language="en",
    priority=15,
    max_per_issue=3,
    fetch_limit=4,
    timezone="UTC",
)


def _fixture(name: str) -> object:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_fetches_unique_ids_with_bounded_concurrency_and_stable_order() -> None:
    active = 0
    max_active = 0
    detail_requests: list[int] = []
    delays = {101: 0.03, 102: 0.01, 103: 0.02, 104: 0.0}

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, max_active
        name = request.url.path.rsplit("/", maxsplit=1)[-1]
        if name in {"topstories.json", "beststories.json", "newstories.json"}:
            return httpx.Response(200, json=_fixture(name), request=request)

        item_id = int(name.removesuffix(".json"))
        detail_requests.append(item_id)
        active += 1
        max_active = max(max_active, active)
        try:
            await asyncio.sleep(delays[item_id])
            return httpx.Response(200, json=_fixture(f"item-{item_id}.json"), request=request)
        finally:
            active -= 1

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await fetch_hacker_news(SOURCE, client, workers=2)

    assert [entry.external_id for entry in result.entries] == ["101", "102", "103", "104"]
    assert [entry.source_position for entry in result.entries] == [0, 1, 2, 3]
    assert sorted(detail_requests) == [101, 102, 103, 104]
    assert max_active == 2
    assert result.warnings == ()


@pytest.mark.asyncio
async def test_skips_invalid_or_non_live_story_items() -> None:
    items: dict[int, object] = {
        201: None,
        202: {"id": 202, "type": "story", "deleted": True, "title": "x", "url": "https://x", "time": 1},
        203: {"id": 203, "type": "story", "dead": True, "title": "x", "url": "https://x", "time": 1},
        204: {"id": 204, "type": "job", "title": "x", "url": "https://x", "time": 1},
        205: {"id": 205, "type": "story", "title": " ", "url": "https://x", "time": 1},
        206: {"id": 206, "type": "story", "title": "x", "time": 1},
        207: {"id": 207, "type": "story", "title": "x", "url": "https://x", "time": True},
        208: {"id": 208, "type": "story", "title": "kept", "url": "https://kept", "time": 2},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", maxsplit=1)[-1]
        if name == "topstories.json":
            return httpx.Response(200, json=list(items), request=request)
        if name in {"beststories.json", "newstories.json"}:
            return httpx.Response(200, json=[], request=request)
        return httpx.Response(200, json=items[int(name.removesuffix(".json"))], request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await fetch_hacker_news(replace(SOURCE, fetch_limit=20), client, workers=2)

    assert [entry.external_id for entry in result.entries] == ["208"]
    assert result.entries[0].source_position == 7


@pytest.mark.asyncio
async def test_detail_failures_become_position_ordered_warnings() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", maxsplit=1)[-1]
        if name == "topstories.json":
            return httpx.Response(200, json=[101, 999, 998], request=request)
        if name in {"beststories.json", "newstories.json"}:
            return httpx.Response(200, json=[], request=request)
        if name == "999.json":
            return httpx.Response(404, request=request)
        if name == "998.json":
            return httpx.Response(200, content=b"{", request=request)
        return httpx.Response(200, json=_fixture("item-101.json"), request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await fetch_hacker_news(replace(SOURCE, fetch_limit=3), client, workers=2)

    assert [entry.external_id for entry in result.entries] == ["101"]
    assert len(result.warnings) == 2
    assert "999" in result.warnings[0]
    assert "998" in result.warnings[1]


@pytest.mark.asyncio
async def test_partial_list_failure_isolated_and_all_list_failures_raise() -> None:
    def partial_handler(request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", maxsplit=1)[-1]
        if name == "topstories.json":
            return httpx.Response(404, request=request)
        if name == "beststories.json":
            return httpx.Response(200, json=[101], request=request)
        if name == "newstories.json":
            return httpx.Response(200, json=[], request=request)
        return httpx.Response(200, json=_fixture("item-101.json"), request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(partial_handler)) as client:
        result = await fetch_hacker_news(SOURCE, client, workers=2)
    assert [entry.external_id for entry in result.entries] == ["101"]
    assert len(result.warnings) == 1
    assert "topstories" in result.warnings[0]

    def failed_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(failed_handler)) as client:
        with pytest.raises(FetchError, match="all Hacker News lists failed"):
            await fetch_hacker_news(SOURCE, client, workers=2)


@pytest.mark.asyncio
async def test_rejects_non_positive_worker_count() -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))) as client:
        with pytest.raises(ValueError, match="workers"):
            await fetch_hacker_news(SOURCE, client, workers=0)
