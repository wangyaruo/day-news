from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from day_news.models import PublicationWindow, WindowBand

SHANGHAI = ZoneInfo("Asia/Shanghai")


def resolve_target_date(now: datetime, explicit: date | None) -> date:
    if explicit is not None:
        return explicit
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(SHANGHAI).date() - timedelta(days=1)


def build_window(target_date: date) -> PublicationWindow:
    target_start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=SHANGHAI)
    return PublicationWindow(
        target_date=target_date,
        fallback_start=target_start - timedelta(days=2),
        target_start=target_start,
        target_end=target_start + timedelta(days=1),
    )


def classify_time(value: datetime, window: PublicationWindow) -> WindowBand:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("value must be timezone-aware")

    shanghai_value = value.astimezone(SHANGHAI)
    if window.target_start <= shanghai_value < window.target_end:
        return WindowBand.TARGET
    if window.fallback_start <= shanghai_value < window.target_start:
        return WindowBand.FALLBACK
    return WindowBand.OUTSIDE
