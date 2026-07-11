from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from day_news.models import Article, Category, SelectionPolicy, SelectionResult, SourceConfig


def select_articles(
    candidates: Sequence[Article],
    sources: Sequence[SourceConfig],
    policy: SelectionPolicy,
) -> SelectionResult:
    ordered = sorted(candidates, key=lambda article: (article.rank_key, article.id))
    target_candidates = [article for article in ordered if not article.is_fallback]
    fallback_candidates = [article for article in ordered if article.is_fallback]
    publisher_caps = _publisher_caps(sources, policy.default_publisher_cap)

    selected: list[Article] = []
    selected_ids: set[str] = set()
    category_counts: Counter[Category] = Counter()
    publisher_counts: Counter[str] = Counter()

    def can_add(article: Article) -> bool:
        cap = publisher_caps.get(article.publisher_id, policy.default_publisher_cap)
        return (
            article.id not in selected_ids
            and len(selected) < policy.max_count
            and publisher_counts[article.publisher_id] < cap
        )

    def add(article: Article) -> bool:
        if not can_add(article):
            return False
        selected.append(article)
        selected_ids.add(article.id)
        category_counts[article.category] += 1
        publisher_counts[article.publisher_id] += 1
        return True

    def seed_categories(pool: Sequence[Article], *, required_only: bool) -> None:
        for category in Category:
            if category_counts[category]:
                continue
            for article in pool:
                if article.category is category and add(article):
                    break
            if required_only and len(category_counts) >= policy.min_categories:
                return

    def seed_publishers(pool: Sequence[Article], *, required_only: bool) -> None:
        for article in pool:
            if article.publisher_id in publisher_counts:
                continue
            add(article)
            if required_only and len(publisher_counts) >= policy.min_publishers:
                return
            if not required_only and len(selected) >= policy.target_count:
                return

    def fill(pool: Sequence[Article], *, respect_category_target: bool) -> None:
        for article in pool:
            if len(selected) >= policy.target_count:
                return
            if respect_category_target and category_counts[article.category] >= policy.category_soft_target:
                continue
            add(article)

    seed_categories(target_candidates, required_only=False)
    seed_publishers(target_candidates, required_only=False)
    fill(target_candidates, respect_category_target=True)
    fill(target_candidates, respect_category_target=False)

    needs_fallback = (
        len(selected) < policy.target_count
        or len(category_counts) < policy.min_categories
        or len(publisher_counts) < policy.min_publishers
    )
    if needs_fallback:
        seed_categories(fallback_candidates, required_only=True)
        seed_publishers(fallback_candidates, required_only=True)
        fill(fallback_candidates, respect_category_target=True)
        fill(fallback_candidates, respect_category_target=False)

    articles = tuple(
        sorted(
            selected,
            key=lambda article: (list(Category).index(article.category), article.rank_key, article.id),
        )
    )
    category_count = len({article.category for article in articles})
    publisher_count = len({article.publisher_id for article in articles})
    valid = (
        len(articles) >= policy.min_count
        and category_count >= policy.min_categories
        and publisher_count >= policy.min_publishers
    )
    failure_reason = None
    if not valid:
        failure_reason = (
            "publication threshold not met: "
            f"count={len(articles)}, categories={category_count}, publishers={publisher_count}"
        )

    return SelectionResult(
        articles=articles,
        valid=valid,
        failure_reason=failure_reason,
    )


def _publisher_caps(
    sources: Sequence[SourceConfig],
    default_cap: int,
) -> dict[str, int]:
    caps: dict[str, int] = {}
    for source in sources:
        if not source.enabled:
            continue
        configured = min(default_cap, source.max_per_issue)
        caps[source.publisher_id] = min(caps.get(source.publisher_id, configured), configured)
    return caps
