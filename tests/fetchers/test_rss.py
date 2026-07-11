from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from day_news.fetchers.http import FetchError
from day_news.fetchers.rss import fetch_rss, parse_feed
from day_news.models import (
    Category,
    FetchBatch,
    RawEntry,
    SourceConfig,
    SourceFetchResult,
    SourceKind,
)

FIXTURE_DIR = Path("tests/fixtures/rss")
SOURCE = SourceConfig(
    id="example-rss",
    publisher_id="example",
    name="Example RSS",
    kind=SourceKind.RSS,
    url="https://example.com/feed.xml",
    category=Category.WORLD,
    language="en",
    priority=10,
    max_per_issue=3,
    fetch_limit=10,
    timezone="UTC",
)


def test_parse_feed_maps_entries_and_prefers_published_and_alternate_link() -> None:
    payload = (FIXTURE_DIR / "sample.xml").read_bytes()

    result = parse_feed(payload, SOURCE)

    assert isinstance(result, SourceFetchResult)
    assert result.source_id == SOURCE.id
    assert len(result.entries) == 3
    assert result.warnings == ()
    assert result.entries == (
        RawEntry(
            external_id="story-1",
            title="First headline",
            url="https://example.com/articles/one",
            published_value="Fri, 10 Jul 2026 08:00:00 GMT",
            summary_html="<p>First <strong>summary</strong>.</p>",
            source_position=0,
        ),
        RawEntry(
            external_id="story-2",
            title="Second headline",
            url="https://example.com/articles/two",
            published_value="2026-07-10T07:00:00Z",
            summary_html="Second summary.",
            source_position=1,
        ),
        RawEntry(
            external_id="story-3",
            title="Undated headline",
            url="https://example.com/articles/three",
            published_value=None,
            summary_html="Third summary.",
            source_position=2,
        ),
    )


def test_parse_feed_respects_fetch_limit_and_keeps_zero_based_positions() -> None:
    payload = (FIXTURE_DIR / "sample.xml").read_bytes()
    source = replace(SOURCE, fetch_limit=2)

    result = parse_feed(payload, source)

    assert [entry.external_id for entry in result.entries] == ["story-1", "story-2"]
    assert [entry.source_position for entry in result.entries] == [0, 1]


def test_partial_feed_returns_valid_entries_with_warning() -> None:
    payload = (FIXTURE_DIR / "partial.xml").read_bytes()

    result = parse_feed(payload, SOURCE)

    assert result.entries == (
        RawEntry(
            external_id="partial-1",
            title="Recoverable headline",
            url="https://example.com/articles/recoverable",
            published_value="Fri, 10 Jul 2026 06:00:00 GMT",
            summary_html="Recoverable summary.",
            source_position=0,
        ),
    )
    assert result.warnings


def test_unreadable_feed_without_entries_raises_fetch_error() -> None:
    with pytest.raises(FetchError, match="unreadable feed"):
        parse_feed(b"<not-a-feed>", SOURCE)


@pytest.mark.asyncio
async def test_fetch_rss_downloads_and_parses_with_injected_transport() -> None:
    payload = (FIXTURE_DIR / "sample.xml").read_bytes()
    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(200, content=payload, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await fetch_rss(SOURCE, client)

    assert requested_urls == [SOURCE.url]
    assert result.source_id == SOURCE.id
    assert [entry.external_id for entry in result.entries] == [
        "story-1",
        "story-2",
        "story-3",
    ]


def test_fetch_batch_keeps_source_entry_pairs_and_outcomes() -> None:
    result = parse_feed((FIXTURE_DIR / "sample.xml").read_bytes(), SOURCE)

    batch = FetchBatch(
        entries=((SOURCE, result.entries[0]),),
        successful_sources=(SOURCE.id,),
        failed_sources={"failed-rss": "timeout"},
        warnings=("partial feed",),
    )

    assert batch.entries == ((SOURCE, result.entries[0]),)
    assert batch.successful_sources == (SOURCE.id,)
    assert batch.failed_sources == {"failed-rss": "timeout"}
    assert batch.warnings == ("partial feed",)
