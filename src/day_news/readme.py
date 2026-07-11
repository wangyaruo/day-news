from __future__ import annotations

from collections.abc import Sequence

from day_news.models import IssueSummary

START_MARKER = "<!-- DAY_NEWS_RECENT_START -->"
END_MARKER = "<!-- DAY_NEWS_RECENT_END -->"


class ReadmeError(ValueError):
    pass


def update_readme(text: str, summaries: Sequence[IssueSummary]) -> str:
    if text.count(START_MARKER) != 1 or text.count(END_MARKER) != 1:
        raise ReadmeError("README must contain exactly one recent-editions marker pair")
    start = text.index(START_MARKER)
    end = text.index(END_MARKER)
    if end < start:
        raise ReadmeError("README recent-editions markers are reversed")

    recent = sorted(summaries, key=lambda summary: summary.target_date, reverse=True)[:10]
    lines = [
        f"- [{summary.target_date.isoformat()}]({summary.path.as_posix()}) · {summary.article_count} 条"
        for summary in recent
    ]
    contents = "\n".join(lines)
    replacement = START_MARKER + "\n"
    if contents:
        replacement += contents + "\n"
    replacement += END_MARKER
    return text[:start] + replacement + text[end + len(END_MARKER) :]
