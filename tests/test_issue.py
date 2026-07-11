from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from markdown_it import MarkdownIt

from day_news.issue import IssueError, content_fingerprint, parse_issue, render_issue
from day_news.models import Article, Category, Issue


def _article(
    index: int,
    category: Category,
    *,
    fallback: bool = False,
    summary: str | None = "Summary.",
) -> Article:
    published = datetime(2026, 7, 10, 8, 0, tzinfo=UTC) - timedelta(days=int(fallback), minutes=index)
    url = f"https://example.com/story-{index}"
    return Article(
        id=f"id-{index}",
        title=f"Title [{index}]!",
        title_key=f"title {index}",
        url=url,
        canonical_url=url,
        source_id=f"source-{index}",
        publisher_id=f"publisher-{index % 2}",
        source_name=f"Source *{index}*",
        category=category,
        published_at=published,
        fetched_at=datetime(2026, 7, 11, 1, 0, tzinfo=UTC),
        summary=summary,
        language="en",
        is_fallback=fallback,
        rank_key=(int(fallback), 10, -int(published.timestamp() * 1_000_000), index, url),
    )


def _issue(*articles: Article, generated_at: datetime | None = None) -> Issue:
    return Issue(
        target_date=date(2026, 7, 10),
        generated_at=generated_at or datetime(2026, 7, 11, 1, 0, tzinfo=UTC),
        articles=tuple(articles),
    )


def _front_matter(rendered: str) -> dict[str, object]:
    _, yaml_text, _ = rendered.split("---", maxsplit=2)
    value = yaml.safe_load(yaml_text)
    assert isinstance(value, dict)
    return value


def test_render_issue_has_fixed_category_order_and_fallback_label() -> None:
    issue = _issue(
        _article(1, Category.TECHNOLOGY, fallback=True, summary=None),
        _article(2, Category.WORLD),
        _article(3, Category.BUSINESS),
    )

    rendered = render_issue(issue)

    assert rendered.index("## 国内与国际") < rendered.index("## 商业与经济")
    assert rendered.index("## 商业与经济") < rendered.index("## 科技与互联网")
    assert "## 文化与生活" not in rendered
    assert "近三日补充" in rendered
    assert "Source \\*1\\*" in rendered
    assert "Title \\[1\\]\\!" in rendered


def test_front_matter_order_counts_and_sorted_dedupe_index() -> None:
    articles = (
        _article(2, Category.WORLD),
        _article(1, Category.BUSINESS, fallback=True),
    )
    rendered = render_issue(_issue(*articles))
    front = _front_matter(rendered)

    assert list(front) == [
        "date",
        "generated_at",
        "article_count",
        "source_count",
        "fallback_count",
        "categories",
        "content_fingerprint",
        "dedupe_index",
    ]
    assert front["article_count"] == 2
    assert front["source_count"] == 2
    assert front["fallback_count"] == 1
    assert front["categories"] == ["world", "business"]
    rows = front["dedupe_index"]
    assert isinstance(rows, list)
    assert [row["id"] for row in rows] == ["id-1", "id-2"]


def test_render_is_byte_identical_and_fingerprint_ignores_generation_time() -> None:
    articles = (_article(1, Category.WORLD), _article(2, Category.SCIENCE))
    first = _issue(*articles)
    second = _issue(*articles, generated_at=first.generated_at + timedelta(hours=1))

    assert render_issue(first) == render_issue(first)
    assert content_fingerprint(first.target_date, first.articles) == content_fingerprint(
        second.target_date, second.articles
    )


def test_summary_markdown_is_escaped_instead_of_creating_unsafe_link() -> None:
    article = _article(
        1,
        Category.WORLD,
        summary="[click](javascript:alert(1)) and *bold*",
    )
    rendered = render_issue(_issue(article))
    html = MarkdownIt("commonmark", {"html": False, "linkify": False}).render(rendered)

    assert 'href="javascript:' not in html
    assert "javascript:alert" in html
    assert "\\[click\\]" in rendered


def test_parse_issue_round_trip_and_rejects_filename_date_mismatch(tmp_path: Path) -> None:
    issue = _issue(
        _article(1, Category.WORLD),
        _article(2, Category.SCIENCE, fallback=True),
    )
    path = tmp_path / "2026-07-10.md"
    path.write_text(render_issue(issue), encoding="utf-8")

    parsed = parse_issue(path)

    assert parsed.target_date == issue.target_date
    assert parsed.generated_at == issue.generated_at
    assert parsed.article_count == 2
    assert parsed.source_count == 2
    assert parsed.fallback_count == 1
    assert parsed.categories == (Category.WORLD, Category.SCIENCE)
    assert len(parsed.dedupe_index) == 2
    assert parsed.body.startswith("# 每日新闻")

    wrong_path = tmp_path / "2026-07-09.md"
    wrong_path.write_text(render_issue(issue), encoding="utf-8")
    with pytest.raises(IssueError, match="does not match"):
        parse_issue(wrong_path)


@pytest.mark.parametrize(
    "content",
    [
        "no front matter",
        "---\ndate: 2026-07-10\n---\nbody",
        "---\ndate: nope\ngenerated_at: nope\n---\nbody",
    ],
)
def test_parse_issue_rejects_malformed_content(tmp_path: Path, content: str) -> None:
    path = tmp_path / "2026-07-10.md"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(IssueError):
        parse_issue(path)
