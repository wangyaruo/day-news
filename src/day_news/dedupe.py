from __future__ import annotations

from collections.abc import Sequence
from difflib import SequenceMatcher

from day_news.models import Article, DedupeResult, HistoryIndex

REASONS = ("stable_id", "canonical_url", "exact_title", "similar_title")


def deduplicate(
    candidates: Sequence[Article],
    history: HistoryIndex,
    similarity_threshold: float = 0.92,
) -> DedupeResult:
    if not 0 < similarity_threshold <= 1:
        raise ValueError("similarity_threshold must be greater than 0 and at most 1")

    known_ids = set(history.ids)
    known_urls = set(history.canonical_urls)
    known_titles = set(history.title_keys)
    removed = {reason: 0 for reason in REASONS}
    kept: list[Article] = []

    for article in sorted(candidates, key=lambda candidate: (candidate.rank_key, candidate.id)):
        reason = _duplicate_reason(
            article,
            known_ids,
            known_urls,
            known_titles,
            similarity_threshold,
        )
        if reason is not None:
            removed[reason] += 1
            continue

        kept.append(article)
        known_ids.add(article.id)
        known_urls.add(article.canonical_url)
        known_titles.add(article.title_key)

    return DedupeResult(articles=tuple(kept), removed_by_reason=removed)


def _duplicate_reason(
    article: Article,
    known_ids: set[str],
    known_urls: set[str],
    known_titles: set[str],
    similarity_threshold: float,
) -> str | None:
    if article.id in known_ids:
        return "stable_id"
    if article.canonical_url in known_urls:
        return "canonical_url"
    if article.title_key in known_titles:
        return "exact_title"
    if any(
        SequenceMatcher(None, article.title_key, known_title).ratio() >= similarity_threshold
        for known_title in sorted(known_titles)
    ):
        return "similar_title"
    return None
