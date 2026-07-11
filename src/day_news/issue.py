from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from day_news.models import CATEGORY_LABELS, Article, Category, Issue, ParsedIssue

SHANGHAI = ZoneInfo("Asia/Shanghai")
MARKDOWN_SPECIAL_RE = re.compile(r"([\\`*{}\[\]()<>#+\-.!_|])")
TEMPLATE_ROOT = Path(__file__).resolve().parents[2] / "templates"


class IssueError(ValueError):
    pass


def content_fingerprint(target_date: date, articles: tuple[Article, ...]) -> str:
    payload: list[object] = [
        target_date.isoformat(),
        [
            {
                "id": article.id,
                "title": article.title,
                "canonical_url": article.canonical_url,
                "publisher_id": article.publisher_id,
                "source_name": article.source_name,
                "category": article.category.value,
                "published_at": article.published_at.astimezone(UTC).isoformat(),
                "summary": article.summary,
                "is_fallback": article.is_fallback,
            }
            for article in articles
        ],
    ]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def render_issue(issue: Issue) -> str:
    if issue.generated_at.tzinfo is None or issue.generated_at.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")

    categories = tuple(
        category for category in Category if any(article.category is category for article in issue.articles)
    )
    dedupe_index = sorted(
        (
            {
                "id": article.id,
                "canonical_url": article.canonical_url,
                "title_key": article.title_key,
            }
            for article in issue.articles
        ),
        key=lambda row: (row["id"], row["canonical_url"], row["title_key"]),
    )
    front_matter: dict[str, object] = {
        "date": issue.target_date.isoformat(),
        "generated_at": issue.generated_at.isoformat(),
        "article_count": len(issue.articles),
        "source_count": len({article.publisher_id for article in issue.articles}),
        "fallback_count": sum(article.is_fallback for article in issue.articles),
        "categories": [category.value for category in categories],
        "content_fingerprint": content_fingerprint(issue.target_date, issue.articles),
        "dedupe_index": dedupe_index,
    }

    number = 0
    sections: list[dict[str, object]] = []
    for category in categories:
        items: list[dict[str, object]] = []
        for article in issue.articles:
            if article.category is not category:
                continue
            number += 1
            items.append(
                {
                    "number": number,
                    "title": _escape_markdown(article.title),
                    "url": article.canonical_url,
                    "source_name": _escape_markdown(article.source_name),
                    "published_at": article.published_at.astimezone(SHANGHAI).strftime("%Y-%m-%d %H:%M CST"),
                    "summary": _escape_markdown(article.summary) if article.summary else None,
                    "is_fallback": article.is_fallback,
                }
            )
        sections.append({"label": CATEGORY_LABELS[category], "items": items})

    environment = Environment(
        loader=FileSystemLoader(TEMPLATE_ROOT),
        autoescape=False,
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    body = environment.get_template("issue.md.j2").render(
        target_date=issue.target_date.isoformat(),
        article_count=len(issue.articles),
        source_count=front_matter["source_count"],
        sections=sections,
    )
    yaml_text = yaml.safe_dump(front_matter, allow_unicode=True, sort_keys=False)
    return f"---\n{yaml_text}---\n\n{body.rstrip()}\n"


def parse_issue(path: Path) -> ParsedIssue:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise IssueError(f"{path}: cannot read issue") from error

    front_matter, body = _split_front_matter(path, text)
    target_date = _parse_date(path, front_matter.get("date"))
    try:
        path_date = date.fromisoformat(path.stem)
    except ValueError as error:
        raise IssueError(f"{path}: invalid issue filename") from error
    if path_date != target_date:
        raise IssueError(f"{path}: filename date does not match front matter")

    generated_at = _parse_datetime(path, front_matter.get("generated_at"))
    article_count = _non_negative_int(path, front_matter, "article_count")
    source_count = _non_negative_int(path, front_matter, "source_count")
    fallback_count = _non_negative_int(path, front_matter, "fallback_count")
    categories = _parse_categories(path, front_matter.get("categories"))
    fingerprint = front_matter.get("content_fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint:
        raise IssueError(f"{path}: invalid content_fingerprint")
    dedupe_index = _parse_dedupe_index(path, front_matter.get("dedupe_index"))

    return ParsedIssue(
        target_date=target_date,
        generated_at=generated_at,
        article_count=article_count,
        source_count=source_count,
        fallback_count=fallback_count,
        categories=categories,
        content_fingerprint=fingerprint,
        dedupe_index=dedupe_index,
        body=body,
        path=path,
    )


def _escape_markdown(value: str) -> str:
    return MARKDOWN_SPECIAL_RE.sub(r"\\\1", value)


def _split_front_matter(path: Path, text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise IssueError(f"{path}: missing YAML front matter")
    end = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.rstrip("\r\n") == "---"),
        None,
    )
    if end is None:
        raise IssueError(f"{path}: unterminated YAML front matter")
    try:
        value = yaml.safe_load("".join(lines[1:end]))
    except yaml.YAMLError as error:
        raise IssueError(f"{path}: invalid YAML front matter") from error
    if not isinstance(value, dict):
        raise IssueError(f"{path}: front matter must be a mapping")
    return value, "".join(lines[end + 1 :]).lstrip("\r\n")


def _parse_date(path: Path, value: object) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise IssueError(f"{path}: invalid date")


def _parse_datetime(path: Path, value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as error:
            raise IssueError(f"{path}: invalid generated_at") from error
    else:
        raise IssueError(f"{path}: invalid generated_at")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise IssueError(f"{path}: generated_at must be timezone-aware")
    return parsed


def _non_negative_int(path: Path, data: dict[str, Any], key: str) -> int:
    value = data.get(key)
    if type(value) is not int or value < 0:
        raise IssueError(f"{path}: invalid {key}")
    return value


def _parse_categories(path: Path, value: object) -> tuple[Category, ...]:
    if not isinstance(value, list):
        raise IssueError(f"{path}: invalid categories")
    try:
        categories = tuple(Category(item) for item in value if isinstance(item, str))
    except ValueError as error:
        raise IssueError(f"{path}: invalid categories") from error
    if len(categories) != len(value) or len(categories) != len(set(categories)):
        raise IssueError(f"{path}: invalid categories")
    return categories


def _parse_dedupe_index(path: Path, value: object) -> tuple[dict[str, str], ...]:
    if not isinstance(value, list):
        raise IssueError(f"{path}: invalid dedupe_index")
    rows: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise IssueError(f"{path}: invalid dedupe_index")
        row = {key: item.get(key) for key in ("id", "canonical_url", "title_key")}
        if not all(isinstance(field, str) for field in row.values()):
            raise IssueError(f"{path}: invalid dedupe_index")
        rows.append(row)  # type: ignore[arg-type]
    return tuple(rows)
