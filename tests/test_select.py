from __future__ import annotations

import random
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from day_news.models import Article, Category, SelectionPolicy, SourceConfig, SourceKind
from day_news.select import select_articles

POLICY = SelectionPolicy(
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
TARGET_TIME = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)


def _article(
    index: int,
    category: Category,
    publisher: str,
    *,
    fallback_days: int = 0,
) -> Article:
    published_at = TARGET_TIME - timedelta(days=fallback_days, minutes=index)
    url = f"https://example.com/{index}"
    return Article(
        id=f"article-{index}",
        title=f"Article {index}",
        title_key=f"article {index}",
        url=url,
        canonical_url=url,
        source_id=f"source-{publisher}",
        publisher_id=publisher,
        source_name=publisher,
        category=category,
        published_at=published_at,
        fetched_at=datetime(2026, 7, 11, 1, 0, tzinfo=UTC),
        summary=None,
        language="en",
        is_fallback=fallback_days > 0,
        rank_key=(
            1 if fallback_days else 0,
            10,
            -int(published_at.timestamp() * 1_000_000),
            index,
            url,
        ),
    )


def _sources(articles: Iterable[Article], caps: dict[str, int] | None = None) -> tuple[SourceConfig, ...]:
    caps = caps or {}
    by_publisher: dict[str, Article] = {}
    for article in articles:
        by_publisher.setdefault(article.publisher_id, article)
    return tuple(
        SourceConfig(
            id=article.source_id,
            publisher_id=publisher,
            name=publisher,
            kind=SourceKind.RSS,
            url=f"https://example.com/{publisher}.xml",
            category=article.category,
            language="en",
            priority=10,
            max_per_issue=caps.get(publisher, 3),
            fetch_limit=60,
            timezone="UTC",
        )
        for publisher, article in sorted(by_publisher.items())
    )


def test_twenty_four_valid_target_items_need_no_fallback() -> None:
    categories = list(Category)
    target = [_article(index, categories[index % len(categories)], f"publisher-{index % 8}") for index in range(24)]
    fallback = [_article(100, Category.WORLD, "fallback-publisher", fallback_days=1)]
    candidates = target + fallback

    result = select_articles(candidates, _sources(candidates), POLICY)

    assert result.valid is True
    assert len(result.articles) == 24
    assert not any(article.is_fallback for article in result.articles)


def test_fallback_repairs_missing_category_after_target_count_reached() -> None:
    categories = [Category.WORLD, Category.BUSINESS, Category.TECHNOLOGY]
    target = [_article(index, categories[index % 3], f"publisher-{index % 8}") for index in range(24)]
    repair = _article(100, Category.SCIENCE, "publisher-8", fallback_days=1)
    candidates = target + [repair]

    result = select_articles(candidates, _sources(candidates), POLICY)

    assert result.valid is True
    assert len(result.articles) == 25
    assert repair in result.articles
    assert len({article.category for article in result.articles}) == 4


def test_four_publishers_fail_even_when_count_and_categories_pass() -> None:
    categories = list(Category)[:4]
    candidates = [_article(index, categories[index % 4], f"publisher-{index % 4}") for index in range(12)]

    result = select_articles(candidates, _sources(candidates), POLICY)

    assert len(result.articles) == 12
    assert result.valid is False
    assert result.failure_reason is not None
    assert "publishers=4" in result.failure_reason


def test_exact_minimum_threshold_passes() -> None:
    categories = list(Category)[:4]
    candidates = [_article(index, categories[index % 4], f"publisher-{index % 5}") for index in range(12)]

    result = select_articles(candidates, _sources(candidates), POLICY)

    assert len(result.articles) == 12
    assert len({article.category for article in result.articles}) == 4
    assert len({article.publisher_id for article in result.articles}) == 5
    assert result.valid is True
    assert result.failure_reason is None


def test_configured_publisher_cap_overrides_default() -> None:
    categories = list(Category)
    capped = [_article(index, categories[index % 6], "capped") for index in range(5)]
    others = [_article(20 + index, categories[index % 6], f"publisher-{index % 6}") for index in range(18)]
    candidates = capped + others

    result = select_articles(candidates, _sources(candidates, {"capped": 2}), POLICY)

    assert sum(article.publisher_id == "capped" for article in result.articles) == 2


def test_selection_is_deterministic_and_grouped_by_category() -> None:
    categories = list(Category)
    candidates = [_article(index, categories[index % 6], f"publisher-{index % 8}") for index in range(24)] + [
        _article(100, Category.SCIENCE, "fallback-1", fallback_days=1),
        _article(101, Category.CULTURE, "fallback-2", fallback_days=2),
    ]
    shuffled = list(candidates)
    random.Random(42).shuffle(shuffled)

    first = select_articles(candidates, _sources(candidates), POLICY)
    second = select_articles(shuffled, _sources(candidates), POLICY)

    assert [article.id for article in first.articles] == [article.id for article in second.articles]
    category_positions = [list(Category).index(article.category) for article in first.articles]
    assert category_positions == sorted(category_positions)
    assert all(
        article.published_at >= TARGET_TIME - timedelta(days=2, minutes=200)
        for article in first.articles
        if article.is_fallback
    )
