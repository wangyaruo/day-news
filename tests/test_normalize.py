from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone, tzinfo

import pytest

from day_news.models import Category, RawEntry, SourceConfig, SourceKind
from day_news.normalize import (
    build_rank_key,
    canonicalize_url,
    clean_summary,
    is_tracking_key,
    normalize_entry,
    parse_published,
    title_key,
)
from day_news.time_window import build_window

SOURCE = SourceConfig(
    id="example",
    publisher_id="example",
    name="Example",
    kind=SourceKind.RSS,
    url="https://example.com/feed.xml",
    category=Category.WORLD,
    language="en",
    priority=10,
    max_per_issue=3,
    fetch_limit=60,
    timezone="UTC",
)

BASE_RAW = RawEntry(
    external_id="item-1",
    title="Example story",
    url="https://example.com/story",
    published_value="2026-07-10T12:00:00Z",
    summary_html="<p>Summary</p>",
    source_position=2,
)


class RaisingTimezone(tzinfo):
    def utcoffset(self, value: datetime | None) -> timedelta | None:
        raise RuntimeError("utcoffset failed")


@pytest.mark.parametrize(
    "value",
    [
        "ftp://example.com/story",
        "mailto:editor@example.com",
        "https:///story",
        "https://",
        "https://example.com:not-a-port/story",
        "https://example.com:70000/story",
        "https://[::1/story",
    ],
)
def test_canonicalize_url_rejects_non_http_and_invalid_urls(value: str) -> None:
    assert canonicalize_url(value) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("HTTP://EXAMPLE.COM:80/story/#part", "http://example.com/story"),
        ("HTTPS://EXAMPLE.COM:443/", "https://example.com/"),
        ("https://EXAMPLE.COM:8443/story/", "https://example.com:8443/story"),
        ("http://EXAMPLE.COM:8080/news/#top", "http://example.com:8080/news"),
    ],
)
def test_canonicalize_url_normalizes_authority_path_and_fragment(value: str, expected: str) -> None:
    assert canonicalize_url(value) == expected


def test_canonicalize_url_strips_input_and_normalizes_empty_path_to_root() -> None:
    assert canonicalize_url("  HTTPS://EXAMPLE.COM:443  ") == "https://example.com/"


def test_canonicalize_url_drops_userinfo_from_canonical_authority() -> None:
    value = "https://User:Secret@EXAMPLE.COM/story"
    assert canonicalize_url(value) == "https://example.com/story"


def test_canonicalize_url_preserves_brackets_for_ipvfuture_hosts() -> None:
    value = "HTTP://[v1.Fe80]:8080/story/"
    assert canonicalize_url(value) == "http://[v1.fe80]:8080/story"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://faß.de/story", "https://faß.de/story"),
        ("https://FAẞ.DE/story", "https://faß.de/story"),
    ],
)
def test_canonicalize_url_lowercases_unicode_hostname_without_casefold_collision(
    value: str,
    expected: str,
) -> None:
    assert canonicalize_url(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "https://example.com/?x=\ud800",
        "https://example.com/\ud800",
        "https://\ud800.example/",
    ],
)
def test_canonicalize_url_safely_rejects_unencodable_components(value: str) -> None:
    assert canonicalize_url(value) is None


@pytest.mark.parametrize("character", [" ", "\n", "\t", "\x00", "\u00a0"])
def test_canonicalize_url_rejects_internal_raw_whitespace_and_controls(character: str) -> None:
    assert canonicalize_url(f"https://example.com/a{character}b") is None


def test_canonicalize_url_percent_encodes_unicode_path() -> None:
    assert canonicalize_url("https://example.com/新闻") == "https://example.com/%E6%96%B0%E9%97%BB"


def test_canonicalize_url_encodes_unsafe_path_characters() -> None:
    value = r"https://example.com/a<>[]\b"
    assert canonicalize_url(value) == "https://example.com/a%3C%3E%5B%5D%5Cb"


def test_canonicalize_url_preserves_rfc3986_path_separators_and_pchar() -> None:
    value = "https://example.com/a/b-._~!$&'()*+,;=:@c"
    assert canonicalize_url(value) == value


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://example.com/%E6%96%B0", "https://example.com/%E6%96%B0"),
        ("https://example.com/with%20space", "https://example.com/with%20space"),
        ("https://example.com/%ZZ", None),
        ("https://example.com/%", None),
        ("https://example.com/%2", None),
    ],
)
def test_canonicalize_url_validates_existing_path_percent_escapes(
    value: str,
    expected: str | None,
) -> None:
    assert canonicalize_url(value) == expected


def test_canonicalize_url_rejects_markdown_destination_injection_path() -> None:
    value = "https://example.com/foo>) ![x](https://attacker.example/x)"
    assert canonicalize_url(value) is None


def test_canonicalize_url_removes_only_known_tracking_parameters() -> None:
    value = "https://EXAMPLE.com/story/?id=7&utm_source=x&fbclid=y#section"
    assert canonicalize_url(value) == "https://example.com/story?id=7"


def test_canonicalize_url_filters_tracking_case_insensitively_and_sorts_remaining_query() -> None:
    value = (
        "https://example.com/story?z=&UTM_Campaign=x&fbclid=1&GCLID=2&mc_CID=3&MC_EID=4&SpM=5"
        "&b=two&a=&b=one&utm=business"
    )

    assert canonicalize_url(value) == "https://example.com/story?a=&b=one&b=two&utm=business&z="


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("utm_source", True),
        ("UTM_Custom", True),
        ("fbclid", True),
        ("GCLID", True),
        ("mc_cid", True),
        ("MC_EID", True),
        ("SpM", True),
        ("utm", False),
        ("campaign", False),
    ],
)
def test_is_tracking_key_matches_only_known_tracking_names(key: str, expected: bool) -> None:
    assert is_tracking_key(key) is expected


def test_title_key_normalizes_width_case_punctuation_and_space() -> None:
    assert title_key("ＡI：  Big   News!") == "ai big news"


def test_title_key_replaces_unicode_punctuation_and_symbols_with_spaces() -> None:
    assert title_key(" C++\t&\nAI—News ©2026 ") == "c ai news 2026"


def test_summary_removes_unsafe_html_and_stays_within_limit() -> None:
    value = "<style>x</style><script>alert(1)</script><p>" + "新" * 181 + "</p>"
    result = clean_summary(value, limit=180)
    assert result is not None
    assert len(result) == 180
    assert result.endswith("…")
    assert "alert" not in result


def test_summary_keeps_only_folded_text_from_html() -> None:
    value = "<p>Hello&nbsp; world</p><div>Next <b>item</b></div>"
    assert clean_summary(value, limit=180) == "Hello world Next item"


@pytest.mark.parametrize("value", [None, "", "<script>bad()</script><style>x</style><p> \n </p>"])
def test_summary_returns_none_when_no_safe_text_remains(value: str | None) -> None:
    assert clean_summary(value, limit=180) is None


def test_summary_preserves_exact_limit_and_truncates_one_character_over() -> None:
    exact = "新" * 180

    assert clean_summary(exact, limit=180) == exact
    assert clean_summary(exact + "闻", limit=180) == "新" * 179 + "…"


@pytest.mark.parametrize("limit", [0, -1])
def test_summary_rejects_non_positive_limits(limit: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        clean_summary("Summary", limit=limit)


def test_parse_published_converts_aware_datetime_to_utc() -> None:
    value = datetime(2026, 7, 10, 17, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))

    result = parse_published(value, source_timezone=None)

    assert result == datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
    assert result is not None
    assert result.tzinfo is UTC


def test_parse_published_accepts_integer_timestamp_but_rejects_booleans() -> None:
    expected = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
    timestamp = int(expected.timestamp())

    assert parse_published(timestamp, source_timezone=None) == expected
    assert parse_published(True, source_timezone="UTC") is None
    assert parse_published(False, source_timezone="UTC") is None


def test_parse_published_accepts_aware_string_and_converts_it_to_utc() -> None:
    result = parse_published("2026-07-10T20:00:00+08:00", source_timezone=None)
    assert result == datetime(2026, 7, 10, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "value",
    [datetime(2026, 7, 10, 12, 0), "2026-07-10 12:00:00"],
)
def test_parse_published_uses_configured_timezone_for_naive_values(value: str | datetime) -> None:
    result = parse_published(value, source_timezone="Asia/Shanghai")
    assert result == datetime(2026, 7, 10, 4, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "value",
    [datetime(2026, 7, 10, 12, 0), "2026-07-10 12:00:00"],
)
def test_parse_published_rejects_naive_values_without_configured_timezone(value: str | datetime) -> None:
    assert parse_published(value, source_timezone=None) is None


@pytest.mark.parametrize(
    ("value", "source_timezone"),
    [
        ("not a date", "UTC"),
        (datetime(2026, 7, 10, 12, 0), "Mars/Olympus"),
        ("2026-07-10 12:00:00", "Mars/Olympus"),
        (10**100, None),
    ],
)
def test_parse_published_returns_none_for_invalid_values_and_timezones(
    value: str | int | datetime,
    source_timezone: str | None,
) -> None:
    assert parse_published(value, source_timezone=source_timezone) is None


def test_parse_published_safely_rejects_raising_timezone() -> None:
    value = datetime(2026, 7, 10, 12, 0, tzinfo=RaisingTimezone())
    assert parse_published(value, source_timezone=None) is None


def test_rank_key_sorting_obeys_the_complete_ordering_contract() -> None:
    newer = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
    older = datetime(2026, 7, 10, 11, 0, tzinfo=UTC)
    candidates = [
        (
            "fallback",
            build_rank_key(
                is_fallback=True,
                priority=0,
                published_at=newer,
                source_position=0,
                canonical_url="https://example.com/fallback",
            ),
        ),
        (
            "higher-priority-number",
            build_rank_key(
                is_fallback=False,
                priority=20,
                published_at=newer,
                source_position=0,
                canonical_url="https://example.com/priority-20",
            ),
        ),
        (
            "older",
            build_rank_key(
                is_fallback=False,
                priority=10,
                published_at=older,
                source_position=0,
                canonical_url="https://example.com/older",
            ),
        ),
        (
            "later-position",
            build_rank_key(
                is_fallback=False,
                priority=10,
                published_at=newer,
                source_position=2,
                canonical_url="https://example.com/later-position",
            ),
        ),
        (
            "url-z",
            build_rank_key(
                is_fallback=False,
                priority=10,
                published_at=newer,
                source_position=1,
                canonical_url="https://example.com/z",
            ),
        ),
        (
            "url-a",
            build_rank_key(
                is_fallback=False,
                priority=10,
                published_at=newer,
                source_position=1,
                canonical_url="https://example.com/a",
            ),
        ),
    ]

    assert [name for name, _ in sorted(candidates, key=lambda item: item[1])] == [
        "url-a",
        "url-z",
        "later-position",
        "older",
        "higher-priority-number",
        "fallback",
    ]


def test_rank_key_uses_exact_utc_epoch_microseconds() -> None:
    utc_value = datetime(1970, 1, 1, 0, 0, 0, 1, tzinfo=UTC)
    offset_value = datetime(1970, 1, 1, 8, 0, 0, 1, tzinfo=timezone(timedelta(hours=8)))

    utc_key = build_rank_key(
        is_fallback=False,
        priority=10,
        published_at=utc_value,
        source_position=0,
        canonical_url="https://example.com/story",
    )
    offset_key = build_rank_key(
        is_fallback=False,
        priority=10,
        published_at=offset_value,
        source_position=0,
        canonical_url="https://example.com/story",
    )

    assert utc_key[2] == -1
    assert offset_key == utc_key


def test_rank_key_rejects_naive_published_at() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        build_rank_key(
            is_fallback=False,
            priority=10,
            published_at=datetime(2026, 7, 10, 12, 0),
            source_position=0,
            canonical_url="https://example.com/story",
        )


def test_rank_key_wraps_raising_timezone_as_clear_value_error() -> None:
    value = datetime(2026, 7, 10, 12, 0, tzinfo=RaisingTimezone())

    with pytest.raises(ValueError, match="published_at must be timezone-aware") as error:
        build_rank_key(
            is_fallback=False,
            priority=10,
            published_at=value,
            source_position=0,
            canonical_url="https://example.com/story",
        )

    assert isinstance(error.value.__cause__, RuntimeError)


def test_normalize_entry_marks_fallback_and_builds_stable_id() -> None:
    raw = RawEntry(
        external_id="item-1",
        title="Example story",
        url="https://example.com/story?utm_medium=rss",
        published_value="2026-07-09T12:00:00Z",
        summary_html="<p>Summary</p>",
        source_position=2,
    )
    article = normalize_entry(
        raw,
        SOURCE,
        fetched_at=datetime(2026, 7, 11, 1, 0, tzinfo=UTC),
        window=build_window(date(2026, 7, 10)),
        summary_limit=180,
    )
    assert article is not None
    assert article.is_fallback is True
    assert article.canonical_url == "https://example.com/story"
    assert article.rank_key[0] == 1
    assert article.id == hashlib.sha256(f"{SOURCE.id}\0item-1".encode()).hexdigest()


def test_normalize_entry_builds_display_title_summary_and_utc_fetched_time() -> None:
    raw = replace(BASE_RAW, title=" ＡI\t Big\n News! ", summary_html="<p>abcdef</p>")
    fetched_at = datetime(2026, 7, 11, 9, 0, tzinfo=timezone(timedelta(hours=8)))

    article = normalize_entry(
        raw,
        SOURCE,
        fetched_at=fetched_at,
        window=build_window(date(2026, 7, 10)),
        summary_limit=5,
    )

    assert article is not None
    assert article.title == "AI Big News!"
    assert article.title_key == "ai big news"
    assert article.summary == "abcd…"
    assert article.is_fallback is False
    assert article.fetched_at == datetime(2026, 7, 11, 1, 0, tzinfo=UTC)
    assert article.fetched_at.tzinfo is UTC


def test_normalize_entry_uses_canonical_url_for_id_without_external_id() -> None:
    raw = replace(BASE_RAW, external_id=None, url="https://EXAMPLE.com/story/?utm_source=rss#top")

    article = normalize_entry(
        raw,
        SOURCE,
        fetched_at=datetime(2026, 7, 11, 1, 0, tzinfo=UTC),
        window=build_window(date(2026, 7, 10)),
        summary_limit=180,
    )

    assert article is not None
    assert article.canonical_url == "https://example.com/story"
    expected = hashlib.sha256(f"{SOURCE.id}\0{article.canonical_url}".encode()).hexdigest()
    assert article.id == expected


def test_normalize_entry_strips_the_display_url() -> None:
    raw = replace(BASE_RAW, url="  https://example.com/story  ")

    article = normalize_entry(
        raw,
        SOURCE,
        fetched_at=datetime(2026, 7, 11, 1, 0, tzinfo=UTC),
        window=build_window(date(2026, 7, 10)),
        summary_limit=180,
    )

    assert article is not None
    assert article.url == "https://example.com/story"
    assert article.canonical_url == "https://example.com/story"


@pytest.mark.parametrize(
    "raw",
    [
        replace(BASE_RAW, title=None),
        replace(BASE_RAW, title=" \t\n　"),
        replace(BASE_RAW, url=None),
        replace(BASE_RAW, url="ftp://example.com/story"),
        replace(BASE_RAW, url="https:///story"),
        replace(BASE_RAW, url="https://example.com/?x=\ud800"),
        replace(BASE_RAW, published_value=None),
        replace(BASE_RAW, published_value="not a date"),
    ],
)
def test_normalize_entry_rejects_missing_or_invalid_required_values(raw: RawEntry) -> None:
    article = normalize_entry(
        raw,
        SOURCE,
        fetched_at=datetime(2026, 7, 11, 1, 0, tzinfo=UTC),
        window=build_window(date(2026, 7, 10)),
        summary_limit=180,
    )
    assert article is None


def test_normalize_entry_rejects_naive_published_time_without_source_timezone() -> None:
    raw = replace(BASE_RAW, published_value=datetime(2026, 7, 10, 12, 0))

    article = normalize_entry(
        raw,
        replace(SOURCE, timezone=None),
        fetched_at=datetime(2026, 7, 11, 1, 0, tzinfo=UTC),
        window=build_window(date(2026, 7, 10)),
        summary_limit=180,
    )

    assert article is None


def test_normalize_entry_rejects_publication_time_outside_window() -> None:
    raw = replace(BASE_RAW, published_value="2026-07-07T15:59:59Z")

    article = normalize_entry(
        raw,
        SOURCE,
        fetched_at=datetime(2026, 7, 11, 1, 0, tzinfo=UTC),
        window=build_window(date(2026, 7, 10)),
        summary_limit=180,
    )

    assert article is None


def test_normalize_entry_rejects_naive_fetched_at() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        normalize_entry(
            BASE_RAW,
            SOURCE,
            fetched_at=datetime(2026, 7, 11, 1, 0),
            window=build_window(date(2026, 7, 10)),
            summary_limit=180,
        )


def test_normalize_entry_wraps_raising_fetched_timezone_as_clear_value_error() -> None:
    fetched_at = datetime(2026, 7, 11, 1, 0, tzinfo=RaisingTimezone())

    with pytest.raises(ValueError, match="fetched_at must be timezone-aware") as error:
        normalize_entry(
            BASE_RAW,
            SOURCE,
            fetched_at=fetched_at,
            window=build_window(date(2026, 7, 10)),
            summary_limit=180,
        )

    assert isinstance(error.value.__cause__, RuntimeError)
