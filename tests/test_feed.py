from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import feedparser
import pytest

from day_news.config import ConfigError, load_site_config
from day_news.feed import build_rss
from day_news.models import IssueSummary, SiteConfig


def _site_config() -> SiteConfig:
    return SiteConfig(
        title="每日新闻",
        description="每天北京时间 9:00 自动更新的免费新闻日刊",
        site_url="https://wangyaruo.github.io/day-news/",
        base_path="/day-news/",
        repository_url="https://github.com/wangyaruo/day-news",
        issues_url="https://github.com/wangyaruo/day-news/issues",
        language="zh-CN",
    )


def _summary(index: int) -> IssueSummary:
    issue_date = date(2026, 7, 10) - timedelta(days=index)
    return IssueSummary(
        target_date=issue_date,
        path=Path(issue_date.strftime("content/%Y/%m/%Y-%m-%d.md")),
        article_count=24 - index % 5,
        source_count=8 - index % 2,
        generated_at=datetime(2026, 7, 11, 1, 0, tzinfo=UTC) - timedelta(days=index),
    )


def test_loads_repository_site_configuration() -> None:
    config = load_site_config(Path("config/site.toml"))
    assert config == _site_config()


@pytest.mark.parametrize(
    "site_url,base_path",
    [
        ("http://example.com/day-news/", "/day-news/"),
        ("https://example.com/day-news/", "day-news/"),
        ("https://example.com/day-news/", "/other/"),
    ],
)
def test_rejects_invalid_site_url_and_base_path(
    tmp_path: Path,
    site_url: str,
    base_path: str,
) -> None:
    path = tmp_path / "site.toml"
    path.write_text(
        (
            'title = "News"\n'
            'description = "Description"\n'
            f'site_url = "{site_url}"\n'
            f'base_path = "{base_path}"\n'
            'repository_url = "https://github.com/example/repo"\n'
            'issues_url = "https://github.com/example/repo/issues"\n'
            'language = "zh-CN"\n'
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_site_config(path)


def test_rss_keeps_latest_thirty_newest_first_and_is_deterministic() -> None:
    issues = [_summary(index) for index in range(31)]

    first = build_rss(issues, _site_config())
    second = build_rss(list(reversed(issues)), _site_config())
    parsed = feedparser.parse(first)

    assert first == second
    assert parsed.bozo == 0
    assert len(parsed.entries) == 30
    assert parsed.entries[0].title == "每日新闻 · 2026-07-10"
    assert parsed.entries[-1].title == "每日新闻 · 2026-06-11"
    assert parsed.entries[0].link == "https://wangyaruo.github.io/day-news/issues/2026-07-10/"
    assert parsed.entries[0].id == parsed.entries[0].link
    assert parsed.feed.updated_parsed is not None


def test_rss_xml_escapes_titles_and_has_stable_descriptions() -> None:
    payload = build_rss((_summary(0),), replace(_site_config(), title="每日 & 新闻"))
    parsed = feedparser.parse(payload)

    assert b"&amp;" in payload
    assert parsed.entries[0].title == "每日 & 新闻 · 2026-07-10"
    assert parsed.entries[0].description == "24 条新闻，8 个来源"


def test_empty_rss_is_valid_and_omits_last_build_date() -> None:
    payload = build_rss((), _site_config())
    parsed = feedparser.parse(payload)

    assert parsed.bozo == 0
    assert parsed.entries == []
    assert "updated_parsed" not in parsed.feed
    assert b"lastBuildDate" not in payload
