from __future__ import annotations

import shutil
from collections import defaultdict
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from markdown_it import MarkdownIt

from day_news.feed import build_rss
from day_news.issue import parse_issue
from day_news.models import CATEGORY_LABELS, AppConfig, IssueSummary, ParsedIssue, SiteConfig

TEMPLATE_ROOT = Path(__file__).resolve().parents[2] / "templates"
ASSET_ROOT = Path(__file__).resolve().parents[2] / "assets"


def build_site(
    content_root: Path,
    output_root: Path,
    source_config: AppConfig,
    site_config: SiteConfig,
) -> None:
    if content_root.resolve() == output_root.resolve():
        raise ValueError("output_root must differ from content_root")
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True)

    issues = _discover_issues(content_root)
    summaries = tuple(
        IssueSummary(
            target_date=issue.target_date,
            path=issue.path,
            article_count=issue.article_count,
            source_count=issue.source_count,
            generated_at=issue.generated_at,
        )
        for issue in issues
    )
    route = _route_builder(site_config.base_path)
    environment = Environment(
        loader=FileSystemLoader(TEMPLATE_ROOT),
        autoescape=select_autoescape(("html", "xml"), default=True),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    environment.globals.update(route=route, site=site_config)
    markdown = MarkdownIt(
        "commonmark",
        {"html": False, "linkify": False, "typographer": False},
    )

    issue_rows = [
        {
            "date": issue.target_date,
            "url": route(f"issues/{issue.target_date.isoformat()}/"),
            "article_count": issue.article_count,
            "source_count": issue.source_count,
        }
        for issue in issues
    ]
    _render(
        environment,
        output_root / "index.html",
        "index.html.j2",
        page_title=site_config.title,
        latest=issue_rows[0] if issue_rows else None,
        recent=issue_rows[:10],
    )

    for index, issue in enumerate(issues):
        newer = issue_rows[index - 1] if index > 0 else None
        older = issue_rows[index + 1] if index + 1 < len(issue_rows) else None
        _render(
            environment,
            output_root / f"issues/{issue.target_date.isoformat()}/index.html",
            "issue.html.j2",
            page_title=f"{site_config.title} · {issue.target_date.isoformat()}",
            issue=issue,
            issue_html=markdown.render(issue.body),
            newer=newer,
            older=older,
        )

    months: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
    for row in issue_rows:
        months[row["date"].strftime("%Y-%m")].append(row)
    month_rows = [
        {
            "month": month,
            "url": route(f"archive/{month}/"),
            "issues": rows,
        }
        for month, rows in sorted(months.items(), reverse=True)
    ]
    _render(
        environment,
        output_root / "archive/index.html",
        "archive.html.j2",
        page_title=f"归档 · {site_config.title}",
        months=month_rows,
    )
    for month in month_rows:
        _render(
            environment,
            output_root / f"archive/{month['month']}/index.html",
            "month.html.j2",
            page_title=f"{month['month']} · {site_config.title}",
            month=month,
        )

    enabled_sources = [
        {
            "name": source.name,
            "url": source.url,
            "category": CATEGORY_LABELS[source.category],
            "language": source.language,
        }
        for source in source_config.sources
        if source.enabled
    ]
    _render(
        environment,
        output_root / "sources/index.html",
        "sources.html.j2",
        page_title=f"新闻源 · {site_config.title}",
        sources=enabled_sources,
    )
    _render(
        environment,
        output_root / "about/index.html",
        "about.html.j2",
        page_title=f"关于 · {site_config.title}",
    )

    asset_output = output_root / "assets/styles.css"
    asset_output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ASSET_ROOT / "styles.css", asset_output)
    (output_root / "rss.xml").write_bytes(build_rss(summaries, site_config))


def _discover_issues(content_root: Path) -> list[ParsedIssue]:
    if not content_root.exists():
        return []
    issues = [parse_issue(path) for path in sorted(content_root.rglob("*.md"))]
    return sorted(issues, key=lambda issue: issue.target_date, reverse=True)


def _route_builder(base_path: str):
    def route(path: str = "") -> str:
        return base_path + path.lstrip("/")

    return route


def _render(
    environment: Environment,
    path: Path,
    template_name: str,
    **context: object,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = environment.get_template(template_name).render(**context).rstrip() + "\n"
    path.write_text(rendered, encoding="utf-8", newline="\n")
