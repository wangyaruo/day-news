from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence

import httpx

from day_news.fetchers.hacker_news import fetch_hacker_news
from day_news.fetchers.rss import fetch_rss
from day_news.models import FetchBatch, RawEntry, SourceConfig, SourceFetchResult, SourceKind

type Fetcher = Callable[[SourceConfig, httpx.AsyncClient], Awaitable[SourceFetchResult]]


FETCHERS: dict[SourceKind, Fetcher] = {
    SourceKind.RSS: fetch_rss,
    SourceKind.HACKER_NEWS: fetch_hacker_news,
}


async def fetch_all(
    sources: Sequence[SourceConfig],
    client: httpx.AsyncClient,
    *,
    registry: Mapping[SourceKind, Fetcher] = FETCHERS,
) -> FetchBatch:
    enabled = [source for source in sources if source.enabled]
    tasks = [registry[source.kind](source, client) for source in enabled]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    entries: list[tuple[SourceConfig, RawEntry]] = []
    successful: list[str] = []
    failed: dict[str, str] = {}
    warnings: list[str] = []

    for source, result in zip(enabled, results, strict=True):
        if isinstance(result, BaseException):
            failed[source.id] = str(result)
            continue
        successful.append(source.id)
        warnings.extend(f"{source.id}: {warning}" for warning in result.warnings)
        entries.extend((source, entry) for entry in result.entries)

    return FetchBatch(
        entries=tuple(entries),
        successful_sources=tuple(successful),
        failed_sources=failed,
        warnings=tuple(warnings),
    )
