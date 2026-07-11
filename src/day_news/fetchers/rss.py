from __future__ import annotations

import feedparser
import httpx

from day_news.fetchers.http import FetchError, get_with_retry
from day_news.models import RawEntry, SourceConfig, SourceFetchResult


def parse_feed(payload: bytes, source: SourceConfig) -> SourceFetchResult:
    feed = feedparser.parse(payload)
    warnings = (str(feed.bozo_exception),) if feed.bozo else ()
    entries = []

    for position, entry in enumerate(feed.entries[: source.fetch_limit]):
        links = entry.get("links", [])
        alternate = next(
            (link.get("href") for link in links if link.get("rel", "alternate") == "alternate"),
            None,
        )
        entries.append(
            RawEntry(
                external_id=entry.get("id") or entry.get("guid"),
                title=entry.get("title"),
                url=alternate or entry.get("link"),
                published_value=entry.get("published") or entry.get("updated"),
                summary_html=entry.get("summary") or entry.get("description"),
                source_position=position,
            )
        )

    if feed.bozo and not entries:
        raise FetchError(f"unreadable feed: {feed.bozo_exception}")

    return SourceFetchResult(
        source_id=source.id,
        entries=tuple(entries),
        warnings=warnings,
    )


async def fetch_rss(
    source: SourceConfig,
    client: httpx.AsyncClient,
) -> SourceFetchResult:
    response = await get_with_retry(client, source.url)
    return parse_feed(response.content, source)
