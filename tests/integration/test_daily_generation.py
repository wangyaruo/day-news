from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from day_news.fetchers import Fetcher
from day_news.generate import generate_issue
from day_news.models import (
    AppConfig,
    Category,
    GenerationStatus,
    RawEntry,
    SelectionPolicy,
    SiteConfig,
    SourceConfig,
    SourceFetchResult,
    SourceKind,
)
from day_news.site import build_site
from day_news.validate import validate_content, validate_site

TARGET = date(2026, 7, 10)
GENERATED_AT = datetime(2026, 7, 11, 1, 0, tzinfo=UTC)


def _setup(root: Path) -> tuple[AppConfig, SiteConfig, Path, Path, Path]:
    policy = SelectionPolicy(24, 12, 30, 4, 5, 3, 4, 30, 180, 0.92)
    categories = [Category.WORLD, Category.BUSINESS, Category.TECHNOLOGY, Category.SCIENCE, Category.CULTURE]
    sources = tuple(
        SourceConfig(
            id=f"source-{index}",
            publisher_id=f"publisher-{index}",
            name=f"Source {index}",
            kind=SourceKind.RSS,
            url=f"https://example.com/{index}.xml",
            category=category,
            language="en",
            priority=10 + index,
            max_per_issue=3,
            fetch_limit=20,
            timezone="UTC",
        )
        for index, category in enumerate(categories)
    ) + (
        SourceConfig(
            id="broken",
            publisher_id="broken",
            name="Broken",
            kind=SourceKind.HACKER_NEWS,
            url="https://example.com/hn",
            category=Category.TECHNOLOGY,
            language="en",
            priority=30,
            max_per_issue=3,
            fetch_limit=20,
            timezone="UTC",
        ),
    )
    site = SiteConfig(
        title="每日新闻",
        description="离线集成测试",
        site_url="https://wangyaruo.github.io/day-news/",
        base_path="/day-news/",
        repository_url="https://github.com/wangyaruo/day-news",
        issues_url="https://github.com/wangyaruo/day-news/issues",
        language="zh-CN",
    )
    content = root / "content"
    readme = root / "README.md"
    report = root / "report.json"
    readme.write_text(
        "# News\n\n<!-- DAY_NEWS_RECENT_START -->\n<!-- DAY_NEWS_RECENT_END -->\n",
        encoding="utf-8",
    )
    return AppConfig(policy, sources), site, content, readme, report


def _registry(*, reverse: bool = False) -> dict[SourceKind, Fetcher]:
    async def rss(source: SourceConfig, client: httpx.AsyncClient) -> SourceFetchResult:
        source_number = int(source.id.rsplit("-", maxsplit=1)[-1])
        entries = [
            RawEntry(
                external_id=f"{source.id}-{index}",
                title=f"Topic {source_number * 3 + index} {chr(0x4E00 + source_number * 3 + index) * 10}",
                url=f"https://example.com/{source.id}/{index}?utm_source=test",
                published_value=(
                    "2026-07-09T08:00:00Z"
                    if source_number == 4 and index == 1
                    else f"2026-07-10T{8 + index:02d}:00:00Z"
                ),
                summary_html=(
                    "<script>bad()</script><p>[click](javascript:alert(1))</p>"
                    if source_number == 0 and index == 0
                    else "<p>Safe summary</p>"
                ),
                source_position=index,
            )
            for index in range(3 if source_number < 2 else 2)
        ]
        if source_number == 0:
            entries.extend(
                [
                    RawEntry(None, "Missing time", "https://example.com/missing", None, None, 20),
                    RawEntry(None, entries[0].title, entries[0].url, entries[0].published_value, None, 21),
                ]
            )
        if reverse:
            entries.reverse()
        return SourceFetchResult(source.id, tuple(entries))

    async def broken(source: SourceConfig, client: httpx.AsyncClient) -> SourceFetchResult:
        raise RuntimeError("offline source failure")

    return {SourceKind.RSS: rss, SourceKind.HACKER_NEWS: broken}


async def _run(root: Path, *, reverse: bool = False):
    config, site, content, readme, report = _setup(root)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(500))) as client:
        result = await generate_issue(
            TARGET,
            config=config,
            content_root=content,
            readme_path=readme,
            report_path=report,
            generated_at=GENERATED_AT,
            client=client,
            registry=_registry(reverse=reverse),
        )
    return result, config, site, content, readme, report


@pytest.mark.asyncio
async def test_offline_full_pipeline_is_deterministic_and_idempotent(tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    first, config, site, content, readme, report = await _run(first_root)
    second, _, _, _, _, _ = await _run(second_root, reverse=True)

    assert first.status is GenerationStatus.CREATED
    assert second.status is GenerationStatus.CREATED
    assert first.content_path is not None and second.content_path is not None
    assert first.content_path.read_bytes() == second.content_path.read_bytes()
    assert "offline source failure" in report.read_text(encoding="utf-8")
    assert "2026-07-10" in readme.read_text(encoding="utf-8")

    output = first_root / "dist"
    build_site(content, output, config, site)
    assert validate_content(content) == ()
    assert validate_site(output, site) == ()

    calls = 0

    async def must_not_fetch(source: SourceConfig, client: httpx.AsyncClient) -> SourceFetchResult:
        nonlocal calls
        calls += 1
        raise AssertionError("must not fetch")

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(500))) as client:
        again = await generate_issue(
            TARGET,
            config=config,
            content_root=content,
            readme_path=readme,
            report_path=report,
            generated_at=GENERATED_AT,
            client=client,
            registry={SourceKind.RSS: must_not_fetch, SourceKind.HACKER_NEWS: must_not_fetch},
        )
    assert again.status is GenerationStatus.SKIPPED_EXISTS
    assert calls == 0
