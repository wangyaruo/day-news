from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import UTC, datetime
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_datetime

from day_news.models import Article, PublicationWindow, RawEntry, SourceConfig, WindowBand
from day_news.time_window import classify_time

TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid", "spm"}
WHITESPACE_RE = re.compile(r"\s+")
INVALID_PERCENT_ESCAPE_RE = re.compile(r"%(?![0-9A-Fa-f]{2})")
PATH_SAFE_CHARACTERS = "/-._~!$&'()*+,;=:@%"
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def is_tracking_key(key: str) -> bool:
    normalized_key = key.casefold()
    return normalized_key.startswith("utm_") or normalized_key in TRACKING_KEYS


def canonicalize_url(url: str) -> str | None:
    try:
        stripped_url = url.strip()
        stripped_url.encode("utf-8")
        if any(character.isspace() or unicodedata.category(character) == "Cc" for character in stripped_url):
            return None
        parts = urlsplit(stripped_url)
        scheme = parts.scheme.casefold()
        hostname = parts.hostname
        port = parts.port
    except (AttributeError, TypeError, UnicodeError, ValueError):
        return None

    if scheme not in {"http", "https"} or not hostname:
        return None
    if any(character.isspace() or unicodedata.category(character) == "Cc" for character in hostname):
        return None

    authority = parts.netloc.rsplit("@", maxsplit=1)[-1]
    if authority.endswith(":"):
        return None

    normalized_host = hostname.lower()
    if authority.startswith("[") or ":" in normalized_host:
        normalized_host = f"[{normalized_host}]"

    netloc = normalized_host
    is_default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    if port is not None and not is_default_port:
        netloc += f":{port}"

    path = parts.path or "/"
    if INVALID_PERCENT_ESCAPE_RE.search(path):
        return None
    if path != "/":
        path = path.rstrip("/") or "/"
    path = quote(path, safe=PATH_SAFE_CHARACTERS)

    query_items = [
        (key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if not is_tracking_key(key)
    ]
    query_items.sort()
    query = urlencode(query_items, doseq=True)

    return urlunsplit((scheme, netloc, path, query, ""))


def title_key(title: str) -> str:
    normalized = unicodedata.normalize("NFKC", title).casefold()
    without_punctuation = "".join(
        " " if unicodedata.category(character)[0] in {"P", "S"} else character for character in normalized
    )
    return _fold_whitespace(without_punctuation)


def clean_summary(value: str | None, *, limit: int) -> str | None:
    if limit <= 0:
        raise ValueError("limit must be positive")
    if value is None:
        return None

    soup = BeautifulSoup(value, "html.parser")
    for unsafe_element in soup.find_all(["script", "style"]):
        unsafe_element.decompose()

    text = _fold_whitespace(soup.get_text(" "))
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _to_utc(
    value: datetime,
    *,
    field_name: str,
    naive_timezone: str | None = None,
) -> datetime:
    error_message = f"{field_name} must be timezone-aware"

    try:
        offset = value.utcoffset() if value.tzinfo is not None else None
    except Exception as error:
        raise ValueError(error_message) from error

    if offset is None:
        if naive_timezone is None:
            raise ValueError(error_message)
        try:
            timezone = ZoneInfo(naive_timezone)
        except (TypeError, ValueError, ZoneInfoNotFoundError) as error:
            raise ValueError(error_message) from error
        value = value.replace(tzinfo=timezone)

    try:
        return value.astimezone(UTC)
    except Exception as error:
        raise ValueError(error_message) from error


def parse_published(value: str | int | datetime | None, source_timezone: str | None) -> datetime | None:
    if value is None or isinstance(value, bool):
        return None

    try:
        if isinstance(value, datetime):
            published_at = value
        elif isinstance(value, int):
            published_at = datetime.fromtimestamp(value, tz=UTC)
        elif isinstance(value, str):
            published_at = parse_datetime(value)
        else:
            return None
    except (OSError, OverflowError, TypeError, ValueError):
        return None

    try:
        return _to_utc(published_at, field_name="published_at", naive_timezone=source_timezone)
    except ValueError:
        return None


def build_rank_key(
    *,
    is_fallback: bool,
    priority: int,
    published_at: datetime,
    source_position: int,
    canonical_url: str,
) -> tuple[int, int, int, int, str]:
    published_delta = _to_utc(published_at, field_name="published_at") - EPOCH
    epoch_microseconds = (
        published_delta.days * 86_400 + published_delta.seconds
    ) * 1_000_000 + published_delta.microseconds
    return (int(is_fallback), priority, -epoch_microseconds, source_position, canonical_url)


def normalize_entry(
    raw: RawEntry,
    source: SourceConfig,
    *,
    fetched_at: datetime,
    window: PublicationWindow,
    summary_limit: int,
) -> Article | None:
    fetched_at_utc = _to_utc(fetched_at, field_name="fetched_at")
    if summary_limit <= 0:
        raise ValueError("summary_limit must be positive")

    if raw.title is None or raw.url is None:
        return None

    display_title = _fold_whitespace(unicodedata.normalize("NFKC", raw.title))
    normalized_title_key = title_key(display_title)
    if not display_title or not normalized_title_key:
        return None

    display_url = raw.url.strip()
    canonical_url = canonicalize_url(display_url)
    if canonical_url is None:
        return None

    published_at = parse_published(raw.published_value, source.timezone)
    if published_at is None:
        return None

    window_band = classify_time(published_at, window)
    if window_band is WindowBand.OUTSIDE:
        return None

    is_fallback = window_band is WindowBand.FALLBACK
    identity_value = raw.external_id or canonical_url
    article_id = hashlib.sha256(f"{source.id}\0{identity_value}".encode()).hexdigest()

    return Article(
        id=article_id,
        title=display_title,
        title_key=normalized_title_key,
        url=display_url,
        canonical_url=canonical_url,
        source_id=source.id,
        publisher_id=source.publisher_id,
        source_name=source.name,
        category=source.category,
        published_at=published_at,
        fetched_at=fetched_at_utc,
        summary=clean_summary(raw.summary_html, limit=summary_limit),
        language=source.language,
        is_fallback=is_fallback,
        rank_key=build_rank_key(
            is_fallback=is_fallback,
            priority=source.priority,
            published_at=published_at,
            source_position=raw.source_position,
            canonical_url=canonical_url,
        ),
    )


def _fold_whitespace(value: str) -> str:
    return WHITESPACE_RE.sub(" ", value).strip()
