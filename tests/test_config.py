from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import get_type_hints

import pytest

from day_news.config import ConfigError, load_config
from day_news.models import Article, Category, RawEntry, RunReport, SourceKind

CONFIG_PATH = Path(__file__).parents[1] / "config" / "sources.toml"


def test_loads_expected_policy_source_kinds_and_categories() -> None:
    config = load_config(CONFIG_PATH)

    assert (
        config.policy.target_count,
        config.policy.min_count,
        config.policy.max_count,
    ) == (24, 12, 30)
    assert {source.kind for source in config.sources} == {
        SourceKind.RSS,
        SourceKind.HACKER_NEWS,
    }
    assert {source.category for source in config.sources} == set(Category)


def test_each_category_has_at_least_two_enabled_publishers() -> None:
    config = load_config(CONFIG_PATH)
    publishers_by_category: defaultdict[Category, set[str]] = defaultdict(set)

    for source in config.sources:
        if source.enabled:
            publishers_by_category[source.category].add(source.publisher_id)

    assert all(len(publishers_by_category[category]) >= 2 for category in Category)


def test_enabled_publishers_and_capacity_satisfy_policy() -> None:
    config = load_config(CONFIG_PATH)
    caps_by_publisher: defaultdict[str, list[int]] = defaultdict(list)

    for source in config.sources:
        if source.enabled:
            caps_by_publisher[source.publisher_id].append(source.max_per_issue)

    assert len(caps_by_publisher) >= config.policy.min_publishers
    assert sum(min(caps) for caps in caps_by_publisher.values()) >= config.policy.target_count


def test_duplicate_source_ids_are_rejected(tmp_path: Path) -> None:
    config_path = tmp_path / "duplicate-sources.toml"
    config_path.write_text(
        """
[policy]
target_count = 24
min_count = 12
max_count = 30
min_categories = 4
min_publishers = 5
default_publisher_cap = 3
category_soft_target = 4
history_days = 30
summary_limit = 180
similarity_threshold = 0.92

[[sources]]
id = "same"
publisher_id = "publisher-one"
name = "Source One"
kind = "rss"
url = "https://example.com/one.xml"
category = "world"
language = "en"
priority = 10
max_per_issue = 3
fetch_limit = 60

[[sources]]
id = "same"
publisher_id = "publisher-two"
name = "Source Two"
kind = "rss"
url = "https://example.com/two.xml"
category = "business"
language = "en"
priority = 20
max_per_issue = 3
fetch_limit = 60
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="duplicate source id"):
        load_config(config_path, require_category_coverage=False)


def test_nullable_article_input_fields_are_part_of_the_public_contract() -> None:
    raw_entry_hints = get_type_hints(RawEntry)
    article_hints = get_type_hints(Article)

    assert raw_entry_hints["external_id"] == str | None
    assert raw_entry_hints["title"] == str | None
    assert raw_entry_hints["url"] == str | None
    assert raw_entry_hints["summary_html"] == str | None
    assert article_hints["summary"] == str | None


def test_run_report_serializes_string_date_and_sorted_sources() -> None:
    report = RunReport(
        target_date="2026-07-11",
        successful_sources=["source-z", "source-a"],
        failed_sources={"source-z": "timeout", "source-a": "invalid feed"},
    )

    payload = report.to_dict()

    assert list(payload) == [
        "target_date",
        "status",
        "successful_sources",
        "failed_sources",
        "fetched_count",
        "window_count",
        "duplicate_count",
        "selected_count",
        "fallback_count",
        "failure_reason",
    ]
    assert payload["target_date"] == "2026-07-11"
    assert payload["successful_sources"] == ["source-a", "source-z"]
    assert payload["failed_sources"] == {
        "source-a": "invalid feed",
        "source-z": "timeout",
    }


def test_non_table_source_is_wrapped_as_config_error(tmp_path: Path) -> None:
    config_path = tmp_path / "non-table-source.toml"
    config_path.write_text(
        """
sources = [1]

[policy]
target_count = 24
min_count = 12
max_count = 30
min_categories = 4
min_publishers = 5
default_publisher_cap = 3
category_soft_target = 4
history_days = 30
summary_limit = 180
similarity_threshold = 0.92
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="invalid configuration"):
        load_config(config_path, require_category_coverage=False)
