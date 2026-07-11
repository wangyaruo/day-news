from __future__ import annotations

from datetime import date
from pathlib import Path

from day_news.site import build_site
from day_news.validate import validate_content, validate_site
from tests.test_site import site_config, source_config, write_issue


def test_valid_content_and_site_pass_offline_validation(tmp_path: Path) -> None:
    content = tmp_path / "content"
    output = tmp_path / "dist"
    write_issue(content, date(2026, 7, 10))
    build_site(content, output, source_config(), site_config())

    assert validate_content(content) == ()
    assert validate_site(output, site_config()) == ()


def test_broken_internal_link_reports_origin_and_target(tmp_path: Path) -> None:
    content = tmp_path / "content"
    output = tmp_path / "dist"
    write_issue(content, date(2026, 7, 10))
    build_site(content, output, source_config(), site_config())
    index = output / "index.html"
    index.write_text(
        index.read_text(encoding="utf-8").replace(
            "</main>",
            '<a href="/day-news/missing/">missing</a></main>',
        ),
        encoding="utf-8",
    )

    errors = validate_site(output, site_config())
    assert any("index.html" in error and "missing" in error for error in errors)


def test_rejects_local_links_that_escape_base_path(tmp_path: Path) -> None:
    content = tmp_path / "content"
    output = tmp_path / "dist"
    write_issue(content, date(2026, 7, 10))
    build_site(content, output, source_config(), site_config())
    index = output / "index.html"
    index.write_text(
        index.read_text(encoding="utf-8").replace(
            "</main>",
            '<img src="/outside/image.png"></main>',
        ),
        encoding="utf-8",
    )

    errors = validate_site(output, site_config())
    assert any("escapes base path" in error for error in errors)


def test_validate_content_reports_malformed_issue(tmp_path: Path) -> None:
    path = tmp_path / "content/2026/07/2026-07-10.md"
    path.parent.mkdir(parents=True)
    path.write_text("broken", encoding="utf-8")
    errors = validate_content(tmp_path / "content")
    assert len(errors) == 1
    assert "2026-07-10.md" in errors[0]
