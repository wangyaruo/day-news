from __future__ import annotations

import asyncio
from dataclasses import replace

import httpx
import pytest

from day_news.fetchers import fetch_all
from day_news.models import Category, RawEntry, SourceConfig, SourceFetchResult, SourceKind

RSS_SOURCE = SourceConfig(
    id="working",
    publisher_id="working",
    name="Working",
    kind=SourceKind.RSS,
    url="https://example.com/rss",
    category=Category.WORLD,
    language="en",
    priority=10,
    max_per_issue=3,
    fetch_limit=10,
    timezone="UTC",
)
HN_SOURCE = replace(
    RSS_SOURCE,
    id="broken",
    publisher_id="broken",
    name="Broken",
    kind=SourceKind.HACKER_NEWS,
    url="https://example.com/hn",
)
ENTRY = RawEntry(
    external_id="one",
    title="One",
    url="https://example.com/one",
    published_value=1,
    summary_html=None,
    source_position=0,
)


@pytest.mark.asyncio
async def test_fetch_all_isolates_failures_and_skips_disabled_sources() -> None:
    calls: list[str] = []

    async def working(source: SourceConfig, client: httpx.AsyncClient) -> SourceFetchResult:
        calls.append(source.id)
        return SourceFetchResult(source.id, (ENTRY,), ("minor warning",))

    async def broken(source: SourceConfig, client: httpx.AsyncClient) -> SourceFetchResult:
        calls.append(source.id)
        raise RuntimeError("boom")

    disabled = replace(RSS_SOURCE, id="disabled", enabled=False)
    registry = {SourceKind.RSS: working, SourceKind.HACKER_NEWS: broken}
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(500))) as client:
        batch = await fetch_all((HN_SOURCE, disabled, RSS_SOURCE), client, registry=registry)

    assert calls == ["broken", "working"]
    assert batch.successful_sources == ("working",)
    assert batch.failed_sources == {"broken": "boom"}
    assert batch.entries == ((RSS_SOURCE, ENTRY),)
    assert batch.warnings == ("working: minor warning",)


@pytest.mark.asyncio
async def test_fetch_all_restores_configuration_order_after_async_completion() -> None:
    async def rss(source: SourceConfig, client: httpx.AsyncClient) -> SourceFetchResult:
        await asyncio.sleep(0)
        return SourceFetchResult(source.id, (replace(ENTRY, external_id=source.id),))

    async def hn(source: SourceConfig, client: httpx.AsyncClient) -> SourceFetchResult:
        await asyncio.sleep(0.01)
        return SourceFetchResult(source.id, (replace(ENTRY, external_id=source.id),))

    registry = {SourceKind.RSS: rss, SourceKind.HACKER_NEWS: hn}
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(500))) as client:
        batch = await fetch_all((HN_SOURCE, RSS_SOURCE), client, registry=registry)

    assert batch.successful_sources == ("broken", "working")
    assert [entry.external_id for _, entry in batch.entries] == ["broken", "working"]
