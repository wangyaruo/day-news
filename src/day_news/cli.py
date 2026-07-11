from __future__ import annotations

import argparse
import asyncio
import re
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path

import httpx

from day_news.config import ConfigError, load_config, load_site_config
from day_news.generate import generate_issue
from day_news.models import GenerationStatus
from day_news.site import build_site
from day_news.time_window import resolve_target_date
from day_news.validate import validate_content, validate_site

USER_AGENT = "wangyaruo/day-news (+https://github.com/wangyaruo/day-news)"


class CliInputError(ValueError):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CliInputError(message)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _build_parser().parse_args(argv)
        if args.command == "target-date":
            print(resolve_target_date(_now(), explicit=None).isoformat())
            return 0
        if args.command == "generate":
            return _generate_command(args)
        if args.command == "build":
            return _build_command(args)
        if args.command == "validate":
            return _validate_command(args)
        raise CliInputError("missing command")
    except (CliInputError, ConfigError) as error:
        print(f"输入或配置错误：{error}", file=sys.stderr)
        return 2
    except Exception as error:
        print(f"执行失败：{error}", file=sys.stderr)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="day-news")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("target-date")

    generate = subcommands.add_parser("generate")
    generate.add_argument("--date", type=_date_value)
    generate.add_argument("--force", action="store_true")
    generate.add_argument("--report", type=Path)
    generate.add_argument("--content", type=Path, default=Path("content"))
    generate.add_argument("--readme", type=Path, default=Path("README.md"))
    generate.add_argument("--config", type=Path, default=Path("config/sources.toml"))

    build = subcommands.add_parser("build")
    build.add_argument("--content", type=Path, default=Path("content"))
    build.add_argument("--output", type=Path, default=Path("dist"))
    build.add_argument("--sources-config", type=Path, default=Path("config/sources.toml"))
    build.add_argument("--config", type=Path, default=Path("config/site.toml"))

    validate = subcommands.add_parser("validate")
    validate.add_argument("--content", type=Path, default=Path("content"))
    validate.add_argument("--site", type=Path, default=Path("dist"))
    validate.add_argument("--sources-config", type=Path, default=Path("config/sources.toml"))
    validate.add_argument("--config", type=Path, default=Path("config/site.toml"))
    return parser


def _date_value(value: str) -> date:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from error


def _generate_command(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    target_date = resolve_target_date(_now(), explicit=args.date)
    report_path = args.report or Path(f"build/reports/{target_date.isoformat()}.json")

    async def run():
        async with httpx.AsyncClient(headers={"user-agent": USER_AGENT}) as client:
            return await generate_issue(
                target_date,
                config=config,
                content_root=args.content,
                readme_path=args.readme,
                report_path=report_path,
                generated_at=_now(),
                client=client,
                force=args.force,
            )

    result = asyncio.run(run())
    if result.status is GenerationStatus.FAILED_THRESHOLD:
        print(f"未达到发布门槛：{target_date}", file=sys.stderr)
        return 3
    print(f"日刊状态：{result.status.value} · {target_date}")
    return 0


def _build_command(args: argparse.Namespace) -> int:
    sources = load_config(args.sources_config)
    site = load_site_config(args.config)
    build_site(args.content, args.output, sources, site)
    print(f"网站已构建：{args.output}")
    return 0


def _validate_command(args: argparse.Namespace) -> int:
    load_config(args.sources_config)
    site = load_site_config(args.config)
    errors = (*validate_content(args.content), *validate_site(args.site, site))
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("校验通过")
    return 0


def _now() -> datetime:
    return datetime.now(UTC)
