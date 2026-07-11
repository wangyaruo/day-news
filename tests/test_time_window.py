from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from day_news.models import WindowBand
from day_news.time_window import SHANGHAI, build_window, classify_time, resolve_target_date


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 7, 10, 16, 30, tzinfo=UTC), date(2026, 7, 10)),
        (datetime(2026, 1, 1, 1, 0, tzinfo=UTC), date(2025, 12, 31)),
        (datetime(2024, 3, 1, 1, 0, tzinfo=UTC), date(2024, 2, 29)),
    ],
)
def test_resolve_target_date_uses_previous_shanghai_calendar_day(now: datetime, expected: date) -> None:
    assert resolve_target_date(now, explicit=None) == expected


def test_resolve_target_date_prefers_explicit_date() -> None:
    explicit = date(2026, 6, 1)

    assert resolve_target_date(datetime(2026, 6, 2, 12, 0), explicit=explicit) == explicit


def test_resolve_target_date_rejects_naive_now_without_explicit_date() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        resolve_target_date(datetime(2026, 7, 11, 0, 30), explicit=None)


def test_build_window_uses_shanghai_midnight_boundaries() -> None:
    window = build_window(date(2026, 7, 10))

    assert window.target_date == date(2026, 7, 10)
    assert window.fallback_start == datetime(2026, 7, 8, 0, 0, tzinfo=SHANGHAI)
    assert window.target_start == datetime(2026, 7, 10, 0, 0, tzinfo=SHANGHAI)
    assert window.target_end == datetime(2026, 7, 11, 0, 0, tzinfo=SHANGHAI)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (datetime(2026, 7, 7, 15, 59, tzinfo=UTC), WindowBand.OUTSIDE),
        (datetime(2026, 7, 7, 16, 0, tzinfo=UTC), WindowBand.FALLBACK),
        (datetime(2026, 7, 9, 15, 59, tzinfo=UTC), WindowBand.FALLBACK),
        (datetime(2026, 7, 9, 16, 0, tzinfo=UTC), WindowBand.TARGET),
        (datetime(2026, 7, 10, 15, 59, tzinfo=UTC), WindowBand.TARGET),
        (datetime(2026, 7, 10, 16, 0, tzinfo=UTC), WindowBand.OUTSIDE),
    ],
)
def test_classify_time_obeys_half_open_shanghai_window_boundaries(
    value: datetime,
    expected: WindowBand,
) -> None:
    assert classify_time(value, build_window(date(2026, 7, 10))) is expected


def test_classify_time_rejects_naive_published_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        classify_time(datetime(2026, 7, 10, 12, 0), build_window(date(2026, 7, 10)))
