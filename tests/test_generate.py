from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from day_news.fetchers import Fetcher
from day_news.generate import _atomic_write_text, generate_issue
from day_news.issue import IssueError, parse_issue
from day_news.models import (
    AppConfig,
    Category,
    GenerationStatus,
    RawEntry,
    SelectionPolicy,
    SourceConfig,
    SourceFetchResult,
    SourceKind,
)

TARGET = date(2026, 7, 10)
GENERATED_AT = datetime(2026, 7, 11, 1, 0, tzinfo=UTC)
README_TEXT = "# News\n\n<!-- DAY_NEWS_RECENT_START -->\n<!-- DAY_NEWS_RECENT_END -->\n"


def _policy() -> SelectionPolicy:
    return SelectionPolicy(
        target_count=24,
        min_count=12,
        max_count=30,
        min_categories=4,
        min_publishers=5,
        default_publisher_cap=3,
        category_soft_target=4,
        history_days=30,
        summary_limit=180,
        similarity_threshold=0.92,
    )


def _source(index: int, category: Category, *, broken: bool = False) -> SourceConfig:
    return SourceConfig(
        id="broken" if broken else f"source-{index}",
        publisher_id="broken" if broken else f"publisher-{index}",
        name="Broken" if broken else f"Source {index}",
        kind=SourceKind.HACKER_NEWS if broken else SourceKind.RSS,
        url=f"https://example.com/{index}",
        category=category,
        language="en",
        priority=10 + index,
        max_per_issue=3,
        fetch_limit=10,
        timezone="UTC",
    )


def _config(*, include_broken: bool = False) -> AppConfig:
    sources = (
        _source(0, Category.WORLD),
        _source(1, Category.BUSINESS),
        _source(2, Category.TECHNOLOGY),
        _source(3, Category.SCIENCE),
        _source(4, Category.WORLD),
    )
    if include_broken:
        sources += (_source(5, Category.CULTURE, broken=True),)
    return AppConfig(policy=_policy(), sources=sources)


def _registry(*, changed: bool = False, insufficient: bool = False) -> dict[SourceKind, Fetcher]:
    counts = {"source-0": 3, "source-1": 3, "source-2": 2, "source-3": 2, "source-4": 2}

    async def rss(source: SourceConfig, client: httpx.AsyncClient) -> SourceFetchResult:
        count = 1 if insufficient else counts[source.id]
        source_number = int(source.id.rsplit("-", maxsplit=1)[-1])
        entries = []
        for index in range(count):
            is_changed = changed and source.id == "source-0" and index == 0
            unique_number = source_number * 3 + index
            entries.append(
                RawEntry(
                    external_id=f"{source.id}-{index}",
                    title=(
                        "Changed unique headline"
                        if is_changed
                        else f"Topic {unique_number} {chr(0x4E00 + unique_number) * 12}"
                    ),
                    url=f"https://example.com/{source.id}/{index}{'-changed' if is_changed else ''}",
                    published_value=f"2026-07-10T{8 + index:02d}:00:00Z",
                    summary_html=f"<p>Summary {source.id}-{index}</p>",
                    source_position=index,
                )
            )
        return SourceFetchResult(source.id, tuple(entries))

    async def broken(source: SourceConfig, client: httpx.AsyncClient) -> SourceFetchResult:
        raise RuntimeError("boom")

    return {SourceKind.RSS: rss, SourceKind.HACKER_NEWS: broken}


def _paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    content = tmp_path / "content"
    readme = tmp_path / "README.md"
    report = tmp_path / "build/report.json"
    readme.write_text(README_TEXT, encoding="utf-8")
    return content, readme, report


async def _generate(
    tmp_path: Path,
    *,
    config: AppConfig | None = None,
    registry: dict[SourceKind, Fetcher] | None = None,
    generated_at: datetime = GENERATED_AT,
    force: bool = False,
):
    content, readme, report = (
        _paths(tmp_path)
        if not (tmp_path / "README.md").exists()
        else (
            tmp_path / "content",
            tmp_path / "README.md",
            tmp_path / "build/report.json",
        )
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(500))) as client:
        result = await generate_issue(
            TARGET,
            config=config or _config(),
            content_root=content,
            readme_path=readme,
            report_path=report,
            generated_at=generated_at,
            client=client,
            registry=registry or _registry(),
            force=force,
        )
    return result, content, readme, report


@pytest.mark.asyncio
async def test_valid_run_creates_issue_readme_and_report(tmp_path: Path) -> None:
    result, content, readme, report = await _generate(tmp_path)
    issue_path = content / "2026/07/2026-07-10.md"

    assert result.status is GenerationStatus.CREATED
    assert result.content_path == issue_path
    assert issue_path.exists()
    assert "2026-07-10" in readme.read_text(encoding="utf-8")
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["status"] == "created"
    assert payload["selected_count"] == 12
    assert payload["failed_sources"] == {}


@pytest.mark.asyncio
async def test_existing_valid_issue_skips_before_fetching(tmp_path: Path) -> None:
    first, content, readme, report = await _generate(tmp_path)
    before = first.content_path.read_bytes() if first.content_path else b""

    async def must_not_fetch(source: SourceConfig, client: httpx.AsyncClient) -> SourceFetchResult:
        raise AssertionError("fetcher should not be called")

    registry = {SourceKind.RSS: must_not_fetch, SourceKind.HACKER_NEWS: must_not_fetch}
    second, _, _, _ = await _generate(tmp_path, registry=registry)

    assert second.status is GenerationStatus.SKIPPED_EXISTS
    assert second.content_path is not None
    assert second.content_path.read_bytes() == before
    assert json.loads(report.read_text(encoding="utf-8"))["status"] == "skipped_exists"
    assert "2026-07-10" in readme.read_text(encoding="utf-8")
    assert content.exists()


@pytest.mark.asyncio
async def test_existing_malformed_issue_raises_instead_of_skipping(tmp_path: Path) -> None:
    content, _, _ = _paths(tmp_path)
    path = content / "2026/07/2026-07-10.md"
    path.parent.mkdir(parents=True)
    path.write_text("broken", encoding="utf-8")

    with pytest.raises(IssueError):
        await _generate(tmp_path)


@pytest.mark.asyncio
async def test_threshold_failure_writes_only_report(tmp_path: Path) -> None:
    config = AppConfig(policy=_policy(), sources=(_source(0, Category.WORLD),))
    result, content, readme, report = await _generate(
        tmp_path,
        config=config,
        registry=_registry(insufficient=True),
    )

    assert result.status is GenerationStatus.FAILED_THRESHOLD
    assert not (content / "2026/07/2026-07-10.md").exists()
    assert readme.read_text(encoding="utf-8") == README_TEXT
    assert json.loads(report.read_text(encoding="utf-8"))["status"] == "failed_threshold"


@pytest.mark.asyncio
async def test_failed_source_is_reported_while_others_publish(tmp_path: Path) -> None:
    result, _, _, report = await _generate(tmp_path, config=_config(include_broken=True))
    payload = json.loads(report.read_text(encoding="utf-8"))

    assert result.status is GenerationStatus.CREATED
    assert payload["failed_sources"] == {"broken": "boom"}
    assert payload["successful_sources"] == [f"source-{index}" for index in range(5)]


@pytest.mark.asyncio
async def test_force_same_content_is_unchanged_and_changed_content_updates(tmp_path: Path) -> None:
    first, _, readme, _ = await _generate(tmp_path)
    assert first.content_path is not None
    original_bytes = first.content_path.read_bytes()
    original_generated_at = parse_issue(first.content_path).generated_at
    original_readme = readme.read_bytes()

    same, _, _, _ = await _generate(
        tmp_path,
        generated_at=GENERATED_AT + timedelta(hours=1),
        force=True,
    )
    assert same.status is GenerationStatus.UNCHANGED
    assert first.content_path.read_bytes() == original_bytes
    assert parse_issue(first.content_path).generated_at == original_generated_at
    assert readme.read_bytes() == original_readme

    changed, _, _, _ = await _generate(
        tmp_path,
        registry=_registry(changed=True),
        generated_at=GENERATED_AT + timedelta(hours=2),
        force=True,
    )
    assert changed.status is GenerationStatus.UPDATED
    assert first.content_path.read_bytes() != original_bytes


def test_atomic_write_cleans_temporary_file_when_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "nested/file.txt"

    def fail_replace(source: Path, target: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr("day_news.generate.os.replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        _atomic_write_text(destination, "value")

    assert not destination.exists()
    assert list(destination.parent.glob(".*.tmp")) == []
