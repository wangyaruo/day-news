from __future__ import annotations

from datetime import UTC, datetime

import pytest

from day_news.dedupe import deduplicate
from day_news.models import Article, Category, HistoryIndex


def _article(
    article_id: str,
    *,
    url: str | None = None,
    title_key: str | None = None,
    position: int = 0,
    rank_key: tuple[int, int, int, int, str] | None = None,
) -> Article:
    canonical_url = url or f"https://example.com/{article_id}"
    normalized_title = title_key or f"title {article_id}"
    return Article(
        id=article_id,
        title=normalized_title,
        title_key=normalized_title,
        url=canonical_url,
        canonical_url=canonical_url,
        source_id="source",
        publisher_id="publisher",
        source_name="Source",
        category=Category.WORLD,
        published_at=datetime(2026, 7, 10, 12, 0, tzinfo=UTC),
        fetched_at=datetime(2026, 7, 11, 1, 0, tzinfo=UTC),
        summary=None,
        language="en",
        is_fallback=False,
        rank_key=rank_key or (0, 10, 0, position, canonical_url),
    )


def test_deduplicates_in_fixed_reason_order() -> None:
    similar = "major science discovery " + "x" * 30
    history = HistoryIndex(
        ids=frozenset({"history-id", "all-match"}),
        canonical_urls=frozenset({"https://example.com/history-url", "https://example.com/all"}),
        title_keys=frozenset({"history exact title", similar, "all title"}),
    )
    candidates = (
        _article(
            "all-match",
            url="https://example.com/all",
            title_key="all title",
            position=0,
        ),
        _article("history-id", position=1),
        _article("url-match", url="https://example.com/history-url", position=2),
        _article("title-match", title_key="history exact title", position=3),
        _article("similar-match", title_key=similar[:-1] + "y", position=4),
        _article("kept", position=5),
    )

    result = deduplicate(candidates, history, similarity_threshold=0.92)

    assert [article.id for article in result.articles] == ["kept"]
    assert result.removed_by_reason == {
        "stable_id": 2,
        "canonical_url": 1,
        "exact_title": 1,
        "similar_title": 1,
    }


def test_current_issue_duplicates_and_shuffle_are_deterministic() -> None:
    tied_rank = (0, 10, -1, 0, "https://example.com/shared")
    first = _article("a", url="https://example.com/shared", rank_key=tied_rank)
    second = _article("b", url="https://example.com/shared", rank_key=tied_rank)
    third = _article("c", position=2)

    forward = deduplicate((second, third, first), HistoryIndex())
    reverse = deduplicate((first, third, second), HistoryIndex())

    assert [article.id for article in forward.articles] == ["a", "c"]
    assert [article.id for article in reverse.articles] == ["a", "c"]
    assert forward.removed_by_reason["canonical_url"] == 1


def test_similarity_below_threshold_is_retained() -> None:
    history = HistoryIndex(title_keys=frozenset({"alpha beta gamma"}))
    candidate = _article("new", title_key="alpha delta omega")

    result = deduplicate((candidate,), history, similarity_threshold=0.92)

    assert result.articles == (candidate,)
    assert result.removed_by_reason == {
        "stable_id": 0,
        "canonical_url": 0,
        "exact_title": 0,
        "similar_title": 0,
    }


@pytest.mark.parametrize("threshold", [0.0, -0.1, 1.01])
def test_rejects_invalid_similarity_threshold(threshold: float) -> None:
    with pytest.raises(ValueError, match="similarity_threshold"):
        deduplicate((), HistoryIndex(), similarity_threshold=threshold)
