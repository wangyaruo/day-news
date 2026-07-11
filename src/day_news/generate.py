from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path

import httpx

from day_news.dedupe import deduplicate
from day_news.fetchers import FETCHERS, Fetcher, fetch_all
from day_news.history import load_history
from day_news.issue import content_fingerprint, parse_issue, render_issue
from day_news.models import (
    AppConfig,
    GenerationResult,
    GenerationStatus,
    Issue,
    IssueSummary,
    RunReport,
    SourceKind,
)
from day_news.normalize import normalize_entry
from day_news.readme import update_readme
from day_news.select import select_articles
from day_news.time_window import build_window


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
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")

    content_path = content_root / target_date.strftime("%Y/%m/%Y-%m-%d.md")
    report = RunReport(target_date=target_date.isoformat())
    existing = parse_issue(content_path) if content_path.exists() else None

    if existing is not None and not force:
        report.status = GenerationStatus.SKIPPED_EXISTS.value
        _atomic_write_json(report_path, report.to_dict())
        return GenerationResult(
            status=GenerationStatus.SKIPPED_EXISTS,
            target_date=target_date,
            content_path=content_path,
            report_path=report_path,
        )

    batch = await fetch_all(config.sources, client, registry=registry)
    report.successful_sources.extend(batch.successful_sources)
    report.failed_sources.update(batch.failed_sources)
    report.fetched_count = len(batch.entries)

    window = build_window(target_date)
    normalized = []
    for source, raw_entry in batch.entries:
        article = normalize_entry(
            raw_entry,
            source,
            fetched_at=generated_at,
            window=window,
            summary_limit=config.policy.summary_limit,
        )
        if article is not None:
            normalized.append(article)
    report.window_count = len(normalized)

    history = load_history(
        content_root,
        target_date,
        days=config.policy.history_days,
    )
    dedupe_result = deduplicate(
        normalized,
        history,
        similarity_threshold=config.policy.similarity_threshold,
    )
    report.duplicate_count = sum(dedupe_result.removed_by_reason.values())
    selection = select_articles(dedupe_result.articles, config.sources, config.policy)
    report.selected_count = len(selection.articles)
    report.fallback_count = sum(article.is_fallback for article in selection.articles)

    if not selection.valid:
        report.status = GenerationStatus.FAILED_THRESHOLD.value
        report.failure_reason = selection.failure_reason
        _atomic_write_json(report_path, report.to_dict())
        return GenerationResult(
            status=GenerationStatus.FAILED_THRESHOLD,
            target_date=target_date,
            content_path=None,
            report_path=report_path,
        )

    issue = Issue(
        target_date=target_date,
        generated_at=generated_at,
        articles=selection.articles,
    )
    rendered = render_issue(issue)
    new_fingerprint = content_fingerprint(target_date, selection.articles)
    summaries = _issue_summaries(
        content_root,
        content_path,
        readme_path,
        IssueSummary(
            target_date=target_date,
            path=_relative_link(content_path, readme_path.parent),
            article_count=len(selection.articles),
            source_count=len({article.publisher_id for article in selection.articles}),
            generated_at=generated_at,
        ),
    )
    readme_text = readme_path.read_text(encoding="utf-8")
    updated_readme = update_readme(readme_text, summaries)

    if existing is not None and existing.content_fingerprint == new_fingerprint:
        report.status = GenerationStatus.UNCHANGED.value
        _atomic_write_json(report_path, report.to_dict())
        return GenerationResult(
            status=GenerationStatus.UNCHANGED,
            target_date=target_date,
            content_path=content_path,
            report_path=report_path,
        )

    _atomic_write_many(
        {
            content_path: rendered,
            readme_path: updated_readme,
        }
    )
    status = GenerationStatus.UPDATED if existing is not None else GenerationStatus.CREATED
    report.status = status.value
    _atomic_write_json(report_path, report.to_dict())
    return GenerationResult(
        status=status,
        target_date=target_date,
        content_path=content_path,
        report_path=report_path,
    )


def _issue_summaries(
    content_root: Path,
    target_path: Path,
    readme_path: Path,
    new_summary: IssueSummary,
) -> tuple[IssueSummary, ...]:
    summaries: list[IssueSummary] = []
    paths = sorted(content_root.rglob("*.md")) if content_root.exists() else ()
    for path in paths:
        if path == target_path:
            continue
        parsed = parse_issue(path)
        summaries.append(
            IssueSummary(
                target_date=parsed.target_date,
                path=_relative_link(path, readme_path.parent),
                article_count=parsed.article_count,
                source_count=parsed.source_count,
                generated_at=parsed.generated_at,
            )
        )
    summaries.append(new_summary)
    return tuple(summaries)


def _relative_link(path: Path, root: Path) -> Path:
    try:
        return path.relative_to(root)
    except ValueError:
        return path


def _atomic_write_text(path: Path, text: str) -> None:
    _atomic_write_many({path: text})


def _atomic_write_json(path: Path, value: object) -> None:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    _atomic_write_text(path, text)


def _atomic_write_many(values: Mapping[Path, str]) -> None:
    staged: list[tuple[Path, Path]] = []
    try:
        for destination, text in values.items():
            destination.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{destination.name}.",
                suffix=".tmp",
                dir=destination.parent,
            )
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(text)
                    handle.flush()
                    os.fsync(handle.fileno())
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
            staged.append((temporary, destination))

        for temporary, destination in staged:
            os.replace(temporary, destination)
    finally:
        for temporary, _destination in staged:
            temporary.unlink(missing_ok=True)
