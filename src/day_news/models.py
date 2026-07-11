from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path


class Category(StrEnum):
    WORLD = "world"
    BUSINESS = "business"
    TECHNOLOGY = "technology"
    SCIENCE = "science"
    CULTURE = "culture"
    SPORTS = "sports"


class SourceKind(StrEnum):
    RSS = "rss"
    HACKER_NEWS = "hacker_news"


CATEGORY_LABELS: dict[Category, str] = {
    Category.WORLD: "国内与国际",
    Category.BUSINESS: "商业与经济",
    Category.TECHNOLOGY: "科技与互联网",
    Category.SCIENCE: "科学与健康",
    Category.CULTURE: "文化与生活",
    Category.SPORTS: "体育",
}


class WindowBand(StrEnum):
    TARGET = "target"
    FALLBACK = "fallback"
    OUTSIDE = "outside"


class GenerationStatus(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    SKIPPED_EXISTS = "skipped_exists"
    FAILED_THRESHOLD = "failed_threshold"


type RankKey = tuple[int, int, int, int, str]


@dataclass(frozen=True, slots=True)
class SourceConfig:
    id: str
    publisher_id: str
    name: str
    kind: SourceKind
    url: str
    category: Category
    language: str
    priority: int
    max_per_issue: int
    fetch_limit: int
    enabled: bool = True
    timezone: str | None = None


@dataclass(frozen=True, slots=True)
class SelectionPolicy:
    target_count: int
    min_count: int
    max_count: int
    min_categories: int
    min_publishers: int
    default_publisher_cap: int
    category_soft_target: int
    history_days: int
    summary_limit: int
    similarity_threshold: float


@dataclass(frozen=True, slots=True)
class AppConfig:
    policy: SelectionPolicy
    sources: tuple[SourceConfig, ...]


@dataclass(frozen=True, slots=True)
class RawEntry:
    external_id: str | None
    title: str | None
    url: str | None
    published_value: str | int | datetime | None
    summary_html: str | None
    source_position: int


@dataclass(frozen=True, slots=True)
class SourceFetchResult:
    source_id: str
    entries: tuple[RawEntry, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FetchBatch:
    entries: tuple[tuple[SourceConfig, RawEntry], ...]
    successful_sources: tuple[str, ...]
    failed_sources: dict[str, str]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Article:
    id: str
    title: str
    title_key: str
    url: str
    canonical_url: str
    source_id: str
    publisher_id: str
    source_name: str
    category: Category
    published_at: datetime
    fetched_at: datetime
    summary: str | None
    language: str
    is_fallback: bool
    rank_key: RankKey


@dataclass(frozen=True, slots=True)
class PublicationWindow:
    target_date: date
    fallback_start: datetime
    target_start: datetime
    target_end: datetime


@dataclass(frozen=True, slots=True)
class HistoryIndex:
    ids: frozenset[str] = field(default_factory=frozenset)
    canonical_urls: frozenset[str] = field(default_factory=frozenset)
    title_keys: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class DedupeResult:
    articles: tuple[Article, ...]
    removed_by_reason: dict[str, int]


@dataclass(slots=True)
class RunReport:
    target_date: str
    status: str = "running"
    successful_sources: list[str] = field(default_factory=list)
    failed_sources: dict[str, str] = field(default_factory=dict)
    fetched_count: int = 0
    window_count: int = 0
    duplicate_count: int = 0
    selected_count: int = 0
    fallback_count: int = 0
    failure_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "target_date": self.target_date,
            "status": self.status,
            "successful_sources": sorted(self.successful_sources),
            "failed_sources": dict(sorted(self.failed_sources.items())),
            "fetched_count": self.fetched_count,
            "window_count": self.window_count,
            "duplicate_count": self.duplicate_count,
            "selected_count": self.selected_count,
            "fallback_count": self.fallback_count,
            "failure_reason": self.failure_reason,
        }


@dataclass(frozen=True, slots=True)
class GenerationResult:
    status: GenerationStatus
    target_date: date
    content_path: Path | None
    report_path: Path
