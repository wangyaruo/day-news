from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import yaml

from day_news.models import HistoryIndex


class HistoryError(ValueError):
    pass


def load_history(
    content_root: Path,
    target_date: date,
    days: int = 30,
) -> HistoryIndex:
    if days < 1:
        raise ValueError("days must be at least 1")

    ids: set[str] = set()
    canonical_urls: set[str] = set()
    title_keys: set[str] = set()

    for offset in range(1, days + 1):
        issue_date = target_date - timedelta(days=offset)
        path = content_root / issue_date.strftime("%Y/%m/%Y-%m-%d.md")
        if not path.exists():
            continue
        rows = _read_dedupe_rows(path)
        for row in rows:
            ids.add(row["id"])
            canonical_urls.add(row["canonical_url"])
            title_keys.add(row["title_key"])

    return HistoryIndex(
        ids=frozenset(ids),
        canonical_urls=frozenset(canonical_urls),
        title_keys=frozenset(title_keys),
    )


def _read_dedupe_rows(path: Path) -> list[dict[str, str]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise HistoryError(f"{path}: cannot read edition") from error

    if not lines or lines[0] != "---":
        raise HistoryError(f"{path}: missing YAML front matter")
    try:
        end = lines.index("---", 1)
    except ValueError as error:
        raise HistoryError(f"{path}: unterminated YAML front matter") from error

    try:
        front_matter = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError as error:
        raise HistoryError(f"{path}: invalid YAML front matter") from error
    if not isinstance(front_matter, dict):
        raise HistoryError(f"{path}: front matter must be a mapping")

    raw_rows = front_matter.get("dedupe_index")
    if not isinstance(raw_rows, list):
        raise HistoryError(f"{path}: dedupe_index must be a list")

    rows: list[dict[str, str]] = []
    for position, raw_row in enumerate(raw_rows):
        if not isinstance(raw_row, dict):
            raise HistoryError(f"{path}: invalid dedupe_index row {position}")
        values = {key: raw_row.get(key) for key in ("id", "canonical_url", "title_key")}
        if not all(isinstance(value, str) for value in values.values()):
            raise HistoryError(f"{path}: invalid dedupe_index row {position}")
        rows.append(values)  # type: ignore[arg-type]
    return rows
