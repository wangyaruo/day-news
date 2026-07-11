from __future__ import annotations

import tomllib
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from day_news.models import AppConfig, Category, SelectionPolicy, SiteConfig, SourceConfig, SourceKind


class ConfigError(ValueError):
    pass


_POLICY_INTEGER_KEYS = (
    "target_count",
    "min_count",
    "max_count",
    "min_categories",
    "min_publishers",
    "default_publisher_cap",
    "category_soft_target",
    "history_days",
    "summary_limit",
)
_POLICY_KEYS = frozenset((*_POLICY_INTEGER_KEYS, "similarity_threshold"))
_SOURCE_KEYS = frozenset(
    {
        "id",
        "publisher_id",
        "name",
        "kind",
        "url",
        "category",
        "language",
        "priority",
        "max_per_issue",
        "fetch_limit",
        "enabled",
        "timezone",
    }
)
_SITE_KEYS = frozenset(
    {
        "title",
        "description",
        "site_url",
        "base_path",
        "repository_url",
        "issues_url",
        "language",
    }
)


def load_config(path: Path, *, require_category_coverage: bool = True) -> AppConfig:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        policy = _load_policy(data["policy"])
        sources = tuple(_load_source(source_data) for source_data in data["sources"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError(f"invalid configuration: {exc}") from exc

    _validate_unique_source_ids(sources)
    _validate_policy(policy)
    _validate_source_limits(sources, policy)
    if require_category_coverage:
        _validate_enabled_source_coverage(sources, policy)

    return AppConfig(policy=policy, sources=sources)


def load_site_config(path: Path) -> SiteConfig:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise TypeError("site configuration must be a table")
        _reject_unknown_keys(data, _SITE_KEYS, "site")
        config = SiteConfig(
            title=_required_string(data, "title"),
            description=_required_string(data, "description"),
            site_url=_required_string(data, "site_url"),
            base_path=_required_string(data, "base_path"),
            repository_url=_required_string(data, "repository_url"),
            issues_url=_required_string(data, "issues_url"),
            language=_required_string(data, "language"),
        )
        _validate_site_config(config)
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise ConfigError(f"invalid site configuration: {exc}") from exc
    return config


def _validate_site_config(config: SiteConfig) -> None:
    if not config.base_path.startswith("/") or not config.base_path.endswith("/"):
        raise ValueError("base_path must start and end with a slash")
    parts = urlsplit(config.site_url)
    if parts.scheme != "https" or not parts.hostname or parts.path != config.base_path or parts.query or parts.fragment:
        raise ValueError("site_url must be HTTPS and match base_path")
    for name, value in (
        ("repository_url", config.repository_url),
        ("issues_url", config.issues_url),
    ):
        url = urlsplit(value)
        if url.scheme != "https" or not url.hostname:
            raise ValueError(f"{name} must be an HTTPS URL")


def _load_policy(data: object) -> SelectionPolicy:
    if not isinstance(data, dict):
        raise TypeError("policy must be a table")

    _reject_unknown_keys(data, _POLICY_KEYS, "policy")

    return SelectionPolicy(
        target_count=_required_integer(data, "target_count"),
        min_count=_required_integer(data, "min_count"),
        max_count=_required_integer(data, "max_count"),
        min_categories=_required_integer(data, "min_categories"),
        min_publishers=_required_integer(data, "min_publishers"),
        default_publisher_cap=_required_integer(data, "default_publisher_cap"),
        category_soft_target=_required_integer(data, "category_soft_target"),
        history_days=_required_integer(data, "history_days"),
        summary_limit=_required_integer(data, "summary_limit"),
        similarity_threshold=_required_number(data, "similarity_threshold"),
    )


def _load_source(data: object) -> SourceConfig:
    if not isinstance(data, dict):
        raise TypeError("source entry must be a table")

    _reject_unknown_keys(data, _SOURCE_KEYS, "source")

    enabled = data.get("enabled", True)
    if not isinstance(enabled, bool):
        raise TypeError("source enabled must be a boolean")

    return SourceConfig(
        id=_required_string(data, "id"),
        publisher_id=_required_string(data, "publisher_id"),
        name=_required_string(data, "name"),
        kind=SourceKind(_required_string(data, "kind")),
        url=_required_url(data),
        category=Category(_required_string(data, "category")),
        language=_required_string(data, "language"),
        priority=_required_integer(data, "priority"),
        max_per_issue=_required_integer(data, "max_per_issue"),
        fetch_limit=_required_integer(data, "fetch_limit"),
        enabled=enabled,
        timezone=_optional_timezone(data.get("timezone")),
    )


def _required_string(data: dict[str, object], key: str) -> str:
    value = data[key]
    if not isinstance(value, str):
        raise TypeError(f"{key} must be a non-empty string")

    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{key} must be a non-empty string")
    return stripped


def _required_integer(data: dict[str, object], key: str) -> int:
    value = data[key]
    if type(value) is not int:
        raise TypeError(f"{key} must be an integer")
    return value


def _required_number(data: dict[str, object], key: str) -> float:
    value = data[key]
    if type(value) not in (int, float):
        raise TypeError(f"{key} must be a number")
    return float(value)


def _required_url(data: dict[str, object]) -> str:
    value = _required_string(data, "url")
    message = "url must use http or https and include a host"
    try:
        parts = urlsplit(value)
        hostname = parts.hostname
    except ValueError as exc:
        raise ValueError(message) from exc
    if parts.scheme not in {"http", "https"} or not hostname:
        raise ValueError(message)
    return value


def _optional_timezone(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("timezone must be a non-empty string or null")

    timezone = value.strip()
    if not timezone:
        raise ValueError("timezone must be a non-empty string")
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("timezone must be a valid IANA time zone") from exc
    return timezone


def _reject_unknown_keys(data: dict[str, object], allowed_keys: frozenset[str], section: str) -> None:
    unknown_keys = data.keys() - allowed_keys
    if unknown_keys:
        raise ValueError(f"unknown {section} key: {min(unknown_keys)}")


def _validate_unique_source_ids(sources: tuple[SourceConfig, ...]) -> None:
    seen: set[str] = set()
    for source in sources:
        if source.id in seen:
            raise ConfigError(f"duplicate source id: {source.id}")
        seen.add(source.id)


def _validate_policy(policy: SelectionPolicy) -> None:
    if not 12 <= policy.min_count <= policy.target_count <= policy.max_count <= 30:
        raise ConfigError(
            "invalid configuration: count policy must satisfy 12 <= min_count <= target_count <= max_count <= 30"
        )
    if not 1 <= policy.min_categories <= len(Category):
        raise ConfigError(f"invalid configuration: min_categories must be between 1 and {len(Category)}")
    if not 1 <= policy.min_publishers <= policy.max_count:
        raise ConfigError(f"invalid configuration: min_publishers must be between 1 and max_count ({policy.max_count})")
    if policy.default_publisher_cap < 1:
        raise ConfigError("invalid configuration: default_publisher_cap must be at least 1")
    if not 1 <= policy.category_soft_target <= policy.max_count:
        raise ConfigError(
            f"invalid configuration: category_soft_target must be between 1 and max_count ({policy.max_count})"
        )
    if policy.history_days < 1:
        raise ConfigError("invalid configuration: history_days must be at least 1")
    if policy.summary_limit < 1:
        raise ConfigError("invalid configuration: summary_limit must be at least 1")
    if not 0 < policy.similarity_threshold <= 1:
        raise ConfigError("invalid configuration: similarity_threshold must be greater than 0 and at most 1")


def _validate_source_limits(sources: tuple[SourceConfig, ...], policy: SelectionPolicy) -> None:
    for source in sources:
        if source.priority < 0:
            raise ConfigError(f"invalid configuration: source {source.id} priority must be at least 0")
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
        raise ConfigError(f"invalid configuration: enabled publisher count must be at least {policy.min_publishers}")

    capacity = sum(min(caps) for caps in caps_by_publisher.values())
    if capacity < policy.target_count:
        raise ConfigError(
            f"invalid configuration: enabled publisher capacity must be at least target_count ({policy.target_count})"
        )
