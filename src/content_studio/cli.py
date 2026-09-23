from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys

import httpx

from .paths import config_dir
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
    auto_enqueue_new_posts,
    auto_enqueue_outliers,
    sync_account,
)
from .pipeline import DEFAULT_GLOSSARY_PATH, PipelineError, run_pipeline
from .store import DEFAULT_STORE_PATH, StoreError, StudioStore
from .structure import ReportError


DEFAULT_COOKIE_PATH = config_dir() / "douyin-cookies.json"
DEFAULT_DB_PATH = config_dir() / "data/creator-metrics.sqlite3"
DEFAULT_DATA_DIR = config_dir()
DEFAULT_REPORTS_DIR = DEFAULT_DATA_DIR / "studio"
DEFAULT_DOWNLOADS_DIR = DEFAULT_DATA_DIR / "downloads"
DEFAULT_PORT = 8780
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
    pipeline.add_argument("--data-dir", type=Path, default=config_dir())
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

    check = commands.add_parser("check", help="核对 profile.yaml：哪些必填没填、哪些可选没填")
    check.add_argument("--profile", type=Path, default=None, help="不给就按 环境变量 → 仓库根目录 → ~/.config/content-studio 找")
    serve.add_argument("--data-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    serve.add_argument("--downloads-dir", type=Path, default=DEFAULT_DOWNLOADS_DIR)

    check_plan = commands.add_parser("check-visual-plan", help="视觉规格的算术检查（在叫评审之前跑）")
    check_plan.add_argument("project", type=Path, help="口播项目目录")
    check_plan.add_argument("--shots", type=Path, default=Path("~/.agents/skills/video-shotcraft/references/shots"))

    phone = commands.add_parser("phone-preview", help="成片压成 540p、切成每段不超过 28 MB 的手机预览")
    phone.add_argument("project", type=Path, help="口播项目目录，或配置根目录下的项目名")
    phone.add_argument("--out", type=Path, default=None, help="输出到别的目录（默认 项目/final/手机预览）")

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


def sync_everything(
    store: StudioStore,
    *,
    cookie_path: Path,
    creator_db: Path,
    enqueue: bool = True,
    has_report=lambda _video_id: False,
) -> dict:
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
        summary["creator_metrics"] = sync_creator_metrics(cookie_path=cookie_path, creator_db=creator_db)
    if enqueue:
        # Every recent post from a followed account, so its transcript lands in 进项; the
        # outlier pass on top of it still catches older breakouts outside that window.
        queued = auto_enqueue_new_posts(store, has_report=has_report) + auto_enqueue_outliers(store, has_report=has_report)
        summary["enqueued"] = len(queued)
    return summary


def sync_creator_metrics(*, cookie_path: Path, creator_db: Path) -> dict:
    """Snapshot creator-backend metrics for Park's own videos (last 90 days)."""
    try:
        cookies = load_cookie_file(cookie_path)
        headers = {"Referer": CREATOR_MANAGE_URL, "User-Agent": DEFAULT_USER_AGENT}
        with httpx.Client(cookies=cookies, headers=headers, follow_redirects=True, timeout=30.0) as client:
            with CreatorMetricsStore(creator_db) as metrics_store:
                result = CreatorMetricsSyncer(client=client, store=metrics_store).sync(days=90, delay_seconds=1.5)
        return {"status": "ok", **result.__dict__}
    except CreatorMetricsError as exc:
        return {"status": "failed", "error": str(exc)}


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


def run_check(args: argparse.Namespace) -> int:
    from . import profile

    path = profile.find_profile(args.profile)
    data = profile.load(path) if path else {}
    checks = profile.check(data)
    print(profile.render_checklist(checks, path))
    return 0 if profile.summary(checks)["ok"] else 1


def run_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from . import profile
    from .web import create_app

    # 启动前把 profile 读进来。缺必填项不拦着起服务——页面上会有横幅说缺什么，
    # 比直接退出对第一次装的人友好；但终端里也打一遍，别让人对着空白页猜。
    profile_path = profile.find_profile()
    profile_data = profile.load(profile_path) if profile_path else None
    checks = profile.check(profile_data or {})
    if profile_path is None or not profile.summary(checks)["ok"]:
        print(profile.render_checklist(checks, profile_path), flush=True)
        print("", flush=True)

    # Without this nothing the service logs ever reaches the launchd log, and access logs are
    # off — so a batch of jobs appearing in the queue cannot be traced to the request that made it.
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    app = create_app(
        store_path=args.store,
        cookie_path=args.cookies,
        creator_db=args.creator_db,
        data_dir=args.data_dir,
        downloads_dir=args.downloads_dir,
        profile=profile_data,
    )
    print(f"内容拆解台已启动：http://127.0.0.1:{args.port}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info", access_log=True)
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


def run_check_visual_plan(args: argparse.Namespace) -> int:
    """视觉规格的算术检查。在叫独立评审之前跑——评审只该看判断题。"""
    from . import visual_check

    base = args.project.expanduser()
    result = visual_check.run(
        base / "part-b-body" / "visual-plan.json",
        shots_root=args.shots.expanduser(),
        words_path=base / "subtitles" / "words.json",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 1


def run_phone_preview(args: argparse.Namespace) -> int:
    from . import phone, profile, release

    base = args.project.expanduser()
    if not base.is_dir():
        root = (profile.load(profile.find_profile()) if profile.find_profile() else {}).get("video_projects_root")
        base = Path(str(root or "")).expanduser() / str(args.project)
    if not base.is_dir():
        raise ValueError(f"找不到项目：{args.project}")
    found = release.find_video(base)
    if not found:
        raise ValueError(f"{base.name} 里还没有成片")
    parts = phone.make_preview(base, base / found, out=args.out.expanduser() if args.out else None)
    for part in parts:
        print(f"{part['name']}  {part['mb']} MB")
    return 0


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
            "check": run_check,
            "write-schedule": run_write_schedule,
            "check-visual-plan": run_check_visual_plan,
            "phone-preview": run_phone_preview,
        }
        if args.command in handlers:
            return handlers[args.command](args)
    except (CreatorMetricsError, PipelineError, ReportError, AccountError, StoreError, OSError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
