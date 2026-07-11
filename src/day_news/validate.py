from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlsplit

import feedparser
from bs4 import BeautifulSoup

from day_news.issue import IssueError, parse_issue
from day_news.models import SiteConfig


def validate_content(content_root: Path) -> tuple[str, ...]:
    errors: list[str] = []
    seen_dates: dict[object, Path] = {}
    if not content_root.exists():
        return ()
    for path in sorted(content_root.rglob("*.md")):
        try:
            issue = parse_issue(path)
        except IssueError as error:
            errors.append(str(error))
            continue
        previous = seen_dates.get(issue.target_date)
        if previous is not None:
            errors.append(f"{path}: duplicate date also found in {previous}")
        else:
            seen_dates[issue.target_date] = path
    return tuple(errors)


def validate_site(output_root: Path, site_config: SiteConfig) -> tuple[str, ...]:
    errors: list[str] = []
    root = output_root.resolve()
    for html_path in sorted(output_root.rglob("*.html")) if output_root.exists() else ():
        soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")
        for tag in soup.find_all(True):
            for attribute in ("href", "src"):
                value = tag.get(attribute)
                if isinstance(value, str):
                    error = _validate_link(value, html_path, root, site_config.base_path)
                    if error is not None:
                        errors.append(error)

    rss_path = output_root / "rss.xml"
    if not rss_path.exists():
        errors.append(f"{rss_path}: missing RSS feed")
    else:
        parsed = feedparser.parse(rss_path.read_bytes())
        if parsed.bozo:
            errors.append(f"{rss_path}: invalid RSS: {parsed.bozo_exception}")
    return tuple(errors)


def _validate_link(
    value: str,
    origin: Path,
    output_root: Path,
    base_path: str,
) -> str | None:
    if not value or value.startswith("#"):
        return None
    parsed = urlsplit(value)
    if parsed.scheme in {"http", "https", "mailto"} or parsed.netloc:
        return None
    if parsed.scheme:
        return f"{origin}: unsupported link scheme: {value}"

    decoded_path = unquote(parsed.path)
    if not decoded_path.startswith(base_path):
        return f"{origin}: local link escapes base path: {value}"
    relative = decoded_path[len(base_path) :]
    if ".." in Path(relative).parts:
        return f"{origin}: local link traverses outside site: {value}"

    if not relative or decoded_path.endswith("/"):
        relative = f"{relative.rstrip('/')}/index.html" if relative else "index.html"
    target = (output_root / relative).resolve()
    try:
        target.relative_to(output_root)
    except ValueError:
        return f"{origin}: local link traverses outside site: {value}"
    if not target.exists():
        return f"{origin}: missing local target {value} -> {target}"
    return None
