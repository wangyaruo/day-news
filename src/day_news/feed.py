from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from email.utils import format_datetime
from xml.etree import ElementTree

from day_news.models import IssueSummary, SiteConfig


def build_rss(
    issues: Sequence[IssueSummary],
    site_config: SiteConfig,
) -> bytes:
    latest = sorted(
        issues,
        key=lambda issue: (issue.target_date, issue.generated_at, issue.path.as_posix()),
        reverse=True,
    )[:30]

    rss = ElementTree.Element("rss", {"version": "2.0"})
    channel = ElementTree.SubElement(rss, "channel")
    ElementTree.SubElement(channel, "title").text = site_config.title
    ElementTree.SubElement(channel, "link").text = site_config.site_url
    ElementTree.SubElement(channel, "description").text = site_config.description
    ElementTree.SubElement(channel, "language").text = site_config.language

    if latest:
        ElementTree.SubElement(channel, "lastBuildDate").text = _rss_date(latest[0].generated_at)

    for issue in latest:
        issue_url = f"{site_config.site_url}issues/{issue.target_date.isoformat()}/"
        item = ElementTree.SubElement(channel, "item")
        ElementTree.SubElement(item, "title").text = f"{site_config.title} · {issue.target_date.isoformat()}"
        ElementTree.SubElement(item, "link").text = issue_url
        ElementTree.SubElement(item, "guid", {"isPermaLink": "true"}).text = issue_url
        ElementTree.SubElement(item, "pubDate").text = _rss_date(issue.generated_at)
        ElementTree.SubElement(item, "description").text = f"{issue.article_count} 条新闻，{issue.source_count} 个来源"

    ElementTree.indent(rss, space="  ")
    return ElementTree.tostring(rss, encoding="utf-8", xml_declaration=True) + b"\n"


def _rss_date(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("RSS dates must be timezone-aware")
    return format_datetime(value.astimezone(UTC), usegmt=True)
