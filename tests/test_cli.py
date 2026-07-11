from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from day_news.cli import main
from day_news.config import ConfigError
from day_news.models import GenerationResult, GenerationStatus


def test_target_date_uses_shanghai_previous_day(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "day_news.cli._now",
        lambda: datetime(2026, 7, 11, 1, 0, tzinfo=UTC),
    )
    assert main(["target-date"]) == 0
    assert capsys.readouterr().out.strip() == "2026-07-10"


def test_invalid_date_returns_exit_two(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["generate", "--date", "not-a-date"]) == 2
    assert "YYYY-MM-DD" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (GenerationStatus.CREATED, 0),
        (GenerationStatus.UPDATED, 0),
        (GenerationStatus.UNCHANGED, 0),
        (GenerationStatus.SKIPPED_EXISTS, 0),
        (GenerationStatus.FAILED_THRESHOLD, 3),
    ],
)
def test_generate_maps_result_status_to_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: GenerationStatus,
    expected: int,
) -> None:
    async def fake_generate(target_date: date, **kwargs: object) -> GenerationResult:
        report_path = kwargs["report_path"]
        assert isinstance(report_path, Path)
        return GenerationResult(status, target_date, None, report_path)

    monkeypatch.setattr("day_news.cli.generate_issue", fake_generate)
    exit_code = main(
        [
            "generate",
            "--date",
            "2026-07-10",
            "--content",
            str(tmp_path / "content"),
            "--readme",
            str(tmp_path / "README.md"),
            "--report",
            str(tmp_path / "report.json"),
        ]
    )
    assert exit_code == expected


def test_configuration_error_returns_two(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_config(path: Path):
        raise ConfigError("bad config")

    monkeypatch.setattr("day_news.cli.load_config", fail_config)
    assert main(["generate", "--date", "2026-07-10"]) == 2


def test_build_and_validate_commands(tmp_path: Path) -> None:
    output = tmp_path / "dist"
    assert main(["build", "--content", str(tmp_path / "content"), "--output", str(output)]) == 0
    assert (output / "index.html").exists()
    assert main(["validate", "--content", str(tmp_path / "content"), "--site", str(output)]) == 0
    (output / "rss.xml").unlink()
    assert main(["validate", "--content", str(tmp_path / "content"), "--site", str(output)]) == 1


def test_unexpected_error_returns_one(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_build(*args: object, **kwargs: object) -> None:
        raise RuntimeError("unexpected")

    monkeypatch.setattr("day_news.cli.build_site", fail_build)
    assert main(["build"]) == 1
