from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import httpx

from .creator_metrics import (
    CREATOR_MANAGE_URL,
    CreatorMetricsError,
    CreatorMetricsStore,
    CreatorMetricsSyncer,
    DEFAULT_USER_AGENT,
    load_cookie_file,
)


DEFAULT_COOKIE_PATH = Path("~/.config/content-studio/douyin-cookies.json")
DEFAULT_DB_PATH = Path("~/.config/content-studio/data/creator-metrics.sqlite3")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="content-studio")
    commands = parser.add_subparsers(dest="command", required=True)
    sync = commands.add_parser(
        "creator-sync",
        help="manually snapshot creator.douyin.com work metrics for the last 90 days",
    )
    sync.add_argument("--cookies", type=Path, default=DEFAULT_COOKIE_PATH)
    sync.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    sync.add_argument("--days", type=int, default=90)
    sync.add_argument("--delay-seconds", type=float, default=1.0)
    sync.add_argument("--page-size", type=int, default=12)
    return parser


def run_creator_sync(args: argparse.Namespace) -> int:
    cookie_path = args.cookies.expanduser().resolve()
    repo_root = Path.cwd().resolve()
    try:
        cookie_path.relative_to(repo_root)
    except ValueError:
        pass
    else:
        raise CreatorMetricsError("cookies must be stored outside the content-studio repository")

    cookies = load_cookie_file(cookie_path)
    headers = {"Referer": CREATOR_MANAGE_URL, "User-Agent": DEFAULT_USER_AGENT}
    with httpx.Client(cookies=cookies, headers=headers, follow_redirects=True, timeout=30.0) as client:
        with CreatorMetricsStore(args.db) as store:
            summary = CreatorMetricsSyncer(client=client, store=store).sync(
                days=args.days,
                delay_seconds=args.delay_seconds,
                page_size=args.page_size,
            )
    print(json.dumps({"status": "ok", **summary.__dict__}, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "creator-sync":
            return run_creator_sync(args)
    except (CreatorMetricsError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
