from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from bs4 import BeautifulSoup

from day_news.issue import render_issue
from day_news.models import (
    AppConfig,
    Article,
    Category,
    Issue,
    SelectionPolicy,
    SiteConfig,
    SourceConfig,
    SourceKind,
)
from day_news.site import build_site


def site_config() -> SiteConfig:
    return SiteConfig(
        title="每日新闻",
        description="每日摘要",
        site_url="https://wangyaruo.github.io/day-news/",
        base_path="/day-news/",
        repository_url="https://github.com/wangyaruo/day-news",
        issues_url="https://github.com/wangyaruo/day-news/issues",
        language="zh-CN",
    )


def source_config() -> AppConfig:
    policy = SelectionPolicy(24, 12, 30, 4, 5, 3, 4, 30, 180, 0.92)
    sources = (
        SourceConfig(
            id="enabled",
            publisher_id="publisher",
            name="Enabled <Source>",
            kind=SourceKind.RSS,
            url="https://example.com/feed.xml",
            category=Category.WORLD,
            language="en",
            priority=10,
            max_per_issue=3,
            fetch_limit=60,
            timezone="UTC",
        ),
        SourceConfig(
            id="disabled",
            publisher_id="disabled",
            name="Disabled Source",
            kind=SourceKind.RSS,
            url="https://example.com/disabled.xml",
            category=Category.BUSINESS,
            language="en",
            priority=20,
            max_per_issue=3,
            fetch_limit=60,
            enabled=False,
            timezone="UTC",
        ),
    )
    return AppConfig(policy=policy, sources=sources)


def write_issue(content_root: Path, issue_date: date, index: int = 0) -> Path:
    published = datetime.combine(issue_date, datetime.min.time(), UTC) + timedelta(hours=8)
    url = f"https://example.com/{issue_date.isoformat()}"
    article = Article(
        id=f"id-{issue_date}",
        title=f"Title {issue_date}",
        title_key=f"title {issue_date}",
        url=url,
        canonical_url=url,
        source_id="enabled",
        publisher_id="publisher",
        source_name="Enabled Source",
        category=list(Category)[index % len(Category)],
        published_at=published,
        fetched_at=published + timedelta(days=1),
        summary="Summary",
        language="en",
        is_fallback=False,
        rank_key=(0, 10, -int(published.timestamp() * 1_000_000), 0, url),
    )
    issue = Issue(
        target_date=issue_date,
        generated_at=published + timedelta(days=1),
        articles=(article,),
    )
    path = content_root / issue_date.strftime("%Y/%m/%Y-%m-%d.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_issue(issue), encoding="utf-8")
    return path


def test_builds_all_routes_links_sources_and_assets(tmp_path: Path) -> None:
    content = tmp_path / "content"
    output = tmp_path / "dist"
    newest = date(2026, 7, 10)
    for index in range(31):
        write_issue(content, newest - timedelta(days=index), index)

    build_site(content, output, source_config(), site_config())

    expected = (
        output / "index.html",
        output / "issues/2026-07-10/index.html",
        output / "archive/index.html",
        output / "archive/2026-07/index.html",
        output / "archive/2026-06/index.html",
        output / "sources/index.html",
        output / "about/index.html",
        output / "assets/styles.css",
        output / "rss.xml",
    )
    assert all(path.exists() for path in expected)

    index_html = (output / "index.html").read_text(encoding="utf-8")
    assert "/day-news/issues/2026-07-10/" in index_html
    assert "/day-news/assets/styles.css" in index_html
    assert "https://fonts." not in index_html

    sources_html = (output / "sources/index.html").read_text(encoding="utf-8")
    soup = BeautifulSoup(sources_html, "html.parser")
    assert "Enabled <Source>" in soup.get_text()
    assert "Disabled Source" not in soup.get_text()
    assert soup.find("script") is None

    newest_html = (output / "issues/2026-07-10/index.html").read_text(encoding="utf-8")
    oldest_html = (output / "issues/2026-06-10/index.html").read_text(encoding="utf-8")
    assert "/day-news/issues/2026-07-09/" in newest_html
    assert "/day-news/issues/2026-06-11/" in oldest_html


def test_clean_rebuild_is_deterministic_and_removes_stale_routes(tmp_path: Path) -> None:
    content = tmp_path / "content"
    output = tmp_path / "dist"
    first_path = write_issue(content, date(2026, 7, 10))
    write_issue(content, date(2026, 7, 9), 1)

    build_site(content, output, source_config(), site_config())
    first = {path.relative_to(output): path.read_bytes() for path in output.rglob("*") if path.is_file()}
    build_site(content, output, source_config(), site_config())
    second = {path.relative_to(output): path.read_bytes() for path in output.rglob("*") if path.is_file()}
    assert first == second

    first_path.unlink()
    build_site(content, output, source_config(), site_config())
    assert not (output / "issues/2026-07-10").exists()


def test_empty_site_still_builds_fixed_routes_and_valid_rss(tmp_path: Path) -> None:
    output = tmp_path / "dist"
    build_site(tmp_path / "empty", output, source_config(), site_config())
    assert (output / "index.html").exists()
    assert (output / "archive/index.html").exists()
    assert (output / "rss.xml").exists()
