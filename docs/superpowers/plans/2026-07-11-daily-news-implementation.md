# Daily News Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended)
> or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax
> for tracking.

**Goal:** Build a free, keyless daily news publication that creates one Markdown edition per day, updates its
archive, and deploys a static GitHub Pages site at 09:00 Asia/Shanghai.

**Architecture:** A Python 3.12 package asynchronously fetches configured RSS/Atom feeds and Hacker News,
normalizes and deduplicates candidates, applies deterministic diversity rules, and atomically writes an edition
plus a run report. The same package renders Markdown editions into a static site and RSS feed; GitHub Actions
tests, generates, commits, and deploys the result without a personal token.

**Tech Stack:** Python 3.12, `httpx`, `feedparser`, `python-dateutil`, `beautifulsoup4`, `PyYAML`, `Jinja2`,
`markdown-it-py`, `pytest`, `pytest-asyncio`, `ruff`, GitHub Actions, GitHub Pages.

---

## Scope and fixed contracts

This is one cohesive pipeline, so it remains one implementation plan. Keep each task independently testable
and commit after every green task.

The following contracts are fixed for all tasks:

- Dates and publication windows use `Asia/Shanghai`.
- A target edition prefers the target date, then may use the two preceding dates.
- Source diversity is counted by `publisher_id`, not by individual feed.
- Lower numeric source priority is better.
- The candidate ordering key is target date first, lower priority, newer publication time, lower source
  position, then canonical URL.
- A valid edition contains 12–30 items, at least 4 categories, and at least 5 publishers; the target is 24 items.
- Each publisher contributes at most 3 items unless its configured cap is lower.
- Historical deduplication covers the preceding 30 calendar days and uses a machine-readable `dedupe_index`
  in front matter.
- CLI exit codes are `0` for success/no-op, `2` for invalid input/configuration, `3` for an unmet publication
  threshold, and `1` for an unexpected failure.
- Site routes are rooted at `https://wangyaruo.github.io/day-news/` and generated below `/day-news/`.

## File map

| Path | Responsibility |
| --- | --- |
| `pyproject.toml` | Exact runtime/dev dependencies, package metadata, CLI entry point, pytest and Ruff configuration |
| `config/sources.toml` | Selection policy and all keyless news sources |
| `config/site.toml` | Site URL, repository URL, Issues URL, title, and description |
| `src/day_news/models.py` | Enums and immutable domain/result models |
| `src/day_news/config.py` | TOML parsing and cross-field validation |
| `src/day_news/time_window.py` | Shanghai target-date and 72-hour window calculations |
| `src/day_news/normalize.py` | Date, URL, title, summary, stable ID, and rank normalization |
| `src/day_news/fetchers/http.py` | Async timeout, retry, and retryable-status behavior |
| `src/day_news/fetchers/rss.py` | RSS/Atom parsing and fetching |
| `src/day_news/fetchers/hacker_news.py` | HN list/detail fetching with bounded concurrency |
| `src/day_news/fetchers/__init__.py` | Fetcher registry and single-source failure isolation |
| `src/day_news/history.py` | Read `dedupe_index` from the previous 30 days |
| `src/day_news/dedupe.py` | Stable ID, canonical URL, exact title, and 0.92 similarity deduplication |
| `src/day_news/select.py` | Deterministic quotas, diversity repair, fallback, and thresholds |
| `src/day_news/issue.py` | Edition/front-matter parsing and deterministic Markdown rendering |
| `src/day_news/readme.py` | Controlled recent-editions block replacement |
| `src/day_news/generate.py` | End-to-end generation, report writing, no-op, and atomic writes |
| `src/day_news/feed.py` | Deterministic RSS 2.0 for the latest 30 editions |
| `src/day_news/site.py` | Static route generation, archives, source/about pages, and asset copying |
| `src/day_news/validate.py` | Offline content, link, RSS, and site checks |
| `src/day_news/cli.py` | `generate`, `build`, `validate`, and `target-date` commands |
| `templates/` | Markdown and HTML Jinja templates |
| `assets/styles.css` | Local responsive styling; no third-party resources |
| `tests/fixtures/` | Fixed RSS, Atom, HN, content, and expected-output fixtures |
| `.github/workflows/ci.yml` | Pull-request and push checks |
| `.github/workflows/publish.yml` | Scheduled/manual generation, bot commit, build, and Pages deployment |

### Task 1: Bootstrap the Python project

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `README.md`
- Create: `src/day_news/__init__.py`
- Create: `tests/test_package.py`

- [ ] **Step 1: Create the dependency and tool configuration**

Create `pyproject.toml` with this complete content:

```toml
[build-system]
requires = ["setuptools==80.9.0"]
build-backend = "setuptools.build_meta"

[project]
name = "day-news"
version = "0.1.0"
description = "A keyless, automatically published daily news digest"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
  "beautifulsoup4==4.13.4",
  "feedparser==6.0.11",
  "httpx==0.28.1",
  "Jinja2==3.1.6",
  "markdown-it-py==3.0.0",
  "python-dateutil==2.9.0.post0",
  "PyYAML==6.0.2",
]

[project.optional-dependencies]
dev = [
  "pytest==8.4.1",
  "pytest-asyncio==0.26.0",
  "pytest-cov==6.2.1",
  "ruff==0.12.3",
]

[project.scripts]
day-news = "day_news.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
addopts = "-ra"
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 120
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]
```

Create `.gitignore`:

```gitignore
.venv/
__pycache__/
.pytest_cache/
.ruff_cache/
*.py[cod]
*.egg-info/
build/
dist/
.coverage
htmlcov/
```

Create the initial `README.md` so editable installation can resolve the declared readme:

```markdown
# 每日新闻

每天北京时间 9:00 自动更新的免费新闻日刊。

<!-- DAY_NEWS_RECENT_START -->
<!-- DAY_NEWS_RECENT_END -->
```

Create an empty `src/day_news/__init__.py` so setuptools discovers the package before the first editable install.

- [ ] **Step 2: Install the exact development dependencies**

Run:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev]"
```

Expected: installation exits `0` and `day-news` is installed in editable mode.

- [ ] **Step 3: Write the failing package test**

Create `tests/test_package.py`:

```python
from day_news import __version__


def test_package_exposes_version() -> None:
    assert __version__ == "0.1.0"
```

- [ ] **Step 4: Run the test and verify the expected failure**

Run:

```bash
.venv/bin/pytest tests/test_package.py -v
```

Expected: FAIL with an import error for `__version__`.

- [ ] **Step 5: Add the minimal package implementation**

Create `src/day_news/__init__.py`:

```python
__version__ = "0.1.0"
```

- [ ] **Step 6: Run package and style checks**

Run:

```bash
.venv/bin/pytest tests/test_package.py -v
.venv/bin/ruff check .
```

Expected: one test passes and Ruff exits `0`.

- [ ] **Step 7: Commit the bootstrap**

```bash
git add pyproject.toml .gitignore README.md src/day_news/__init__.py tests/test_package.py
git commit -m "chore: 初始化 Python 项目"
```

### Task 2: Define domain models and validated source configuration

**Files:**
- Create: `src/day_news/models.py`
- Create: `src/day_news/config.py`
- Create: `config/sources.toml`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing configuration tests**

Create `tests/test_config.py` with these tests:

```python
from pathlib import Path

import pytest

from day_news.config import ConfigError, load_config
from day_news.models import Category, SourceKind


def test_loads_repository_configuration() -> None:
    config = load_config(Path("config/sources.toml"))
    assert config.policy.target_count == 24
    assert config.policy.min_count == 12
    assert config.policy.max_count == 30
    assert {source.kind for source in config.sources} == {SourceKind.RSS, SourceKind.HACKER_NEWS}
    assert {source.category for source in config.sources} == set(Category)


def test_each_category_has_two_publishers() -> None:
    config = load_config(Path("config/sources.toml"))
    for category in Category:
        publishers = {
            source.publisher_id
            for source in config.sources
            if source.enabled and source.category is category
        }
        assert len(publishers) >= 2


def test_configuration_can_reach_minimum_publishers() -> None:
    config = load_config(Path("config/sources.toml"))
    publishers = {source.publisher_id for source in config.sources if source.enabled}
    assert len(publishers) >= config.policy.min_publishers
    capacity = sum(
        min(
            source.max_per_issue
            for source in config.sources
            if source.enabled and source.publisher_id == publisher
        )
        for publisher in publishers
    )
    assert capacity >= config.policy.target_count


def test_rejects_duplicate_source_ids(tmp_path: Path) -> None:
    path = tmp_path / "sources.toml"
    path.write_text(
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
publisher_id = "one"
name = "One"
kind = "rss"
url = "https://example.com/one.xml"
category = "world"
language = "en"
priority = 10
max_per_issue = 3
fetch_limit = 60
enabled = true

[[sources]]
id = "same"
publisher_id = "two"
name = "Two"
kind = "rss"
url = "https://example.com/two.xml"
category = "world"
language = "en"
priority = 20
max_per_issue = 3
fetch_limit = 60
enabled = true
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="duplicate source id"):
        load_config(path, require_category_coverage=False)
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
.venv/bin/pytest tests/test_config.py -v
```

Expected: FAIL because `day_news.config` and `day_news.models` do not exist.

- [ ] **Step 3: Implement the exact models**

Create `src/day_news/models.py` with these public contracts:

```python
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any


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


CATEGORY_LABELS = {
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
    ids: frozenset[str] = frozenset()
    canonical_urls: frozenset[str] = frozenset()
    title_keys: frozenset[str] = frozenset()


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

    def to_dict(self) -> dict[str, Any]:
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
```

- [ ] **Step 4: Implement TOML loading and validation**

Create `src/day_news/config.py`. Its public entry point must be:

```python
from pathlib import Path
import tomllib

from day_news.models import AppConfig, Category, SelectionPolicy, SourceConfig, SourceKind


class ConfigError(ValueError):
    pass


def load_config(path: Path, *, require_category_coverage: bool = True) -> AppConfig:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    try:
        policy = SelectionPolicy(**data["policy"])
        sources = tuple(
            SourceConfig(
                id=item["id"],
                publisher_id=item["publisher_id"],
                name=item["name"],
                kind=SourceKind(item["kind"]),
                url=item["url"],
                category=Category(item["category"]),
                language=item["language"],
                priority=int(item["priority"]),
                max_per_issue=int(item["max_per_issue"]),
                fetch_limit=int(item["fetch_limit"]),
                enabled=bool(item.get("enabled", True)),
                timezone=item.get("timezone"),
            )
            for item in data["sources"]
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError(f"invalid configuration: {exc}") from exc

    ids = [source.id for source in sources]
    if len(ids) != len(set(ids)):
        raise ConfigError("duplicate source id")
    if not 12 <= policy.min_count <= policy.target_count <= policy.max_count <= 30:
        raise ConfigError("invalid count policy")
    if not 0.0 < policy.similarity_threshold <= 1.0:
        raise ConfigError("invalid similarity threshold")
    for source in sources:
        if not 1 <= source.max_per_issue <= policy.default_publisher_cap:
            raise ConfigError(f"invalid source cap: {source.id}")
        if source.fetch_limit < 1:
            raise ConfigError(f"invalid fetch limit: {source.id}")
    if require_category_coverage:
        for category in Category:
            publishers = {
                source.publisher_id
                for source in sources
                if source.enabled and source.category is category
            }
            if len(publishers) < 2:
                raise ConfigError(f"category needs two publishers: {category.value}")
        enabled_publishers = {source.publisher_id for source in sources if source.enabled}
        if len(enabled_publishers) < policy.min_publishers:
            raise ConfigError("configuration cannot reach minimum publishers")
        publisher_capacity = sum(
            min(
                source.max_per_issue
                for source in sources
                if source.enabled and source.publisher_id == publisher
            )
            for publisher in enabled_publishers
        )
        if publisher_capacity < policy.target_count:
            raise ConfigError("configuration cannot reach target count")
    return AppConfig(policy=policy, sources=sources)
```

- [ ] **Step 5: Add the initial keyless source configuration**

Create `config/sources.toml` with the policy above and these enabled sources:

```toml
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
id = "bbc-world"
publisher_id = "bbc"
name = "BBC World"
kind = "rss"
url = "https://feeds.bbci.co.uk/news/world/rss.xml"
category = "world"
language = "en"
priority = 10
max_per_issue = 3
fetch_limit = 60
enabled = true
timezone = "UTC"

[[sources]]
id = "guardian-world"
publisher_id = "guardian"
name = "The Guardian World"
kind = "rss"
url = "https://www.theguardian.com/world/rss"
category = "world"
language = "en"
priority = 20
max_per_issue = 3
fetch_limit = 60
enabled = true
timezone = "Europe/London"

[[sources]]
id = "bbc-business"
publisher_id = "bbc"
name = "BBC Business"
kind = "rss"
url = "https://feeds.bbci.co.uk/news/business/rss.xml"
category = "business"
language = "en"
priority = 10
max_per_issue = 3
fetch_limit = 60
enabled = true
timezone = "UTC"

[[sources]]
id = "guardian-business"
publisher_id = "guardian"
name = "The Guardian Business"
kind = "rss"
url = "https://www.theguardian.com/business/rss"
category = "business"
language = "en"
priority = 20
max_per_issue = 3
fetch_limit = 60
enabled = true
timezone = "Europe/London"

[[sources]]
id = "bbc-technology"
publisher_id = "bbc"
name = "BBC Technology"
kind = "rss"
url = "https://feeds.bbci.co.uk/news/technology/rss.xml"
category = "technology"
language = "en"
priority = 10
max_per_issue = 3
fetch_limit = 60
enabled = true
timezone = "UTC"

[[sources]]
id = "guardian-technology"
publisher_id = "guardian"
name = "The Guardian Technology"
kind = "rss"
url = "https://www.theguardian.com/technology/rss"
category = "technology"
language = "en"
priority = 20
max_per_issue = 3
fetch_limit = 60
enabled = true
timezone = "Europe/London"

[[sources]]
id = "hacker-news"
publisher_id = "hacker-news"
name = "Hacker News"
kind = "hacker_news"
url = "https://hacker-news.firebaseio.com/v0"
category = "technology"
language = "en"
priority = 15
max_per_issue = 3
fetch_limit = 120
enabled = true
timezone = "UTC"

[[sources]]
id = "bbc-science"
publisher_id = "bbc"
name = "BBC Science & Environment"
kind = "rss"
url = "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml"
category = "science"
language = "en"
priority = 10
max_per_issue = 3
fetch_limit = 60
enabled = true
timezone = "UTC"

[[sources]]
id = "guardian-science"
publisher_id = "guardian"
name = "The Guardian Science"
kind = "rss"
url = "https://www.theguardian.com/science/rss"
category = "science"
language = "en"
priority = 20
max_per_issue = 3
fetch_limit = 60
enabled = true
timezone = "Europe/London"

[[sources]]
id = "bbc-culture"
publisher_id = "bbc"
name = "BBC Culture"
kind = "rss"
url = "https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml"
category = "culture"
language = "en"
priority = 10
max_per_issue = 3
fetch_limit = 60
enabled = true
timezone = "UTC"

[[sources]]
id = "guardian-culture"
publisher_id = "guardian"
name = "The Guardian Culture"
kind = "rss"
url = "https://www.theguardian.com/culture/rss"
category = "culture"
language = "en"
priority = 20
max_per_issue = 3
fetch_limit = 60
enabled = true
timezone = "Europe/London"

[[sources]]
id = "bbc-sport"
publisher_id = "bbc"
name = "BBC Sport"
kind = "rss"
url = "https://feeds.bbci.co.uk/sport/rss.xml"
category = "sports"
language = "en"
priority = 10
max_per_issue = 3
fetch_limit = 60
enabled = true
timezone = "UTC"

[[sources]]
id = "guardian-sport"
publisher_id = "guardian"
name = "The Guardian Sport"
kind = "rss"
url = "https://www.theguardian.com/sport/rss"
category = "sports"
language = "en"
priority = 20
max_per_issue = 3
fetch_limit = 60
enabled = true
timezone = "Europe/London"

[[sources]]
id = "npr-world"
publisher_id = "npr"
name = "NPR World"
kind = "rss"
url = "https://feeds.npr.org/1004/rss.xml"
category = "world"
language = "en"
priority = 15
max_per_issue = 3
fetch_limit = 60
enabled = true
timezone = "America/New_York"

[[sources]]
id = "npr-business"
publisher_id = "npr"
name = "NPR Business"
kind = "rss"
url = "https://feeds.npr.org/1006/rss.xml"
category = "business"
language = "en"
priority = 15
max_per_issue = 3
fetch_limit = 60
enabled = true
timezone = "America/New_York"

[[sources]]
id = "npr-technology"
publisher_id = "npr"
name = "NPR Technology"
kind = "rss"
url = "https://feeds.npr.org/1019/rss.xml"
category = "technology"
language = "en"
priority = 15
max_per_issue = 3
fetch_limit = 60
enabled = true
timezone = "America/New_York"

[[sources]]
id = "npr-science"
publisher_id = "npr"
name = "NPR Science"
kind = "rss"
url = "https://feeds.npr.org/1007/rss.xml"
category = "science"
language = "en"
priority = 15
max_per_issue = 3
fetch_limit = 60
enabled = true
timezone = "America/New_York"

[[sources]]
id = "npr-culture"
publisher_id = "npr"
name = "NPR Arts & Life"
kind = "rss"
url = "https://feeds.npr.org/1008/rss.xml"
category = "culture"
language = "en"
priority = 15
max_per_issue = 3
fetch_limit = 60
enabled = true
timezone = "America/New_York"

[[sources]]
id = "espn-sport"
publisher_id = "espn"
name = "ESPN"
kind = "rss"
url = "https://www.espn.com/espn/rss/news"
category = "sports"
language = "en"
priority = 15
max_per_issue = 3
fetch_limit = 60
enabled = true
timezone = "America/New_York"

[[sources]]
id = "dw-world"
publisher_id = "dw"
name = "Deutsche Welle"
kind = "rss"
url = "https://rss.dw.com/rdf/rss-en-all"
category = "world"
language = "en"
priority = 18
max_per_issue = 3
fetch_limit = 60
enabled = true
timezone = "Europe/Berlin"

[[sources]]
id = "cnbc-business"
publisher_id = "cnbc"
name = "CNBC Business"
kind = "rss"
url = "https://www.cnbc.com/id/10001147/device/rss/rss.html"
category = "business"
language = "en"
priority = 18
max_per_issue = 3
fetch_limit = 60
enabled = true
timezone = "America/New_York"

[[sources]]
id = "ars-technica"
publisher_id = "ars-technica"
name = "Ars Technica"
kind = "rss"
url = "https://feeds.arstechnica.com/arstechnica/index"
category = "technology"
language = "en"
priority = 18
max_per_issue = 3
fetch_limit = 60
enabled = true
timezone = "America/New_York"

[[sources]]
id = "solidot"
publisher_id = "solidot"
name = "Solidot"
kind = "rss"
url = "https://www.solidot.org/index.rss"
category = "technology"
language = "zh-CN"
priority = 12
max_per_issue = 3
fetch_limit = 60
enabled = true
timezone = "Asia/Shanghai"

[[sources]]
id = "nasa-science"
publisher_id = "nasa"
name = "NASA"
kind = "rss"
url = "https://www.nasa.gov/news-release/feed/"
category = "science"
language = "en"
priority = 18
max_per_issue = 3
fetch_limit = 60
enabled = true
timezone = "America/New_York"

[[sources]]
id = "smithsonian-culture"
publisher_id = "smithsonian"
name = "Smithsonian Magazine"
kind = "rss"
url = "https://www.smithsonianmag.com/rss/latest_articles/"
category = "culture"
language = "en"
priority = 18
max_per_issue = 3
fetch_limit = 60
enabled = true
timezone = "America/New_York"
```

- [ ] **Step 6: Run the focused and full tests**

Run:

```bash
.venv/bin/pytest tests/test_config.py -v
.venv/bin/pytest -q
.venv/bin/ruff check .
```

Expected: all tests pass and Ruff exits `0`.

- [ ] **Step 7: Commit models and configuration**

```bash
git add src/day_news/models.py src/day_news/config.py config/sources.toml tests/test_config.py
git commit -m "feat: 添加新闻源配置模型"
```

### Task 3: Implement Shanghai publication windows

**Files:**
- Create: `src/day_news/time_window.py`
- Test: `tests/test_time_window.py`

- [ ] **Step 1: Write failing boundary tests**

Create tests for year rollover, leap day, explicit dates, and all half-open boundaries:

```python
from datetime import date, datetime, timezone

import pytest

from day_news.models import WindowBand
from day_news.time_window import build_window, classify_time, resolve_target_date


def test_default_target_date_uses_shanghai() -> None:
    now = datetime(2026, 7, 10, 16, 30, tzinfo=timezone.utc)
    assert resolve_target_date(now, explicit=None) == date(2026, 7, 10)


def test_year_rollover() -> None:
    now = datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)
    assert resolve_target_date(now, explicit=None) == date(2025, 12, 31)


def test_leap_day_target() -> None:
    now = datetime(2024, 3, 1, 1, 0, tzinfo=timezone.utc)
    assert resolve_target_date(now, explicit=None) == date(2024, 2, 29)


def test_explicit_target_date_wins() -> None:
    now = datetime(2026, 7, 11, 1, 0, tzinfo=timezone.utc)
    assert resolve_target_date(now, explicit=date(2026, 6, 1)) == date(2026, 6, 1)


def test_classifies_three_day_window() -> None:
    window = build_window(date(2026, 7, 10))
    assert classify_time(datetime(2026, 7, 7, 15, 59, tzinfo=timezone.utc), window) is WindowBand.OUTSIDE
    assert classify_time(datetime(2026, 7, 7, 16, 0, tzinfo=timezone.utc), window) is WindowBand.FALLBACK
    assert classify_time(datetime(2026, 7, 9, 15, 59, tzinfo=timezone.utc), window) is WindowBand.FALLBACK
    assert classify_time(datetime(2026, 7, 9, 16, 0, tzinfo=timezone.utc), window) is WindowBand.TARGET
    assert classify_time(datetime(2026, 7, 10, 15, 59, tzinfo=timezone.utc), window) is WindowBand.TARGET
    assert classify_time(datetime(2026, 7, 10, 16, 0, tzinfo=timezone.utc), window) is WindowBand.OUTSIDE


def test_rejects_naive_now() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        resolve_target_date(datetime(2026, 7, 11, 9, 0), explicit=None)
```

- [ ] **Step 2: Run and verify the tests fail**

Run: `.venv/bin/pytest tests/test_time_window.py -v`

Expected: FAIL because `day_news.time_window` does not exist.

- [ ] **Step 3: Implement the fixed window contract**

Create `src/day_news/time_window.py`:

```python
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from day_news.models import PublicationWindow, WindowBand


SHANGHAI = ZoneInfo("Asia/Shanghai")


def resolve_target_date(now: datetime, explicit: date | None) -> date:
    if explicit is not None:
        return explicit
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(SHANGHAI).date() - timedelta(days=1)


def build_window(target_date: date) -> PublicationWindow:
    target_start = datetime.combine(target_date, time.min, SHANGHAI)
    return PublicationWindow(
        target_date=target_date,
        fallback_start=target_start - timedelta(days=2),
        target_start=target_start,
        target_end=target_start + timedelta(days=1),
    )


def classify_time(value: datetime, window: PublicationWindow) -> WindowBand:
    if value.tzinfo is None:
        raise ValueError("published time must be timezone-aware")
    shanghai_value = value.astimezone(SHANGHAI)
    if window.target_start <= shanghai_value < window.target_end:
        return WindowBand.TARGET
    if window.fallback_start <= shanghai_value < window.target_start:
        return WindowBand.FALLBACK
    return WindowBand.OUTSIDE
```

- [ ] **Step 4: Run focused and full checks**

```bash
.venv/bin/pytest tests/test_time_window.py -v
.venv/bin/pytest -q
.venv/bin/ruff check .
```

Expected: all commands exit `0`.

- [ ] **Step 5: Commit the time-window behavior**

```bash
git add src/day_news/time_window.py tests/test_time_window.py
git commit -m "feat: 添加北京时间新闻窗口"
```

### Task 4: Normalize URLs, titles, summaries, dates, and articles

**Files:**
- Create: `src/day_news/normalize.py`
- Test: `tests/test_normalize.py`

- [ ] **Step 1: Write failing normalization tests**

Cover HTTP(S)-only links, retained business parameters, tracking removal, Unicode titles,
180/181-character summaries, scripts/styles, naive source dates, and rank ordering.
Include this core regression:

```python
from datetime import date, datetime, timezone

from day_news.models import Category, RawEntry, SourceConfig, SourceKind
from day_news.normalize import canonicalize_url, clean_summary, normalize_entry, title_key
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


def test_canonicalize_url_removes_only_known_tracking_parameters() -> None:
    value = "https://EXAMPLE.com/story/?id=7&utm_source=x&fbclid=y#section"
    assert canonicalize_url(value) == "https://example.com/story?id=7"


def test_title_key_normalizes_width_case_punctuation_and_space() -> None:
    assert title_key("ＡI：  Big   News!") == "ai big news"


def test_summary_removes_unsafe_html_and_stays_within_limit() -> None:
    value = "<style>x</style><script>alert(1)</script><p>" + "新" * 181 + "</p>"
    result = clean_summary(value, limit=180)
    assert result is not None
    assert len(result) == 180
    assert result.endswith("…")
    assert "alert" not in result


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
        fetched_at=datetime(2026, 7, 11, 1, 0, tzinfo=timezone.utc),
        window=build_window(date(2026, 7, 10)),
        summary_limit=180,
    )
    assert article is not None
    assert article.is_fallback is True
    assert article.canonical_url == "https://example.com/story"
    assert article.rank_key[0] == 1
```

- [ ] **Step 2: Run and verify the tests fail**

Run: `.venv/bin/pytest tests/test_normalize.py -v`

Expected: FAIL because `day_news.normalize` does not exist.

- [ ] **Step 3: Implement the normalization API**

Create `src/day_news/normalize.py` with this complete implementation:

```python
import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_datetime

from day_news.models import Article, PublicationWindow, RawEntry, SourceConfig, WindowBand
from day_news.time_window import classify_time


TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid", "spm"}


def is_tracking_key(key: str) -> bool:
    lowered = key.casefold()
    return lowered.startswith("utm_") or lowered in TRACKING_KEYS


def canonicalize_url(url: str) -> str | None:
    try:
        parsed = urlsplit(url.strip())
        if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
            return None
        scheme = parsed.scheme.casefold()
        host = parsed.hostname.casefold()
        port = parsed.port
    except ValueError:
        return None
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = host if port is None or default_port else f"{host}:{port}"
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not is_tracking_key(key)
        ),
        doseq=True,
    )
    return urlunsplit((scheme, netloc, path, query, ""))


def title_key(title: str) -> str:
    normalized = unicodedata.normalize("NFKC", title).casefold()
    cleaned = "".join(
        " " if unicodedata.category(character)[0] in {"P", "S"} else character
        for character in normalized
    )
    return " ".join(cleaned.split())


def clean_summary(value: str | None, *, limit: int) -> str | None:
    if not value:
        return None
    soup = BeautifulSoup(value, "html.parser")
    for node in soup(["script", "style"]):
        node.decompose()
    text = " ".join(soup.get_text(" ", strip=True).split())
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def parse_published(
    value: str | int | datetime | None,
    source_timezone: str | None,
) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, int):
        parsed = datetime.fromtimestamp(value, tz=timezone.utc)
    else:
        try:
            parsed = parse_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
    if parsed.tzinfo is None:
        if source_timezone is None:
            return None
        parsed = parsed.replace(tzinfo=ZoneInfo(source_timezone))
    return parsed.astimezone(timezone.utc)


def build_rank_key(
    *, is_fallback: bool, priority: int, published_at: datetime,
    source_position: int, canonical_url: str,
) -> tuple[int, int, int, int, str]:
    epoch_microseconds = int(published_at.timestamp() * 1_000_000)
    return (
        1 if is_fallback else 0,
        priority,
        -epoch_microseconds,
        source_position,
        canonical_url,
    )


def normalize_entry(
    raw: RawEntry,
    source: SourceConfig,
    *,
    fetched_at: datetime,
    window: PublicationWindow,
    summary_limit: int,
) -> Article | None:
    if not raw.title or not raw.url:
        return None
    canonical_url = canonicalize_url(raw.url)
    if canonical_url is None:
        return None
    published_at = parse_published(raw.published_value, source.timezone)
    if published_at is None:
        return None
    band = classify_time(published_at, window)
    if band is WindowBand.OUTSIDE:
        return None
    title = " ".join(unicodedata.normalize("NFKC", raw.title).split())
    normalized_title = title_key(title)
    if not normalized_title:
        return None
    stable_value = raw.external_id or canonical_url
    stable_id = hashlib.sha256(f"{source.id}\0{stable_value}".encode()).hexdigest()
    is_fallback = band is WindowBand.FALLBACK
    return Article(
        id=stable_id,
        title=title,
        title_key=normalized_title,
        url=raw.url.strip(),
        canonical_url=canonical_url,
        source_id=source.id,
        publisher_id=source.publisher_id,
        source_name=source.name,
        category=source.category,
        published_at=published_at,
        fetched_at=fetched_at,
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
```

Return `None` for missing title, missing link, invalid/non-HTTP(S) link, missing time, or an out-of-window time.

- [ ] **Step 4: Run all normalization and project checks**

```bash
.venv/bin/pytest tests/test_normalize.py -v
.venv/bin/pytest -q
.venv/bin/ruff check .
```

Expected: all commands exit `0`.

- [ ] **Step 5: Commit normalization**

```bash
git add src/day_news/normalize.py tests/test_normalize.py
git commit -m "feat: 添加新闻内容规范化"
```

### Task 5: Add retryable HTTP and RSS/Atom fetching

**Files:**
- Modify: `src/day_news/models.py`
- Create: `src/day_news/fetchers/__init__.py`
- Create: `src/day_news/fetchers/http.py`
- Create: `src/day_news/fetchers/rss.py`
- Create: `tests/fixtures/rss/sample.xml`
- Create: `tests/fixtures/rss/partial.xml`
- Test: `tests/fetchers/test_http.py`
- Test: `tests/fetchers/test_rss.py`

- [ ] **Step 1: Add failing HTTP retry tests**

Use `httpx.MockTransport` to prove that transport errors and statuses `408`, `429`, and `5xx` receive at most
three total attempts, while an ordinary `404` receives one attempt. The central test should be:

```python
import httpx
import pytest

from day_news.fetchers.http import FetchError, get_with_retry


@pytest.mark.asyncio
async def test_retries_retryable_status_then_succeeds() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(503, request=request)
        return httpx.Response(200, content=b"ok", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await get_with_retry(client, "https://example.com/feed", delays=(0.0, 0.0))
    assert response.content == b"ok"
    assert calls == 3


@pytest.mark.asyncio
async def test_does_not_retry_non_retryable_404() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(404, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(FetchError, match="404"):
            await get_with_retry(client, "https://example.com/missing", delays=(0.0, 0.0))
    assert calls == 1
```

- [ ] **Step 2: Add failing RSS/Atom tests and fixtures**

Create a fixed feed containing one `published` entry, one `updated`-only entry, and one entry without a date.
Assert that parsing preserves all three as `RawEntry` values and that `published` wins over `updated`.
Add a partially malformed feed with one valid entry and assert that it returns the valid entry plus a warning.

The primary test signature is:

```python
from pathlib import Path

from day_news.fetchers.rss import parse_feed
from day_news.models import Category, SourceConfig, SourceKind


def test_parse_feed_prefers_published_and_keeps_missing_time() -> None:
    source = SourceConfig(
        id="fixture",
        publisher_id="fixture",
        name="Fixture",
        kind=SourceKind.RSS,
        url="https://example.com/feed.xml",
        category=Category.WORLD,
        language="en",
        priority=10,
        max_per_issue=3,
        fetch_limit=60,
        timezone="UTC",
    )
    payload = Path("tests/fixtures/rss/sample.xml").read_bytes()
    result = parse_feed(payload, source)
    assert len(result.entries) == 3
    assert result.entries[0].published_value == "Fri, 10 Jul 2026 08:00:00 GMT"
    assert result.entries[1].published_value == "2026-07-10T07:00:00Z"
    assert result.entries[2].published_value is None
```

- [ ] **Step 3: Verify both test modules fail**

```bash
.venv/bin/pytest tests/fetchers/test_http.py tests/fetchers/test_rss.py -v
```

Expected: FAIL because the fetcher modules and result models do not exist.

- [ ] **Step 4: Add fetch result models**

Add these immutable models to `src/day_news/models.py`:

```python
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
```

- [ ] **Step 5: Implement bounded retry behavior**

Create `src/day_news/fetchers/http.py` with this complete implementation:

```python
import asyncio
from collections.abc import Sequence

import httpx


class FetchError(RuntimeError):
    pass


RETRYABLE_STATUSES = {408, 429}


async def get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    timeout: float = 10.0,
    delays: Sequence[float] = (1.0, 2.0),
) -> httpx.Response:
    last_error: Exception | None = None
    for attempt in range(len(delays) + 1):
        try:
            response = await client.get(url, timeout=timeout)
            if response.status_code in RETRYABLE_STATUSES or response.status_code >= 500:
                raise FetchError(f"retryable HTTP status {response.status_code}")
            if response.status_code >= 400:
                raise FetchError(f"HTTP status {response.status_code}")
            return response
        except (httpx.TransportError, httpx.TimeoutException, FetchError) as exc:
            last_error = exc
            retryable = not isinstance(exc, FetchError) or "retryable" in str(exc)
            if not retryable or attempt == len(delays):
                break
            await asyncio.sleep(delays[attempt])
    raise FetchError(f"request failed for {url}: {last_error}") from last_error
```

- [ ] **Step 6: Implement RSS parsing and fetching**

Create `src/day_news/fetchers/rss.py`. `parse_feed(payload, source)` must use `feedparser.parse`, cap entries
at `source.fetch_limit`, take `published` before `updated`, choose the Atom `alternate` link when present,
preserve missing times for the normalizer to reject, and return a warning when `feed.bozo` is true.
`fetch_rss(source, client)` must call `get_with_retry` and then `parse_feed`.

Use these exact public signatures:

```python
def parse_feed(payload: bytes, source: SourceConfig) -> SourceFetchResult:
    feed = feedparser.parse(payload)
    warnings = (str(feed.bozo_exception),) if feed.bozo else ()
    entries: list[RawEntry] = []
    for position, entry in enumerate(feed.entries[: source.fetch_limit]):
        links = entry.get("links", [])
        alternate = next(
            (link.get("href") for link in links if link.get("rel", "alternate") == "alternate"),
            None,
        )
        entries.append(
            RawEntry(
                external_id=entry.get("id") or entry.get("guid"),
                title=entry.get("title"),
                url=alternate or entry.get("link"),
                published_value=entry.get("published") or entry.get("updated"),
                summary_html=entry.get("summary") or entry.get("description"),
                source_position=position,
            )
        )
    if feed.bozo and not entries:
        raise FetchError(f"unreadable feed: {feed.bozo_exception}")
    return SourceFetchResult(source_id=source.id, entries=tuple(entries), warnings=warnings)


async def fetch_rss(source: SourceConfig, client: httpx.AsyncClient) -> SourceFetchResult:
    response = await get_with_retry(client, source.url)
    return parse_feed(response.content, source)
```

- [ ] **Step 7: Run focused and full checks**

```bash
.venv/bin/pytest tests/fetchers/test_http.py tests/fetchers/test_rss.py -v
.venv/bin/pytest -q
.venv/bin/ruff check .
```

Expected: all tests pass and Ruff exits `0`.

- [ ] **Step 8: Commit HTTP and RSS fetching**

```bash
git add src/day_news/models.py src/day_news/fetchers tests/fixtures/rss tests/fetchers
git commit -m "feat: 添加 RSS 抓取与重试"
```

### Task 6: Fetch Hacker News and isolate source failures

**Files:**
- Create: `src/day_news/fetchers/hacker_news.py`
- Modify: `src/day_news/fetchers/__init__.py`
- Create: `tests/fixtures/hn/`
- Test: `tests/fetchers/test_hacker_news.py`
- Test: `tests/fetchers/test_batch.py`

- [ ] **Step 1: Write failing HN tests**

Use `httpx.MockTransport` fixtures for `topstories`, `beststories`, `newstories`, and item JSON.
Test that ID order is stable despite response order, duplicate IDs are fetched once,
deleted/dead/non-story/null items are skipped, missing external URLs are skipped, and one detail failure
does not fail the whole source. Use `fetch_limit=4` and `workers=2` in tests.

- [ ] **Step 2: Write the failing source-isolation test**

Inject one fetcher that raises and one that succeeds, then assert `fetch_all` returns the successful entries
and records the failed source:

```python
assert batch.successful_sources == ("working",)
assert batch.failed_sources == {"broken": "boom"}
assert len(batch.entries) == 1
```

- [ ] **Step 3: Verify both test modules fail**

```bash
.venv/bin/pytest tests/fetchers/test_hacker_news.py tests/fetchers/test_batch.py -v
```

Expected: FAIL because the HN and batch implementations do not exist.

- [ ] **Step 4: Implement HN fetching**

`fetch_hacker_news(source, client, workers=12)` must:

1. Fetch `topstories.json`, `beststories.json`, and `newstories.json`.
2. Deduplicate IDs while preserving first appearance.
3. Truncate to `source.fetch_limit`.
4. Fetch details with `asyncio.Semaphore(workers)` and `get_with_retry`.
5. Preserve list position as `source_position`, even when details complete out of order.
6. Keep only live `story` items with non-empty title, external URL, and integer `time`.
7. Convert HN time to a UTC `datetime` and leave the summary empty.
8. Return warnings for individual detail failures; fail the source only when every list request fails.

The result construction must be equivalent to:

```python
RawEntry(
    external_id=str(item["id"]),
    title=item["title"],
    url=item["url"],
    published_value=int(item["time"]),
    summary_html=None,
    source_position=position,
)
```

- [ ] **Step 5: Implement the fetcher registry and batch isolation**

In `src/day_news/fetchers/__init__.py`, use this complete batch implementation:

```python
import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence

import httpx

from day_news.fetchers.hacker_news import fetch_hacker_news
from day_news.fetchers.rss import fetch_rss
from day_news.models import FetchBatch, RawEntry, SourceConfig, SourceFetchResult, SourceKind


type Fetcher = Callable[[SourceConfig, httpx.AsyncClient], Awaitable[SourceFetchResult]]


FETCHERS: dict[SourceKind, Fetcher] = {
    SourceKind.RSS: fetch_rss,
    SourceKind.HACKER_NEWS: fetch_hacker_news,
}


async def fetch_all(
    sources: Sequence[SourceConfig],
    client: httpx.AsyncClient,
    *,
    registry: Mapping[SourceKind, Fetcher] = FETCHERS,
) -> FetchBatch:
    enabled = [source for source in sources if source.enabled]
    tasks = [registry[source.kind](source, client) for source in enabled]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    entries: list[tuple[SourceConfig, RawEntry]] = []
    successful: list[str] = []
    failed: dict[str, str] = {}
    warnings: list[str] = []
    for source, result in zip(enabled, results, strict=True):
        if isinstance(result, BaseException):
            failed[source.id] = str(result)
            continue
        successful.append(source.id)
        warnings.extend(f"{source.id}: {warning}" for warning in result.warnings)
        entries.extend((source, entry) for entry in result.entries)
    return FetchBatch(
        entries=tuple(entries),
        successful_sources=tuple(successful),
        failed_sources=failed,
        warnings=tuple(warnings),
    )
```

The `zip` over configuration-order sources restores deterministic result ordering and never cancels successful sources.

- [ ] **Step 6: Run focused and full checks**

```bash
.venv/bin/pytest tests/fetchers/test_hacker_news.py tests/fetchers/test_batch.py -v
.venv/bin/pytest -q
.venv/bin/ruff check .
```

Expected: all commands exit `0`.

- [ ] **Step 7: Commit HN and batch fetching**

```bash
git add src/day_news/fetchers tests/fixtures/hn tests/fetchers
git commit -m "feat: 添加 Hacker News 抓取"
```

### Task 7: Load history and perform deterministic deduplication

**Files:**
- Modify: `src/day_news/models.py`
- Create: `src/day_news/history.py`
- Create: `src/day_news/dedupe.py`
- Test: `tests/test_history.py`
- Test: `tests/test_dedupe.py`

- [ ] **Step 1: Write failing 30-day history tests**

Create temporary editions whose YAML front matter contains:

```yaml
dedupe_index:
  - id: abc
    canonical_url: https://example.com/a
    title_key: example a
```

Assert the target date minus 30 days is included, minus 31 days is excluded, malformed front matter raises
`HistoryError`, and URL/title values are loaded exactly.

- [ ] **Step 2: Write failing deduplication tests**

Cover the four ordered reasons: stable ID, canonical URL, exact `title_key`, and
`SequenceMatcher >= 0.92`. Shuffle the candidate input and assert the same IDs and order remain.
Assert a similarity below `0.92` is retained.

- [ ] **Step 3: Run and verify failure**

```bash
.venv/bin/pytest tests/test_history.py tests/test_dedupe.py -v
```

Expected: FAIL because the history and dedupe modules do not exist.

- [ ] **Step 4: Add result models**

Append to `src/day_news/models.py`:

```python
@dataclass(frozen=True, slots=True)
class DedupeResult:
    articles: tuple[Article, ...]
    removed_by_reason: dict[str, int]
```

- [ ] **Step 5: Implement history loading**

`load_history(content_root, target_date, days=30)` must inspect only exact date paths from
`target_date - 1 day` through `target_date - 30 days`, parse YAML between the first two `---` lines with
`yaml.safe_load`, require each `dedupe_index` row to have string `id`, `canonical_url`, and `title_key`,
and return a `HistoryIndex`. Raise `HistoryError` for a present but malformed edition.

- [ ] **Step 6: Implement ordered deduplication**

`deduplicate(candidates, history, similarity_threshold=0.92)` must first sort by `Article.rank_key`.
For each candidate, reject on the first matching reason in this order:

```text
history/current stable ID
history/current canonical URL
history/current exact title key
history/current title similarity >= threshold
```

When an article is kept, add all three keys to the current sets. Return deterministic kept articles and reason
counts named `stable_id`, `canonical_url`, `exact_title`, and `similar_title`.

- [ ] **Step 7: Run focused and full checks**

```bash
.venv/bin/pytest tests/test_history.py tests/test_dedupe.py -v
.venv/bin/pytest -q
.venv/bin/ruff check .
```

Expected: all commands exit `0`.

- [ ] **Step 8: Commit history and dedupe**

```bash
git add src/day_news/models.py src/day_news/history.py src/day_news/dedupe.py tests/test_history.py tests/test_dedupe.py
git commit -m "feat: 添加跨期新闻去重"
```

### Task 8: Select a diverse edition and enforce publication thresholds

**Files:**
- Modify: `src/day_news/models.py`
- Create: `src/day_news/select.py`
- Test: `tests/test_select.py`

- [ ] **Step 1: Write failing deterministic selection tests**

Add factories that create articles across dates, categories, and publishers. Cover these exact cases:

- 24 valid target-date items produce no fallback items.
- 24 target-date items from only three categories add fallback items to reach four categories, without exceeding 30.
- Four publishers fail even when item/category counts pass.
- Exactly `12 items / 4 categories / 5 publishers` passes.
- A configured publisher cap of 2 overrides the default cap of 3.
- Candidate order shuffling does not change selected IDs or output order.
- Fallback items are never older than the two permitted dates.

- [ ] **Step 2: Run and verify failure**

Run: `.venv/bin/pytest tests/test_select.py -v`

Expected: FAIL because `day_news.select` does not exist.

- [ ] **Step 3: Add the selection result model**

Append to `src/day_news/models.py`:

```python
@dataclass(frozen=True, slots=True)
class SelectionResult:
    articles: tuple[Article, ...]
    valid: bool
    failure_reason: str | None
```

- [ ] **Step 4: Implement the fixed selection algorithm**

Create `select_articles(candidates, sources, policy)` in `src/day_news/select.py` with this sequence:

1. Sort all candidates by `rank_key` and split target/fallback.
2. Select target-date diversity seeds: one best item per category, then one best item per unseen publisher.
3. Fill toward 24 by rank while enforcing per-publisher caps and a soft per-category target of 4.
4. If count is below 24, categories below 4, or publishers below 5, run the same seed/fill logic over
   fallback candidates.
5. When count already reached 24 but coverage still needs repair, append repair items up to 30.
6. Never remove a higher-ranked selected representative merely to exceed the target count.
7. Return articles grouped by fixed `Category` order and then by `rank_key`.
8. Mark invalid unless final count is at least 12, categories at least 4, and publishers at least 5.

Use `publisher_id` for all source-count and cap calculations. Build effective publisher caps from the minimum
configured `max_per_issue` for that publisher.

- [ ] **Step 5: Run focused and full checks**

```bash
.venv/bin/pytest tests/test_select.py -v
.venv/bin/pytest -q
.venv/bin/ruff check .
```

Expected: all commands exit `0`.

- [ ] **Step 6: Commit deterministic selection**

```bash
git add src/day_news/models.py src/day_news/select.py tests/test_select.py
git commit -m "feat: 添加日刊筛选与发布门槛"
```

### Task 9: Render editions and update README safely

**Files:**
- Modify: `src/day_news/models.py`
- Create: `src/day_news/issue.py`
- Create: `src/day_news/readme.py`
- Create: `templates/issue.md.j2`
- Modify: `README.md`
- Test: `tests/test_issue.py`
- Test: `tests/test_readme.py`

- [ ] **Step 1: Write failing edition rendering tests**

Assert fixed category order, omitted empty categories, fallback labeling, absent blank-summary lines,
sorted `dedupe_index`, parse/render round trips, and byte-identical repeated rendering.
The rendered item format is fixed as:

```markdown
### 1. [Original title](<https://example.com/story>)

> Example Source · 2026-07-10 16:00 CST · 近三日补充

Short summary.
```

- [ ] **Step 2: Write failing README marker tests**

Use exactly these markers:

```markdown
<!-- DAY_NEWS_RECENT_START -->
<!-- DAY_NEWS_RECENT_END -->
```

Assert only marker contents change, at most ten editions appear in descending order,
duplicate/missing/reversed markers raise `ReadmeError`, and the second update is byte-identical.

- [ ] **Step 3: Run and verify failure**

```bash
.venv/bin/pytest tests/test_issue.py tests/test_readme.py -v
```

Expected: FAIL because edition and README modules do not exist.

- [ ] **Step 4: Add issue models**

Append to `src/day_news/models.py`:

```python
@dataclass(frozen=True, slots=True)
class Issue:
    target_date: date
    generated_at: datetime
    articles: tuple[Article, ...]


@dataclass(frozen=True, slots=True)
class IssueSummary:
    target_date: date
    path: Path
    article_count: int
    source_count: int
    generated_at: datetime


@dataclass(frozen=True, slots=True)
class ParsedIssue:
    target_date: date
    generated_at: datetime
    article_count: int
    source_count: int
    fallback_count: int
    categories: tuple[Category, ...]
    content_fingerprint: str
    dedupe_index: tuple[dict[str, str], ...]
    body: str
    path: Path
```

- [ ] **Step 5: Implement deterministic front matter and Markdown**

Add `content_fingerprint(target_date, articles)` using SHA-256 over a UTF-8 JSON array with
`sort_keys=True` and separators `(',', ':')`. Include only target date and ordered display fields: ID,
title, canonical URL, publisher, source name, category, publication time, summary, and fallback flag.

`render_issue(issue)` must create YAML with `sort_keys=False`, UTF-8 Unicode, and these keys in order:
`date`, `generated_at`, `article_count`, `source_count`, `fallback_count`, `categories`,
`content_fingerprint`, `dedupe_index`. Count publishers, not feeds, in `source_count`. Format
`generated_at` as ISO 8601 and displayed publication times in Shanghai time with `CST`.
Store category slugs in YAML and use `CATEGORY_LABELS` only for visible Markdown/HTML headings.
Before interpolation, backslash-escape Markdown metacharacters in titles, source names, and summaries.
Wrap canonical URLs in Markdown angle brackets. Add a regression whose summary contains
`[click](javascript:alert(1))` and assert the rendered site contains plain text rather than a link.

`parse_issue(path) -> ParsedIssue` must validate that the file date matches front-matter `date`, reconstruct
every `ParsedIssue` field required by the site builder, and raise `IssueError` for malformed files.

- [ ] **Step 6: Implement controlled README updates**

Create a README whose recent block initially contains no issues and explains the project, website URL,
source/copyright policy, and the commands `day-news generate`, `day-news build`, and `day-news validate`.
`update_readme(text, summaries)` must replace only the unique marker range with links like:

```markdown
- [2026-07-10](content/2026/07/2026-07-10.md) · 24 条
```

- [ ] **Step 7: Run focused and full checks**

```bash
.venv/bin/pytest tests/test_issue.py tests/test_readme.py -v
.venv/bin/pytest -q
.venv/bin/ruff check .
```

Expected: all commands exit `0`.

- [ ] **Step 8: Commit rendering and README support**

```bash
git add src/day_news/models.py src/day_news/issue.py src/day_news/readme.py \
  templates/issue.md.j2 README.md tests/test_issue.py tests/test_readme.py
git commit -m "feat: 生成日刊 Markdown 与索引"
```

### Task 10: Orchestrate generation, reports, idempotency, and atomic writes

**Files:**
- Modify: `src/day_news/models.py`
- Modify: `src/day_news/issue.py`
- Create: `src/day_news/generate.py`
- Test: `tests/test_generate.py`

- [ ] **Step 1: Write failing end-to-end generation tests with fake fetchers**

Use temporary content/README/report paths and an injected fetcher registry. Cover:

- A valid run creates one date file, updates README, and writes a successful JSON report.
- An existing valid date file returns `SKIPPED_EXISTS` before any fetcher is called.
- An existing malformed or wrong-date file raises `IssueError` rather than silently skipping.
- Threshold failure writes only the report and creates neither the edition nor README changes.
- One failed source is recorded while other sources still produce an edition.
- `force=True` with the same content fingerprint preserves the original bytes and `generated_at`.
- `force=True` with changed selected content atomically replaces only the target edition and README block.

- [ ] **Step 2: Run and verify failure**

Run: `.venv/bin/pytest tests/test_generate.py -v`

Expected: FAIL because `day_news.generate` does not exist.

- [ ] **Step 3: Add atomic write helpers**

Create private helpers in `src/day_news/generate.py` that make the parent directory, write a sibling temporary
file in UTF-8, flush and `os.fsync`, then call `os.replace`. Use a separate JSON helper that serializes with
`ensure_ascii=False`, `sort_keys=True`, `indent=2`, and a trailing newline. Tests must inject an exception
before replacement and assert no destination file or temporary file remains.

- [ ] **Step 4: Implement the generation pipeline**

Create this public async entry point in `src/day_news/generate.py`:

```python
async def generate_issue(
    target_date: date,
    *,
    config: AppConfig,
    content_root: Path,
    readme_path: Path,
    report_path: Path,
    generated_at: datetime,
    client: httpx.AsyncClient,
    registry: Mapping[SourceKind, Fetcher] = FETCHERS,
    force: bool = False,
) -> GenerationResult:
```

Implement this exact order:

1. Resolve `content/YYYY/MM/YYYY-MM-DD.md`.
2. If it exists and `force` is false, parse and validate it, write a `skipped_exists` report,
   and return before network access.
3. Fetch all enabled sources and initialize `RunReport` with successful/failed source data.
4. Normalize every `(source, RawEntry)` and count both fetched and in-window items.
5. Load 30-day history, deduplicate, and select.
6. On invalid selection, write an atomic `failed_threshold` report and return without touching content or README.
7. Build the new `Issue`, Markdown, updated recent summaries, and updated README entirely in memory.
8. When forcing an existing edition, compare content fingerprints; if equal, preserve the old bytes and
   return `UNCHANGED`.
9. Write the edition and README to sibling temporary files, `fsync`, then replace their destinations with `os.replace`.
10. Write the final report atomically and return `CREATED` or `UPDATED`.

The report JSON must use `RunReport.to_dict()`, UTF-8, `ensure_ascii=False`, `sort_keys=True`, and a trailing newline.

- [ ] **Step 5: Run focused and full checks**

```bash
.venv/bin/pytest tests/test_generate.py -v
.venv/bin/pytest -q
.venv/bin/ruff check .
```

Expected: all commands exit `0`.

- [ ] **Step 6: Commit generation orchestration**

```bash
git add src/day_news/models.py src/day_news/issue.py src/day_news/generate.py tests/test_generate.py
git commit -m "feat: 编排每日新闻生成流程"
```

### Task 11: Load editions and generate deterministic RSS

**Files:**
- Modify: `src/day_news/models.py`
- Modify: `src/day_news/config.py`
- Create: `config/site.toml`
- Create: `src/day_news/feed.py`
- Test: `tests/test_feed.py`

- [ ] **Step 1: Write failing site-config and RSS tests**

Test `config/site.toml` loads the exact project URL and repository URLs. Build 31 fixed issue summaries and
assert RSS contains the latest 30, newest first, parses with `feedparser` and `bozo == 0`, uses absolute issue
URLs as both link and GUID, XML-escapes titles, and remains byte-identical across repeated builds. Also assert
an empty issue sequence creates a valid feed with no items and no `lastBuildDate`.

- [ ] **Step 2: Run and verify failure**

Run: `.venv/bin/pytest tests/test_feed.py -v`

Expected: FAIL because site configuration and feed generation do not exist.

- [ ] **Step 3: Add site configuration**

Create `config/site.toml`:

```toml
title = "每日新闻"
description = "每天北京时间 9:00 自动更新的免费新闻日刊"
site_url = "https://wangyaruo.github.io/day-news/"
base_path = "/day-news/"
repository_url = "https://github.com/wangyaruo/day-news"
issues_url = "https://github.com/wangyaruo/day-news/issues"
language = "zh-CN"
```

Add an immutable `SiteConfig` model and `load_site_config(path)` validation. Require HTTPS `site_url`,
a leading and trailing slash on `base_path`, and matching URL path `/day-news/`.

- [ ] **Step 4: Implement deterministic RSS 2.0**

Create `build_rss(issues, site_config) -> bytes` in `src/day_news/feed.py` using
`xml.etree.ElementTree`. Use at most 30 issues, sorted newest first. The channel `lastBuildDate` is the newest
issue `generated_at`; each item uses:

```text
title: 每日新闻 · YYYY-MM-DD
link/guid: https://wangyaruo.github.io/day-news/issues/YYYY-MM-DD/
pubDate: the edition generated_at as RFC 2822
description: N 条新闻，M 个来源
```

Never use the current build time. Omit `lastBuildDate` when there are no issues. Register no third-party
namespace and include a final newline.

- [ ] **Step 5: Run focused and full checks**

```bash
.venv/bin/pytest tests/test_feed.py -v
.venv/bin/pytest -q
.venv/bin/ruff check .
```

Expected: all commands exit `0`.

- [ ] **Step 6: Commit site configuration and RSS**

```bash
git add src/day_news/models.py src/day_news/config.py config/site.toml src/day_news/feed.py tests/test_feed.py
git commit -m "feat: 生成日刊 RSS 订阅"
```

### Task 12: Build and validate the static GitHub Pages site

**Files:**
- Create: `src/day_news/site.py`
- Create: `src/day_news/validate.py`
- Create: `templates/base.html.j2`
- Create: `templates/index.html.j2`
- Create: `templates/issue.html.j2`
- Create: `templates/archive.html.j2`
- Create: `templates/month.html.j2`
- Create: `templates/sources.html.j2`
- Create: `templates/about.html.j2`
- Create: `assets/styles.css`
- Test: `tests/test_site.py`
- Test: `tests/test_validate.py`

- [ ] **Step 1: Write failing site tests**

Build fixtures with 0, 1, 10, and 31 editions across month/year boundaries. Assert these exact outputs:

```text
dist/index.html
dist/issues/YYYY-MM-DD/index.html
dist/archive/index.html
dist/archive/YYYY-MM/index.html
dist/sources/index.html
dist/about/index.html
dist/assets/styles.css
dist/rss.xml
```

Assert latest/recent links, month grouping, first/last previous-next boundaries, enabled sources only,
`/day-news/` asset paths, escaped source content, no `<script>` elements, no third-party fonts/assets,
and byte-identical clean rebuilds. Delete one source edition before a rebuild and assert the stale output
route disappears.

- [ ] **Step 2: Write failing validator tests**

Create a fixture with a broken internal link and assert validation fails with the originating file and missing
target. Also test a valid site, parse `rss.xml` with `feedparser`, and reject local `href` or `src` values
that escape `/day-news/`.

- [ ] **Step 3: Run and verify failure**

```bash
.venv/bin/pytest tests/test_site.py tests/test_validate.py -v
```

Expected: FAIL because the site builder and validator do not exist.

- [ ] **Step 4: Implement site discovery and clean builds**

Create `build_site(content_root, output_root, source_config, site_config)`. It must remove only the supplied
`output_root`, recreate it, discover `content/YYYY/MM/YYYY-MM-DD.md`, parse every issue, sort newest first,
and render Markdown with:

```python
MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False})
```

Create Jinja with `select_autoescape(("html", "xml"))`. Render all fixed routes, copy `assets/styles.css`,
and write the bytes returned by `build_rss` to `rss.xml`. Internal URLs must be built through one
`route(path)` helper that prepends `site_config.base_path`.

- [ ] **Step 5: Create the minimal accessible templates and CSS**

`base.html.j2` must contain semantic header/main/footer elements, viewport metadata, local stylesheet,
RSS `<link>`, repository navigation, and no JavaScript. The issue template renders already-sanitized Markdown
HTML with Jinja's `safe` only at that single boundary. CSS must provide readable maximum width, system fonts,
visible focus styles, responsive spacing, light/dark color support, and no external URL.

- [ ] **Step 6: Implement offline validation**

`validate_site(output_root, site_config)` must parse generated HTML with `BeautifulSoup`, map local links below
`base_path` back to filesystem targets, verify every target exists, reject local traversal, parse RSS with
`feedparser`, and return a tuple of error strings. `validate_content(content_root)` must parse every issue and
reject duplicate dates or date/path mismatches.

- [ ] **Step 7: Run focused and full checks**

```bash
.venv/bin/pytest tests/test_site.py tests/test_validate.py -v
.venv/bin/pytest -q
.venv/bin/ruff check .
```

Expected: all commands exit `0`.

- [ ] **Step 8: Commit site generation and validation**

```bash
git add src/day_news/site.py src/day_news/validate.py templates assets tests/test_site.py tests/test_validate.py
git commit -m "feat: 构建日刊静态网站"
```

### Task 13: Add the CLI and an offline full-pipeline regression

**Files:**
- Create: `src/day_news/cli.py`
- Create: `src/day_news/__main__.py`
- Create: `tests/integration/test_daily_generation.py`
- Create: `tests/fixtures/integration/`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI exit-code tests**

Test valid/invalid `YYYY-MM-DD`, default target date, generate no-op, threshold failure exit `3`,
configuration error exit `2`, unexpected error exit `1`, clean build, and validation failure.
Patch network and current time; CLI tests must not use live sources.

- [ ] **Step 2: Write the failing offline golden test**

Create RSS/Atom/HN fixtures that yield at least 12 selected items across 4 categories and 5 publishers for
target date `2026-07-10`, plus duplicates, missing times, unsafe HTML, one failed source, and fallback items.
Assert:

- Generated Markdown matches `tests/fixtures/integration/expected-2026-07-10.md` byte for byte.
- Report counts and failed-source reason match a fixed JSON object.
- README recent block contains the edition.
- Site build and validation pass.
- Shuffling raw input produces identical edition bytes.
- A second non-force run calls no fetcher and changes no file.

- [ ] **Step 3: Run and verify failure**

```bash
.venv/bin/pytest tests/test_cli.py tests/integration/test_daily_generation.py -v
```

Expected: FAIL because the CLI and complete fixture set do not exist.

- [ ] **Step 4: Implement the CLI**

Create `main(argv: Sequence[str] | None = None) -> int` with subcommands:

```text
day-news target-date
day-news generate [--date YYYY-MM-DD] [--force] [--report PATH] [--content PATH] [--readme PATH]
day-news build [--content PATH] [--output PATH]
day-news validate [--config PATH] [--content PATH] [--site PATH]
```

Defaults are `config/sources.toml`, `config/site.toml`, `content`, `dist`, `README.md`, and
`build/reports/YYYY-MM-DD.json`. `generate` creates one `httpx.AsyncClient` with user agent
`wangyaruo/day-news (+https://github.com/wangyaruo/day-news)` and passes it to `generate_issue`
inside `asyncio.run`. `build` performs a clean build. `validate` validates configuration, content,
and an existing site. Print concise Chinese status messages and map exceptions/statuses to the fixed exit codes.

Create `src/day_news/__main__.py`:

```python
from day_news.cli import main


raise SystemExit(main())
```

- [ ] **Step 5: Complete the fixed fixtures and golden files**

Keep every fixture timestamp explicit and every expected order deterministic. Do not record live responses.
Ensure the five publishers are distinct by `publisher_id`, not merely by feed ID.

- [ ] **Step 6: Run the full offline verification**

```bash
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/day-news build --content tests/fixtures/integration/content --output build/test-site
.venv/bin/day-news validate --content tests/fixtures/integration/content --site build/test-site
```

Expected: all tests and commands exit `0`.

- [ ] **Step 7: Commit CLI and integration coverage**

```bash
git add src/day_news/cli.py src/day_news/__main__.py tests/test_cli.py tests/integration tests/fixtures/integration
git commit -m "feat: 添加日刊命令行与集成测试"
```

### Task 14: Add CI, scheduled publishing, live bootstrap, and deployment verification

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `.github/workflows/publish.yml`
- Modify: `README.md`
- Create: `content/2026/07/2026-07-10.md` through the CLI

- [ ] **Step 1: Write CI workflow**

Create `.github/workflows/ci.yml` for `pull_request` and pushes to `main`, with `contents: read`, cancellable
per-ref concurrency, Python 3.12, dependency installation, and these commands:

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: python -m pip install -e ".[dev]"
      - run: ruff check .
      - run: ruff format --check .
      - run: pytest -q
      - run: day-news build --output dist
      - run: day-news validate --site dist
```

- [ ] **Step 2: Write publish workflow triggers and permissions**

Create `.github/workflows/publish.yml` with:

```yaml
on:
  push:
    branches: [main]
  schedule:
    - cron: "0 1 * * *"
    - cron: "20 1 * * *"
  workflow_dispatch:
    inputs:
      mode:
        type: choice
        options: [generate-and-deploy, deploy-only]
        default: generate-and-deploy
      target_date:
        type: string
        required: false
      force:
        type: boolean
        default: false

permissions: {}

concurrency:
  group: day-news-publish-${{ github.repository }}
  cancel-in-progress: false
```

Use three jobs:

1. `generate`:
   - Use this job condition:

     ```yaml
     if: >-
       ${{ github.event_name == 'schedule' ||
           (github.event_name == 'workflow_dispatch' && inputs.mode == 'generate-and-deploy') }}
     ```
   - Grant `contents: write`; test first; validate target date; forbid force outside manual mode.
   - Generate, prebuild, validate, commit only `content/` and `README.md`, push without force,
     output current SHA, and upload the report with `if: always()` for 14 days.
2. `build`:
   - Declare `needs: generate` and condition
     `${{ always() && needs.generate.result != 'failure' && needs.generate.result != 'cancelled' }}`
     so push and deploy-only events survive a skipped generate job.
   - Grant `contents: read`; check out `${{ needs.generate.outputs.commit_sha || github.sha }}`.
   - Reinstall, test, build, validate, configure Pages, and upload `dist/`.
3. `deploy`:
   - Depend on `build`, require build success, and grant only `pages: write` and `id-token: write`.
   - Use the `github-pages` environment and deploy the uploaded artifact.

Use `actions/checkout@v4`, `actions/setup-python@v5`, `actions/upload-artifact@v4`,
`actions/configure-pages@v5`, `actions/upload-pages-artifact@v3`, and `actions/deploy-pages@v4`.
The scheduled run must finish deployment itself because a bot push made with `GITHUB_TOKEN` does not
recursively trigger another workflow.

Implement the jobs with this complete structure:

```yaml
jobs:
  generate:
    if: >-
      ${{ github.event_name == 'schedule' ||
          (github.event_name == 'workflow_dispatch' && inputs.mode == 'generate-and-deploy') }}
    runs-on: ubuntu-latest
    permissions:
      contents: write
    outputs:
      commit_sha: ${{ steps.commit.outputs.commit_sha }}
    steps:
      - uses: actions/checkout@v4
        with:
          ref: main
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: python -m pip install -e ".[dev]"
      - run: ruff check .
      - run: ruff format --check .
      - run: pytest -q
      - id: date
        env:
          INPUT_TARGET_DATE: ${{ inputs.target_date }}
        run: |
          target="$INPUT_TARGET_DATE"
          if [ -z "$target" ]; then
            target="$(day-news target-date)"
          fi
          if ! [[ "$target" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
            echo "Invalid target date: $target" >&2
            exit 2
          fi
          echo "target_date=$target" >> "$GITHUB_OUTPUT"
      - name: Generate edition
        env:
          TARGET_DATE: ${{ steps.date.outputs.target_date }}
          FORCE: ${{ inputs.force }}
        run: |
          args=(--date "$TARGET_DATE" --report "build/reports/$TARGET_DATE.json")
          if [ "$GITHUB_EVENT_NAME" = "workflow_dispatch" ] && [ "$FORCE" = "true" ]; then
            args+=(--force)
          fi
          day-news generate "${args[@]}"
      - run: day-news build --output dist
      - run: day-news validate --site dist
      - id: commit
        env:
          TARGET_DATE: ${{ steps.date.outputs.target_date }}
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add -- content README.md
          if git diff --cached --quiet; then
            echo "No content changes"
          else
            git commit -m "news: 发布 ${TARGET_DATE} 日刊"
            git push
          fi
          echo "commit_sha=$(git rev-parse HEAD)" >> "$GITHUB_OUTPUT"
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: generation-report-${{ steps.date.outputs.target_date }}
          path: build/reports/*.json
          if-no-files-found: ignore
          retention-days: 14

  build:
    needs: generate
    if: >-
      ${{ always() && needs.generate.result != 'failure' &&
          needs.generate.result != 'cancelled' }}
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ needs.generate.outputs.commit_sha || github.sha }}
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: python -m pip install -e ".[dev]"
      - run: ruff check .
      - run: ruff format --check .
      - run: pytest -q
      - run: day-news build --output dist
      - run: day-news validate --site dist
      - uses: actions/configure-pages@v5
      - uses: actions/upload-pages-artifact@v3
        with:
          path: dist

  deploy:
    needs: build
    if: ${{ needs.build.result == 'success' }}
    runs-on: ubuntu-latest
    permissions:
      pages: write
      id-token: write
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - id: deployment
        uses: actions/deploy-pages@v4
```

- [ ] **Step 3: Add exact bot commit behavior**

The generate job must use:

```bash
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add -- content README.md
if git diff --cached --quiet; then
  echo "No content changes"
else
  git commit -m "news: 发布 ${TARGET_DATE} 日刊"
  git push
fi
echo "commit_sha=$(git rev-parse HEAD)" >> "$GITHUB_OUTPUT"
```

Never add `dist/`, build reports, or a PAT.

- [ ] **Step 4: Document repository settings and recovery**

Update README with:

- Settings → Pages → Source must be “GitHub Actions”.
- Actions workflow permissions must allow read/write.
- Branch protection/rulesets must permit `github-actions[bot]` to push or the no-key auto-commit cannot work.
- Cron is UTC and may be delayed; 09:20 is an idempotent retry, not a strict SLA.
- `workflow_dispatch` deploy-only recovers a failed deployment without rewriting content.

- [ ] **Step 5: Run the final local verification before live data**

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest -q
.venv/bin/day-news build --output dist
.venv/bin/day-news validate --site dist
git diff --check
```

Expected: every command exits `0`.

- [ ] **Step 6: Smoke-test configured live sources**

Run a live smoke generation into ignored build paths first:

```bash
mkdir -p build/smoke-content build/reports
cp README.md build/smoke-README.md
.venv/bin/day-news generate \
  --date 2026-07-10 \
  --content build/smoke-content \
  --readme build/smoke-README.md \
  --report build/reports/source-smoke.json
```

Replace or disable only feeds that fail because their official endpoint changed. Preserve at least two publishers
per category and at least five publishers overall. Record failures in the report rather than editing tests to use
the network.

- [ ] **Step 7: Generate the first real edition and rebuild**

```bash
.venv/bin/day-news generate --date 2026-07-10 --report build/reports/2026-07-10.json
.venv/bin/day-news build --output dist
.venv/bin/day-news validate --site dist
```

Expected: the edition exists at `content/2026/07/2026-07-10.md`, README lists it, the report is successful,
and site validation exits `0`.

- [ ] **Step 8: Commit workflows and the first edition**

```bash
git add .github/workflows README.md config src templates assets tests pyproject.toml .gitignore \
  content/2026/07/2026-07-10.md
git commit -m "feat: 发布自动更新的每日新闻日刊"
```

- [ ] **Step 9: Re-run repository verification on the committed tree**

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest -q
.venv/bin/day-news build --output dist
.venv/bin/day-news validate --site dist
git status --short
```

Expected: all checks exit `0`; `git status --short` is empty because `dist/` and reports are ignored.

- [ ] **Step 10: Push and configure GitHub Pages**

```bash
git push -u origin main
gh api --method POST repos/wangyaruo/day-news/pages -f build_type=workflow
gh workflow run publish.yml -f mode=deploy-only
RUN_ID=$(gh run list --workflow publish.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch "$RUN_ID" --exit-status
```

If the Pages endpoint already exists, the POST may return `409`; verify its current build type with
`gh api repos/wangyaruo/day-news/pages` and continue only when it reports `workflow`.

- [ ] **Step 11: Verify the public result**

```bash
curl -sS -I https://wangyaruo.github.io/day-news/
curl -sS https://wangyaruo.github.io/day-news/rss.xml
```

Expected: the site returns HTTP `200`, and `rss.xml` is valid RSS containing the first edition.
