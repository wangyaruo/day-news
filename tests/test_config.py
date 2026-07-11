from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import get_type_hints

import pytest

from day_news.config import ConfigError, load_config
from day_news.models import Article, Category, RawEntry, RunReport, SourceKind

CONFIG_PATH = Path(__file__).parents[1] / "config" / "sources.toml"
EXPECTED_SOURCE_IDS = frozenset(
    {
        "ars-technica",
        "bbc-business",
        "bbc-culture",
        "bbc-science",
        "bbc-sport",
        "bbc-technology",
        "bbc-world",
        "cnbc-business",
        "dw-world",
        "espn-sport",
        "guardian-business",
        "guardian-culture",
        "guardian-science",
        "guardian-sport",
        "guardian-technology",
        "guardian-world",
        "hacker-news",
        "nasa-science",
        "npr-business",
        "npr-culture",
        "npr-science",
        "npr-technology",
        "npr-world",
        "smithsonian-culture",
        "solidot",
    }
)
POLICY_INTEGER_FIELDS = (
    ("target_count", "24"),
    ("min_count", "12"),
    ("max_count", "30"),
    ("min_categories", "4"),
    ("min_publishers", "5"),
    ("default_publisher_cap", "3"),
    ("category_soft_target", "4"),
    ("history_days", "30"),
    ("summary_limit", "180"),
)
POLICY_SEMANTIC_CASES = (
    ("min_categories", "4", "0"),
    ("min_categories", "4", str(len(Category) + 1)),
    ("min_publishers", "5", "0"),
    ("min_publishers", "5", "-1"),
    ("min_publishers", "5", "31"),
    ("default_publisher_cap", "3", "0"),
    ("default_publisher_cap", "3", "-1"),
    ("category_soft_target", "4", "0"),
    ("category_soft_target", "4", "-1"),
    ("history_days", "30", "0"),
    ("history_days", "30", "-1"),
    ("summary_limit", "180", "0"),
    ("summary_limit", "180", "-1"),
)


def _base_config_text() -> str:
    return CONFIG_PATH.read_text(encoding="utf-8")


def _replace_once(content: str, old: str, new: str) -> str:
    assert old in content
    return content.replace(old, new, 1)


def _replace_source_line(content: str, source_id: str, old: str, new: str) -> str:
    source_start = content.index(f'id = "{source_id}"')
    source_end = content.find("\n[[sources]]", source_start)
    if source_end == -1:
        source_end = len(content)
    source_block = content[source_start:source_end]
    assert old in source_block
    return content[:source_start] + source_block.replace(old, new, 1) + content[source_end:]


def _write_temp_config(tmp_path: Path, content: str) -> Path:
    config_path = tmp_path / "sources.toml"
    config_path.write_text(content, encoding="utf-8")
    return config_path


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
    assert len(config.sources) == 25
    assert {source.id for source in config.sources} == EXPECTED_SOURCE_IDS


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


@pytest.mark.parametrize("invalid_literal", ["10.9", "true", '"10"'])
def test_source_priority_requires_a_toml_integer(tmp_path: Path, invalid_literal: str) -> None:
    content = _replace_once(_base_config_text(), "priority = 10", f"priority = {invalid_literal}")
    config_path = _write_temp_config(tmp_path, content)

    with pytest.raises(ConfigError, match="priority must be an integer"):
        load_config(config_path, require_category_coverage=False)


def test_source_priority_must_not_be_negative(tmp_path: Path) -> None:
    content = _replace_once(_base_config_text(), "priority = 10", "priority = -1")
    config_path = _write_temp_config(tmp_path, content)

    with pytest.raises(ConfigError, match="priority must be at least 0"):
        load_config(config_path, require_category_coverage=False)


@pytest.mark.parametrize("invalid_literal", ["true", "10.5", '"10"'])
@pytest.mark.parametrize(("field", "valid_literal"), POLICY_INTEGER_FIELDS)
def test_policy_integer_fields_require_toml_integers(
    tmp_path: Path,
    field: str,
    valid_literal: str,
    invalid_literal: str,
) -> None:
    content = _replace_once(
        _base_config_text(),
        f"{field} = {valid_literal}",
        f"{field} = {invalid_literal}",
    )
    config_path = _write_temp_config(tmp_path, content)

    with pytest.raises(ConfigError, match=rf"{field} must be an integer"):
        load_config(config_path, require_category_coverage=False)


@pytest.mark.parametrize("invalid_literal", ["true", '"0.92"'])
def test_similarity_threshold_rejects_bool_and_string(tmp_path: Path, invalid_literal: str) -> None:
    content = _replace_once(
        _base_config_text(),
        "similarity_threshold = 0.92",
        f"similarity_threshold = {invalid_literal}",
    )
    config_path = _write_temp_config(tmp_path, content)

    with pytest.raises(ConfigError, match="similarity_threshold must be a number"):
        load_config(config_path, require_category_coverage=False)


def test_similarity_threshold_accepts_toml_integer(tmp_path: Path) -> None:
    content = _replace_once(
        _base_config_text(),
        "similarity_threshold = 0.92",
        "similarity_threshold = 1",
    )
    config = load_config(
        _write_temp_config(tmp_path, content),
        require_category_coverage=False,
    )

    assert config.policy.similarity_threshold == 1.0


@pytest.mark.parametrize("invalid_literal", ["0", "-0.1", "1.01"])
def test_similarity_threshold_must_be_in_range(tmp_path: Path, invalid_literal: str) -> None:
    content = _replace_once(
        _base_config_text(),
        "similarity_threshold = 0.92",
        f"similarity_threshold = {invalid_literal}",
    )
    config_path = _write_temp_config(tmp_path, content)

    with pytest.raises(ConfigError, match="similarity_threshold"):
        load_config(config_path, require_category_coverage=False)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("min_count = 12", "min_count = 11"),
        ("target_count = 24", "target_count = 11"),
        ("max_count = 30", "max_count = 31"),
        ("min_count = 12", "min_count = 25"),
        ("max_count = 30", "max_count = 23"),
    ],
)
def test_count_policy_rejects_invalid_order_or_bounds(tmp_path: Path, old: str, new: str) -> None:
    config_path = _write_temp_config(tmp_path, _replace_once(_base_config_text(), old, new))

    with pytest.raises(ConfigError, match="count policy"):
        load_config(config_path, require_category_coverage=False)


@pytest.mark.parametrize(("field", "valid_literal", "invalid_literal"), POLICY_SEMANTIC_CASES)
def test_policy_semantics_reject_invalid_values(
    tmp_path: Path,
    field: str,
    valid_literal: str,
    invalid_literal: str,
) -> None:
    content = _replace_once(
        _base_config_text(),
        f"{field} = {valid_literal}",
        f"{field} = {invalid_literal}",
    )
    config_path = _write_temp_config(tmp_path, content)

    with pytest.raises(ConfigError, match=field):
        load_config(config_path, require_category_coverage=False)


@pytest.mark.parametrize(
    ("field", "original"),
    [
        ("id", "bbc-world"),
        ("publisher_id", "bbc"),
        ("name", "BBC World"),
        ("language", "en"),
    ],
)
def test_required_source_strings_reject_whitespace(
    tmp_path: Path,
    field: str,
    original: str,
) -> None:
    content = _replace_once(
        _base_config_text(),
        f'{field} = "{original}"',
        f'{field} = "   "',
    )
    config_path = _write_temp_config(tmp_path, content)

    with pytest.raises(ConfigError, match=rf"{field} must be a non-empty string"):
        load_config(config_path, require_category_coverage=False)


def test_required_source_strings_are_stripped(tmp_path: Path) -> None:
    content = _base_config_text()
    for field, value in (
        ("id", "bbc-world"),
        ("publisher_id", "bbc"),
        ("name", "BBC World"),
        ("url", "https://feeds.bbci.co.uk/news/world/rss.xml"),
        ("language", "en"),
    ):
        content = _replace_once(
            content,
            f'{field} = "{value}"',
            f'{field} = "  {value}  "',
        )

    source = load_config(
        _write_temp_config(tmp_path, content),
        require_category_coverage=False,
    ).sources[0]

    assert (source.id, source.publisher_id, source.name, source.url, source.language) == (
        "bbc-world",
        "bbc",
        "BBC World",
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        "en",
    )


@pytest.mark.parametrize(
    "invalid_url",
    ["ftp://example.com/feed", "example.com/feed", "https:///feed"],
)
def test_source_url_requires_http_scheme_and_host(tmp_path: Path, invalid_url: str) -> None:
    content = _replace_once(
        _base_config_text(),
        'url = "https://feeds.bbci.co.uk/news/world/rss.xml"',
        f'url = "{invalid_url}"',
    )
    config_path = _write_temp_config(tmp_path, content)

    with pytest.raises(ConfigError, match="url must use http or https and include a host"):
        load_config(config_path, require_category_coverage=False)


@pytest.mark.parametrize("invalid_timezone", ["Mars/Olympus_Mons", "   "])
def test_source_timezone_must_be_valid_iana_name(tmp_path: Path, invalid_timezone: str) -> None:
    content = _replace_once(
        _base_config_text(),
        'timezone = "UTC"',
        f'timezone = "{invalid_timezone}"',
    )
    config_path = _write_temp_config(tmp_path, content)

    with pytest.raises(ConfigError, match="timezone"):
        load_config(config_path, require_category_coverage=False)


def test_unknown_source_key_is_rejected(tmp_path: Path) -> None:
    content = _replace_once(_base_config_text(), "enabled = true", "enable = false")
    config_path = _write_temp_config(tmp_path, content)

    with pytest.raises(ConfigError, match="unknown source key: enable"):
        load_config(config_path, require_category_coverage=False)


def test_unknown_policy_key_is_rejected(tmp_path: Path) -> None:
    content = _replace_once(
        _base_config_text(),
        "similarity_threshold = 0.92",
        "similarity_threshold = 0.92\nunexpected = true",
    )
    config_path = _write_temp_config(tmp_path, content)

    with pytest.raises(ConfigError, match="unknown policy key: unexpected"):
        load_config(config_path, require_category_coverage=False)


@pytest.mark.parametrize("invalid_cap", ["0", "-1", "4"])
def test_source_cap_must_be_within_policy_limit(tmp_path: Path, invalid_cap: str) -> None:
    content = _replace_once(
        _base_config_text(),
        "max_per_issue = 3",
        f"max_per_issue = {invalid_cap}",
    )
    config_path = _write_temp_config(tmp_path, content)

    with pytest.raises(ConfigError, match="max_per_issue"):
        load_config(config_path, require_category_coverage=False)


@pytest.mark.parametrize("invalid_limit", ["0", "-1"])
def test_source_fetch_limit_must_be_positive(tmp_path: Path, invalid_limit: str) -> None:
    content = _replace_once(
        _base_config_text(),
        "fetch_limit = 60",
        f"fetch_limit = {invalid_limit}",
    )
    config_path = _write_temp_config(tmp_path, content)

    with pytest.raises(ConfigError, match="fetch_limit"):
        load_config(config_path, require_category_coverage=False)


def test_category_coverage_rejects_fewer_than_two_enabled_publishers(tmp_path: Path) -> None:
    content = _base_config_text()
    for source_id in ("guardian-sport", "espn-sport"):
        content = _replace_source_line(content, source_id, "enabled = true", "enabled = false")
    config_path = _write_temp_config(tmp_path, content)

    with pytest.raises(ConfigError, match="undercovered categories: sports"):
        load_config(config_path)


def test_enabled_publisher_count_must_reach_policy_minimum(tmp_path: Path) -> None:
    content = _replace_once(_base_config_text(), "min_publishers = 5", "min_publishers = 12")
    config_path = _write_temp_config(tmp_path, content)

    with pytest.raises(ConfigError, match="enabled publisher count"):
        load_config(config_path)


def test_enabled_publisher_capacity_must_reach_target(tmp_path: Path) -> None:
    content = _base_config_text().replace("max_per_issue = 3", "max_per_issue = 1")
    config_path = _write_temp_config(tmp_path, content)

    with pytest.raises(ConfigError, match="enabled publisher capacity"):
        load_config(config_path)
