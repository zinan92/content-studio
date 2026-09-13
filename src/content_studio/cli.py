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
from .accounts import (
    AccountError,
    ContentDownloaderClient,
    PLATFORM_DOUYIN,
    add_account,
    auto_enqueue_outliers,
    sync_account,
)
from .pipeline import DEFAULT_GLOSSARY_PATH, PipelineError, run_pipeline
from .store import DEFAULT_STORE_PATH, StoreError, StudioStore
from .structure import ReportError


DEFAULT_COOKIE_PATH = Path("~/.config/content-studio/douyin-cookies.json")
DEFAULT_DB_PATH = Path("~/.config/content-studio/data/creator-metrics.sqlite3")
DEFAULT_DATA_DIR = Path("~/.config/content-studio")
DEFAULT_REPORTS_DIR = DEFAULT_DATA_DIR / "studio"
DEFAULT_DOWNLOADS_DIR = DEFAULT_DATA_DIR / "downloads"
DEFAULT_PORT = 8765
PLIST_LABEL = "com.park.content-studio.daily-sync"


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
    pipeline = commands.add_parser(
        "pipeline",
        help="run Douyin links through download, transcription, structure, and report",
    )
    pipeline.add_argument("--url", dest="urls", action="append", required=True)
    pipeline.add_argument("--cookies", type=Path, default=DEFAULT_COOKIE_PATH)
    pipeline.add_argument("--data-dir", type=Path, default=Path("~/.config/content-studio"))
    pipeline.add_argument("--downloads-dir", type=Path, default=None)
    pipeline.add_argument("--whisper-model", default="turbo")
    pipeline.add_argument("--creator-db", type=Path, default=DEFAULT_DB_PATH)
    pipeline.add_argument("--glossary", type=Path, default=DEFAULT_GLOSSARY_PATH)
    add = commands.add_parser("add-account", help="add a creator profile link to the library")
    add.add_argument("url")
    add.add_argument("--self", dest="is_self", action="store_true", help="mark as Park's own account")
    add.add_argument("--store", type=Path, default=DEFAULT_STORE_PATH)
    add.add_argument("--cookies", type=Path, default=DEFAULT_COOKIE_PATH)

    sync_all = commands.add_parser(
        "sync", help="one serial pass: sync every Douyin account, creator metrics, and queue breakouts"
    )
    sync_all.add_argument("--store", type=Path, default=DEFAULT_STORE_PATH)
    sync_all.add_argument("--cookies", type=Path, default=DEFAULT_COOKIE_PATH)
    sync_all.add_argument("--creator-db", type=Path, default=DEFAULT_DB_PATH)
    sync_all.add_argument("--no-enqueue", action="store_true")

    work = commands.add_parser("work", help="process queued teardown jobs and exit")
    work.add_argument("--store", type=Path, default=DEFAULT_STORE_PATH)
    work.add_argument("--cookies", type=Path, default=DEFAULT_COOKIE_PATH)
    work.add_argument("--creator-db", type=Path, default=DEFAULT_DB_PATH)
    work.add_argument("--data-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    work.add_argument("--downloads-dir", type=Path, default=DEFAULT_DOWNLOADS_DIR)
    work.add_argument("--max-jobs", type=int, default=None)

    serve = commands.add_parser("serve", help="start the local web app on 127.0.0.1")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument("--store", type=Path, default=DEFAULT_STORE_PATH)
    serve.add_argument("--cookies", type=Path, default=DEFAULT_COOKIE_PATH)
    serve.add_argument("--creator-db", type=Path, default=DEFAULT_DB_PATH)
    serve.add_argument("--data-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    serve.add_argument("--downloads-dir", type=Path, default=DEFAULT_DOWNLOADS_DIR)

    plist = commands.add_parser(
        "write-schedule", help="write (but do not load) a launchd plist for a daily sync"
    )
    plist.add_argument("--hour", type=int, default=9)
    plist.add_argument("--minute", type=int, default=30)
    plist.add_argument("--output", type=Path, default=DEFAULT_DATA_DIR / f"{PLIST_LABEL}.plist")
    return parser


def _cookie_client_factory(cookie_path: Path):
    cookies = load_cookie_file(cookie_path)
    return lambda: ContentDownloaderClient(cookies)


def run_add_account(args: argparse.Namespace) -> int:
    with _open_store(args.store) as store:
        factory = None
        if "douyin.com" in args.url and "/user/" not in args.url:
            factory = _cookie_client_factory(args.cookies)
        account = add_account(store, args.url, client_factory=factory, is_self=args.is_self)
    print(json.dumps({"status": "ok", "account": account}, ensure_ascii=False))
    return 0


def sync_everything(store: StudioStore, *, cookie_path: Path, creator_db: Path, enqueue: bool = True) -> dict:
    """One pass over every Douyin account. Stops the whole pass on risk control."""
    from .accounts import RiskControlStop

    factory = _cookie_client_factory(cookie_path)
    summary: dict = {"accounts": [], "creator_metrics": None, "enqueued": 0}
    for account in store.accounts():
        if account["platform"] != PLATFORM_DOUYIN:
            continue
        try:
            result = sync_account(store, account["id"], client_factory=factory)
            summary["accounts"].append({"id": account["id"], "status": "ok", "videos": result["video_count"]})
        except RiskControlStop as exc:
            summary["accounts"].append({"id": account["id"], "status": "stopped", "error": str(exc)})
            summary["stopped"] = str(exc)
            return summary
        except AccountError as exc:
            summary["accounts"].append({"id": account["id"], "status": "failed", "error": str(exc)})
    if store.self_account() is not None:
        try:
            cookies = load_cookie_file(cookie_path)
            headers = {"Referer": CREATOR_MANAGE_URL, "User-Agent": DEFAULT_USER_AGENT}
            with httpx.Client(cookies=cookies, headers=headers, follow_redirects=True, timeout=30.0) as client:
                with CreatorMetricsStore(creator_db) as metrics_store:
                    result = CreatorMetricsSyncer(client=client, store=metrics_store).sync(days=90, delay_seconds=1.5)
            summary["creator_metrics"] = {"status": "ok", **result.__dict__}
        except CreatorMetricsError as exc:
            summary["creator_metrics"] = {"status": "failed", "error": str(exc)}
    if enqueue:
        summary["enqueued"] = len(auto_enqueue_outliers(store))
    return summary


def run_sync(args: argparse.Namespace) -> int:
    with _open_store(args.store) as store:
        summary = sync_everything(
            store, cookie_path=args.cookies, creator_db=args.creator_db, enqueue=not args.no_enqueue
        )
    print(json.dumps(summary, ensure_ascii=False))
    return 1 if summary.get("stopped") else 0


def run_work(args: argparse.Namespace) -> int:
    from .worker import TeardownWorker, WorkerConfig

    with _open_store(args.store) as store:
        store.recover_interrupted_jobs()
        worker = TeardownWorker(
            store,
            WorkerConfig(
                cookie_path=args.cookies,
                data_dir=args.data_dir,
                downloads_dir=args.downloads_dir,
                creator_db=args.creator_db,
            ),
        )
        processed = worker.drain(args.max_jobs)
    print(json.dumps({"status": "ok", "processed": processed}, ensure_ascii=False))
    return 0


def run_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .web import create_app

    app = create_app(
        store_path=args.store,
        cookie_path=args.cookies,
        creator_db=args.creator_db,
        data_dir=args.data_dir,
        downloads_dir=args.downloads_dir,
    )
    print(f"内容拆解台已启动：http://127.0.0.1:{args.port}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


def run_write_schedule(args: argparse.Namespace) -> int:
    output = args.output.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    repo = Path(__file__).resolve().parents[2]
    log_dir = DEFAULT_DATA_DIR.expanduser() / "logs"
    output.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{PLIST_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{sys.executable}</string><string>-m</string><string>content_studio</string><string>sync</string>
  </array>
  <key>WorkingDirectory</key><string>{repo}</string>
  <key>EnvironmentVariables</key><dict><key>PYTHONPATH</key><string>{repo / "src"}</string></dict>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>{args.hour}</integer><key>Minute</key><integer>{args.minute}</integer></dict>
  <key>StandardOutPath</key><string>{log_dir / "daily-sync.log"}</string>
  <key>StandardErrorPath</key><string>{log_dir / "daily-sync.log"}</string>
</dict>
</plist>
""",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "written_not_loaded",
                "plist": str(output),
                "enable": f"mkdir -p {log_dir} && cp {output} ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/{PLIST_LABEL}.plist",
                "disable": f"launchctl unload ~/Library/LaunchAgents/{PLIST_LABEL}.plist && rm ~/Library/LaunchAgents/{PLIST_LABEL}.plist",
            },
            ensure_ascii=False,
        )
    )
    return 0


class _open_store:
    def __init__(self, path: Path) -> None:
        self.path = path

    def __enter__(self) -> StudioStore:
        self.store = StudioStore(self.path)
        return self.store

    def __exit__(self, *_: object) -> None:
        self.store.close()


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


def run_pipeline_command(args: argparse.Namespace) -> int:
    receipt = run_pipeline(
        args.urls,
        cookie_path=args.cookies,
        data_dir=args.data_dir,
        downloads_dir=args.downloads_dir,
        whisper_model=args.whisper_model,
        creator_db=args.creator_db,
        glossary_path=args.glossary,
    )
    print(json.dumps(receipt, ensure_ascii=False))
    return 0 if receipt["status"] == "ok" else 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "creator-sync":
            return run_creator_sync(args)
        if args.command == "pipeline":
            return run_pipeline_command(args)
        handlers = {
            "add-account": run_add_account,
            "sync": run_sync,
            "work": run_work,
            "serve": run_serve,
            "write-schedule": run_write_schedule,
        }
        if args.command in handlers:
            return handlers[args.command](args)
    except (CreatorMetricsError, PipelineError, ReportError, AccountError, StoreError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
