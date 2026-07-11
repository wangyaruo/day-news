from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from day_news.models import IssueSummary
from day_news.readme import END_MARKER, START_MARKER, ReadmeError, update_readme

BASE = f"# Header\n\nBefore\n{START_MARKER}\nold\n{END_MARKER}\nAfter\n"


def _summary(index: int) -> IssueSummary:
    issue_date = date(2026, 7, 10) - timedelta(days=index)
    return IssueSummary(
        target_date=issue_date,
        path=Path(issue_date.strftime("content/%Y/%m/%Y-%m-%d.md")),
        article_count=24 - index,
        source_count=8,
        generated_at=datetime(2026, 7, 11, 1, 0, tzinfo=UTC),
    )


def test_update_readme_changes_only_marker_contents_and_is_idempotent() -> None:
    summaries = [_summary(2), _summary(0), _summary(1)]

    updated = update_readme(BASE, summaries)

    assert updated.startswith(f"# Header\n\nBefore\n{START_MARKER}\n")
    assert updated.endswith(f"{END_MARKER}\nAfter\n")
    assert updated.index("2026-07-10") < updated.index("2026-07-09")
    assert "- [2026-07-10](content/2026/07/2026-07-10.md) · 24 条" in updated
    assert update_readme(updated, summaries) == updated


def test_update_readme_limits_recent_editions_to_ten() -> None:
    updated = update_readme(BASE, [_summary(index) for index in range(12)])
    assert updated.count("- [2026-") == 10
    assert "2026-06-29" not in updated


@pytest.mark.parametrize(
    "text",
    [
        "no markers",
        f"{START_MARKER}\n{START_MARKER}\n{END_MARKER}",
        f"{START_MARKER}\n{END_MARKER}\n{END_MARKER}",
        f"{END_MARKER}\n{START_MARKER}",
    ],
)
def test_update_readme_rejects_invalid_markers(text: str) -> None:
    with pytest.raises(ReadmeError):
        update_readme(text, [])
