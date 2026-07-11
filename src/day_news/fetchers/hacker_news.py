from __future__ import annotations

import asyncio
from typing import Any

import httpx

from day_news.fetchers.http import FetchError, get_with_retry
from day_news.models import RawEntry, SourceConfig, SourceFetchResult

LIST_NAMES = ("topstories", "beststories", "newstories")


async def fetch_hacker_news(
    source: SourceConfig,
    client: httpx.AsyncClient,
    workers: int = 12,
) -> SourceFetchResult:
    if workers < 1:
        raise ValueError("workers must be at least 1")

    base_url = source.url.rstrip("/")
    list_results = await asyncio.gather(
        *(_fetch_id_list(client, base_url, name) for name in LIST_NAMES),
    )

    warnings: list[str] = []
    ordered_ids: list[int] = []
    seen_ids: set[int] = set()
    successful_lists = 0

    for name, (ids, error) in zip(LIST_NAMES, list_results, strict=True):
        if error is not None:
            warnings.append(f"{name}: {error}")
            continue
        successful_lists += 1
        for item_id in ids:
            if type(item_id) is int and item_id not in seen_ids:
                seen_ids.add(item_id)
                ordered_ids.append(item_id)

    if successful_lists == 0:
        detail = "; ".join(warnings)
        raise FetchError(f"all Hacker News lists failed: {detail}")

    semaphore = asyncio.Semaphore(workers)
    detail_results = await asyncio.gather(
        *(
            _fetch_detail(client, base_url, semaphore, position, item_id)
            for position, item_id in enumerate(ordered_ids[: source.fetch_limit])
        )
    )

    entries: list[RawEntry] = []
    for _position, entry, warning in detail_results:
        if warning is not None:
            warnings.append(warning)
        elif entry is not None:
            entries.append(entry)

    return SourceFetchResult(
        source_id=source.id,
        entries=tuple(entries),
        warnings=tuple(warnings),
    )


async def _fetch_id_list(
    client: httpx.AsyncClient,
    base_url: str,
    name: str,
) -> tuple[list[Any], str | None]:
    url = f"{base_url}/{name}.json"
    try:
        response = await get_with_retry(client, url)
        payload = response.json()
        if not isinstance(payload, list):
            raise FetchError("response is not a JSON array")
    except (FetchError, TypeError, ValueError) as error:
        return [], str(error)
    return payload, None


async def _fetch_detail(
    client: httpx.AsyncClient,
    base_url: str,
    semaphore: asyncio.Semaphore,
    position: int,
    item_id: int,
) -> tuple[int, RawEntry | None, str | None]:
    url = f"{base_url}/item/{item_id}.json"
    try:
        async with semaphore:
            response = await get_with_retry(client, url)
        item = response.json()
    except (FetchError, TypeError, ValueError) as error:
        return position, None, f"item {item_id}: {error}"

    return position, _raw_entry(item, position), None


def _raw_entry(item: object, position: int) -> RawEntry | None:
    if not isinstance(item, dict):
        return None
    if item.get("deleted") or item.get("dead") or item.get("type") != "story":
        return None

    item_id = item.get("id")
    title = item.get("title")
    url = item.get("url")
    published = item.get("time")
    if type(item_id) is not int or type(published) is not int:
        return None
    if not isinstance(title, str) or not title.strip():
        return None
    if not isinstance(url, str) or not url.strip():
        return None

    return RawEntry(
        external_id=str(item_id),
        title=title,
        url=url,
        published_value=published,
        summary_html=None,
        source_position=position,
    )
