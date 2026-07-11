from __future__ import annotations

import tomllib
from collections import defaultdict
from pathlib import Path

from day_news.models import AppConfig, Category, SelectionPolicy, SourceConfig, SourceKind


class ConfigError(ValueError):
    pass


def load_config(path: Path, *, require_category_coverage: bool = True) -> AppConfig:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        policy_data = data["policy"]
        policy = SelectionPolicy(
            target_count=int(policy_data["target_count"]),
            min_count=int(policy_data["min_count"]),
            max_count=int(policy_data["max_count"]),
            min_categories=int(policy_data["min_categories"]),
            min_publishers=int(policy_data["min_publishers"]),
            default_publisher_cap=int(policy_data["default_publisher_cap"]),
            category_soft_target=int(policy_data["category_soft_target"]),
            history_days=int(policy_data["history_days"]),
            summary_limit=int(policy_data["summary_limit"]),
            similarity_threshold=float(policy_data["similarity_threshold"]),
        )
        sources = tuple(_load_source(source_data) for source_data in data["sources"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError(f"invalid configuration: {exc}") from exc

    _validate_unique_source_ids(sources)
    _validate_policy(policy)
    _validate_source_limits(sources, policy)
    if require_category_coverage:
        _validate_enabled_source_coverage(sources, policy)

    return AppConfig(policy=policy, sources=sources)


def _load_source(data: object) -> SourceConfig:
    if not isinstance(data, dict):
        raise TypeError("source entry must be a table")

    enabled = data.get("enabled", True)
    if not isinstance(enabled, bool):
        raise TypeError("source enabled must be a boolean")

    timezone = data.get("timezone")
    if timezone is not None and not isinstance(timezone, str):
        raise TypeError("source timezone must be a string or null")

    return SourceConfig(
        id=_required_string(data, "id"),
        publisher_id=_required_string(data, "publisher_id"),
        name=_required_string(data, "name"),
        kind=SourceKind(data["kind"]),
        url=_required_string(data, "url"),
        category=Category(data["category"]),
        language=_required_string(data, "language"),
        priority=int(data["priority"]),
        max_per_issue=int(data["max_per_issue"]),
        fetch_limit=int(data["fetch_limit"]),
        enabled=enabled,
        timezone=timezone,
    )


def _required_string(data: dict[str, object], key: str) -> str:
    value = data[key]
    if not isinstance(value, str):
        raise TypeError(f"{key} must be a string")
    return value


def _validate_unique_source_ids(sources: tuple[SourceConfig, ...]) -> None:
    seen: set[str] = set()
    for source in sources:
        if source.id in seen:
            raise ConfigError(f"duplicate source id: {source.id}")
        seen.add(source.id)


def _validate_policy(policy: SelectionPolicy) -> None:
    if not 12 <= policy.min_count <= policy.target_count <= policy.max_count <= 30:
        raise ConfigError(
            "invalid configuration: count policy must satisfy "
            "12 <= min_count <= target_count <= max_count <= 30"
        )
    if not 0 < policy.similarity_threshold <= 1:
        raise ConfigError("invalid configuration: similarity_threshold must be greater than 0 and at most 1")


def _validate_source_limits(sources: tuple[SourceConfig, ...], policy: SelectionPolicy) -> None:
    for source in sources:
        if not 1 <= source.max_per_issue <= policy.default_publisher_cap:
            raise ConfigError(
                f"invalid configuration: source {source.id} max_per_issue must be between 1 "
                f"and {policy.default_publisher_cap}"
            )
        if source.fetch_limit < 1:
            raise ConfigError(f"invalid configuration: source {source.id} fetch_limit must be at least 1")


def _validate_enabled_source_coverage(
    sources: tuple[SourceConfig, ...],
    policy: SelectionPolicy,
) -> None:
    publishers_by_category: dict[Category, set[str]] = {category: set() for category in Category}
    caps_by_publisher: defaultdict[str, list[int]] = defaultdict(list)

    for source in sources:
        if not source.enabled:
            continue
        publishers_by_category[source.category].add(source.publisher_id)
        caps_by_publisher[source.publisher_id].append(source.max_per_issue)

    undercovered = [category.value for category, publishers in publishers_by_category.items() if len(publishers) < 2]
    if undercovered:
        raise ConfigError(
            "invalid configuration: each category must have at least two enabled publishers; "
            f"undercovered categories: {', '.join(undercovered)}"
        )

    if len(caps_by_publisher) < policy.min_publishers:
        raise ConfigError(
            "invalid configuration: enabled publisher count must be at least "
            f"{policy.min_publishers}"
        )

    capacity = sum(min(caps) for caps in caps_by_publisher.values())
    if capacity < policy.target_count:
        raise ConfigError(
            "invalid configuration: enabled publisher capacity must be at least "
            f"target_count ({policy.target_count})"
        )
