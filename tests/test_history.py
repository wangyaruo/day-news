from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from day_news.history import HistoryError, load_history


def _write_issue(root: Path, issue_date: date, front_matter: str) -> Path:
    path = root / issue_date.strftime("%Y/%m/%Y-%m-%d.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{front_matter}\n---\n\nBody\n", encoding="utf-8")
    return path


def _dedupe_row(value: str) -> str:
    return (
        f"dedupe_index:\n  - id: {value}\n    canonical_url: https://example.com/{value}\n    title_key: title {value}"
    )


def test_load_history_date_boundaries_and_exact_values(tmp_path: Path) -> None:
    target = date(2026, 7, 10)
    _write_issue(tmp_path, target - timedelta(days=1), _dedupe_row("day-1"))
    _write_issue(tmp_path, target - timedelta(days=30), _dedupe_row("day-30"))
    _write_issue(tmp_path, target - timedelta(days=31), _dedupe_row("day-31"))
    _write_issue(tmp_path, target, _dedupe_row("target"))

    history = load_history(tmp_path, target, days=30)

    assert history.ids == frozenset({"day-1", "day-30"})
    assert history.canonical_urls == frozenset({"https://example.com/day-1", "https://example.com/day-30"})
    assert history.title_keys == frozenset({"title day-1", "title day-30"})


@pytest.mark.parametrize(
    "content",
    [
        "not front matter",
        "---\ndedupe_index: [\n---\n",
        "---\ndedupe_index: nope\n---\n",
        "---\ndedupe_index:\n  - id: abc\n    canonical_url: 7\n    title_key: title\n---\n",
        "---\ndate: 2026-07-09\n---\n",
    ],
)
def test_present_malformed_issue_raises_history_error(tmp_path: Path, content: str) -> None:
    target = date(2026, 7, 10)
    path = tmp_path / "2026/07/2026-07-09.md"
    path.parent.mkdir(parents=True)
    path.write_text(content, encoding="utf-8")

    with pytest.raises(HistoryError, match="2026-07-09.md"):
        load_history(tmp_path, target)
