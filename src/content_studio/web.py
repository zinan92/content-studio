from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
import json
import subprocess
import sys
import os
import re
import logging
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .paths import config_dir
from .accounts import (
    PENDING_NOTES,
    PLATFORM_DOUYIN,
    AccountError,
    ContentDownloaderClient,
    add_account,
    sync_account,
)
from .creator_metrics import CookieFileError, load_cookie_file
from . import today as today_plan
from . import vault
from . import video_project
from . import copypack
from . import outline as outline_mod
from .video_project import VideoProjectError
from .positioning import PositioningError
from .store import StoreError, StudioStore, now_iso
from .worker import TeardownWorker, WorkerConfig, normalize_video_url


logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent / "static"
REPORT_STALE_DAYS = 7
LEGACY_REPORT_DIRS = (config_dir() / "m1",)


class UrlBody(BaseModel):
    url: str
    is_self: bool = False


class StandardBody(BaseModel):
    text: str
    source: str = ""


class JobBody(BaseModel):
    url: str | None = None
    video_id: str | None = None
    source: str | None = None


class CheckBody(BaseModel):
    day: str
    key: str
    checked: bool


class TriageBody(BaseModel):
    path: str
    status: str | None = None


class TopicBody(BaseModel):
    title: str | None = None
    note_paths: list[str] | None = None
    formats: str | None = None
    status: str | None = None
    memo: str | None = None
    published_url: str | None = None
    account_id: int | None = None
    archived: bool | None = None


class SnoozeBody(BaseModel):
    days: int = 14


class StageBody(BaseModel):
    stage: str | None = None  # "outline" = step back to the outline; None = clear the override


class SkillBody(BaseModel):
    name: str
    title: str = ""
    stage: str
    use: str = ""
    invoke: str = ""
    author: str | None = None
    repo: str | None = None
    dir: str | None = None
    path: str | None = None
    own: bool = False
    previous: str | None = None


class BackfillMarkBody(BaseModel):
    platform: str
    done: bool = True


class BackfillCancelBody(BaseModel):
    cancel: bool = True


class BackfillSkipBody(BaseModel):
    platform: str
    skip: bool = True


class DailyPickBody(BaseModel):
    key: str
    path: str
    item: str


class AnnaBody(BaseModel):
    scope: str
    message: str
    note_path: str | None = None
    report_id: str | None = None


class VideoLinkBody(BaseModel):
    name: str | None = None


class PublishJobBody(BaseModel):
    platform: str
    mode: str
    auto: bool = False  # D 补发里一声令下起的：发完不在浏览器里弹页面


class ApproveBody(BaseModel):
    gate: str
    note: str | None = None


class V2ApproveBody(BaseModel):
    gate: str
    message: str


class V2StartBody(BaseModel):
    job: str


class V2SettingsBody(BaseModel):
    values: dict[str, Any]
    scope: str = "project"  # project：只改这条视频；default：设为 Park 以后的默认


class AdoptBody(BaseModel):
    path: str


class AdoptBody(BaseModel):
    path: str


class WorktableBody(BaseModel):
    text: str
    filename: str | None = None
    overwrite: bool = False


class PublishBody(BaseModel):
    video_id: str | None = None


class CopyBody(BaseModel):
    platforms: dict[str, dict[str, Any]]


class SkipBody(BaseModel):
    platform: str
    skip: bool


class RecordBody(BaseModel):
    platform: str
    published: bool
    url: str | None = None


class ArticleBody(BaseModel):
    markdown: str


class SettingsBody(BaseModel):
    threshold: float | None = None
    auto_enqueue_limit: int | None = None
    auto_enqueue_threshold: float | None = None
    sync_pages: int | None = None
    sync_delay_seconds: float | None = None
    obsidian_vault: str | None = None
    yanxishi_admin_url: str | None = None
    video_projects_root: str | None = None
    douyin_archive: str | None = None
    local_video_roots: list[str] | None = None
    platform_accounts: dict[str, dict[str, Any]] | None = None
    tracker_keep: list[str] | None = None
    profiles: dict[str, dict[str, Any]] | None = None
    traffic_tags: dict[str, list[str]] | None = None


class StepApproveBody(BaseModel):
    key: str
    approved: bool = True
    by: str = "park"  # "machine"：补发提前打包时机器替他定的稿


class WriteBody(BaseModel):
    instruction: str | None = None


class ShootBody(BaseModel):
    text: str | None = None
    top: bool = False
    move: int | None = None  # -1 上移 / +1 下移
    planned_day: str | None = None  # 周历：排在哪天拍（YYYY-MM-DD）；传空字符串 = 不排了


class ModeBody(BaseModel):
    mode: str


class CellSentBody(BaseModel):
    sent: bool = True


class WendyBody(BaseModel):
    message: str = ""
    page: str = "today"  # 他在哪一页回的她：today / positioning（定位页聊的是方向，带上定位原文）


class PlanBody(BaseModel):
    day: str | None = None
    text: str | None = None
    done: bool | None = None


class DmBody(BaseModel):
    received: int
    replied: int
    day: str | None = None


class ProfileBody(BaseModel):
    name: str | None = None
    bio: str | None = None
    mtime: float | None = None


class AccountKindBody(BaseModel):
    kind: str


class FeedMarkBody(BaseModel):
    seen: bool | None = None
    note: str | None = None
    opened: bool | None = None


class SwipeBody(BaseModel):
    url: str | None = None
    note: str | None = None
    collection: str | None = None


class CountBody(BaseModel):
    value: int
    day: str | None = None


class DriverMarkBody(BaseModel):
    key: str
    reason: str | None = None


class ReachBody(BaseModel):
    day: str
    platform: str
    views: int | None = None  # None clears the entry


class BackgroundOps:
    """Single-flight background syncs so the UI never blocks and never double-fetches.

    "all"（自己的全部账号）、"benchmarks"（对标）、单个账号都会碰抖音，互相排队：同一时间只有一趟。
    """

    BATCHES = ("all", "benchmarks")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.syncing: set[int] = set()
        self.full_sync_running = False
        self.benchmarks_running = False
        self.last_full_sync: dict[str, Any] | None = None

    @property
    def busy(self) -> bool:
        return self.full_sync_running or self.benchmarks_running or bool(self.syncing)

    def _flag(self, key: str, value: bool) -> None:
        if key == "all":
            self.full_sync_running = value
        else:
            self.benchmarks_running = value

    def run(self, key: int | str, fn: Callable[[], Any]) -> bool:
        with self._lock:
            if self.busy:
                return False
            if key in self.BATCHES:
                self._flag(key, True)  # type: ignore[arg-type]
            else:
                self.syncing.add(key)  # type: ignore[arg-type]

        def target() -> None:
            try:
                result = fn()
                if key in self.BATCHES:
                    self.last_full_sync = result
            except Exception as exc:  # noqa: BLE001 - surfaced through account status
                logger.warning("background sync %s failed: %s", key, exc)
                if key in self.BATCHES:
                    self.last_full_sync = {"error": str(exc)}
            finally:
                with self._lock:
                    if key in self.BATCHES:
                        self._flag(key, False)  # type: ignore[arg-type]
                    else:
                        self.syncing.discard(key)  # type: ignore[arg-type]

        threading.Thread(target=target, name=f"sync-{key}", daemon=True).start()
        return True


def vault_status(raw: str) -> dict[str, Any]:
    path = Path(raw).expanduser()
    if not path.is_dir():
        return {"path": raw, "ok": False, "message": f"找不到 Obsidian 库：{raw}。在设置里改成你的库所在文件夹"}
    return {"path": raw, "ok": True, "message": None}


def _creator_rows(creator_db: Path | None) -> dict[str, dict[str, Any]]:
    if creator_db is None:
        return {}
    path = creator_db.expanduser()
    if not path.is_file():
        return {}
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM creator_video_metrics").fetchall()
    except sqlite3.Error:
        return {}
    return {row["video_id"]: {k: row[k] for k in row.keys() if k != "raw_json"} for row in rows}


def _apply_profile(store: StudioStore, data: dict[str, Any] | None) -> None:
    """profile.yaml 是「一个人告诉工作台的所有事」；这里把它落到运行时状态上。

    只在启动时做一次，而且只填空不覆盖：设置页里手改过的值优先。账号只登记不同步——
    第一次启动就去抓六个账号会把人吓跑，让他自己点「同步全部账号」。
    """
    vault.configure((data or {}).get("vault") or None)
    if not data:
        return
    from . import anna as anna_mod
    from . import outline as outline_mod
    from . import profile as profile_mod
    from .accounts import AccountError, add_account

    current = store.settings()
    patch: dict[str, Any] = {}
    vault_path_cfg = str((data.get("vault") or {}).get("path") or "").strip()
    if vault_path_cfg and current.get("obsidian_vault") in ("", None):
        patch["obsidian_vault"] = vault_path_cfg
    root = str(data.get("video_projects_root") or "").strip()
    if root and not current.get("video_projects_root"):
        patch["video_projects_root"] = root
    archive_cfg = str(data.get("douyin_archive") or "").strip()
    if archive_cfg and current.get("douyin_archive") != archive_cfg:
        patch["douyin_archive"] = archive_cfg
    roots_cfg = [str(r) for r in (data.get("local_video_roots") or []) if str(r).strip()]
    if roots_cfg and current.get("local_video_roots") != roots_cfg:
        patch["local_video_roots"] = roots_cfg
    # Anna 的角色文件和提纲框架：profile 指到哪就读哪；环境变量已设的不动（那是显式覆盖）。
    wendy_cfg = data.get("wendy") or {}
    if isinstance(wendy_cfg, dict):
        from . import wendy as wendy_mod

        for key, env_name in (("role", wendy_mod.ROLE_ENV), ("hermes", wendy_mod.HERMES_ENV)):
            value = str(wendy_cfg.get(key) or "").strip()
            if value and not os.environ.get(env_name):
                os.environ[env_name] = value
    anna_cfg = data.get("anna") or {}
    if isinstance(anna_cfg, dict):
        for key, env_name in (("role", anna_mod.ANNA_ROLE_ENV), ("workflows", outline_mod.WORKFLOWS_ENV)):
            value = str(anna_cfg.get(key) or "").strip()
            if value and not os.environ.get(env_name):
                os.environ[env_name] = value
    platforms = (data.get("me") or {}).get("platforms") or {}
    if isinstance(platforms, dict) and not current.get("platform_accounts"):
        patch["platform_accounts"] = {
            k: {"on": True, "handle": str(v).strip()} for k, v in platforms.items()
            if k in profile_mod.PLATFORM_KEYS and str(v or "").strip()
        }
    if patch:
        store.update_settings(patch)
    me_url = str((data.get("me") or {}).get("douyin") or "").strip()
    if me_url and store.self_account() is None:
        try:
            add_account(store, me_url, is_self=True)
        except AccountError as exc:
            logger.warning("profile: 自己的账号没登记上：%s", exc)
    known = {a["profile_url"] for a in store.accounts()}
    for url in data.get("benchmarks") or []:
        url = str(url or "").strip()
        if url and url not in known:
            try:
                add_account(store, url)
            except AccountError as exc:
                logger.warning("profile: 对标账号 %s 没登记上：%s", url[:40], exc)


SCREEN_REACH_APP = Path("~/Applications/内容工作台读数.app").expanduser()


def _start_screen_reach() -> str:
    """叫「内容工作台读数」小 App 读一次小红书；没装就说一声。"""
    if not SCREEN_REACH_APP.exists():
        return "没装读数小 App，小红书只能每天 9:25 读"
    try:
        subprocess.run(["open", "-g", str(SCREEN_REACH_APP)], check=False, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"读数小 App 没叫起来：{exc}"
    return "started"


def create_app(
    *,
    store_path: Path,
    cookie_path: Path,
    creator_db: Path | None,
    data_dir: Path,
    downloads_dir: Path,
    client_factory: Callable[[], Any] | None = None,
    sync_all_fn: Callable[[StudioStore], dict] | None = None,
    creator_sync_fn: Callable[[], dict] | None = None,
    worker: TeardownWorker | None = None,
    start_worker: bool = True,
    drafts_dir: Path | None = None,
    write_fn: Callable[[str], str] | None = None,
    brief_fn: Callable[[str], dict] | None = None,
    outline_fn: Callable[[str], str] | None = None,
    coupon_fn: Callable[[str], str] | None = None,
    review_fn: Callable[[str], dict] | None = None,
    suggest_fn: Callable[[str], str] | None = None,
    x_profile_read_fn: Callable[[], dict] | None = None,
    x_profile_update_fn: Callable[..., dict] | None = None,
    opening_fn: Callable[[str], dict] | None = None,
    qa_fn: Callable[[str], dict] | None = None,
    anna_fn: Callable[[str, str, str | None], dict] | None = None,
    wendy_fn: Callable[[str, str, str | None], dict] | None = None,
    runs_dir: Path | None = None,
    runner_command: str | None = None,
    publishers: dict[str, dict[str, Any]] | None = None,
    profile: dict[str, Any] | None = None,
) -> FastAPI:
    from . import writer
    from . import board as board_mod
    from . import publish_desk as publish_desk_mod

    store = StudioStore(store_path)
    _apply_profile(store, profile)
    store.recover_interrupted_writes()
    store.recover_interrupted_publishes()
    # 2026-09-16: the vault's Clippings folder was renamed to 002_clippings.
    store.rename_note_prefix("Clippings", "002_clippings")
    review_lock = threading.Lock()
    drafts_root = (drafts_dir or writer.DEFAULT_DRAFTS_DIR).expanduser()
    writing: set[int] = set()
    writing_lock = threading.Lock()
    ops = BackgroundOps()
    if creator_sync_fn is None and client_factory is None and creator_db is not None:
        def creator_sync_fn() -> dict:
            from .cli import sync_creator_metrics

            return sync_creator_metrics(cookie_path=cookie_path, creator_db=creator_db)
    data_dir = data_dir.expanduser()
    report_dirs = [data_dir, *(path.expanduser() for path in LEGACY_REPORT_DIRS)]
    worker = worker or TeardownWorker(
        store,
        WorkerConfig(cookie_path=cookie_path, data_dir=data_dir, downloads_dir=downloads_dir, creator_db=creator_db),
    )

    def factory() -> Any:
        if client_factory is not None:
            return client_factory()
        return ContentDownloaderClient(load_cookie_file(cookie_path))

    def full_sync() -> dict:
        if sync_all_fn is not None:
            result = sync_all_fn(store)
        else:
            from .cli import sync_everything

            # 小红书读数要截 Park 自己 Chrome 的窗口，只有「内容工作台读数」小 App 有录屏和控制 Chrome 的授权，
            # 所以这里只是叫它起来跑一趟（和每天 9:25 同一件事），结果一分钟左右后自己写进来。
            result = {"xiaohongshu": _start_screen_reach()}
            result.update(sync_everything(
                store,
                cookie_path=cookie_path,
                creator_db=creator_db or Path("/nonexistent"),
                benchmarks=False,
            ))
        worker.notify()
        if not result.get("stopped"):
            start_archive(limit=5)
        return result

    def benchmark_sync() -> dict:
        from .cli import sync_benchmarks

        result = sync_benchmarks(store, cookie_path=cookie_path, factory=factory)
        store.log_event("sync", f"老师和对标同步完：{sum(1 for a in result['accounts'] if a['status'] == 'ok')} 个号")
        return result

    stop_auto = threading.Event()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if start_worker:
            worker.start()
            threading.Timer(5, _pack_resume_all).start()
        yield
        stop_auto.set()
        worker.stop()

    app = FastAPI(title="内容工作台", docs_url=None, redoc_url=None, lifespan=lifespan)

    from .publisher import PublishError

    @app.exception_handler(PublishError)
    async def _publish_error(_request: Any, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    @app.exception_handler(VideoProjectError)
    async def _video_missing(_request: Any, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=404, content={"error": str(exc)})

    @app.exception_handler(vault.VaultError)
    async def _vault_missing(_request: Any, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=404, content={"error": str(exc)})

    from .standard import StandardError

    @app.exception_handler(PositioningError)
    @app.exception_handler(StandardError)
    @app.exception_handler(StoreError)
    @app.exception_handler(AccountError)
    @app.exception_handler(ValueError)
    async def _friendly(_request: Any, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    # -- helpers ------------------------------------------------------------

    def report_file(video_id: str) -> Path | None:
        if not video_id.isdigit():
            return None
        for base in report_dirs:
            candidate = base / "reports" / video_id / "report.json"
            if candidate.is_file():
                return candidate
        return None

    def job_view(job: dict[str, Any] | None) -> dict[str, Any] | None:
        if job is None:
            return None
        return {k: job[k] for k in ("id", "stage", "error", "source", "created_at", "updated_at", "url", "video_id")}

    DEEP_SYNC_PAGES = 15

    def teardown_state(video_id: str) -> dict[str, Any]:
        job = store.job_for_video(video_id)
        has_report = report_file(video_id) is not None
        return {"has_report": has_report, "job": job_view(job)}

    def account_view(account: dict[str, Any], threshold: float) -> dict[str, Any]:
        videos = store.videos(account["id"])
        median = store.account_median(account["id"])
        chronological = sorted(
            (v for v in videos if v["likes"] is not None and not v["is_image_post"]),
            key=lambda v: v["published_at"] or "",
        )
        return {
            **account,
            "pending_note": PENDING_NOTES.get(account["platform"]),
            "syncing": account["id"] in ops.syncing or (account["platform"] == PLATFORM_DOUYIN and (ops.full_sync_running if account["is_self"] else ops.benchmarks_running)),
            "video_count": len(videos),
            "latest_published_at": next((v["published_at"] for v in videos if v["published_at"]), None),
            "median_likes": median,
            "breakout_count": sum(1 for v in chronological if median and v["likes"] / median >= threshold),
            "spark": [v["likes"] for v in chronological][-60:],
        }

    # -- state --------------------------------------------------------------

    def _setup_state() -> dict[str, Any]:
        from . import profile as profile_mod

        if profile is None:
            return {"present": False, "ok": False, "missing_required": [], "missing_optional": [],
                    "hint": "还没有 profile.yaml：复制 profile.example.yaml 填一份，或在设置里逐项填"}
        out = profile_mod.summary(profile_mod.check(profile))
        out["present"] = True
        out["path"] = profile.get("_path")
        return out

    @app.get("/api/update")
    def get_update(fetch: bool = True) -> dict[str, Any]:
        from . import updater

        try:
            return updater.status(fetch=fetch)
        except updater.UpdateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/update")
    def post_update() -> dict[str, Any]:
        from . import updater

        try:
            return updater.apply()
        except updater.UpdateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/brand/logo")
    def brand_logo() -> Response:
        """profile.yaml 里 brand.logo 指的 SVG；没配就 404，前端保留对勾。"""
        from . import conf

        logo = conf.brand()["logo"]
        path = Path(logo).expanduser() if logo else None
        if not path or not path.is_file() or path.suffix.lower() != ".svg":
            raise HTTPException(status_code=404, detail="没有配置 logo")
        return FileResponse(path, media_type="image/svg+xml")

    @app.get("/api/state")
    def state() -> dict[str, Any]:
        try:
            load_cookie_file(cookie_path)
            cookies = {"ok": True, "message": None}
        except CookieFileError as exc:
            cookies = {"ok": False, "message": str(exc)}
        jobs = store.jobs(500)
        from . import conf

        b = conf.brand()
        return {
            "brand": {**b, "logo": "/api/brand/logo" if b["logo"] else ""},
            "settings": store.settings(),
            "self_account": store.self_account(),
            "my_accounts": [
                {k: a[k] for k in ("id", "platform", "nickname", "profile_url", "follower_count")} for a in store.my_accounts()
            ],
            "setup": _setup_state(),
            # 进项的日报 tab 跟 profile.yaml 的 dailies 走：拿掉一份日报只改配置，不改页面
            "daily_sources": [{"key": s.key, "label": s.label} for s in vault.DAILY_SOURCES],
            "vault": vault_status(store.settings()["obsidian_vault"]),
            "cookies": cookies,
            "creator_metrics_available": bool(_creator_rows(creator_db)),
            "full_sync_running": ops.full_sync_running,
            "benchmarks_running": ops.benchmarks_running,
            "last_full_sync": ops.last_full_sync,
            "active_jobs": sum(1 for j in jobs if j["stage"] not in ("done", "failed")),
            "account_count": len(store.accounts()),
            "benchmark_count": len(store.followed_accounts()),
        }

    @app.put("/api/settings")
    def put_settings(body: SettingsBody) -> dict[str, Any]:
        patch = {k: v for k, v in body.model_dump().items() if v is not None}
        if patch.get("video_projects_root"):
            from . import icloud

            # 存之前拦：存进去以后每个剪辑页都会报错，不如当场说清楚。
            icloud.refuse_synced_root(Path(patch["video_projects_root"]).expanduser())
        return store.update_settings(patch)

    @app.post("/api/sync")
    def sync_all() -> dict[str, Any]:
        """你自己的全部账号：抖音主号和后台、B站、X、YouTube、小红书。不碰对标。"""
        started = ops.run("all", full_sync)
        return {"started": started, "message": "开始同步你自己的全部账号" if started else "已经有一趟同步在跑，等它跑完"}

    @app.post("/api/sync/benchmarks")
    def sync_benchmarks_route() -> dict[str, Any]:
        """对标账号：每个号只看最新一页，只在对标雷达页点。"""
        started = ops.run("benchmarks", benchmark_sync)
        n = len(store.followed_accounts())
        return {"started": started, "message": f"开始同步 {n} 个对标账号，每个号只看最新一页" if started else "已经有一趟同步在跑，等它跑完"}

    # -- my videos ----------------------------------------------------------

    @app.get("/api/mine")
    def mine(account_id: int | None = None) -> dict[str, Any]:
        me = store.self_account(account_id) or store.self_account()
        if me is None:
            return {"account": None, "videos": []}
        creator = _creator_rows(creator_db)
        videos = []
        for video in store.videos(me["id"]):
            metrics = creator.get(video["video_id"])
            videos.append({**video, "creator": metrics, **teardown_state(video["video_id"])})
        median = store.account_median(me["id"])
        return {
            "account": {**me, "syncing": me["id"] in ops.syncing or ops.full_sync_running},
            "median_likes": median,
            "videos": videos,
        }

    # -- accounts -----------------------------------------------------------

    @app.get("/api/accounts")
    def accounts() -> list[dict[str, Any]]:
        threshold = float(store.settings()["threshold"])
        return [account_view(a, threshold) for a in store.followed_accounts()]

    @app.get("/api/followed/posts")
    def followed_posts(days: int = 7) -> dict[str, Any]:
        """What the accounts Park follows posted lately — the 对标 tab in 进项."""
        posts = [{**v, **teardown_state(v["video_id"])} for v in store.followed_posts(days)]
        return {"posts": posts, "days": days, "account_count": len(store.followed_accounts())}

    @app.post("/api/accounts")
    def post_account(body: UrlBody) -> dict[str, Any]:
        needs_client = "douyin.com" in body.url and "/user/" not in body.url
        account = add_account(store, body.url, client_factory=factory if needs_client else None, is_self=body.is_self)
        syncing = False
        if account["platform"] == PLATFORM_DOUYIN:
            syncing = ops.run(account["id"], lambda: _sync_and_queue(account["id"], first=True))
        threshold = float(store.settings()["threshold"])
        return {"account": {**account_view(account, threshold), "syncing": syncing}}

    def _sync_and_queue(account_id: int, deep: bool = False, first: bool = False) -> dict:
        from .cli import BENCHMARK_PAGES

        is_self = bool(store.account(account_id)["is_self"])
        # 对标平时只看最新一页（省抖音额度）；刚加进来那次读够 3 页好算中位数，「往回翻」才多翻
        pages = DEEP_SYNC_PAGES if deep else (None if is_self or first else BENCHMARK_PAGES)
        result = sync_account(store, account_id, client_factory=factory, pages=pages)
        acct = store.account(account_id)
        store.log_event("sync", f"{'往回翻完' if deep else '同步完'} {acct.get('nickname') or '账号'}，这次拉到 {result.get('video_count', '?')} 条作品")
        if not deep and is_self and creator_sync_fn is not None:
            result["creator_metrics"] = creator_sync_fn()
        return result

    @app.post("/api/accounts/{account_id}/sync")
    def post_sync(account_id: int, deep: bool = False) -> dict[str, Any]:
        account = store.account(account_id)
        if account["platform"] != PLATFORM_DOUYIN:
            raise AccountError(PENDING_NOTES.get(account["platform"], "该平台抓取待接入"))
        started = ops.run(account_id, lambda: _sync_and_queue(account_id, deep=deep))
        if not started:
            return {"started": False, "message": "这个账号正在同步中"}
        return {"started": True, "message": f"开始往回翻，最多 {DEEP_SYNC_PAGES} 页（约 {DEEP_SYNC_PAGES * 20} 条），一两分钟" if deep else "开始同步"}

    @app.get("/api/accounts/{account_id}/videos")
    def account_videos(account_id: int) -> dict[str, Any]:
        """一个对标账号的全部作品（不只爆款），带中位倍数和拆解状态。"""
        account = store.account(account_id)
        median = store.account_median(account_id)
        rows = []
        for v in store.videos(account_id):
            multiple = round(v["likes"] / median, 1) if median and v["likes"] is not None else None
            rows.append({**v, "multiple": multiple, "account_nickname": account["nickname"], "account_median": median,
                         **teardown_state(v["video_id"])})
        return {"account_id": account_id, "nickname": account["nickname"], "median": median, "videos": rows}

    @app.delete("/api/accounts/{account_id}")
    def delete_account(account_id: int) -> dict[str, Any]:
        store.delete_account(account_id)
        return {"ok": True}

    @app.patch("/api/accounts/{account_id}")
    def patch_account(account_id: int, body: AccountKindBody) -> dict[str, Any]:
        """老师 / 对标（9/30 Park：一个人只有一个身份，既是老师又是对标的算对标）。"""
        account = store.account(account_id)
        if account["is_self"]:
            raise ValueError("这是你自己的号")
        if body.kind not in ("teacher", "benchmark"):
            raise ValueError("只能是老师或对标")
        store.update_account(account_id, kind=body.kind)
        threshold = float(store.settings()["threshold"])
        return {"account": account_view(store.account(account_id), threshold)}

    @app.get("/api/feed")
    def get_feed(days: int = 7) -> dict[str, Any]:
        """老师和对标新发的视频：Park 自己去看，看过了点一下。不下载、不拆、不按点赞筛（9/30 Park：
        「他俩出了视频我都去看就好了」「视频可能刚跑了 6 个小时，你怎么知道最终结果怎么样」）。
        想拆、想复刻，他点了才做。"""
        days = min(max(days, 1), 30)
        marks = store.feed_marks()
        swiped = {r["url"]: r["id"] for r in store.swipe_videos()}
        kinds = {a["id"]: a for a in store.followed_accounts()}
        out: dict[str, list[dict[str, Any]]] = {"teacher": [], "benchmark": []}
        for v in store.followed_posts(days):
            acct = kinds.get(v["account_id"]) or {}
            kind = "teacher" if acct.get("kind") == "teacher" else "benchmark"
            url = f"https://www.douyin.com/video/{v['video_id']}"
            mark = marks.get(v["video_id"]) or {}
            out[kind].append({
                "video_id": v["video_id"], "url": url, "title": v.get("title") or "", "account": acct.get("nickname") or "", "account_id": v["account_id"],
                "published_at": v.get("published_at"), "duration_seconds": v.get("duration_seconds"), "likes": v.get("likes"), "is_image_post": bool(v.get("is_image_post")),
                "seen_at": mark.get("seen_at"), "opened_at": mark.get("opened_at"), "note": mark.get("note") or "", "swipe_id": swiped.get(url), **teardown_state(v["video_id"]),
            })
        counts = {k: {"total": len(rows), "unseen": sum(1 for r in rows if not r["seen_at"])} for k, rows in out.items()}
        accounts = {k: [a["nickname"] or "未同步" for a in kinds.values() if ("teacher" if a.get("kind") == "teacher" else "benchmark") == k] for k in out}
        return {"days": days, **out, "counts": counts, "accounts": accounts}

    @app.put("/api/feed/{video_id}")
    def put_feed_mark(video_id: str, body: FeedMarkBody) -> dict[str, Any]:
        if store.video(video_id) is None:
            raise ValueError("找不到这条视频")
        store.set_feed_mark(video_id, seen=body.seen, note=body.note, opened=body.opened)
        return {"ok": True}

    @app.get("/api/outliers")
    def outliers(threshold: float | None = None) -> list[dict[str, Any]]:
        value = threshold if threshold is not None else float(store.settings()["threshold"])
        return [{**video, **teardown_state(video["video_id"])} for video in store.outliers(value)]

    # -- jobs ---------------------------------------------------------------

    @app.get("/api/jobs")
    def jobs() -> list[dict[str, Any]]:
        results = []
        # 同一条视频失败了好几次，队列里只列最近一次，带上次数（9/29 以前一条失败了 37 次，把队列刷满了）
        all_jobs = store.jobs(limit=1000)
        fails: dict[str, int] = {}
        for job in all_jobs:
            if job["stage"] == "failed" and job["video_id"]:
                fails[job["video_id"]] = fails.get(job["video_id"], 0) + 1
        seen_failed: set[str] = set()
        shown = []
        for job in all_jobs:
            if job["stage"] == "failed" and job["video_id"]:
                if job["video_id"] in seen_failed:
                    continue
                seen_failed.add(job["video_id"])
            shown.append({**job, "attempts": fails.get(job["video_id"] or "", 0)})
        for job in shown[:200]:
            video = store.video(job["video_id"]) if job["video_id"] else None
            results.append(
                {
                    **job_view(job),
                    "title": video["title"] if video else None,
                    "has_report": bool(job["video_id"] and report_file(job["video_id"])),
                    "running": worker.current_job_id == job["id"],
                    "attempts": job.get("attempts", 0),
                }
            )
        return results

    @app.post("/api/jobs")
    def post_job(body: JobBody) -> dict[str, Any]:
        if body.video_id:
            if not body.video_id.isdigit():
                raise ValueError("视频编号无效")
            url, video_id = f"https://www.douyin.com/video/{body.video_id}", body.video_id
        else:
            url, video_id = normalize_video_url(body.url or "")
        job, created = store.enqueue(url=url, video_id=video_id, source=body.source or "手动添加", retry_failed=True)
        worker.notify()
        return {"job": job_view(job), "created": created, "message": "已加入拆解队列" if created else "这条视频已经在队列里或拆解过了"}

    @app.delete("/api/jobs/{job_id}")
    def cancel(job_id: int) -> dict[str, Any]:
        store.cancel_job(job_id)
        return {"ok": True}

    @app.post("/api/jobs/{job_id}/retry")
    def retry(job_id: int) -> dict[str, Any]:
        job = store.retry_job(job_id)
        worker.notify()
        return {"job": job_view(job)}

    # -- reports ------------------------------------------------------------

    @app.get("/api/reports")
    def reports() -> list[dict[str, Any]]:
        archived = store.archived_reports()
        seen: dict[str, dict[str, Any]] = {}
        for base in report_dirs:
            for path in sorted((base / "reports").glob("*/report.json")):
                video_id = path.parent.name
                if video_id in seen:
                    continue
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if data.get("schema_version", 1) < 2:
                    continue
                seen[video_id] = {
                    "video_id": video_id,
                    "title": data.get("title"),
                    "author": data.get("author"),
                    "generated_at": data.get("generated_at"),
                    "multiple": (data.get("facts") or {}).get("multiple_of_median"),
                    "is_self": bool((data.get("facts") or {}).get("creator_avg_view_second")),
                    "archived_at": archived.get(video_id),
                }
        # Benchmark reports nobody opened in 7 days are archived when the list is read, so the unread count stays meaningful.
        stale_before = (datetime.now(timezone.utc) - timedelta(days=REPORT_STALE_DAYS)).isoformat()
        for item in seen.values():
            if not item["archived_at"] and not item["is_self"] and (item["generated_at"] or "9") < stale_before:
                item["archived_at"] = store.archive_report(item["video_id"])
                item["auto_archived"] = True
        return sorted(seen.values(), key=lambda r: r.get("generated_at") or "", reverse=True)

    @app.get("/api/reports/{video_id}")
    def report(video_id: str) -> dict[str, Any]:
        path = report_file(video_id)
        if path is None:
            raise HTTPException(status_code=404, detail="这条视频还没有拆解报告")
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema_version", 1) < 2:
            raise HTTPException(status_code=404, detail="这是旧版报告，请重新拆解这条视频")
        return data

    @app.post("/api/reports/{video_id}/archive")
    def archive_report(video_id: str) -> dict[str, Any]:
        if report_file(video_id) is None:
            raise HTTPException(status_code=404, detail="这条视频还没有拆解报告")
        return {"video_id": video_id, "archived_at": store.archive_report(video_id)}

    @app.delete("/api/reports/{video_id}/archive")
    def unarchive_report(video_id: str) -> dict[str, Any]:
        if report_file(video_id) is None:
            raise HTTPException(status_code=404, detail="这条视频还没有拆解报告")
        store.unarchive_report(video_id)
        return {"video_id": video_id, "archived_at": None}

    # -- vault (read-only Obsidian) ----------------------------------------

    def vault_path() -> str:
        return store.settings()["obsidian_vault"]

    def parse_day(raw: str | None) -> date:
        if not raw:
            return date.today()
        try:
            return date.fromisoformat(raw)
        except ValueError as exc:
            raise ValueError("日期格式应为 YYYY-MM-DD") from exc

    @app.get("/api/today/dailies")
    def today_dailies(day: str | None = None) -> dict[str, Any]:
        target = parse_day(day)
        checks = store.daily_checks(target.isoformat())
        items = vault.dailies(vault_path(), target)
        return {"day": target.isoformat(), "items": [{**item, "checked_at": checks.get(item["key"])} for item in items]}

    @app.put("/api/today/checks")
    def put_check(body: CheckBody) -> dict[str, Any]:
        parse_day(body.day)
        if body.key not in {s.key for s in vault.DAILY_SOURCES} | {k for k, _, _ in READ_DAILIES} | {"video_shot"}:
            raise ValueError("未知的勾选项")
        return {"day": body.day, "checks": store.set_daily_check(body.day, body.key, body.checked)}

    @app.get("/api/vault/inbox")
    def vault_inbox(days: int = 1, source: str | None = None) -> dict[str, Any]:
        since = vault.window_start(min(max(days, 1), 30))
        from . import board

        triage = store.triage()
        items = vault.inbox(vault_path(), since=since, sources=(source,) if source else None)
        # A note that already became a video should not look like fresh material.
        used: dict[str, dict[str, Any]] = {}
        video_of: dict[int, str] = {}
        try:
            _, links, _ = _backfill_state()
            video_of = {tid: vid for vid, tid in links.items()}
        except Exception:  # noqa: BLE001 - the jump target is a nicety, never block 进项
            pass
        for topic in store.topics(include_archived=True):
            shipped = board.is_shipped(topic)
            dropped = bool(topic.get("archived_at")) and not shipped
            for path in topic["note_paths"]:
                row = {"topic_id": topic["id"], "title": topic["title"], "shipped": shipped, "dropped": dropped,
                       "video_id": topic.get("published_video_id") or video_of.get(topic["id"])}
                # 还在做的优先；标过「不做了」的，只在没别的选题占着这篇时才显示。
                if path not in used or (used[path]["dropped"] and not dropped):
                    used[path] = row
        from . import hot

        rows = [{**item, "triage": (triage.get(item["path"]) or {}).get("status"), "used_by": used.get(item["path"])} for item in items]
        return {
            "since": since.isoformat(timespec="minutes"),
            "items": hot.mark_breakouts(rows, store.outliers(float(store.settings()["threshold"]))),
        }

    @app.put("/api/vault/triage")
    def put_triage(body: TriageBody) -> dict[str, Any]:
        root = vault.vault_root(vault_path())
        vault.safe_path(root, body.path)
        store.set_triage(body.path, body.status)
        topic = None
        if body.status == "topic":
            topic = store.topic_for_note(body.path)
            if topic is None:
                note = vault.read_note(vault_path(), body.path)
                me = store.self_account()
                topic = store.create_topic(note["title"], note_paths=[body.path], account_id=me["id"] if me else None)
                store.log_event("pool", f"《{topic['title'][:30]}》从进项进了选题池", topic["id"])
            elif topic.get("archived_at"):
                # 以前标过「不做了」。再点一次「入选题池」就是改主意了，把它拿回看板——
                # 否则接口返回成功、选题却还在归档里，进项和加工中永远对不上。
                topic = store.update_topic(topic["id"], archived_at=None)
                store.log_event("pool", f"《{topic['title'][:30]}》又捡回来了", topic["id"])
            else:
                store.log_event("pool", f"《{topic['title'][:30]}》从进项进了选题池", topic["id"])
        elif body.status:
            store.log_event("triage", f"进项里「{body.path.split('/')[-1][:30]}」标成了{ {'shot': '拍过了', 'ignored': '暂不拍', 'back': '捡回来'}.get(body.status, body.status) }")
        return {"path": body.path, "triage": body.status, "topic": topic}

    # -- skills -----------------------------------------------------------

    @app.get("/api/skills")
    def list_skills() -> dict[str, Any]:
        from . import skills

        return skills.load_skills(user=skills.user_path())

    @app.put("/api/skills")
    def put_skill(body: SkillBody) -> dict[str, Any]:
        """加一个或改一个。第一次改的时候把仓库里的种子复制成 Park 自己的清单。"""
        from . import skills

        entry = skills.upsert(body.model_dump(exclude={"previous"}), user=skills.user_path(), previous=body.previous)
        return {"skill": entry}

    @app.delete("/api/skills/{name}")
    def delete_skill(name: str) -> dict[str, Any]:
        from . import skills

        if not skills.remove(name, user=skills.user_path()):
            raise ValueError("这个 skill 已经不在清单里了")
        return {"ok": True}

    @app.get("/api/skills/{name}/doc")
    def skill_doc(name: str) -> dict[str, Any]:
        from . import skills

        return skills.read_doc(name, user=skills.user_path())

    @app.get("/api/anna/soul")
    def anna_soul() -> dict[str, Any]:
        """Anna 每轮读的文件：角色、knowledge、原则、定位、三点评分。只读列出来。"""
        home = str(Path.home())
        return {"files": [{"i": i, "name": Path(p).name, "path": p.replace(home, "~")} for i, p in enumerate(anna_mod.load_soul()["sources"])]}

    @app.get("/api/anna/soul/{index}")
    def anna_soul_doc(index: int) -> dict[str, Any]:
        sources = anna_mod.load_soul()["sources"]
        if not 0 <= index < len(sources):
            raise ValueError("没有这个文件")
        path = Path(sources[index])
        text = path.read_text(encoding="utf-8", errors="replace")
        return {"name": path.name, "path": str(path).replace(str(Path.home()), "~"), "body": anna_mod._strip_frontmatter(text)[:60000]}

    # -- topics & today plan ---------------------------------------------

    @app.get("/api/topics")
    def list_topics(archived: bool = False) -> list[dict[str, Any]]:
        return store.topics(include_archived=archived)

    @app.post("/api/topics")
    def post_topic(body: TopicBody) -> dict[str, Any]:
        return store.create_topic(
            body.title or "",
            note_paths=body.note_paths,
            formats=body.formats or "both",
            account_id=body.account_id,
            memo=body.memo,
        )

    @app.patch("/api/topics/{topic_id}")
    def patch_topic(topic_id: int, body: TopicBody) -> dict[str, Any]:
        fields = {k: v for k, v in body.model_dump(exclude={"archived"}).items() if v is not None}
        if body.archived is not None:
            fields["archived_at"] = now_iso() if body.archived else None
        topic = store.update_topic(topic_id, **fields)
        if body.archived:
            # 「不做了」= 这几篇笔记重新变成可选的。不清掉 triage 的话，进项会一直显示
            # 「已入选题池」，而那个选题已经不在看板上——点不进去，也加不回来。
            for path in topic.get("note_paths") or []:
                if (store.triage().get(path) or {}).get("status") == "topic":
                    store.set_triage(path, None)
        return topic

    # -- 每周复盘定下的调整，写提纲时带上 -------------------------------------

    def latest_adjustments() -> list[str]:
        row = store._row("SELECT data FROM reviews WHERE state IN ('done', 'failed') AND data IS NOT NULL ORDER BY week DESC LIMIT 1")
        if not row:
            return []
        try:
            return [str(item) for item in (json.loads(row["data"]).get("next_week") or [])][:3]
        except (ValueError, AttributeError):
            return []

    def _save_transcript(job: dict[str, Any]) -> None:
        """A followed account's video, once torn down, becomes a readable note in 进项."""
        from . import transcripts

        video_id = job.get("video_id")
        video = store.video(video_id) if video_id else None
        if video is None:
            return
        account = store.account(video["account_id"])
        report = _load_report(video_id)
        if report is None:
            return
        text = transcripts.transcript_text(report)
        mine = bool(account["is_self"])
        who = account.get("nickname") or ("我" if mine else "对标")
        if mine:
            # 自己的视频不做时效和「太薄」筛选：这是我的内容库，每一条都要在，
            # 包括短的和没爆的——分析自己的风格时，失败的那几条同样是证据。
            folder = transcripts.MINE_FOLDER
        else:
            skip = transcripts.is_thin(
                title=video.get("title") or "",
                text=text,
                duration_seconds=(report.get("transcript") or {}).get("duration_seconds"),
                published_at=video.get("published_at"),
            )
            if skip:
                logger.info("transcript skipped %s: %s", video_id, skip)
                return
            folder = transcripts.FOLDER
        name = transcripts.note_name(published_at=video.get("published_at"), account=who, title=video.get("title") or "")
        markdown = transcripts.render(video=video, account=who, report=report, text=text)
        path = transcripts.write_note(vault.vault_root(vault_path()), name, markdown, folder=folder)
        logger.info("transcript saved %s", path)
        store.log_event("teardown", f"拆完了{'自己' if mine else who}的《{(video.get('title') or '')[:24]}》，文字稿落进 {folder}")

    worker.on_done = _save_transcript

    def _load_report(video_id: str) -> dict[str, Any] | None:
        path = report_file(video_id)
        if path is None:
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if data.get("schema_version", 1) >= 2 else None

    def _run_review(now_value: datetime) -> None:
        from . import review

        key = review.week_key(now_value)
        try:
            me = store.self_account()
            if me is None:
                raise review.ReviewError("还没有连接自己的抖音号")
            own = store.videos(me["id"])
            breakouts = store.outliers(float(store.settings()["threshold"]))
            ids = [v["video_id"] for v in own] + [b["video_id"] for b in breakouts]
            reports_by_id = {vid: data for vid in ids if (data := _load_report(vid))}
            inputs = review.gather_inputs(
                own_videos=own, median_likes=store.account_median(me["id"]), creator=_creator_rows(creator_db),
                reports=reports_by_id, topics=store.topics(include_archived=True), breakouts=breakouts, now=now_value,
            )
            inputs["kpi"] = _week_kpi(now_value.astimezone().date())
            data = review.generate_review(inputs, **({"review_fn": review_fn} if review_fn else {}))
            store.set_review(key, state="done", data=data)
        except Exception as exc:  # noqa: BLE001 - shown on the review page
            logger.warning("review %s failed: %s", key, exc)
            store.set_review(key, state="failed", error=str(exc)[:300] or type(exc).__name__)
        finally:
            review_lock.release()

    def _week_kpi(today: date) -> dict[str, Any]:
        """周复盘要看的执行分：出摊几天、私信没回完几天、减了几分，跳过时写的理由（摆出重复的借口）。"""
        from . import driver

        since = (today - timedelta(days=driver.WINDOW)).isoformat()
        cfg = kpi_config()
        reads = {}
        for i in range(driver.WINDOW):
            d = today - timedelta(days=i)
            ok = read_state(d)[1] if d.isoformat() >= cfg["read_started"] else None
            if ok is not None:
                reads[d.isoformat()] = ok
        days = driver.kpi_days(today, posted=shipped_days(), dms=store.dm_entries(since), started=cfg["started"],
                               x_replies=store.kpi_counts(since, "x_replies"), x_target=int(cfg["x_replies_daily"]),
                               reads=reads, read_started=cfg["read_started"])
        week = _week(driver.week_start(today), today)
        return {
            # 这一周（周一起）发了几条新视频、每周下限、周过完以后少了几条（少一条减 1 分，已经算进 week_demerits）
            "new_videos": week["new_videos"], "new_target": week["new_target"], "new_short": week["new_short"], "week_demerits": week["demerits"],
            "read_missed": sum(d["rd"] == "miss" for d in days),
            "x_missed": sum(d["xr"] == "miss" for d in days),
            "posted": sum(d["ship"] == "ok" for d in days),
            "dm_missed": sum(d["dm"] == "miss" for d in days),
            "demerits": driver.demerits(days),
            "skips": [{"day": r["day"], "what": r["key"], "reason": r["reason"]} for r in store.driver_log(since, "skip")],
        }

    @app.get("/api/review")
    def get_review() -> dict[str, Any]:
        from . import review

        key = review.week_key(datetime.now(timezone.utc))
        return store.review(key) or {"week": key, "state": "missing", "error": None, "data": None}

    @app.post("/api/review/generate")
    def post_review() -> dict[str, Any]:
        from . import review

        now_value = datetime.now(timezone.utc)
        if not review_lock.acquire(blocking=False):
            return {"started": False, "message": "复盘正在生成"}
        store.set_review(review.week_key(now_value), state="running")
        threading.Thread(target=_run_review, args=(now_value,), name="review", daemon=True).start()
        return {"started": True, "message": "开始复盘这一周，一般 1–3 分钟"}

    @app.post("/api/topics/{topic_id}/wechat-handoff")
    def handoff_to_wechat_pipeline(topic_id: int) -> dict[str, Any]:
        """把写好的文章送进 004_内容加工中，交给 Park 现成的公众号流程。

        路径不叫 /handoff：那个已经是研习室那条线的，同名会把它整个盖掉。
        """
        from . import handoff as handoff_mod, writer

        topic = store.topic(topic_id)
        draft = writer.read_draft(topic)
        if not draft:
            raise ValueError("这个选题还没有文章")
        try:
            result = handoff_mod.handoff(vault.vault_root(vault_path()), topic=topic, markdown=draft["markdown"])
        except handoff_mod.HandoffError as exc:
            raise ValueError(str(exc)) from exc
        store.log_event("handoff", f"《{result['title'][:28]}》已交接到 004_内容加工中，等配图排版", topic_id)
        return result

    # -- 触达：Park's first KPI, every platform in one number -----------------

    def platform_forms() -> dict[str, str]:
        """每个平台现在发什么（设置里选过的优先）。打包、发布台、今天都读这一份。"""
        from . import reach

        accounts = store.settings()["platform_accounts"] or {}
        return {key: reach.form_of(key, accounts) for key, _, _ in reach.PLATFORMS}

    def _platform_rows(ready: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        """每个平台：发布通道有没有、登录还在不在、数据是不是自动来的。

        三种状态，不是两种：已连接（有真实通道且登录没过期）、要登录（有通道但凭据旧了）、
        手动（根本没有通道）。一个永远亮不起来的灯就是骗人。
        """
        from . import publisher, reach

        opened = store.settings()["platform_accounts"] or {}
        me = store.self_account()
        ready = publisher.readiness(publisher_specs()) if ready is None else ready
        rows = []
        for key, label, auto in reach.PLATFORMS:
            style = reach.PLATFORM_STYLE.get(key, {})
            channel = ready.get(key)
            if channel is None:
                state, note = "manual", "手动发布"
                if key == "wechat_mp":
                    # 真去问微信，不写死：40164 是 IP 白名单、40125 是 AppSecret，两件事要分清。
                    # 带 6 小时缓存——每次渲染都问一次会把微信每天的取令牌配额耗光。
                    from . import wechat

                    wx = wechat.state()
                    state = "ready" if wx["ok"] else "setup"
                    note = ("凭据没问题，图文发布通道还没做" if wx["ok"] else wx["note"])
            elif channel.get("blocked"):
                state, note = "blocked", channel["note"]
            elif channel.get("setup"):
                state, note = "setup", channel["note"]
            else:
                state = "stale" if channel["likely_expired"] else "linked"
                note = channel["note"]
            row = {
                "key": key, "label": label, "mark": style.get("mark", label[:1]), "hue": style.get("hue", "#888"),
                "auto_publish": channel is not None and not channel.get("blocked") and not channel.get("setup"), "auto_data": auto, "state": state, "note": note,
                "login_hint": (channel or {}).get("login_hint", ""),
                "handle": (opened.get(key) or {}).get("handle") or ("" if key != "douyin" else (me or {}).get("nickname") or ""),
                "on": bool((opened.get(key) or {}).get("on")) or key == "douyin",
                "admin": copypack.PLATFORMS.get(key, {}).get("admin"),
            }
            rows.append(row)
        return rows

    @app.get("/api/platforms")
    def platforms() -> dict[str, Any]:
        return {"platforms": _platform_rows()}

    def _skipped(video_id: str | None, topic_id: int | None) -> set[str]:
        """这一条哪些平台不发：补发工作台里标的（tracker_skip，按抖音作品）加上发布台上跳过的（publish_skips，按选题）。"""
        out = set((store.settings().get("tracker_skip") or {}).get(video_id) or []) if video_id else set()
        return out | (store.publish_skips(topic_id) if topic_id else set())

    def _on_keys() -> set[str]:
        from . import publisher

        return {p["key"] for p in _platform_rows(publisher.readiness(publisher_specs())) if p.get("on")}

    def _fresh(topic: dict[str, Any]) -> bool:
        """打包、发布页挂着的是「新的那条」：还没上抖音，或者抖音上是两周内发的。
        10/3：补发的老内容昨晚批量打包过，选题的更新时间是新的，但它们走补发工作台，不该挂在打包页上。"""
        vid = topic.get("published_video_id")
        video = store.video(vid) if vid else None
        if video is None:
            return True
        cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
        return (video.get("published_at") or "") >= cutoff

    def _unfinished(topic: dict[str, Any], on_keys: set[str]) -> bool:
        """还没发完：没点「发布完毕」、没「不补发」，还有开着的平台既没发、也没标不发。
        发了算三种：发布台的记录、补发工作台里点的「发了」（backfill_marks）、抖音挂上了作品。"""
        vid = topic.get("published_video_id")
        if topic.get("closed_at") or (vid and vid in set(store.settings().get("tracker_cancel") or [])):
            return False
        done = set(store.publish_records(topic["id"])) | _skipped(vid, topic["id"])
        if vid:
            done |= {"douyin"} | store.backfill_marks().get(vid, set())
        return bool(on_keys - done)

    @app.get("/api/publish/desk")
    def publish_desk(topic_id: int | None = None) -> dict[str, Any]:
        """发布台：一条内容铺在所有平台上。哪条内容由 topic_id 定，没给就取最接近能发的那条。"""
        from . import approvals, board, copypack, handoff as handoff_mod, publish_desk, publisher

        cards = [c for c in get_board(None)["cards"] if not c.get("snoozed_until")]
        cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
        shipped = [{"id": t["id"], "title": t["title"], "stage": "shipped", "focus": False, "updated_at": t.get("updated_at")}
                   for t in store.topics() if board.is_shipped(t) and (t.get("updated_at") or "") >= cutoff]
        ordered = publish_desk.order_candidates(cards, shipped)
        candidates = []
        for c in ordered:
            n = len(store.publish_records(c["id"])) + (1 if c["stage"] == "shipped" and "douyin" not in store.publish_records(c["id"]) else 0)
            candidates.append({"id": c["id"], "title": c["title"], "stage": c["stage"], "stage_label": dict(board.MILESTONES).get(c["stage"], c["stage"]), "shipped_count": n})
        sendable = publish_desk.ready_to_publish(candidates)
        waiting = publish_desk.waiting_for(candidates) if not sendable else None
        # 9/29 Park：一条发完了就收起来；没指定哪条时，打包和发布只挑还有平台没发的那条。
        # 10/3：抖音发出只是第一个平台——还有开着的平台没发也没跳过、也没点「发布完毕」，就还没发完。
        on_keys = _on_keys()
        on_count = len(on_keys)
        unfinished = [c for c in sendable if (t := store.topic(c["id"])) and _fresh(t) and _unfinished(t, on_keys)]
        chosen = next((c for c in candidates if c["id"] == topic_id), None) if topic_id is not None else (unfinished[0] if unfinished else None)
        if topic_id is not None and chosen is None:
            # 不在候选里（归档了、或者太老）也允许直接打开——链接可能是从别处带过来的。
            t = store.topic(topic_id)
            chosen = {"id": t["id"], "title": t["title"], "stage": "shipped" if board.is_shipped(t) else "outline", "stage_label": "", "shipped_count": len(store.publish_records(t["id"]))}
        ready = publisher.readiness(publisher_specs())
        platform_rows = _platform_rows(ready)
        if chosen is None:
            empty = {"title": "", "body": "", "tags": []}
            # 手上没有要发的：告诉 Park 刚发完的是哪条（各平台链接）、下一条在哪（9/29：发布页不能一片空白）
            done = [c for c in sendable if c not in unfinished]
            finished = None
            if done:
                last = done[0]
                recs = store.publish_records(last["id"])
                finished = {"id": last["id"], "title": last["title"], "shipped_count": last["shipped_count"], "on_count": on_count,
                            "links": {k: {"url": v.get("url"), "label": (copypack.PLATFORMS.get(k) or {}).get("label", k)} for k, v in recs.items()}}
            return {"candidates": [], "waiting": waiting or publish_desk.waiting_for(candidates), "finished": finished,
                    "others": candidates, "topic": None, "video": None, "has_copy": False, "has_article": False, "entry": empty, "forms": platform_forms(),
                    "platforms": publish_desk.rows(platform_rows, specs=copypack.PLATFORMS, publishers=publisher_specs(), readiness=ready, records={}, jobs=[], entry=empty)}
        topic = store.topic(chosen["id"])
        copy = copypack.read_copy(drafts_root, topic["id"])
        entry = publish_desk.shared_entry(copy)
        video = final_video_path(topic)
        article = writer.read_draft(topic)
        handoff_done = False
        try:
            root = vault.vault_root(vault_path())
            handoff_done = (root / handoff_mod.FOLDER / handoff_mod.slug(topic["title"]) / handoff_mod.PACKAGE / "wechat-article.md").exists()
        except (vault.VaultError, OSError):
            pass
        rows = publish_desk.rows(platform_rows, specs=copypack.PLATFORMS, publishers=publisher_specs(), readiness=ready,
                                 records=store.publish_records(topic["id"]), jobs=store.publish_jobs(topic["id"]), entry=entry,
                                 douyin_linked=board.is_shipped(topic), handoff_done=handoff_done, skips=store.publish_skips(topic["id"]),
                                 copies=(copy or {}).get("platforms"))
        return {
            # 能发的才列出来；其余的留在 others 里，页面上折起来。
            "candidates": sendable,
            "waiting": waiting,
            "others": [c for c in candidates if c["id"] not in {s["id"] for s in sendable}],
            "topic": {**chosen, "published_video_id": topic.get("published_video_id"), "published_url": topic.get("published_url"), "closed_at": topic.get("closed_at"),
                      "video_project": topic.get("video_project"), "write_state": topic.get("write_state"), "write_error": topic.get("write_error")},
            "video": {"path": str(video), "name": video.name, "mb": round(video.stat().st_size / 1_048_576, 1)} if video else None,
            "release": (release_info := _release_for(topic)),
            "approvals": approvals.status((st := _approval_state(topic, release_info))["folder"], st["fps"]),
            "has_copy": bool(entry["title"] or entry["body"]),
            "has_article": article is not None,
            "forms": platform_forms(),
            "next": publish_desk.next_step(rows),
            # 左边那张仿平台页面要填真的内容：文章标题、摘要、正文开头（纯文字）
            "article": _article_preview(article["markdown"]) if article else None,
            "entry": entry,
            "platforms": rows,
        }

    @app.get("/api/reach")
    def get_reach(days: int = 14) -> dict[str, Any]:
        from . import reach

        days = min(max(days, 7), 90)
        today = date.today()
        since = (today - timedelta(days=days - 1)).isoformat()
        me = store.self_account()
        auto = reach.daily_views(store.account_snapshots(me["id"], since), days, today) if me else {}
        totals: dict[str, dict[str, int]] = {(today - timedelta(days=i)).isoformat(): {} for i in range(days)}
        for day_key, views in auto.items():
            if views:
                totals[day_key]["douyin"] = views
        synced = store.post_synced_at()
        # YouTube 在 Park 授权「查看」之后才开始有读数；有了就按自动算。
        pulled = [k for k in reach.PLATFORM_KEYS if k != "douyin" and (k in reach.AUTO_KEYS or k in synced)]
        read_state: dict[str, str] = {}
        for key in pulled:
            rows = store.post_snapshots(key, since)
            seen = {str(r["fetched_at"])[:10] for r in rows}
            for day_key, views in reach.daily_views(rows, days, today).items():
                # 那天读过就记下（哪怕涨了 0）；没读过才空着。9/29 以前涨 0 也显示「—」，看着像没读到。
                if day_key in totals and (views or day_key in seen):
                    totals[day_key][key] = views
            first = min(seen) if seen else None
            read_state[key] = ("baseline" if first == today.isoformat() else "read") if today.isoformat() in seen else "not_read"
        for row in store.reach_entries(since):
            # 自动的平台以读到的为准；以前手填的旧数只在还没开始自动读的日子里算。
            if row["day"] in totals and row["platform"] not in totals[row["day"]]:
                totals[row["day"]][row["platform"]] = int(row["views"])
        accounts = store.settings()["platform_accounts"] or {}
        today_key = today.isoformat()
        return {
            **reach.summary(totals, today),
            "platforms": [
                {"key": key, "label": label, "auto": auto_flag or key in pulled, "on": bool((accounts.get(key) or {}).get("on")) or auto_flag or key in pulled,
                 "handle": (accounts.get(key) or {}).get("handle") or "", "today": totals[today_key].get(key),
                 # 自动的平台今天读了没有：baseline = 今天第一次读，只能当基准，明天起才算得出涨了多少
                 "read": read_state.get(key), "stats_url": reach.STATS_URLS.get(key),
                 # 9/29 注意力分层：主攻的 core=True，其余降权（页面上放右边、淡一点）
                 "core": key in reach.CORE,
                 # 发什么（视频 / 文字 / 图文）；能选的平台给出选项，设置里改，存进 platform_accounts[key].form
                 "form": reach.form_of(key, accounts), "form_choices": [{"key": f, "label": reach.FORM_LABEL[f]} for f in reach.FORM_CHOICES.get(key, ())]}
                for key, label, auto_flag in reach.PLATFORMS
            ],
            "douyin_synced_at": me["last_synced_at"] if me else None,
            "synced_at": {**synced, **({"douyin": me["last_synced_at"]} if me else {})},
        }

    @app.put("/api/reach")
    def put_reach(body: ReachBody) -> dict[str, Any]:
        from . import reach

        if body.platform not in reach.PLATFORM_KEYS or body.platform in reach.AUTO_KEYS or body.platform in store.post_synced_at():
            raise ValueError("这个平台的数据是自动读的，不用手填")
        parse_day(body.day)
        if body.views is not None and body.views < 0:
            raise ValueError("触达不能是负数")
        store.set_reach(body.day, body.platform, body.views)
        return get_reach()

    # -- the one video in production ----------------------------------------

    @app.post("/api/topics/{topic_id}/focus")
    def focus_topic(topic_id: int) -> dict[str, Any]:
        topic = store.topic(topic_id)
        if topic.get("archived_at"):
            raise ValueError("这条已经归档了")
        previous = store.focus_topic()
        store.set_focus(topic_id)
        swapped = previous and previous["id"] != topic_id
        store.log_event("focus", f"开始做《{topic['title'][:30]}》" + (f"，《{previous['title'][:20]}》放回选题池" if swapped else ""), topic_id)
        return {"topic": store.topic(topic_id), "previous": previous["title"] if swapped else None}

    @app.delete("/api/topics/{topic_id}/focus")
    def unfocus_topic(topic_id: int) -> dict[str, Any]:
        store.topic(topic_id)
        current = store.focus_topic()
        if current and current["id"] == topic_id:
            store.set_focus(None)
            store.log_event("focus", f"《{current['title'][:30]}》放回了选题池", topic_id)
        return {"topic": store.topic(topic_id)}

    @app.post("/api/topics/{topic_id}/close")
    def close_topic(topic_id: int) -> dict[str, Any]:
        """「发布完毕」：这条结了，从加工中拿掉。还没发的平台（比如小宇宙）以后照样能在发布台补。"""
        topic = store.topic(topic_id)
        if not store.publish_records(topic_id) and not topic.get("published_video_id"):
            raise ValueError("一个平台都还没发，先发再点「发布完毕」")
        if topic.get("is_focus"):
            store.set_focus(None)
        topic = store.update_topic(topic_id, closed_at=now_iso())
        store.log_event("close", f"《{topic['title'][:30]}》发布完毕，从加工中拿掉", topic_id)
        return {"topic": topic}

    @app.delete("/api/topics/{topic_id}/close")
    def reopen_topic(topic_id: int) -> dict[str, Any]:
        topic = store.update_topic(topic_id, closed_at=None)
        store.log_event("close", f"《{topic['title'][:30]}》撤销发布完毕，放回加工中", topic_id)
        return {"topic": topic}

    @app.post("/api/topics/{topic_id}/snooze")
    def snooze_topic(topic_id: int, body: SnoozeBody) -> dict[str, Any]:
        store.topic(topic_id)
        days = min(max(body.days, 1), 90)
        return {"topic": store.update_topic(topic_id, snoozed_until=(date.today() + timedelta(days=days)).isoformat(), is_focus=0)}

    @app.delete("/api/topics/{topic_id}/snooze")
    def unsnooze_topic(topic_id: int) -> dict[str, Any]:
        store.topic(topic_id)
        return {"topic": store.update_topic(topic_id, snoozed_until=None)}

    @app.post("/api/topics/{topic_id}/stage")
    def set_stage(topic_id: int, body: StageBody) -> dict[str, Any]:  # noqa: D401
        """Step the focus video back to 提纲 (or clear that override) — the pipeline can move backwards."""
        store.topic(topic_id)
        if body.stage not in (None, "outline"):
            raise ValueError("只能退回到提纲")
        title = store.topic(topic_id)["title"][:30]
        store.log_event("stage", f"《{title}》{'退回提纲重写' if body.stage == 'outline' else '提纲改好了，回到录制'}", topic_id)
        return {"topic": store.update_topic(topic_id, manual_stage=body.stage)}

    # -- article line ------------------------------------------------------

    def _write_topic(topic_id: int, instruction: str = "") -> None:
        failed = None
        try:
            topic = store.topic(topic_id)
            result = writer.write_article(
                topic,
                vault_raw=vault_path(),
                drafts_dir=drafts_root,
                transcript=_transcript_for_article(topic),
                instruction=instruction,
                **({"write_fn": write_fn} if write_fn else {}),
            )
            current = store.topic(topic_id)
            store.update_topic(
                topic_id,
                article_path=result["article_path"],
                write_state=None,
                write_error=None,
                status="drafting" if current["status"] == "todo" else current["status"],
            )
            # 9/29 起写完不自动配图：Park 先看文章、定稿，再配（打包页定稿文章时开始配）。还要重写的话不白画一轮。
        except Exception as exc:  # noqa: BLE001 - shown on the topic card
            logger.warning("writing topic %s failed: %s", topic_id, exc)
            failed = str(exc)[:300] or type(exc).__name__
            store.update_topic(topic_id, write_state="failed", write_error=failed)
        finally:
            _pack_job_done(topic_id, "article", failed, slot=topic_id)

    @app.post("/api/topics/{topic_id}/polish")
    def start_polish(topic_id: int) -> dict[str, Any]:
        """润色（10/2 Park）：把已经写好的 X 图文文章按付息稿的逻辑重新整理一遍。原文先备份；
        插图行原样保留。改完文章，自动档会重新定稿，公众号排版跟着重排。"""
        from . import coupon

        topic = store.topic(topic_id)
        article = _article_path(topic)
        if article is None or not article.is_file():
            raise HTTPException(status_code=400, detail="还没有文章，先写好再润色")
        with writing_lock:
            if topic_id in writing:
                return {"started": False, "message": "这篇正在写或正在润色"}
            writing.add(topic_id)
        store.update_topic(topic_id, write_state="running", write_error=None)

        def run() -> None:
            failed = None
            try:
                coupon.polish_article(article, **({"write_fn": write_fn} if write_fn else {}))
                store.update_topic(topic_id, write_state=None, write_error=None)
                store.log_event("copy", f"《{topic['title'][:24]}》按付息稿润色好了", topic_id)
            except Exception as exc:  # noqa: BLE001 - 打包页显示
                logger.warning("polish %s failed: %s", topic_id, exc)
                failed = str(exc)[:300] or type(exc).__name__
                store.update_topic(topic_id, write_state="failed", write_error=failed)
            finally:
                _pack_job_done(topic_id, "article", failed, slot=topic_id)

        threading.Thread(target=run, name=f"polish-{topic_id}", daemon=True).start()
        return {"started": True, "message": "开始润色（按付息稿：开头发债、每段付息、最后兑付本金），一般 2–5 分钟"}

    @app.post("/api/topics/{topic_id}/write")
    def start_write(topic_id: int, body: WriteBody | None = None) -> dict[str, Any]:
        topic = store.topic(topic_id)
        instruction = (body.instruction if body else "") or ""
        if topic.get("article_path") and not instruction.strip():
            # 9/29 Park：重写要知道会怎么不一样——已经写过的，重写必须说这次要怎么改
            raise HTTPException(status_code=400, detail="重写要先说这次要怎么改")
        if topic["formats"] == "video":
            # 视频拍完了，文字版也能发（研习室、X）。点了写文章就是要写，不再挡他。
            store.update_topic(topic_id, formats="both")
            store.log_event("stage", f"《{topic['title'][:24]}》加了文章版", topic_id)
        with writing_lock:
            if topic_id in writing:
                return {"started": False, "message": "这篇正在写"}
            writing.add(topic_id)
        store.update_topic(topic_id, write_state="running", write_error=None)
        threading.Thread(target=_write_topic, args=(topic_id, instruction), name=f"write-{topic_id}", daemon=True).start()
        return {"started": True, "message": "开始写了，一般 1–5 分钟"}

    def _outline_topic(topic_id: int) -> None:
        from . import outline

        try:
            result = outline.write_outline(
                store.topic(topic_id), vault_raw=vault_path(), drafts_dir=drafts_root,
                adjustments=latest_adjustments(), **({"write_fn": outline_fn} if outline_fn else {})
            )
            store.update_topic(topic_id, outline_path=result["outline_path"], outline_state=None, outline_error=None, manual_stage=None)
            store.log_event("outline", f"《{store.topic(topic_id)['title'][:30]}》的骨架写好了", topic_id)
            _run_qa(topic_id)
            _start_coupon(topic_id)  # 10/2 Park：骨架后面接着出付息稿
        except Exception as exc:  # noqa: BLE001 - shown on the topic card
            logger.warning("skeleton topic %s failed: %s", topic_id, exc)
            store.update_topic(topic_id, outline_state="failed", outline_error=str(exc)[:300] or type(exc).__name__)
            store.log_event("outline", f"《{store.topic(topic_id)['title'][:24]}》骨架生成失败：{str(exc)[:60]}", topic_id)
        finally:
            with writing_lock:
                writing.discard(-topic_id)

    # -- 付息稿（10/2 Park：观众买了你的国债——开头发债、每 10 秒付息、最后兑付本金）--------------------
    coupon_errors: dict[int, str] = {}

    def _coupon_topic(topic_id: int) -> None:
        from . import coupon, outline

        try:
            topic = store.topic(topic_id)
            sk = outline.read_outline(topic)
            coupon.write_coupon(topic, skeleton=(sk or {}).get("markdown", ""), vault_raw=vault_path(), drafts_dir=drafts_root,
                                **({"write_fn": coupon_fn} if coupon_fn else {}))
            store.log_event("outline", f"《{topic['title'][:30]}》的付息稿写好了", topic_id)
        except Exception as exc:  # noqa: BLE001 - shown on the tab
            logger.warning("coupon topic %s failed: %s", topic_id, exc)
            coupon_errors[topic_id] = str(exc)[:300] or type(exc).__name__
        finally:
            with writing_lock:
                writing.discard(60_000 + topic_id)

    def _start_coupon(topic_id: int) -> bool:
        from . import coupon

        try:
            coupon.load_framework()  # 框架文件不在：不起线程，等他放好了再点
        except Exception as exc:  # noqa: BLE001
            coupon_errors[topic_id] = str(exc)[:300]
            return False
        with writing_lock:
            if 60_000 + topic_id in writing:
                return False
            writing.add(60_000 + topic_id)
        coupon_errors.pop(topic_id, None)
        threading.Thread(target=_coupon_topic, args=(topic_id,), name=f"coupon-{topic_id}", daemon=True).start()
        return True

    @app.get("/api/topics/{topic_id}/coupon")
    def get_coupon(topic_id: int) -> dict[str, Any]:
        from . import coupon

        store.topic(topic_id)
        with writing_lock:
            running = 60_000 + topic_id in writing
        return {"running": running, "error": coupon_errors.get(topic_id), "coupon": coupon.read_coupon(drafts_root, topic_id)}

    @app.post("/api/topics/{topic_id}/coupon")
    def start_coupon(topic_id: int) -> dict[str, Any]:
        from . import coupon

        topic = store.topic(topic_id)
        if not topic.get("outline_path"):
            raise ValueError("先写骨架，付息稿是照着骨架排的")
        coupon.load_framework()
        if not _start_coupon(topic_id):
            return {"started": False, "message": "正在写"}
        return {"started": True, "message": "开始写付息稿，一般 1–3 分钟"}

    @app.put("/api/topics/{topic_id}/coupon")
    def put_coupon(topic_id: int, body: ArticleBody) -> dict[str, Any]:
        from . import coupon

        store.topic(topic_id)
        if not body.markdown.strip():
            raise ValueError("付息稿不能为空")
        path = drafts_root / f"topic-{topic_id}" / coupon.FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body.markdown if body.markdown.endswith("\n") else body.markdown + "\n", encoding="utf-8")
        return coupon.read_coupon(drafts_root, topic_id) or {}

    @app.post("/api/topics/{topic_id}/outline")
    def start_outline(topic_id: int) -> dict[str, Any]:
        topic = store.topic(topic_id)
        if topic["formats"] == "article":
            raise ValueError("这个选题只写文章；先把形式改成「视频」或「文章 + 视频」")
        # 框架文件在 Obsidian 里，Park 随时会改。先读一次，缺了就当场说清楚，
        # 而不是让线程在后台失败、他等两分钟才看到。
        outline_mod.load_framework()
        with writing_lock:
            if -topic_id in writing:
                return {"started": False, "message": "正在写"}
            writing.add(-topic_id)
        store.update_topic(topic_id, outline_state="running", outline_error=None)
        threading.Thread(target=_outline_topic, args=(topic_id,), name=f"outline-{topic_id}", daemon=True).start()
        return {"started": True, "message": "开始写骨架，一般 1–2 分钟"}

    title_errors: dict[int, str] = {}

    def _article_preview(markdown: str, limit: int = 3000) -> dict[str, Any]:
        lines = markdown.splitlines()
        title = next((l[2:].strip() for l in lines if l.startswith("# ")), "")
        paras = [re.sub(r"[*_`>#]+", "", l).strip() for l in lines if l.strip() and not l.startswith("# ")]
        paras = [p for p in paras if p]
        text = "\n\n".join(paras)
        return {"title": title, "summary": (paras[0] if paras else "")[:120], "text": text[:limit], "chars": len(re.sub(r"\s", "", text))}

    def _video_transcript(topic: dict[str, Any]) -> str:
        """视频项目里的原话：优先校对过标点的句子表，没有再用 SRT。"""
        from . import koubo, titles

        if not topic.get("video_project"):
            # 补发的旧视频没有视频项目：用拆解时转写的逐字稿 transcript.json（full_text）。
            # 同目录的 text.txt 是抖音简介，不是原话，只有几十到几百字。
            vid = topic.get("published_video_id")
            if vid and str(vid).isdigit():
                for path in sorted((downloads_dir / "douyin").glob(f"*/{vid}/transcript.json")):
                    try:
                        text = str(json.loads(path.read_text(encoding="utf-8")).get("full_text") or "").strip()
                    except (OSError, ValueError, AttributeError):
                        continue
                    if text:
                        return text
            return ""
        try:
            base = video_project.project_dir(video_root(), topic["video_project"])
            sentences = base / "subtitles" / "transcript.sentences.json"
            if sentences.is_file():
                data = json.loads(sentences.read_text(encoding="utf-8"))
                rows = data.get("transcript") if isinstance(data, dict) else data
                return "".join(str(r.get("text") or "") for r in rows or [] if isinstance(r, dict))
            srt = koubo.find_srt(base)
            return titles.srt_text(srt) if srt else ""
        except (VideoProjectError, OSError, ValueError):
            return ""

    def _transcript_for_article(topic: dict[str, Any]) -> str:
        """写文章要的原话。有成片、却找不到字幕时不写，请 Park 从剪映导出 SRT。
        9/29 Park：9/28 那条的研习室文章是照他 Obsidian 里的语音笔记写的，不是视频原话——项目里找不到字幕，
        写作就悄悄退回了笔记。字幕是他在剪映里校对过的原话，比机器转写准，所以不拿机器转写顶替，也不拿笔记顶替。"""
        text = _video_transcript(topic)
        if text.strip() or not topic.get("video_project"):
            return text
        if final_video_path(topic) is None:
            return ""  # 还没拍完：只有笔记，照笔记写是对的
        raise writer.WriterError("没找到这条的字幕：剪映导出时勾上「字幕 SRT」，把 .srt 放进项目文件夹（和成片放一起也行），再点重写")

    def _title_material(topic: dict[str, Any]) -> tuple[str, str]:
        """转写（视频项目里的 SRT）和骨架。都没有也能出，只是依据少。"""
        from . import koubo, outline, titles

        transcript = _video_transcript(topic)
        skeleton = (outline.read_outline(topic) or {}).get("markdown", "")
        return transcript, skeleton

    def _title_topic(topic_id: int) -> None:
        from . import titles

        try:
            topic = store.topic(topic_id)
            transcript, skeleton = _title_material(topic)
            titles.write_titles(topic, transcript=transcript, skeleton=skeleton, drafts_dir=drafts_root)
            store.log_event("copy", f"《{topic['title'][:24]}》的标题候选出好了", topic_id)
        except Exception as exc:  # noqa: BLE001 - 弹窗里显示
            logger.warning("titles topic %s failed: %s", topic_id, exc)
            title_errors[topic_id] = str(exc)[:300] or type(exc).__name__
        finally:
            with writing_lock:
                writing.discard(30_000 + topic_id)

    @app.post("/api/topics/{topic_id}/titles")
    def start_titles(topic_id: int) -> dict[str, Any]:
        from . import titles

        store.topic(topic_id)
        titles.load_framework()  # 工作流文件缺了当场说，别让他等一分钟才看到
        with writing_lock:
            if 30_000 + topic_id in writing:
                return {"started": False, "message": "正在出"}
            writing.add(30_000 + topic_id)
        title_errors.pop(topic_id, None)
        threading.Thread(target=_title_topic, args=(topic_id,), name=f"titles-{topic_id}", daemon=True).start()
        return {"started": True, "message": "开始出标题，一般半分钟到一分钟"}

    @app.get("/api/topics/{topic_id}/titles")
    def get_titles(topic_id: int) -> dict[str, Any]:
        from . import titles

        store.topic(topic_id)
        with writing_lock:
            running = 30_000 + topic_id in writing
        return {"running": running, "error": title_errors.get(topic_id), "result": titles.read_titles(drafts_root, topic_id)}

    layout_errors: dict[int, str] = {}

    def _article_path(topic: dict[str, Any]) -> Path | None:
        return Path(topic["article_path"]) if topic.get("article_path") else None

    @app.post("/api/topics/{topic_id}/layout")
    def start_layout(topic_id: int) -> dict[str, Any]:
        """用 gzh-design skill 给研习室文章排版；公众号和研习室发布都用这份。"""
        from . import gzh_layout

        topic = store.topic(topic_id)
        article = _article_path(topic)
        if article is None or not article.is_file():
            raise ValueError("先在「研习室文章」写好文章")
        with writing_lock:
            if 50_000 + topic_id in writing:
                return {"started": False, "message": "正在排"}
            writing.add(50_000 + topic_id)
        layout_errors.pop(topic_id, None)

        def run() -> None:
            try:
                gzh_layout.layout(article)
                store.log_event("copy", f"《{topic['title'][:24]}》用 gzh 排好版了", topic_id)
            except Exception as exc:  # noqa: BLE001 - 文章页显示
                logger.warning("gzh layout %s failed: %s", topic_id, exc)
                layout_errors[topic_id] = str(exc)[:300] or type(exc).__name__
            finally:
                _pack_job_done(topic_id, "wx", layout_errors.get(topic_id), slot=50_000 + topic_id)

        threading.Thread(target=run, name=f"layout-{topic_id}", daemon=True).start()
        return {"started": True, "message": f"开始用 gzh 排版（{gzh_layout.THEME}），一般 5–10 分钟"}

    @app.get("/api/topics/{topic_id}/layout")
    def layout_state(topic_id: int) -> dict[str, Any]:
        from . import gzh_layout

        topic = store.topic(topic_id)
        with writing_lock:
            running = 50_000 + topic_id in writing
        return {"running": running, "error": layout_errors.get(topic_id), **gzh_layout.state(_article_path(topic))}

    illustrate_errors: dict[int, str] = {}

    def start_illustrate(topic_id: int) -> bool:
        """配图（Codex 画，4–8 张，5–10 分钟）。已经在配就不再起一个。"""
        from . import illustrate as il

        article = _article_path(store.topic(topic_id))
        if article is None or not article.is_file():
            raise ValueError("先写好文章再配图")
        with writing_lock:
            if 60_000 + topic_id in writing:
                return False
            writing.add(60_000 + topic_id)
        illustrate_errors.pop(topic_id, None)

        def run() -> None:
            try:
                r = il.illustrate(article)
                store.log_event("copy", f"《{store.topic(topic_id)['title'][:24]}》配好了 {len(r['images'])} 张图", topic_id)
            except Exception as exc:  # noqa: BLE001 - 发布台显示
                logger.warning("illustrate %s failed: %s", topic_id, exc)
                illustrate_errors[topic_id] = str(exc)[:300] or type(exc).__name__
            finally:
                _pack_job_done(topic_id, "figs", illustrate_errors.get(topic_id), slot=60_000 + topic_id)

        threading.Thread(target=run, name=f"illustrate-{topic_id}", daemon=True).start()
        return True

    @app.post("/api/topics/{topic_id}/illustrate")
    def post_illustrate(topic_id: int) -> dict[str, Any]:
        started = start_illustrate(topic_id)
        return {"started": started, "message": "开始配图（小黑手绘），一般 5–10 分钟" if started else "正在配"}

    @app.get("/api/topics/{topic_id}/illustrate")
    def get_illustrate(topic_id: int) -> dict[str, Any]:
        from urllib.parse import quote

        from . import illustrate as il

        topic = store.topic(topic_id)
        with writing_lock:
            running = 60_000 + topic_id in writing
        st = il.state(_article_path(topic))
        for img in st["images"]:
            img["url"] = f"/api/topics/{topic_id}/article-file/{il.FOLDER}/{quote(img['file'])}"
        return {"running": running, "error": illustrate_errors.get(topic_id), **st}

    # -- 咨询录音：上传 → 转写 + 分析 → vault 010_咨询/ 一篇左右对照的笔记 --------
    consult_running: set[str] = set()
    consult_lock = threading.Lock()

    def _consult_row(row: dict[str, Any]) -> dict[str, Any]:
        from urllib.parse import quote

        with consult_lock:
            running = row["slug"] in consult_running
        stage = row.get("stage")
        if stage in ("queued", "transcribing", "analyzing", "client") and not running:
            stage = "interrupted"
        note = row.get("note")
        slug_q = quote(row["slug"])
        return {
            "slug": row["slug"], "name": row.get("name"), "day": row.get("day"), "stage": stage, "running": running,
            "error": row.get("error"), "minutes": row.get("minutes"), "note": note, "missing": row.get("missing") or [],
            "obsidian": f"obsidian://open?path={quote(note)}" if note else None,
            "client": f"/api/consults/{slug_q}/client.html" if row.get("client") else None,
            "pdf": f"/api/consults/{slug_q}/client.pdf" if row.get("pdf") else None,
            "client_file": row.get("client"),
        }

    def start_consult(slug: str) -> bool:
        from urllib.parse import quote

        from . import consult

        folder = consult.root() / slug
        with consult_lock:
            if slug in consult_running:
                return False
            consult_running.add(slug)
        consult.save_state(folder, stage="queued", error=None)

        def run() -> None:
            try:
                note = consult.run(folder, vault.vault_root(vault_path()))
                _open_in_browser(f"obsidian://open?path={quote(str(note))}")
            except Exception as exc:  # noqa: BLE001 - shown to Park on the card
                logger.warning("consult %s failed: %s", slug, exc)
                consult.save_state(folder, stage="failed", error=str(exc)[:300] or type(exc).__name__, pid=None)
            finally:
                with consult_lock:
                    consult_running.discard(slug)

        threading.Thread(target=run, name=f"consult-{slug}", daemon=True).start()
        return True

    @app.get("/api/consults")
    def get_consults() -> dict[str, Any]:
        from . import consult

        return {"consults": [_consult_row(r) for r in consult.jobs()][:20]}

    @app.get("/api/consults/playbook")
    def consult_playbook() -> dict[str, Any]:
        """做咨询时照着过的「诊断流程」：vault 010_咨询/诊断流程.md，每次打开都重新读。"""
        from urllib.parse import quote

        from . import consult

        doc = consult.playbook(vault.vault_root(vault_path()))
        return {**doc, "obsidian": "obsidian://open?path=" + quote(doc["path"])}

    @app.get("/api/consults/scripts")
    def consult_scripts() -> dict[str, Any]:
        """回微信用的「统一话术」：vault 010_咨询/统一话术.md，每次打开都重新读。"""
        from urllib.parse import quote

        from . import consult

        doc = consult.playbook(vault.vault_root(vault_path()), consult.SCRIPTS)
        return {**doc, "obsidian": "obsidian://open?path=" + quote(doc["path"])}

    @app.post("/api/consults")
    async def post_consult(request: Request) -> dict[str, Any]:
        from . import consult

        form = await request.form()
        upload, name = form.get("file"), str(form.get("name") or "").strip()
        if upload is None or not getattr(upload, "filename", ""):
            raise HTTPException(status_code=400, detail="没收到录音文件")
        suffix = Path(upload.filename).suffix.lower()
        if suffix not in consult.MEDIA_SUFFIXES:
            raise HTTPException(status_code=400, detail=f"不认识这种文件：{suffix or '没有扩展名'}（支持 m4a、mp3、wav、mp4、mov 等）")
        if not name:
            raise HTTPException(status_code=400, detail="写一下客户是谁")
        day = parse_day(str(form.get("day") or "") or None)
        slug = consult.slug(name, day)
        folder = consult.root() / slug
        with consult_lock:
            if slug in consult_running:
                raise HTTPException(status_code=409, detail="这一场正在处理，等它做完")
        folder.mkdir(parents=True, exist_ok=True)
        # 同一场重新上传：原件和之前的转写、分析、客户版都作废
        for old in [*folder.glob("audio.*"), *folder.glob(f"{consult.ORIGINAL}.*")]:
            old.unlink()
        for cache in ("transcript.json", consult.TEXT_FILE, "analysis.json", "client.json", "客户版.html"):
            (folder / cache).unlink(missing_ok=True)
        with (folder / f"{consult.ORIGINAL}{suffix}").open("wb") as out:
            while chunk := await upload.read(1 << 20):
                out.write(chunk)
        consult.save_state(folder, name=consult.slug(name, day)[5:], day=day.isoformat(), original=upload.filename,
                           created_at=now_iso(), note=None, missing=[])
        start_consult(slug)
        return {"consult": _consult_row({"slug": slug, **consult.load_state(folder)})}

    def _consult_folder(slug: str) -> Path:
        from . import consult

        folder = consult.root() / slug
        if folder.parent != consult.root() or not (folder / "state.json").is_file():
            raise HTTPException(status_code=404, detail="找不到这一场")
        return folder

    @app.get("/api/consults/{slug}/client.html")
    def consult_client(slug: str) -> Response:
        page = _consult_folder(slug) / "客户版.html"
        if not page.is_file():
            raise HTTPException(status_code=404, detail="客户版还没做好")
        return FileResponse(page, media_type="text/html; charset=utf-8")

    @app.get("/api/consults/{slug}/client.pdf")
    def consult_client_pdf(slug: str) -> Response:
        from . import consult

        pdf = consult.load_state(_consult_folder(slug)).get("pdf")
        if not pdf or not Path(pdf).is_file():
            raise HTTPException(status_code=404, detail="客户版 PDF 还没做好")
        return FileResponse(pdf, media_type="application/pdf")

    @app.get("/api/clients")
    def get_clients() -> dict[str, Any]:
        """「客户」页：一个客户一行，档案 + 每一场咨询的两份 summary。"""
        from . import consult

        from urllib.parse import quote

        root = vault.vault_root(vault_path())
        rows = consult.clients(root)
        for row in rows:
            row["consults"] = [_consult_row(c) for c in row["consults"]]
            row["consults"].sort(key=lambda c: c.get("day") or "", reverse=True)
            base = f"/api/clients/{quote(row['name'])}/file/"
            for day in row["files"]:
                for doc in day["sent"]:
                    doc["pdf_url"] = base + quote(doc["pdf"]) if doc["pdf"] else None
                    doc["html_url"] = base + quote(doc["html"]) if doc["html"] else None
                for doc in day["mine"]:
                    doc["obsidian"] = "obsidian://open?path=" + quote(str(consult.client_dir(root, row["name"]) / doc["file"]))
        return {"clients": rows, "fields": list(consult.PROFILE_FIELDS)}

    def _client_file(name: str, file: str) -> Path:
        from . import consult

        home = consult.client_dir(vault.vault_root(vault_path()), name)
        path = home / file
        if home.name != name or "/" in file or file.startswith(".") or not path.is_file():
            raise HTTPException(status_code=404, detail="找不到这个文件")
        return path

    @app.get("/api/clients/{name}/file/{file}")
    def client_file(name: str, file: str) -> Response:
        path = _client_file(name, file)
        media = {".pdf": "application/pdf", ".html": "text/html; charset=utf-8", ".md": "text/markdown; charset=utf-8"}
        return FileResponse(path, media_type=media.get(path.suffix, "application/octet-stream"))

    @app.post("/api/clients/{name}/reveal")
    def reveal_client_file(name: str, file: str) -> dict[str, Any]:
        """在 Finder 里选中这个文件（拖进微信发给客户）。"""
        path = _client_file(name, file)
        if sys.platform == "darwin" and not os.environ.get("CONTENT_STUDIO_NO_OPEN"):
            subprocess.Popen(["open", "-R", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"path": str(path)}

    @app.put("/api/clients/{name}")
    def put_client(name: str, body: dict[str, Any]) -> dict[str, Any]:
        from . import consult

        home = consult.client_dir(vault.vault_root(vault_path()), name)
        if home.name != name:
            raise HTTPException(status_code=400, detail="客户名里有不能用的字符")
        return {"profile": consult.write_profile(home, body)}

    @app.post("/api/consults/{slug}/reveal")
    def reveal_consult(slug: str, what: str = "folder") -> dict[str, Any]:
        """在 Finder 里指给 Park 看：客户版 PDF（发给客户用）或本机留的原件和文字。"""
        from . import consult

        folder = _consult_folder(slug)
        state = consult.load_state(folder)
        client = state.get("pdf") or state.get("client")
        target = Path(client) if what == "client" and client else (consult.audio_of(folder) or folder)
        if sys.platform == "darwin" and not os.environ.get("CONTENT_STUDIO_NO_OPEN"):
            subprocess.Popen(["open", "-R", str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"path": str(target)}

    @app.post("/api/consults/{slug}/retry")
    def retry_consult(slug: str) -> dict[str, Any]:
        from . import consult

        folder = _consult_folder(slug)
        start_consult(slug)
        return {"consult": _consult_row({"slug": slug, **consult.load_state(folder)})}

    @app.get("/api/topics/{topic_id}/article-file/{relative:path}")
    def article_file(topic_id: int, relative: str) -> Response:
        """文章目录里的图（配图），只读，只给图片。"""
        article = _article_path(store.topic(topic_id))
        if article is None:
            raise HTTPException(status_code=404, detail="还没有文章")
        base = article.parent.resolve()
        path = (base / relative).resolve()
        if base not in path.parents or not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise HTTPException(status_code=404, detail="文件不存在")
        return FileResponse(path, headers={"Cache-Control": "no-store"})

    @app.get("/api/topics/{topic_id}/wechat-preview.html")
    def wechat_preview(topic_id: int) -> Response:
        """公众号里会是什么样：和发布时用的是同一份正文（有 gzh 排版用 gzh 的，没有用基础排版），手机宽度。"""
        import html as html_mod

        from . import gzh_layout, wechat_publish

        article = _article_path(store.topic(topic_id))
        if article is None or not article.is_file():
            raise HTTPException(status_code=404, detail="还没写文章")
        title, digest_text, body = wechat_publish.render_html(article.read_text(encoding="utf-8"))
        styled = gzh_layout.current(article)
        if styled is not None:
            body = styled.read_text(encoding="utf-8")
        kind = "gzh 排版（橄榄手记）" if styled is not None else "基础排版（还没用 gzh 排）"
        # 配图是文章目录里的相对路径：预览里换成能打开的地址（发的时候另外传到微信）
        body = re.sub(r'(<img\b[^>]*?\bsrc=")(?!https?:|data:)([^"]+)"', lambda m: f'{m.group(1)}/api/topics/{topic_id}/article-file/{m.group(2)}"', body)
        doc = ('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>'
               '<body style="margin:0;background:#ededed;font-family:-apple-system,PingFang SC,sans-serif">'
               f'<div style="max-width:390px;margin:0 auto;background:#fff;min-height:100vh;padding:20px 16px 40px;box-sizing:border-box">'
               f'<div style="font-size:12px;color:#999;margin-bottom:10px">预览 · {html_mod.escape(kind)}</div>'
               f'<h1 style="font-size:22px;line-height:1.4;margin:0 0 8px;color:#111">{html_mod.escape(title)}</h1>'
               f'<div style="font-size:14px;color:#576b95;margin-bottom:18px">Park的AI世界</div>{body}</div></body></html>')
        return Response(content=doc, media_type="text/html; charset=utf-8",
                        headers={"Content-Security-Policy": "sandbox", "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})

    @app.get("/api/topics/{topic_id}/layout.html")
    def layout_html(topic_id: int) -> Response:
        """排版预览。放进隔离的源：页面是模型生成的，不许碰工作台接口。"""
        from . import gzh_layout

        article = _article_path(store.topic(topic_id))
        page = article.parent / gzh_layout.FILENAME if article else None
        if page is None or not page.is_file():
            raise HTTPException(status_code=404, detail="还没排版")
        doc = f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body style="margin:0;background:#fff">{page.read_text(encoding="utf-8")}</body></html>'
        return Response(content=doc, media_type="text/html; charset=utf-8",
                        headers={"Content-Security-Policy": "sandbox", "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})

    xhs_errors: dict[int, str] = {}

    @app.post("/api/topics/{topic_id}/xhs")
    def start_xhs(topic_id: int) -> dict[str, Any]:
        """研习室文章一字不改排成小红书 3:4 图。"""
        from . import xhs_cards

        topic = store.topic(topic_id)
        article = _article_path(topic)
        if article is None or not article.is_file():
            raise ValueError("先在「研习室文章」写好文章，小红书图文用的就是那一篇")
        with writing_lock:
            if 60_000 + topic_id in writing:
                return {"started": False, "message": "正在出图"}
            writing.add(60_000 + topic_id)
        xhs_errors.pop(topic_id, None)

        def run() -> None:
            try:
                meta = xhs_cards.make_cards(article)
                store.log_event("copy", f"《{topic['title'][:24]}》小红书图文出好了：{meta['images']} 张", topic_id)
            except Exception as exc:  # noqa: BLE001 - 发布台显示
                logger.warning("xhs cards %s failed: %s", topic_id, exc)
                xhs_errors[topic_id] = str(exc)[:300] or type(exc).__name__
            finally:
                _pack_job_done(topic_id, "xhs", xhs_errors.get(topic_id), slot=60_000 + topic_id)

        threading.Thread(target=run, name=f"xhs-{topic_id}", daemon=True).start()
        return {"started": True, "message": "开始出小红书图文，十几秒"}

    @app.get("/api/topics/{topic_id}/xhs")
    def xhs_state(topic_id: int) -> dict[str, Any]:
        from . import xhs_cards

        topic = store.topic(topic_id)
        with writing_lock:
            running = 60_000 + topic_id in writing
        st = xhs_cards.state(_article_path(topic))
        return {"running": running, "error": xhs_errors.get(topic_id), **st,
                "urls": [f"/api/topics/{topic_id}/xhs/{name}" for name in st["images"]]}

    @app.get("/api/topics/{topic_id}/xhs/{name}")
    def xhs_image(topic_id: int, name: str) -> Response:
        from . import xhs_cards

        article = _article_path(store.topic(topic_id))
        if article is None or not re.fullmatch(r"\d{2}\.png", name):
            raise HTTPException(status_code=404, detail="没有这张")
        path = article.parent / xhs_cards.FOLDER / name
        if not path.is_file():
            raise HTTPException(status_code=404, detail="没有这张")
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.post("/api/topics/{topic_id}/xhs/reveal")
    def xhs_reveal(topic_id: int) -> dict[str, Any]:
        """在访达里打开小红书图片文件夹并选中第一张（封面），上传时直接拖或选。只打开，不动文件。"""
        import subprocess

        from . import xhs_cards

        article = _article_path(store.topic(topic_id))
        first = article.parent / xhs_cards.FOLDER / "01.png" if article else None
        if first is None or not first.is_file():
            raise ValueError("还没出图：先点「出图文」")
        subprocess.run(["open", "-R", str(first)], check=False, timeout=10)
        return {"ok": True}

    @app.get("/api/topics/{topic_id}/xhs.zip")
    def xhs_zip(topic_id: int) -> Response:
        """按顺序打包：01 是封面，手机上按文件名顺序选就对了。"""
        import io
        import zipfile

        from . import xhs_cards

        topic = store.topic(topic_id)
        article = _article_path(topic)
        folder = article.parent / xhs_cards.FOLDER if article else None
        images = sorted(folder.glob("*.png")) if folder and folder.is_dir() else []
        if not images:
            raise HTTPException(status_code=404, detail="还没出图")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
            for image in images:
                zf.write(image, image.name)
        from urllib.parse import quote

        filename = quote(f"小红书图文-{topic['title'][:20]}.zip")
        return Response(content=buf.getvalue(), media_type="application/zip",
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"})

    @app.get("/api/topics/{topic_id}/outline")
    def get_outline(topic_id: int) -> dict[str, Any]:
        from . import outline

        data = outline.read_outline(store.topic(topic_id))
        if data is None:
            raise HTTPException(status_code=404, detail="这个选题还没有骨架")
        return data

    @app.put("/api/topics/{topic_id}/outline")
    def put_outline(topic_id: int, body: ArticleBody) -> dict[str, Any]:
        from . import outline

        topic = store.topic(topic_id)
        if not body.markdown.strip():
            raise ValueError("提纲不能为空")
        path = Path(topic["outline_path"]) if topic.get("outline_path") else drafts_root / f"topic-{topic_id}" / outline_mod.FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body.markdown if body.markdown.endswith("\n") else body.markdown + "\n", encoding="utf-8")
        if not topic.get("outline_path"):
            store.update_topic(topic_id, outline_path=str(path))
        return outline.read_outline(store.topic(topic_id)) or {}

    # -- video projects (口播 workflow) -----------------------------------

    def video_root() -> Path:
        return video_project.resolve_root(store.settings()["video_projects_root"] or None)

    @app.get("/api/video-projects")
    def list_video_projects() -> dict[str, Any]:
        try:
            root = video_root()
        except VideoProjectError as exc:
            return {"root": store.settings()["video_projects_root"] or str(video_project.DEFAULT_ROOTS[0]), "error": str(exc), "projects": []}
        linked = {t["video_project"]: t["id"] for t in store.topics(include_archived=True) if t.get("video_project")}
        return {"root": str(root), "error": None, "projects": [{**p, "topic_id": linked.get(p["name"])} for p in video_project.list_projects(root)]}

    @app.get("/api/topics/{topic_id}/video-project")
    def topic_video_project(topic_id: int) -> dict[str, Any]:
        topic = store.topic(topic_id)
        if not topic.get("video_project"):
            raise HTTPException(status_code=404, detail="这个选题还没有关联视频项目")
        return video_project.inspect(video_root(), topic["video_project"])

    @app.put("/api/topics/{topic_id}/video-project")
    def link_video_project(topic_id: int, body: VideoLinkBody) -> dict[str, Any]:
        store.topic(topic_id)
        if body.name:
            video_project.project_dir(video_root(), body.name)
        return store.update_topic(topic_id, video_project=body.name or None)

    @app.post("/api/topics/{topic_id}/video-project")
    def create_video_project(topic_id: int) -> dict[str, Any]:
        from . import outline

        topic = store.topic(topic_id)
        if topic.get("video_project"):
            raise ValueError("这个选题已经关联了视频项目")
        draft = outline.read_outline(topic)
        name = video_project.create_project(
            video_root(), title=topic["title"], today=date.today().isoformat(), outline_markdown=draft["markdown"] if draft else None
        )
        store.update_topic(topic_id, video_project=name)
        return video_project.inspect(video_root(), name)

    # -- Anna: the resident editor (right column) ---------------------------------

    from . import anna as anna_mod

    # One conversation across every page: switching pages changes what Anna sees, not who you talk to.
    ANNA_THREAD = "main"
    store.merge_anna_threads(ANNA_THREAD)
    anna_busy: set[str] = set()
    anna_errors: dict[str, str] = {}
    anna_lock = threading.Lock()

    def _anna_scope(scope: str) -> tuple[str, str, int | None]:
        kind, _, rest = scope.partition(":")
        if kind == "work":
            if not rest.isdigit():
                raise ValueError("这条视频不存在")
            return "work", anna_mod.SCOPE_LABELS["work"], int(rest)
        if kind not in anna_mod.SCOPE_LABELS:
            raise ValueError("未知页面")
        return kind, anna_mod.SCOPE_LABELS[kind], None

    def _report_context(video_id: str) -> str:
        """The teardown Park has open. Without it Anna answers 「这条教了什么方法」 from nothing —
        and the rule she then proposes for 记进标准 would be invented."""
        path = report_file(video_id)
        if path is None:
            return "## Park 正在看的拆解报告\n读不到这份报告"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return "## Park 正在看的拆解报告\n读不到这份报告"
        account = store.account(store.video(video_id)["account_id"]) if store.video(video_id) else None
        whose = "自己的视频" if account and account["is_self"] else "对标"
        facts = data.get("facts") or {}
        head = (f"## Park 正在看的拆解报告（{whose}）\n标题：{data.get('title')}\n作者：{data.get('author')}\n"
                f"点赞 {facts.get('likes')}（是他自己中位数的 {facts.get('multiple_of_median')} 倍）；播放 {facts.get('views')}；"
                f"收藏 {facts.get('collects')}；评论 {facts.get('comments')}；分享 {facts.get('shares')}\n"
                f"主线：{data.get('thesis')}\n开头：{json.dumps(data.get('opening'), ensure_ascii=False)[:600]}\n"
                f"为什么爆：{data.get('why_boom')}\n哪里散了：{data.get('why_scatter')}")
        budget = 7000
        parts = []
        for seg in data.get("segments") or []:
            block = (f"### {seg.get('index')} {seg.get('label')}（{seg.get('start')}–{seg.get('end')} 秒）"
                     f"{'｜跑题' if seg.get('drift') else ''}\n{seg.get('summary')}｜{seg.get('reason')}\n原话：{(seg.get('text') or '')[:400]}")
            if len(block) > budget:
                break
            budget -= len(block)
            parts.append(block)
        return head + "\n\n## 分段\n" + "\n\n".join(parts)

    def _anna_overview() -> str:
        """The standing index of the whole backend, ~1 screen, every turn.

        The page Park happens to be on is a wrapper over the same database; without this Anna
        can only see that one slice and has to guess at everything else. This is deliberately a
        table of contents, not the contents: 83 teardown reports would be tens of thousands of
        characters, and she needs to know they exist far more often than she needs to read one.
        """
        out: list[str] = []
        try:
            data = get_board(None)
            focus = data.get("focus")
            out.append(
                f"- 正在做：{('《' + focus['title'][:30] + '》｜在等：' + focus['next']['text']) if focus else '还没定'}"
                f"\n- 选题池 {len(data.get('pool') or [])} 条；剪辑/待发 {len(data.get('machine') or [])} 条；暂缓 {len(data.get('snoozed') or [])} 条"
            )
        except Exception:  # noqa: BLE001 - the overview must never break a turn
            pass
        try:
            items = vault.inbox(vault_path(), since=vault.window_start(7))
            by_source: dict[str, int] = {}
            for i in items:
                if i.get("triage") in (None, "back") and not i.get("used_by"):
                    by_source[i["source_label"]] = by_source.get(i["source_label"], 0) + 1
            out.append("- 进项近 7 天还没处理：" + ("；".join(f"{k} {v}" for k, v in by_source.items()) or "没有"))
        except Exception:  # noqa: BLE001
            pass
        try:
            r = get_reach(14)
            out.append(f"- 触达：今天 {r['today']}，近 7 天日均 {r['avg7']}")
        except Exception:  # noqa: BLE001
            pass
        try:
            # not `reports = reports()`: that makes the name local and the call raises.
            all_reports = reports()
            recent = "；".join(f"{x['author'] or ''}《{(x['title'] or '')[:20]}》" for x in all_reports[:8])
            out.append(f"- 拆解报告共 {len(all_reports)} 份，最近的：{recent}")
        except Exception:  # noqa: BLE001
            pass
        try:
            accounts = [a["nickname"] or "?" for a in store.followed_accounts()]
            out.append(f"- 关注的账号 {len(accounts)} 个：{'、'.join(accounts)}")
        except Exception:  # noqa: BLE001
            pass
        return "## 工作台全局（这是目录，不是全文）\n" + "\n".join(out) if out else ""

    def _anna_events(limit: int = 12) -> str:
        """最近发生了什么。Without it Anna cannot know a topic just moved out of 进项."""
        rows = store.events(limit)
        if not rows:
            return ""
        def when(iso: str) -> str:
            try:
                dt = datetime.fromisoformat(iso).astimezone()
                return dt.strftime("%m-%d %H:%M")
            except ValueError:
                return iso[:16]
        return "## 最近发生了什么\n" + "\n".join(f"- {when(r['at'])} {r['text']}" for r in rows)

    def _anna_context(kind: str, topic_id: int | None, note_path: str | None, report_id: str | None = None) -> str:
        """What Park is looking at right now, plus the backend index and recent history."""
        from . import board, opening, outline, qa, writer

        lines: list[str] = [x for x in (_anna_overview(), _anna_events()) if x]
        if kind == "input":
            day_value = date.today()
            for item in vault.dailies(vault_path(), day_value):
                if item.get("path"):
                    note = vault.read_note(vault_path(), item["path"])
                    lines.append(f"## 今天的{item['label']}\n{(note.get('body') or '')[:5000]}")
                else:
                    lines.append(f"## 今天的{item['label']}：还没出")
            triage = store.triage()
            used = {p: t for t in store.topics(include_archived=True) for p in (t.get("note_paths") or [])}
            items = vault.inbox(vault_path(), since=vault.window_start(7))[:30]  # vault.inbox compares against naive local mtimes
            rows = []
            for i in items:
                state = "已进加工中" if i["path"] in used else {"topic": "已拿来做", "shot": "拍过了", "ignored": "暂不拍"}.get((triage.get(i["path"]) or {}).get("status"), "还没处理")
                rows.append(f"- [{i['source_label']}] {i['title']}（{state}）{'：' + i['summary'][:80] if i.get('summary') else ''}")
            lines.append("## 近 7 天进来的（Clippings / 我收藏的 / 我写的）\n" + ("\n".join(rows) or "没有新东西"))
            if note_path:
                try:
                    note = vault.read_note(vault_path(), note_path)
                    lines.append(f"## Park 正在读的这篇：{note['title']}\n{(note.get('body') or '')[:8000]}")
                except (vault.VaultError, OSError):
                    pass
        elif kind == "board":
            data = get_board(None)
            stage_names = dict(board.STAGES)
            lines.append("## 看板\n" + ("\n".join(
                f"- [{stage_names.get(c['stage'], c['stage'])}] {c['title']}｜在等：{c['next']['text']}" + (f"｜三点 {c['qa']['total']}/15（{c['qa']['verdict']}）" if c.get("qa") else "") for c in data["cards"]) or "看板是空的"))
            k = data["streak"]
            lines.append(f"## 拍摄\n连续拍摄 {k.get('days')} 天；今天{'已经拍了' if k.get('today_done') else '还没拍'}；距上次拍 {k.get('days_since_last')} 天")
        elif kind == "work" and topic_id is not None:
            topic = store.topic(topic_id)
            lines.append(f"## 这条视频\n标题：{topic['title']}\n状态：{topic.get('status')}{'（已归档）' if topic.get('archived_at') else ''}\n备注：{topic.get('memo') or '（无）'}")
            draft = outline.read_outline(topic)
            lines.append("## 拍摄提纲\n" + (draft["markdown"] if draft else "还没写"))
            from . import coupon as coupon_mod

            cp = coupon_mod.read_coupon(drafts_root, topic_id)
            if cp:
                lines.append("## 付息稿（骨架排成的时间线：开头发债、每 10 秒付息、最后兑付本金）\n" + cp["markdown"][:6000])
            q = qa.load(drafts_root, topic_id)
            if q:
                lines.append("## 三点评分\n" + "\n".join(f"- {label} {q[key]['score']}/5：{q[key]['reason']}" for key, label in qa.POINTS) + f"\n- 结论：{q['verdict']}｜最该改：{q['fix']}" + (f"｜不要讲过头：{q['caution']}" if q.get("caution") else ""))
            op = opening.load(drafts_root, topic_id)
            if op:
                lines.append(f"## 开头 15 秒检查\n{'通过' if op.get('passed') else '没通过'}；主线在第 {op.get('stated_at')} 秒说出；前 15 秒字幕：{op.get('first_15s', '')[:400]}\n改法：{'；'.join(op.get('fixes') or [])}")
            if topic.get("video_project"):
                try:
                    info = video_project.inspect(video_root(), topic["video_project"])
                    gate = info.get("gate") or {}
                    lines.append(f"## 剪辑进度\n项目：{info.get('name')}；{info.get('summary')}；第 {info.get('current_step')} 步{'；已交付成片' if info.get('delivered') else ''}{'；等你：' + gate.get('title', '') if gate else ''}")
                except VideoProjectError as exc:
                    lines.append(f"## 剪辑进度\n读不到项目：{exc}")
            if topic.get("published_video_id"):
                v = store.video(topic["published_video_id"])
                if v:
                    me = store.self_account()
                    median = store.account_median(me["id"]) if me else None
                    mult = round(v["likes"] / median, 1) if median and v.get("likes") is not None else None
                    creator = _creator_rows(creator_db).get(v["video_id"]) or {}
                    lines.append(f"## 发出后的数据\n{v.get('published_at', '')[:10]} 发出；点赞 {v.get('likes')}（是自己中位数的 {mult} 倍）；播放 {v.get('views')}；收藏 {v.get('collects')}；评论 {v.get('comments')}；分享 {v.get('shares')}"
                                 + (f"；2 秒跳出 {creator.get('bounce_rate_2s')}；平均观看 {creator.get('avg_view_second')} 秒；涨粉 {creator.get('fan_increment')}" if creator else ""))
            sources = writer.topic_sources(vault_path(), topic, drafts_root)
            if sources:
                budget = 9000
                chunks = []
                for src in sources:
                    body = src["body"][: max(0, budget)]
                    budget -= len(body)
                    chunks.append(f"### {src['title']}\n{body}")
                lines.append("## 关联的素材\n" + "\n\n".join(chunks))
        elif kind == "output":
            me = store.self_account()
            if me is None:
                lines.append("## 已发出\n还没有连接自己的抖音号")
            else:
                median = store.account_median(me["id"])
                creator = _creator_rows(creator_db)
                cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()[:10]
                rows = []
                for v in [x for x in store.videos(me["id"]) if not x["is_image_post"] and (x["published_at"] or "") >= cutoff][:40]:
                    c = creator.get(v["video_id"]) or {}
                    mult = round(v["likes"] / median, 1) if median and v.get("likes") is not None else None
                    extra = f"；2 秒跳出 {round(c['bounce_rate_2s'] * 100)}%；平均观看 {round(c['avg_view_second'])} 秒；涨粉 {c.get('fan_increment')}；主页访问 {c.get('homepage_visit_count')}" if c.get("avg_view_second") is not None else ""
                    rows.append(f"- {(v['published_at'] or '')[:10]}｜{(v['title'] or '').split(chr(10))[0][:40]}｜点赞 {v['likes']}（{mult}×）；收藏 {v.get('collects')}；评论 {v.get('comments')}；分享 {v.get('shares')}{extra}")
                lines.append(f"## 近 90 天发出的视频（点赞中位数 {median}）\n" + ("\n".join(rows) or "没有"))
                rv = get_review()
                if rv.get("data"):
                    lines.append("## 最近一次每周复盘\n" + json.dumps(rv["data"], ensure_ascii=False)[:3000])
                k = today_plan.shooting_streak(date.today(), shot_days())
                lines.append(f"## 拍摄\n连续拍摄 {k.get('days')} 天；距上次拍 {k.get('days_since_last')} 天")
            if report_id:
                lines.append(_report_context(report_id))
        elif kind == "positioning":
            from . import positioning

            pos = positioning.read()
            lines.append("## Park 的定位页（他正在看的就是这份文件）\n" + (pos["markdown"][:12000] if pos["exists"] else "还没有定位文件"))
            me = store.self_account()
            if me is not None:
                lines.append(f"## 他的抖音主页\n昵称：{me.get('nickname')}；粉丝 {me.get('follower_count')}\n简介：{me.get('signature') or '（没抓到）'}")
                titles = [(v['title'] or '').split(chr(10))[0][:50] for v in store.videos(me["id"]) if not v["is_image_post"]][:12]
                lines.append("## 他最近的视频标题（做「陌生人自测」用）\n" + ("\n".join(f"- {t}" for t in titles) or "没有"))
        elif kind == "consults":
            from . import consult

            rows = consult.clients(vault.vault_root(vault_path()))
            for row in rows[:12]:
                p = row["profile"]
                lines.append(f"## 客户：{row['name']}\n来源：{p['来源'] or '未填'}；首次咨询收费：{p['首次咨询收费'] or '未填'}；"
                             f"画像：{p['画像'] or '未填'}；后续方案：{p['后续方案'] or '未填'}；报价：{p['报价'] or '未填'}")
                note = next((c.get("note") for c in row["consults"] if c.get("note")), None)
                if note and Path(note).is_file():
                    text = Path(note).read_text(encoding="utf-8").split("## 逐段对照")[0]
                    lines.append("### 最近一场咨询的总结\n" + text[-4000:])
            if not rows:
                lines.append("还没有咨询客户。")
        else:
            lines.append("Park 在设置页。")
        return "\n\n".join(lines)

    def _anna_page_label(scope: str) -> str:
        """「进项」「加工中」「《某条视频》」— shown next to each message so Park sees where it was said."""
        try:
            kind, label, topic_id = _anna_scope(scope)
            if kind == "work" and topic_id is not None:
                return f"《{store.topic(topic_id)['title'][:14]}》"
            return label
        except (ValueError, StoreError):
            return ""

    def _anna_vault() -> Path | None:
        try:
            return vault.vault_root(vault_path())
        except Exception:  # noqa: BLE001 - 没配 vault 就只用 <工作台> 块
            return None

    def _anna_dirs() -> dict[str, Path]:
        """vault 之外她能查的：每条视频的拆解报告、下载下来的老师流量视频（文字稿、信息）。"""
        return {"拆解报告：每条视频一个文件夹，report.md 是拆解": data_dir / "reports",
                "老师的流量视频：下载的视频、文字稿和信息": data_dir / "swipe"}

    @app.post("/api/anna/raw")
    def anna_raw(body: dict[str, Any]) -> dict[str, Any]:
        """Anna 整理的一篇，Park 点了按钮：写进 vault 的 003_park原始输出。"""
        root = _anna_vault()
        if root is None:
            raise ValueError("还没设 Obsidian 库")
        try:
            path = anna_mod.save_raw(root, str(body.get("target") or ""), str(body.get("body") or ""))
        except anna_mod.AnnaError as exc:
            raise ValueError(str(exc)) from None
        return {"path": str(path), "name": path.name, "folder": path.parent.name}

    def _anna_turn(scope: str, kind: str, label: str, topic_id: int | None, message: str, note_path: str | None, report_id: str | None = None) -> None:
        try:
            context = _anna_context(kind, topic_id, note_path, report_id)
            chat = store.anna_chat(ANNA_THREAD)
            if topic_id is not None:
                label = f"{label}《{store.topic(topic_id)['title']}》"
            reply = anna_mod.run_turn(scope=scope, scope_label=label, context=context, message=message, session_id=chat["session_id"],
                                      vault=_anna_vault(), extra_dirs=_anna_dirs(), **({"turn_fn": anna_fn} if anna_fn else {}))
            store.append_anna(ANNA_THREAD, {k: reply[k] for k in ("role", "text", "actions", "at", "scope")}, session_id=reply.get("session_id"))
        except Exception as exc:  # noqa: BLE001 - shown in the panel
            logger.warning("anna %s failed: %s", scope, exc)
            with anna_lock:
                anna_errors[ANNA_THREAD] = str(exc)[:300] or type(exc).__name__
        finally:
            with anna_lock:
                anna_busy.discard(ANNA_THREAD)

    @app.get("/api/anna")
    def get_anna(scope: str) -> dict[str, Any]:
        kind, label, topic_id = _anna_scope(scope)
        chat = store.anna_chat(ANNA_THREAD)
        with anna_lock:
            busy = ANNA_THREAD in anna_busy
            error = anna_errors.get(ANNA_THREAD)
        title = store.topic(topic_id)["title"] if kind == "work" and topic_id is not None else None
        pages: dict[str, str] = {}
        messages = []
        for m in chat["messages"]:
            where = m.get("scope") or ""
            if where and where not in pages:
                pages[where] = _anna_page_label(where)
            messages.append({**m, "page": pages.get(where, "")})
        return {"scope": scope, "label": label, "title": title, "messages": messages, "busy": busy, "error": error, "soul": [Path(p).name for p in anna_mod.load_soul()["sources"]]}

    @app.post("/api/anna")
    def post_anna(body: AnnaBody) -> dict[str, Any]:
        kind, label, topic_id = _anna_scope(body.scope)
        message = body.message.strip()
        if not message:
            raise ValueError("先说点什么")
        if len(message) > 4000:
            raise ValueError("一次最多 4000 字")
        if kind == "work" and topic_id is not None:
            store.topic(topic_id)
        with anna_lock:
            if ANNA_THREAD in anna_busy:
                return {"started": False, "message": "Anna 还在想上一条"}
            anna_busy.add(ANNA_THREAD)
            anna_errors.pop(ANNA_THREAD, None)
        store.append_anna(ANNA_THREAD, {"role": "park", "text": message, "at": now_iso(), "scope": body.scope})
        threading.Thread(target=_anna_turn, args=(body.scope, kind, label, topic_id, message, body.note_path, body.report_id), name=f"anna-{body.scope}", daemon=True).start()
        return {"started": True}

    @app.delete("/api/anna")
    def delete_anna(scope: str | None = None) -> dict[str, Any]:
        with anna_lock:
            if ANNA_THREAD in anna_busy:
                raise ValueError("Anna 还在想，等她答完再清")
            anna_errors.pop(ANNA_THREAD, None)
        store.clear_anna(ANNA_THREAD)
        return {"ok": True}

    # -- three-point QA (痛点具象度 / 认知反差度 / 交付可行性) --------------------

    qa_runs: dict[int, dict[str, Any]] = {}
    qa_lock = threading.Lock()

    def _qa_material(topic: dict[str, Any]) -> str:
        parts = [f"备注：{topic['memo']}"] if topic.get("memo") else []
        parts += [f"### {s['title']}\n{s['body']}" for s in writer.topic_sources(vault_path(), topic, drafts_root)]
        return "\n\n".join(parts)

    def _run_qa(topic_id: int) -> None:
        """Score a topic in the calling thread; failures are kept for the tab, never raised."""
        from . import outline, qa

        with qa_lock:
            if (qa_runs.get(topic_id) or {}).get("state") == "running":
                return
            qa_runs[topic_id] = {"state": "running"}
        try:
            topic = store.topic(topic_id)
            draft = outline.read_outline(topic)
            result = qa.score_topic(topic["title"], draft["markdown"] if draft else "", _qa_material(topic), **({"qa_fn": qa_fn} if qa_fn else {}))
            qa.save(drafts_root, topic_id, result)
            with qa_lock:
                qa_runs.pop(topic_id, None)
        except Exception as exc:  # noqa: BLE001 - shown on the outline tab
            logger.warning("qa topic %s failed: %s", topic_id, exc)
            with qa_lock:
                qa_runs[topic_id] = {"state": "failed", "error": str(exc)[:300] or type(exc).__name__}

    @app.get("/api/topics/{topic_id}/qa")
    def get_qa(topic_id: int) -> dict[str, Any]:
        from . import qa

        store.topic(topic_id)
        with qa_lock:
            run = dict(qa_runs.get(topic_id) or {})
        return {"state": run.get("state") or "idle", "error": run.get("error"), "result": qa.load(drafts_root, topic_id)}

    @app.post("/api/topics/{topic_id}/qa")
    def start_qa(topic_id: int) -> dict[str, Any]:
        topic = store.topic(topic_id)
        if not topic.get("outline_path") and not topic.get("memo") and not topic.get("note_paths"):
            raise ValueError("没有提纲也没有素材，没法评")
        with qa_lock:
            if (qa_runs.get(topic_id) or {}).get("state") == "running":
                return {"started": False, "message": "正在评"}
        threading.Thread(target=_run_qa, args=(topic_id,), name=f"qa-{topic_id}", daemon=True).start()
        return {"started": True, "message": "开始按三点评分，一般半分钟"}

    # -- opening 15 seconds ---------------------------------------------------

    opening_runs: dict[int, dict[str, Any]] = {}
    opening_lock = threading.Lock()

    def _score_opening(topic_id: int, project: Path, thesis: str) -> None:
        from . import opening

        try:
            result = opening.score_opening(project, thesis=thesis, **({"opening_fn": opening_fn} if opening_fn else {}))
            opening.save(drafts_root, topic_id, result)
            with opening_lock:
                opening_runs.pop(topic_id, None)
        except Exception as exc:  # noqa: BLE001 - shown on the video tab
            logger.warning("opening topic %s failed: %s", topic_id, exc)
            with opening_lock:
                opening_runs[topic_id] = {"state": "failed", "error": str(exc)[:300] or type(exc).__name__}

    @app.get("/api/topics/{topic_id}/opening")
    def get_opening(topic_id: int) -> dict[str, Any]:
        from . import opening

        _topic, project, _info = linked_project(topic_id)
        found = opening.find_subtitles(project)
        with opening_lock:
            run = dict(opening_runs.get(topic_id) or {})
        return {"state": run.get("state") or "idle", "error": run.get("error"), "result": opening.load(drafts_root, topic_id),
                "subtitles": {"path": str(found[0].relative_to(project)), "label": found[1]} if found else None}

    @app.post("/api/topics/{topic_id}/opening")
    def start_opening(topic_id: int) -> dict[str, Any]:
        from . import opening, outline

        topic, project, _info = linked_project(topic_id)
        if opening.find_subtitles(project) is None:
            raise ValueError("项目里还没有字幕文件：录完把粗剪和字幕放进项目文件夹")
        draft = outline.read_outline(topic)
        thesis = opening.thesis_for(draft["markdown"] if draft else None, topic["title"])
        with opening_lock:
            if (opening_runs.get(topic_id) or {}).get("state") == "running":
                return {"started": False, "message": "正在检查开头"}
            opening_runs[topic_id] = {"state": "running"}
        threading.Thread(target=_score_opening, args=(topic_id, project, thesis), daemon=True).start()
        return {"started": True, "message": "开始检查开头 15 秒，一般半分钟"}

    @app.post("/api/topics/{topic_id}/video-project/worktable")
    def import_worktable(topic_id: int, body: WorktableBody) -> dict[str, Any]:
        topic = store.topic(topic_id)
        if not topic.get("video_project"):
            raise ValueError("这个选题还没有关联视频项目")
        return video_project.import_worktable(
            video_root(), topic["video_project"], text=body.text, source=(body.filename or "粘贴")[:80], overwrite=body.overwrite
        )

    # -- Step 3–4：成片 → 字幕 → 可以标 Hook 的工作台 ---------------------

    def _koubo_dir(topic_id: int) -> Path:
        topic = store.topic(topic_id)
        if not topic.get("video_project"):
            raise ValueError("这个选题还没有关联视频项目")
        return video_project.project_dir(video_root(), topic["video_project"])

    @app.get("/api/topics/{topic_id}/video-project/media")
    def koubo_media(topic_id: int) -> dict[str, Any]:
        from . import koubo

        return koubo.state(_koubo_dir(topic_id))

    @app.post("/api/topics/{topic_id}/video-project/init")
    def koubo_init(topic_id: int) -> dict[str, Any]:
        """补一份 project.json。没有它，14 步进度算不出来，「开始跑」也会被拒。"""
        from . import koubo

        data = koubo.init_project(_koubo_dir(topic_id))
        store.log_event("edit", f"《{store.topic(topic_id)['title'][:24]}》的项目初始化好了，可以按 14 步跑", topic_id)
        return {"presets": data["presets"], "message": "project.json 写好了，现在可以按 14 步跑"}

    @app.post("/api/topics/{topic_id}/video-project/skip-hook")
    def koubo_skip_hook(topic_id: int) -> dict[str, Any]:
        """这条不剪 Hook。

        Hook 那四步存在的唯一理由，是补救一个不够抓人的开头。骨架里已经给了暴论候选，
        录的时候第一句就说它，这四步就没必要了。
        """
        from . import koubo

        base = _koubo_dir(topic_id)
        changed = koubo.skip_hook(base)
        store.log_event("edit", f"《{store.topic(topic_id)['title'][:24]}》这条不剪 Hook，直接进正文", topic_id)
        return {"steps": changed, "message": "记下了：这条不剪 Hook，Step 5/7/8/9 跳过"}

    @app.post("/api/topics/{topic_id}/video-project/external")
    def koubo_external(topic_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        """在外面做完的：Hook（给出剪好的 Hook 视频）或整条（成片已在 final/ 或给出路径）。"""
        from . import koubo

        what = str(payload.get("what") or "")
        raw = str(payload.get("path") or "").strip()
        base = _koubo_dir(topic_id)
        try:
            result = koubo.mark_external(base, what, source=Path(raw) if raw else None)
        except koubo.KouboError as exc:
            raise ValueError(str(exc)) from None
        title = store.topic(topic_id)["title"][:24]
        store.log_event("edit", f"《{title}》{'Hook' if what == 'hook' else '整条'}在外面做完了，已记下", topic_id)
        return {**result, "message": "记下了：Hook 在外面剪好了" if what == "hook" else "记下了：整条在外面做完了，可以去打包"}

    @app.put("/api/topics/{topic_id}/video-project/spec")
    def koubo_spec(topic_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        """Park 从剪映导出后手动选的剪辑规格：Hook、字幕、版式、背景音乐、音效。"""
        from . import koubo

        try:
            spec = koubo.set_spec(_koubo_dir(topic_id), {k: v for k, v in payload.items() if v is not None})
        except koubo.KouboError as exc:
            raise ValueError(str(exc)) from None
        return {"spec": spec}

    @app.put("/api/topics/{topic_id}/video-project/visual-target")
    def koubo_visual_target(topic_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        from . import koubo

        try:
            top = payload.get("max")
            value = koubo.set_visual_target(_koubo_dir(topic_id), float(payload.get("percent")),
                                            None if top in (None, "") else float(top))
        except (koubo.KouboError, TypeError, ValueError) as exc:
            raise ValueError(str(exc) or "比例要是一个数") from None
        text = f"{round(value * 100)}%" if top in (None, "") or float(top) == value * 100 else f"{round(value * 100)}–{round(float(top))}%"
        return {"visual_target": value, "message": f"记下了：动效占正文 {text}"}

    @app.get("/api/topics/{topic_id}/video-project/activity")
    def koubo_activity(topic_id: int) -> dict[str, Any]:
        """谁在这个项目里干活、最后写了什么、这一步做了多久。不管是工作台、Codex 还是 Claude 在跑。"""
        from . import activity

        _topic, path, info = linked_project(topic_id)
        contract_path = path / "project.json"
        try:
            contract = json.loads(contract_path.read_text(encoding="utf-8")) if contract_path.is_file() else {}
        except (OSError, ValueError):
            contract = {}
        return activity.activity(path, contract=contract, current=info.get("current_step"),
                                 gate=info.get("gate"), delivered=bool(info.get("delivered")))

    @app.get("/api/topics/{topic_id}/video-project/latest-export")
    def koubo_latest_export(topic_id: int) -> dict[str, Any]:
        """剪映导出里最新的那一条。名字全是日期，所以带上时长和大小给 Park 核对。"""
        from . import koubo

        root = koubo.exports_root(video_root())
        return {"root": str(root), "latest": koubo.latest_export(root)}

    @app.post("/api/topics/{topic_id}/video-project/adopt")
    def koubo_adopt(topic_id: int, body: AdoptBody) -> dict[str, Any]:
        from . import koubo

        root = koubo.exports_root(video_root()).resolve()
        chosen = Path(body.path).expanduser().resolve()
        # 路径是前端传回来的，必须确认它真的在剪映导出目录里，别让人拷任意文件进项目。
        if not chosen.is_relative_to(root):
            raise ValueError("只能从剪映导出目录里拿")
        srts = [p for p in chosen.parent.iterdir() if p.is_file() and p.suffix.lower() == ".srt"] if chosen.parent != root else []
        result = koubo.adopt(chosen, _koubo_dir(topic_id), srt=srts[0] if srts else None)
        store.log_event("edit", f"《{store.topic(topic_id)['title'][:24]}》放进了粗剪 {chosen.name}", topic_id)
        return {**result, "message": f"{chosen.name} 已经放进项目目录"}

    @app.post("/api/topics/{topic_id}/video-project/transcribe")
    def koubo_transcribe(topic_id: int) -> dict[str, Any]:
        """本机跑 whisper。前端必须先问过 Park——这要占住机器两三分钟。"""
        from . import koubo

        base = _koubo_dir(topic_id)
        video = koubo.find_video(base)
        if video is None:
            raise ValueError("项目目录里没找到成片，先把粗剪放进去")
        with writing_lock:
            key = 10_000 + topic_id
            if key in writing:
                return {"started": False, "message": "正在转写"}
            writing.add(key)

        def run() -> None:
            from . import koubo as k

            try:
                srt = k.transcribe(video, base)
                k.build_worktable(base, srt=srt)
                store.log_event("edit", f"《{store.topic(topic_id)['title'][:24]}》转写完了，工作台可以标 Hook 了", topic_id)
            except Exception as exc:  # noqa: BLE001 - 结果在 media 状态里看
                logger.warning("koubo transcribe %s failed: %s", topic_id, exc)
                store.log_event("edit", f"《{store.topic(topic_id)['title'][:24]}》转写失败：{str(exc)[:80]}", topic_id)
            finally:
                with writing_lock:
                    writing.discard(10_000 + topic_id)

        threading.Thread(target=run, name=f"koubo-{topic_id}", daemon=True).start()
        return {"started": True, "message": f"开始转写 {video.name}，15 分钟的片子大概 2–3 分钟"}

    @app.get("/api/topics/{topic_id}/video-project/transcribe")
    def koubo_transcribe_state(topic_id: int) -> dict[str, Any]:
        with writing_lock:
            return {"running": (10_000 + topic_id) in writing}

    @app.post("/api/topics/{topic_id}/video-project/build-worktable")
    def koubo_build(topic_id: int) -> dict[str, Any]:
        """已经有 SRT 的时候单独建表，不用重新转写。"""
        from . import koubo

        base = _koubo_dir(topic_id)
        srt = koubo.find_srt(base)
        if srt is None:
            raise ValueError("项目目录里没有 SRT")
        koubo.build_worktable(base, srt=srt)
        return {"ok": True, "message": "工作台建好了"}

    @app.get("/api/topics/{topic_id}/video-project/worktable.html", response_class=HTMLResponse)
    def koubo_worktable(topic_id: int) -> str:
        """把 ask-park-video 那张表原样开在工作台里，只多挂一颗「保存到项目」。

        以前这一步是：在别处打开 HTML → 导出 JSON 落进下载文件夹 → 手动拷回
        analysis/worktable.json。现在点一下就写回去了。
        """
        from . import koubo

        return koubo.worktable_html(_koubo_dir(topic_id), save_url=f"/api/topics/{topic_id}/video-project/worktable")

    # -- background workflow runs & gate approvals -----------------------

    def run_view(run: dict[str, Any]) -> dict[str, Any]:
        from . import workflow_runner

        if not run.get("log_path"):
            return {**run, "log_tail": ""}
        current = workflow_runner.status(run)
        if current["state"] != run["state"] and run["state"] in ("starting", "running"):
            store.update_run(run["id"], state=current["state"], finished_at=None if current["state"] == "running" else now_iso())
        return current

    def linked_project(topic_id: int) -> tuple[dict[str, Any], Path, dict[str, Any]]:
        topic = store.topic(topic_id)
        if not topic.get("video_project"):
            raise ValueError("这个选题还没有关联视频项目")
        root = video_root()
        info = video_project.inspect(root, topic["video_project"])
        return topic, video_project.project_dir(root, topic["video_project"]), info

    @app.get("/api/topics/{topic_id}/video-project/run")
    def get_run(topic_id: int) -> dict[str, Any]:
        runs = store.runs(topic_id=topic_id)
        active_elsewhere = [r for r in store.runs(active_only=True) if r["topic_id"] != topic_id]
        return {"run": run_view(runs[0]) if runs else None, "busy_elsewhere": bool(active_elsewhere and run_view(active_elsewhere[0])["state"] == "running")}

    @app.post("/api/topics/{topic_id}/video-project/run")
    def start_run(topic_id: int) -> dict[str, Any]:
        from . import workflow_runner

        topic, path, info = linked_project(topic_id)
        for active in store.runs(active_only=True):
            if run_view(active)["state"] == "running":
                raise ValueError("已经有一个口播项目在后台跑，等它停下或先中止")
        if info["layout"] == "legacy":
            raise ValueError("这是旧版目录，没有 project.json，不能按 14 步继续")
        if info.get("delivered"):
            raise ValueError("这个项目已经交付了")
        if info.get("gate"):
            raise ValueError(f"项目停在 {info['gate']['key']}：{info['gate']['title']}。先处理审批门再继续")
        run_id = store.create_run(topic_id, topic["video_project"])
        started = workflow_runner.start(path, run_id=run_id, runs_dir=runs_dir or workflow_runner.DEFAULT_RUNS_DIR, command=runner_command)
        run = store.update_run(run_id, state="running", **started)
        return {"run": run_view(run), "message": "开始在后台跑口播 workflow，停在下一个审批门会提醒你"}

    @app.delete("/api/topics/{topic_id}/video-project/run")
    def cancel_run(topic_id: int) -> dict[str, Any]:
        from . import workflow_runner

        runs = [r for r in store.runs(topic_id=topic_id, active_only=True)]
        if not runs:
            raise ValueError("没有正在跑的任务")
        workflow_runner.cancel(runs[0])
        return {"run": run_view(store.update_run(runs[0]["id"], state="cancelled", finished_at=now_iso()))}

    @app.get("/api/topics/{topic_id}/video-project/gate")
    def gate_review(topic_id: int) -> dict[str, Any]:
        from . import workflow_runner

        _topic, path, info = linked_project(topic_id)
        if not info.get("gate"):
            raise ValueError("现在没有等待你的审批门")
        return {"gate": info["gate"], "review": workflow_runner.gate_review(path, info["gate"]["key"])}

    @app.post("/api/topics/{topic_id}/video-project/approve")
    def approve_gate(topic_id: int, body: ApproveBody) -> dict[str, Any]:
        from . import workflow_runner

        _topic, path, info = linked_project(topic_id)
        gate = info.get("gate")
        if not gate or gate["key"] != body.gate:
            raise ValueError("这个审批门现在不在等待批准")
        if body.gate == "H1" and not (path / "analysis" / "worktable.json").is_file():
            raise ValueError("先在 worktable 里选 Hook 并导入，再批准")
        record = workflow_runner.approve(path, body.gate, note=body.note)
        return {"approval": record, "project": video_project.inspect(video_root(), _topic["video_project"])}

    # -- 口播动效 v2（park-video-v2）：进度和动作都在它自己的 pv2.py 里 ------------
    def v2_project(topic_id: int) -> tuple[dict[str, Any], Path]:
        from . import video_v2

        topic, path, info = linked_project(topic_id)
        if info["layout"] != "v2" or not video_v2.is_v2(path):
            raise ValueError("这不是 v2 项目（项目里没有 v2/brief.yaml，或者是旧流程的项目）")
        return topic, path

    @app.post("/api/topics/{topic_id}/video-project/v2/approve")
    def approve_v2(topic_id: int, body: V2ApproveBody) -> dict[str, Any]:
        from . import video_v2

        topic, path = v2_project(topic_id)
        record = video_v2.approve(path, body.gate, body.message)
        return {"approval": record, "project": video_project.inspect(video_root(), topic["video_project"])}

    @app.post("/api/topics/{topic_id}/video-project/v2/start")
    def start_v2(topic_id: int, body: V2StartBody) -> dict[str, Any]:
        from . import video_v2

        topic, path = v2_project(topic_id)
        message = video_v2.start(path, body.job)
        return {"message": message, "project": video_project.inspect(video_root(), topic["video_project"])}

    @app.get("/api/topics/{topic_id}/video-project/v2/settings")
    def v2_settings(topic_id: int) -> dict[str, Any]:
        from . import video_v2

        _topic, path = v2_project(topic_id)
        return video_v2.settings(path)

    @app.post("/api/topics/{topic_id}/video-project/v2/settings")
    def save_v2_settings(topic_id: int, body: V2SettingsBody) -> dict[str, Any]:
        from . import video_v2

        _topic, path = v2_project(topic_id)
        if body.scope not in ("project", "default"):
            raise ValueError("scope 只能是 project（这条视频）或 default（以后的默认）")
        result = video_v2.save_settings(path if body.scope == "project" else None, body.values)
        return {"result": result, "settings": video_v2.settings(path)}

    @app.get("/api/video-v2/catalog")
    def v2_catalog() -> dict[str, Any]:
        from . import video_v2

        return video_v2.catalog()

    @app.get("/api/video-v2/media/{kind}/{file}")
    def v2_media(kind: str, file: str) -> FileResponse:
        from . import video_v2

        path = video_v2.media_path(kind, file)
        return FileResponse(path, media_type="video/mp4" if file.endswith(".mp4") else "image/jpeg")

    # -- one-click publishing (Park confirms every job) --------------------

    def publisher_specs() -> dict[str, dict[str, Any]]:
        from . import publisher

        return publishers if publishers is not None else publisher.PUBLISHERS

    def _media_base(topic: dict[str, Any]) -> Path:
        """封面这类发布用的文件放哪：有视频项目就在项目里；补发的旧视频没有项目，放它自己的草稿目录。"""
        if topic.get("video_project"):
            return video_project.project_dir(video_root(), topic["video_project"])
        base = drafts_root / f"topic-{topic['id']}"
        base.mkdir(parents=True, exist_ok=True)
        return base

    def _media_url(topic: dict[str, Any], relative: str) -> str:
        from urllib.parse import quote

        return f"/api/topics/{topic['id']}/media/{quote(relative)}"

    @app.get("/api/topics/{topic_id}/media/{relative:path}")
    def topic_media(topic_id: int, relative: str) -> Response:
        """选题的封面、候选帧，只读。项目里的和补发草稿目录里的都从这里取。"""
        topic = store.topic(topic_id)
        try:
            base = _media_base(topic).resolve()
        except VideoProjectError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        path = (base / relative).resolve()
        if base not in path.parents or not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise HTTPException(status_code=404, detail="文件不存在")
        return FileResponse(path, headers={"Cache-Control": "no-store"})

    def _release_for(topic: dict[str, Any]) -> dict[str, Any] | None:
        """final/ 下的封面和发布文案，带上每张封面的地址。补发的旧视频也有（放在草稿目录）。"""
        from . import release

        try:
            base = _media_base(topic)
        except VideoProjectError:
            return None
        found = release.find_release(base)
        covers = found.get("covers") or {}
        return {"project": topic.get("video_project"), **found,
                "cover_urls": {k: _media_url(topic, v) for k, v in covers.items() if v}}

    def _approval_state(topic: dict[str, Any], release_info: dict[str, Any] | None = None) -> dict[str, Any]:
        """打包页每一步的定稿状态（见 approvals.py）。"""
        from . import approvals, copypack, evidence, gzh_layout, illustrate as il, reach, xhs_cards

        rel = release_info if release_info is not None else _release_for(topic)
        covers: list[Path] = []
        if rel:
            try:
                base = _media_base(topic)
                covers = [base / v for k, v in (rel.get("covers") or {}).items() if v and k in ("landscape", "portrait", "wide")]
            except VideoProjectError:
                pass
        art = _article_path(topic)
        text = art.read_text(encoding="utf-8") if art is not None and art.is_file() else None
        figs = [art.parent / il.FOLDER / i["file"] for i in il.state(art)["images"]] if text else []
        fps = approvals.fingerprints(
            copy=(copypack.read_copy(drafts_root, topic["id"]) or {}).get("platforms"),
            covers=covers, article=il.strip_images(evidence.strip(text)) if text else None, figs=figs,
            wx=gzh_layout.state(art) if text else {},
            xhs=(xhs_cards.state(art) if text else {}) if reach.form_of("xiaohongshu", store.settings()["platform_accounts"]) == "cards" else None,
        )
        return {"fps": fps, "folder": drafts_root / f"topic-{topic['id']}"}

    @app.put("/api/topics/{topic_id}/approve")
    def approve_step(topic_id: int, body: StepApproveBody) -> dict[str, Any]:
        """定稿 / 撤销定稿（改这一步）。"""
        from . import approvals

        topic = store.topic(topic_id)
        st = _approval_state(topic)
        try:
            by = "machine" if body.by == "machine" else "park"
            return {"approvals": approvals.set_approval(st["folder"], body.key, body.approved, st["fps"], by=by)}
        except approvals.ApprovalError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    backfill_root = data_dir / "backfill"

    def archive_root() -> Path | None:
        from . import archive

        return archive.usable_root(store.settings().get("douyin_archive"))

    def final_video_path(topic: dict[str, Any]) -> Path | None:
        if not topic.get("video_project"):
            # 补发的旧视频：抖音成片存档里的那一份（或早先 backfill 目录里的）。只认这两个目录。
            from . import archive

            vid = topic.get("published_video_id")
            if vid:
                found = archive.video_file(archive_root(), vid)
                if found is not None:
                    return found
            if topic.get("video_file"):
                try:
                    path = Path(topic["video_file"]).resolve()
                except OSError:
                    return None
                for base in [b for b in (archive_root(), backfill_root) if b is not None]:
                    try:
                        path.relative_to(base.resolve())
                    except (OSError, ValueError):
                        continue
                    return path if path.is_file() else None
            return None
        try:
            root = video_root()
            info = video_project.inspect(root, topic["video_project"])
        except VideoProjectError:
            return None
        if not info.get("final_video"):
            return None
        return video_project.safe_file(root, topic["video_project"], info["final_video"])

    def _cover_target(topic_id: int) -> tuple[dict[str, Any], Path, Path]:
        topic = store.topic(topic_id)
        video = final_video_path(topic)
        if video is None:
            raise HTTPException(status_code=400, detail="这一条还没有成片，封面要从成片里取人像")
        return topic, _media_base(topic), video

    cover_errors: dict[int, str] = {}

    def _cover_title(topic: dict[str, Any], base: Path) -> tuple[str, bool]:
        """封面上的字就是标题：打包里存的 > 成片包的发布文案 > 选题名。第二个值说是不是 Park 在打包里写的。"""
        from . import copypack, release

        platforms = (copypack.read_copy(drafts_root, topic["id"]) or {}).get("platforms") or {}
        # 9/29 Park：「封面上的字直接就是这个视频的 title。」打包里先写标题，封面跟着它走。
        saved = next((e.get("title") for e in (platforms.get(k) or {} for k in ("douyin", "channels", "xiaohongshu", "bilibili", "youtube")) if e.get("title")), "")
        rel = release.find_release(base).get("copy") or {}
        return (saved or rel.get("title") or topic["title"]), bool(saved)

    @app.get("/api/topics/{topic_id}/cover")
    def cover_options(topic_id: int) -> dict[str, Any]:
        """打包页做封面要的：标题（就是封面上的字）、取帧用的那份视频、机器挑好的一帧 + 另外几张候选、
        正在不在出、上次出错没有。"""
        import hashlib

        from . import cover

        topic, base, video = _cover_target(topic_id)
        title, from_copy = _cover_title(topic, base)
        source = cover.source_video(base, video)
        tag = hashlib.sha1(str(source).encode()).hexdigest()[:8]
        try:
            frames = cover.pick_frames(source, base / "analysis" / f"cover-frames-{tag}")
        except cover.CoverError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        with writing_lock:
            running = 70_000 + topic_id in writing
        return {
            "title": title, "from_copy": from_copy, "lines": cover.split_title(title),
            "source": source.name, "running": running, "error": cover_errors.get(topic_id),
            "progress": cover.progress(base) if running else None,
            "frames": [{"at": f["at"], "score": f["score"], "pick": f["pick"], "url": _media_url(topic, str(f["path"].relative_to(base)))} for f in frames],
        }

    @app.post("/api/topics/{topic_id}/cover")
    def make_cover(topic_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        """出竖、横两张封面（Codex image_gen，5–10 分钟），放进 final/covers/，发布台的交付包会自己认到。"""
        from . import cover

        topic, base, video = _cover_target(topic_id)
        title, _ = _cover_title(topic, base)
        at = float(payload.get("at") or 0)
        with writing_lock:
            if 70_000 + topic_id in writing:
                return {"started": False, "message": "正在出封面"}
            writing.add(70_000 + topic_id)
        cover_errors.pop(topic_id, None)

        def run() -> None:
            try:
                made = cover.generate(base, cover.source_video(base, video), at=at, title=title)
                store.log_event("copy", f"《{title[:24]}》封面出好了：{'、'.join(made)}", topic_id)
            except Exception as exc:  # noqa: BLE001 - 打包页显示
                logger.warning("cover %s failed: %s", topic_id, exc)
                cover_errors[topic_id] = str(exc)[:300] or type(exc).__name__
            finally:
                _pack_job_done(topic_id, "cover", cover_errors.get(topic_id), slot=70_000 + topic_id)

        threading.Thread(target=run, name=f"cover-{topic_id}", daemon=True).start()
        return {"started": True, "message": "开始出封面（图像生成），一般 5–10 分钟"}

    # -- 打包自动档（pack_auto.py）：Park 只定标题，剩下的一步接一步做完、自动定稿 -----------

    pack_lock = threading.Lock()

    def _pack_running(topic_id: int, state: dict[str, Any]) -> set[str]:
        with writing_lock:
            live = set(writing)
        running = set()
        if 70_000 + topic_id in live:
            running.add("cover")
        if topic_id in live:
            running.add("article")
        if 50_000 + topic_id in live:
            running.add("wx")
        if 60_000 + topic_id in live:
            # 配图和小红书出图共用一个占位：看自动档记的是哪一步在跑
            steps = state.get("steps") or {}
            running.add("xhs" if (steps.get("xhs") or {}).get("state") == "running" and (steps.get("figs") or {}).get("state") != "running" else "figs")
        return running

    def _pack_start(topic_id: int, key: str) -> None:
        from . import cover

        if key == "cover":
            _topic, base, video = _cover_target(topic_id)
            source = cover.source_video(base, video)
            import hashlib

            frames = cover.pick_frames(source, base / "analysis" / f"cover-frames-{hashlib.sha1(str(source).encode()).hexdigest()[:8]}")
            pick = next((f for f in frames if f["pick"]), frames[len(frames) // 2] if frames else {"at": 0})
            make_cover(topic_id, {"at": pick["at"]})
        elif key == "article":
            start_write(topic_id)
        elif key == "figs":
            start_illustrate(topic_id)
        elif key == "wx":
            start_layout(topic_id)
        elif key == "xhs":
            start_xhs(topic_id)

    def pack_advance(topic_id: int) -> dict[str, Any]:
        """照 pack_auto.plan 往下走一步：做好的自动定稿，该开始的开始。没 armed 什么都不做。"""
        from . import approvals, pack_auto

        topic = store.topic(topic_id)
        st = _approval_state(topic)
        folder, fps = st["folder"], st["fps"]
        with pack_lock:
            state = pack_auto.load(folder)
            status = approvals.status(folder, fps)
            running = _pack_running(topic_id, state)
            for action, key in pack_auto.plan(state, status, running, title=state.get("title") or "", xhs="xhs" in fps):
                step = (state.get("steps") or {}).get(key) or {}
                if action == "approve":
                    try:
                        status = approvals.set_approval(folder, key, True, fps, by="auto")
                        state = pack_auto.mark(folder, key, state="done", error=None)
                    except approvals.ApprovalError as exc:
                        state = pack_auto.mark(folder, key, state="error", error=str(exc))
                elif action in ("start", "interrupted"):
                    tries = int(step.get("tries") or 0) + 1 if action == "interrupted" else 1
                    try:
                        # 先记「在做」再起任务：任务失败得快（比如出图马上报错），它的「失败」会先写进去，
                        # 再被这里的「在做」盖掉，下一轮当成被打断又重做一遍（10/3 CI 偶发：封面出了两次）
                        state = pack_auto.mark(folder, key, state="running", started_at=pack_auto.now(), tries=tries, error=None,
                                               **({"title": state.get("title")} if key == "cover" else {}))
                        _pack_start(topic_id, key)
                    except Exception as exc:  # noqa: BLE001 - 打包页显示，等 Park 点重试
                        logger.warning("pack %s %s failed to start: %s", topic_id, key, exc)
                        state = pack_auto.mark(folder, key, state="error", error=str(getattr(exc, "detail", "") or exc)[:300])
                elif action == "give_up":
                    state = pack_auto.mark(folder, key, state="error", error="被中断了两次（服务重启），点重试再来")
        return state

    def _pack_job_done(topic_id: int, key: str, error: str | None, *, slot: int) -> None:
        """打包要的任务做完（不管是自动档起的还是手点的）：记一笔，放开占位，自动档往下走。

        顺序要紧：先记下做好了 / 失败了，再放开占位（slot，writing 里那个数）。反过来的话，中间那一下
        自动档看到「记着在做、可线程没了」，当成服务重启打断，重做一遍（10/3 CI 上偶发：失败被记成「被中断了两次」）。"""
        from . import pack_auto

        armed = False
        try:
            folder = drafts_root / f"topic-{topic_id}"
            state = pack_auto.load(folder)
            armed = bool(state.get("armed"))
            if armed:
                pack_auto.mark(folder, key, state="error" if error else "made", error=error)
        except Exception as exc:  # noqa: BLE001 - 不让收尾把任务本身弄成失败
            logger.warning("pack mark after %s %s: %s", key, topic_id, exc)
        finally:
            with writing_lock:
                writing.discard(slot)
        if not armed:
            return
        try:
            pack_advance(topic_id)
        except Exception as exc:  # noqa: BLE001 - 不让收尾把任务本身弄成失败
            logger.warning("pack advance after %s %s: %s", key, topic_id, exc)

    def pack_view(topic_id: int) -> dict[str, Any]:
        from . import approvals, pack_auto

        topic = store.topic(topic_id)
        st = _approval_state(topic)
        state = pack_auto.load(st["folder"])
        status = approvals.status(st["folder"], st["fps"])
        running = _pack_running(topic_id, state)
        detail: dict[str, str] = {}
        if "cover" in running:
            try:
                from . import cover

                _t, base, _v = _cover_target(topic_id)
                detail["cover"] = cover.progress_note(cover.progress(base))
            except Exception:  # noqa: BLE001 - 进度只是一句话
                detail["cover"] = "出图中"
        if "article" in running:
            detail["article"] = "在润色，一般 2–5 分钟" if status["article"]["made"] else "照视频字幕写，一般 1–5 分钟"
        if "figs" in running:
            detail["figs"] = "小黑手绘，一张一张画，5–10 分钟"
        if "wx" in running:
            detail["wx"] = "gzh 排版，5–10 分钟"
        rows = pack_auto.view(state, status, running, xhs="xhs" in st["fps"], detail=detail)
        return {"armed": bool(state.get("armed")), "title": state.get("title") or "", "copy_locked": bool(status["copy"]["approved"] and status["copy"]["valid"]),
                "steps": rows, "ready": all(r["state"] == "done" for r in rows), "busy": any(r["state"] in ("running", "waiting") for r in rows)}

    @app.post("/api/topics/{topic_id}/pack/go")
    def pack_go(topic_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        """Park 定了标题：存标题（描述、话题沿用已经写的；没写过的用成片包里的发布文案），文字定稿，打开自动档。"""
        from . import approvals, copypack, pack_auto

        title = str(payload.get("title") or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="先写标题")
        topic = store.topic(topic_id)
        old = (copypack.read_copy(drafts_root, topic_id) or {}).get("platforms") or {}
        from .publish_desk import shared_entry

        shared = shared_entry({"platforms": old})
        rel = _release_for(topic) or {}
        seed = rel.get("copy") or {}
        body = shared["body"] or seed.get("body") or ""
        tags = shared["tags"] or list(seed.get("tags") or [])
        # B 站、YouTube 不在打包页上露面（10/2 Park），但照样写一份共用的标题和描述，发的时候还能用
        traffic = store.settings().get("traffic_tags") or {}
        keys = [k for k in copypack.PLATFORMS if k in ("douyin", "channels", "xiaohongshu", "bilibili", "youtube")]

        content = [t for t in tags if not any(t in (v or []) for v in traffic.values())]
        if not content:
            # 还没写过内容话题：用出标题时按内容出的那批（10/2 起），视频号、小红书也就有话题了
            from . import titles as titles_mod

            content = list(((titles_mod.read_titles(drafts_root, topic_id) or {}).get("tags")) or [])

        def tags_for(key: str) -> list[str]:
            merged = list(dict.fromkeys([*(traffic.get(key) or []), *content]))
            return merged[: copypack.PLATFORMS[key]["tags"]]

        platforms = {**old, **{k: {"title": title, "body": (old.get(k) or {}).get("body") or body, "tags": tags_for(k)} for k in keys}}
        copypack.save_copy(drafts_root, topic_id, platforms)
        st = _approval_state(topic)
        approvals.set_approval(st["folder"], "copy", True, st["fps"])
        prior = pack_auto.load(st["folder"])
        covers = [str((rel.get("covers") or {}).get(k) or "") for k in ("portrait", "landscape")]
        stem = re.sub(r'[\\/:*?"<>|]', "", title)[:40]  # cover.generate 存封面时的文件名开头
        if any(covers) and not ((prior.get("steps") or {}).get("cover") or {}).get("title") \
                and not any(Path(c).name.startswith(stem) for c in covers if c):
            # 现有封面不是按这个标题出的：记下来，让自动档按新标题重出，不拿旧封面直接定稿
            pack_auto.mark(st["folder"], "cover", state="made", title=shared["title"] or "（旧封面）")
        pack_auto.arm(st["folder"], title)
        pack_advance(topic_id)
        return pack_view(topic_id)

    @app.post("/api/topics/{topic_id}/pack/advance")
    def pack_tick(topic_id: int) -> dict[str, Any]:
        """页面轮询用（POST：会启动任务）。没定标题的不动。"""
        pack_advance(topic_id)
        return pack_view(topic_id)

    @app.get("/api/topics/{topic_id}/pack")
    def pack_get(topic_id: int) -> dict[str, Any]:
        """只读：打开页面时看自动档的状态，不启动任何任务。"""
        return pack_view(topic_id)

    @app.post("/api/topics/{topic_id}/pack/retry")
    def pack_retry(topic_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        from . import pack_auto

        key = str(payload.get("key") or "")
        if key not in pack_auto.ORDER:
            raise HTTPException(status_code=400, detail="没有这一步")
        pack_auto.retry(drafts_root / f"topic-{topic_id}", key)
        {"cover": cover_errors, "figs": illustrate_errors, "wx": layout_errors, "xhs": xhs_errors}.get(key, {}).pop(topic_id, None)
        pack_advance(topic_id)
        return pack_view(topic_id)

    def _pack_resume_all() -> None:
        """服务刚起来：自动档里记着在跑的，重起（被部署重启打断的）。"""
        from . import pack_auto

        for path in sorted(drafts_root.glob(f"topic-*/{pack_auto.FILE}")):
            try:
                state = pack_auto.load(path.parent)
                if state.get("armed") and any((s or {}).get("state") in ("running", "made") for s in (state.get("steps") or {}).values()):
                    pack_advance(int(path.parent.name.split("-", 1)[1]))
            except Exception as exc:  # noqa: BLE001 - 一条坏了不挡别的
                logger.warning("pack resume %s: %s", path, exc)

    phone_errors: dict[int, str] = {}

    def _phone_state(topic_id: int) -> dict[str, Any]:
        from urllib.parse import quote

        from . import phone

        topic = store.topic(topic_id)
        with writing_lock:
            running = 40_000 + topic_id in writing
        parts = []
        if topic.get("video_project"):
            try:
                base = video_project.project_dir(video_root(), topic["video_project"])
                prefix = f"/api/video-projects/{quote(topic['video_project'])}/raw/"
                parts = [{**p, "url": prefix + quote(p["path"])} for p in phone.existing(base)]
            except VideoProjectError:
                parts = []
        return {"running": running, "error": phone_errors.get(topic_id), "parts": parts, "cap_mb": phone.CAP_MB}

    @app.get("/api/topics/{topic_id}/phone-preview")
    def phone_preview_state(topic_id: int) -> dict[str, Any]:
        return _phone_state(topic_id)

    @app.post("/api/topics/{topic_id}/phone-preview")
    def start_phone_preview(topic_id: int) -> dict[str, Any]:
        """成片压成手机能看的大小，只在本机出文件，不上传。"""
        from . import phone

        topic = store.topic(topic_id)
        video = final_video_path(topic)
        if video is None:
            raise ValueError("这一条还没有成片")
        base = video_project.project_dir(video_root(), topic["video_project"])
        with writing_lock:
            if 40_000 + topic_id in writing:
                return {"started": False, "message": "正在压"}
            writing.add(40_000 + topic_id)
        phone_errors.pop(topic_id, None)

        def run() -> None:
            try:
                parts = phone.make_preview(base, video)
                store.log_event("edit", f"《{topic['title'][:24]}》的手机预览好了：{len(parts)} 个文件", topic_id)
            except Exception as exc:  # noqa: BLE001 - 进度页上显示
                logger.warning("phone preview %s failed: %s", topic_id, exc)
                phone_errors[topic_id] = str(exc)[:300] or type(exc).__name__
            finally:
                with writing_lock:
                    writing.discard(40_000 + topic_id)

        threading.Thread(target=run, name=f"phone-{topic_id}", daemon=True).start()
        return {"started": True, "message": "开始压手机预览，12 分钟的片子大约半分钟"}

    @app.get("/api/topics/{topic_id}/publish-jobs")
    def list_publish_jobs(topic_id: int) -> dict[str, Any]:
        from . import copypack, publisher

        topic = store.topic(topic_id)
        video = final_video_path(topic)
        copy = (copypack.read_copy(drafts_root, topic_id) or {}).get("platforms")
        return {
            "platforms": publisher.readiness(publisher_specs()),
            "video": {"path": str(video), "mb": round(video.stat().st_size / 1_048_576, 1)} if video else None,
            "has_copy": bool(copy),
            "jobs": store.publish_jobs(topic_id),
        }

    # 手动传的平台要哪几个文件（9/29 Park：点上传，就弹开那个文件夹，里面是视频和竖、横封面，他自己拖进去）
    UPLOAD_KIT = {
        "douyin": (("video", "视频"), ("portrait", "竖封面"), ("landscape", "横封面")),
        "channels": (("video", "视频"), ("portrait", "竖封面")),
        # 9/29 Park：小红书改发视频（图文三篇共 262 播放，抖音同一条 7,893）。传抖音那条竖版无水印成片。
        "xiaohongshu": (("video", "视频"), ("portrait", "竖封面")),
        "bilibili": (("video", "视频"), ("wide", "16比9封面")),
        "youtube": (("video", "视频"), ("wide", "16比9封面")),
    }

    @app.post("/api/topics/{topic_id}/upload-folder")
    def upload_folder(topic_id: int, body: dict[str, Any]) -> dict[str, Any]:
        """把这个平台要传的文件放进 final/上传-<平台>/，在访达里打开。用硬链接，不多占硬盘。"""
        from . import copypack

        platform = str(body.get("platform") or "")
        kit = UPLOAD_KIT.get(platform)
        if not kit or platform_forms().get(platform) not in (None, "video"):
            raise HTTPException(status_code=400, detail="这个平台没有要准备的上传文件")
        topic = store.topic(topic_id)
        video = final_video_path(topic)
        if video is None:
            raise HTTPException(status_code=400, detail="还没有成片")
        base = _media_base(topic)
        covers = (_release_for(topic) or {}).get("covers") or {}
        label = (copypack.PLATFORMS.get(platform) or {}).get("label", platform).replace(" ", "")
        folder = base / "final" / f"上传-{label}"
        folder.mkdir(parents=True, exist_ok=True)
        for old in folder.iterdir():
            if old.is_file() or old.is_symlink():
                old.unlink()
        if platform == "xiaohongshu":
            # 10/1 Park：小红书的封面框跟着视频的比例走——横屏视频（3 月那批抖音下载版都是 1920×1080）框是 4:3 横的，
            # 放竖封面会被裁掉一半。横屏就放 4:3 横封面。
            from .cover import _dimensions

            w, h = _dimensions(video)
            if w > h:
                kit = (("video", "视频"), ("landscape", "横封面"))
        placed, missing = [], []
        for kind, name in kit:
            if kind == "video":
                src = video
            else:
                rel = covers.get(kind) or (covers.get("landscape") if kind == "wide" else None)
                src = base / rel if rel else None
            if src is None or not src.is_file():
                missing.append(name)
                continue
            dest = folder / f"{name}{src.suffix.lower()}"
            try:
                os.link(src, dest)
            except OSError:
                dest.symlink_to(src)
            placed.append(dest.name)
        # 这个平台的文案也放一份进去：传视频的时候标题、描述、话题就在旁边，不用回工作台复制
        from . import publish_desk

        copy = copypack.read_copy(drafts_root, topic_id) or {}
        own = publish_desk.own_entry(copy.get("platforms"), platform, publish_desk.shared_entry(copy))
        if own.get("title") or own.get("body"):
            tags = " ".join(f"#{t}" for t in own.get("tags") or [])
            (folder / "文案.txt").write_text(f"{own.get('title') or ''}\n\n{own.get('body') or ''}\n\n{tags}\n", encoding="utf-8")
            placed.append("文案.txt")
        if body.get("open", True) and not os.environ.get("CONTENT_STUDIO_NO_OPEN") and sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"folder": str(folder), "files": placed, "missing": missing}

    @app.post("/api/topics/{topic_id}/publish-jobs")
    def prepare_publish(topic_id: int, body: PublishJobBody) -> dict[str, Any]:
        from . import copypack, publisher

        topic = store.topic(topic_id)
        video = final_video_path(topic)
        text_only = bool(publisher_specs().get(body.platform, {}).get("no_video"))
        if video is None and not text_only:
            raise publisher.PublishError("这个选题还没有成片：先关联视频项目并完成剪辑")
        copy = (copypack.read_copy(drafts_root, topic_id) or {}).get("platforms")
        article = Path(topic["article_path"]) if topic.get("article_path") else None
        release_info = _release_for(topic) or {}
        covers = release_info.get("covers") or {}
        # 公众号要 2.35:1：有专门出的公众号封面就用它，没有就用横版（发的时候垫宽）。
        # YouTube、B 站是 16:9 的框：有 16:9 那张就用它，没有退回 4:3 横版。
        chosen = ((covers.get("wechat") if body.platform == "wechat_mp" else None)
                  or (covers.get("wide") if body.platform in ("youtube", "bilibili") else None)
                  or covers.get("landscape"))
        cover = _media_base(topic) / chosen if chosen else None
        # 抖音的封面框横竖各一张
        portrait = _media_base(topic) / covers["portrait"] if covers.get("portrait") else None
        payload = publisher.build_payload(body.platform, body.mode, video=video, copy=copy, publishers=publisher_specs(),
                                          article=article, cover=cover, cover_portrait=portrait)
        if body.auto:
            payload["auto"] = True
        return {"job": store.create_publish_job(topic_id, payload)}

    def _open_in_browser(url: str | None) -> None:
        """发完就在 Park 的默认浏览器里打开那一页（他登录着的那个）。测试里关掉。"""
        if not url or os.environ.get("CONTENT_STUDIO_NO_OPEN") or sys.platform != "darwin":
            return
        try:
            subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass

    def _run_publish(job_id: int) -> None:
        from . import publisher

        job = store.publish_job(job_id)
        copy_platform = publisher_specs()[job["platform"]]["copy_key"]

        try:
            result = publisher.run(job["payload"], publishers=publisher_specs())
        except Exception as exc:  # noqa: BLE001 - shown on the job
            result = {"ok": False, "status": "error", "message": str(exc)}
        ok = bool(result.get("ok"))
        if result.get("status") == "window_closed":
            # 窗口关了、没点发布：这次就算没发生，瓦片回到原样，不挂「上次失败」
            store.update_publish_job(job_id, state="cancelled", result=result, message=publisher.explain(result), finished_at=now_iso())
            return
        store.update_publish_job(job_id, state="done" if ok else "failed", result=result, message=None if ok else publisher.explain(result), finished_at=now_iso())
        if ok and not (job.get("payload") or {}).get("auto"):
            _open_in_browser(publisher.confirm_url(job["platform"], result))
        # 存草稿不算发出去：X / 公众号 / 研习室的脚本在草稿时返回 published=false。
        # 9/24 X 只存了草稿，发布台就标「已发到 X」，按钮也跟着没了。
        if ok and result.get("published") is not False:
            try:
                store.set_publish_record(job["topic_id"], copy_platform, published=True, url=publisher.result_url(result))
            except StoreError:
                pass

    @app.post("/api/publish-jobs/{job_id}/confirm")
    def confirm_publish(job_id: int) -> dict[str, Any]:
        from . import publisher

        job = store.publish_job(job_id)
        publisher.confirmable(job)
        job = store.update_publish_job(job_id, state="running", confirmed_at=now_iso())
        threading.Thread(target=_run_publish, args=(job_id,), name=f"publish-{job_id}", daemon=True).start()
        return {"job": job, "message": f"已确认，开始发布到{job['payload']['platform_label']}"}

    @app.delete("/api/publish-jobs/{job_id}")
    def cancel_publish(job_id: int) -> dict[str, Any]:
        job = store.publish_job(job_id)
        if job["state"] != "awaiting_confirm":
            raise ValueError("只能取消还没确认的发布")
        return {"job": store.update_publish_job(job_id, state="cancelled", finished_at=now_iso())}

    @app.get("/api/video-projects/{name}/raw/{relative:path}")
    def project_raw(name: str, relative: str):
        """按路径服务项目文件，只读。审批页里的相对地址靠它解析；视频支持拖动进度（Range）。"""
        from urllib.parse import quote

        try:
            path = video_project.raw_file(video_root(), name, relative)
        except VideoProjectError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        kind = video_project.RAW_TYPES[path.suffix.lower()]
        headers = {"X-Content-Type-Options": "nosniff"}
        if path.suffix.lower() in {".html", ".svg"}:
            # 能跑脚本的文件一律放进隔离的源：就算在新标签页直接打开，也碰不到工作台的接口。
            headers["Content-Security-Policy"] = "sandbox allow-scripts allow-popups"
        if path.suffix.lower() == ".html":
            base = video_project.project_dir(video_root(), name)
            prefix = f"/api/video-projects/{quote(name)}/raw/"
            html = video_project.rewrite_local_urls(path.read_text(encoding="utf-8", errors="replace"), base, prefix)
            return Response(content=html, media_type=kind, headers=headers)
        return FileResponse(path, media_type=kind, headers=headers)

    @app.get("/api/video-projects/{name}/file")
    def video_project_file(name: str, path: str) -> Response:
        target = video_project.safe_file(video_root(), name, path)
        headers = {"Cache-Control": "no-store"}
        if path == "analysis/worktable.html":
            # The skill's own worktable keeps Park's picks in localStorage, which a sandboxed origin cannot use.
            pass
        elif target.suffix.lower() == ".html":
            # Worktable pages need their own scripts and JSON export, but must not reach this app's API.
            headers["Content-Security-Policy"] = "sandbox allow-scripts allow-downloads allow-popups"
        return FileResponse(target, headers=headers)

    # -- publish & performance -------------------------------------------

    @app.get("/api/topics/{topic_id}/publish")
    def topic_publish(topic_id: int) -> dict[str, Any]:
        from . import publish

        topic = store.topic(topic_id)
        me = store.self_account(topic.get("account_id")) or store.self_account()
        if me is None:
            return {"account": None, "video": None, "suggestions": [], "recent": [], "stale_sync": False}
        videos = [v for v in store.videos(me["id"]) if not v["is_image_post"]]
        taken = {t["published_video_id"] for t in store.topics(include_archived=True) if t.get("published_video_id") and t["id"] != topic_id}
        result: dict[str, Any] = {
            "account": {"id": me["id"], "nickname": me["nickname"], "last_synced_at": me["last_synced_at"], "syncing": me["id"] in ops.syncing or ops.full_sync_running},
            "stale_sync": publish.sync_is_stale(me["last_synced_at"]),
            "video": None,
            "suggestions": [],
            "recent": [{k: v[k] for k in ("video_id", "title", "published_at", "likes")} for v in videos if v["video_id"] not in taken][:15],
        }
        linked = store.video(topic["published_video_id"]) if topic.get("published_video_id") else None
        if linked:
            result["video"] = publish.performance(
                linked,
                median_likes=store.account_median(linked["account_id"]),
                snapshots=store.snapshots(linked["video_id"]),
                creator=_creator_rows(creator_db).get(linked["video_id"]),
                has_report=report_file(linked["video_id"]) is not None,
            ) | {"job": job_view(store.job_for_video(linked["video_id"]))}
        else:
            result["suggestions"] = [
                {k: v[k] for k in ("video_id", "title", "published_at", "likes", "score")} for v in publish.suggest_matches(topic, videos, taken)
            ]
        return result

    @app.put("/api/topics/{topic_id}/publish")
    def link_publish(topic_id: int, body: PublishBody) -> dict[str, Any]:
        topic = store.topic(topic_id)
        if not body.video_id:
            return store.update_topic(topic_id, published_video_id=None)
        video = store.video(body.video_id)
        if video is None or not store.account(video["account_id"])["is_self"]:
            raise ValueError("只能关联你自己账号里已同步的视频")
        fields: dict[str, Any] = {"published_video_id": body.video_id}
        if topic["status"] != "published":
            fields["status"] = "published"
        if not topic.get("published_url"):
            fields["published_url"] = f"https://www.douyin.com/video/{body.video_id}"
        return store.update_topic(topic_id, **fields)

    # -- copy packs & platform records ------------------------------------

    @app.get("/api/topics/{topic_id}/copy")
    def get_copy(topic_id: int) -> dict[str, Any]:
        from . import copypack

        store.topic(topic_id)
        return {
            "platforms_spec": copypack.PLATFORMS,
            "copy": copypack.read_copy(drafts_root, topic_id),
            "records": store.publish_records(topic_id),
        }

    @app.put("/api/topics/{topic_id}/copy")
    def put_copy(topic_id: int, body: CopyBody) -> dict[str, Any]:
        from . import copypack

        store.topic(topic_id)
        unknown = set(body.platforms) - set(copypack.PLATFORMS)
        if unknown:
            raise ValueError(f"未知平台：{sorted(unknown)}")
        current = (copypack.read_copy(drafts_root, topic_id) or {}).get("platforms", {})
        merged = {**current, **{k: {"title": v.get("title") or "", "body": v.get("body") or "", "tags": [str(t).strip().lstrip("#") for t in v.get("tags") or [] if str(t).strip()]} for k, v in body.platforms.items()}}
        copypack.save_copy(drafts_root, topic_id, merged)
        return copypack.read_copy(drafts_root, topic_id) or {}

    @app.put("/api/topics/{topic_id}/platforms")
    def put_record(topic_id: int, body: RecordBody) -> dict[str, Any]:
        from . import copypack

        store.topic(topic_id)
        if body.platform not in copypack.PLATFORMS:
            raise ValueError("未知平台")
        if body.url and not body.url.startswith(("https://", "http://")):
            raise ValueError("链接需要以 https:// 开头")
        return store.set_publish_record(topic_id, body.platform, published=body.published, url=body.url)

    @app.put("/api/topics/{topic_id}/skip")
    def put_skip(topic_id: int, body: SkipBody) -> dict[str, Any]:
        """这一条不发某个平台：发布台的顺序跳过它，走下一个。"""
        from . import copypack

        store.topic(topic_id)
        if body.platform not in copypack.PLATFORMS:
            raise ValueError("未知平台")
        return {"skipped": sorted(store.set_publish_skip(topic_id, body.platform, skip=body.skip))}

    @app.get("/api/topics/{topic_id}/article")
    def get_article(topic_id: int) -> dict[str, Any]:
        draft = writer.read_draft(store.topic(topic_id))
        if draft is None:
            raise HTTPException(status_code=404, detail="这个选题还没有文章草稿")
        return draft

    @app.put("/api/topics/{topic_id}/article")
    def put_article(topic_id: int, body: ArticleBody) -> dict[str, Any]:
        topic = store.topic(topic_id)
        if not body.markdown.strip():
            raise ValueError("正文不能为空")
        path = Path(topic["article_path"]) if topic.get("article_path") else drafts_root / f"topic-{topic_id}" / "article.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body.markdown if body.markdown.endswith("\n") else body.markdown + "\n", encoding="utf-8")
        if not topic.get("article_path"):
            store.update_topic(topic_id, article_path=str(path), status="drafting" if topic["status"] == "todo" else topic["status"])
        return writer.read_draft(store.topic(topic_id)) or {}

    @app.get("/api/topics/{topic_id}/article.md")
    def download_article(topic_id: int) -> Response:
        draft = writer.read_draft(store.topic(topic_id))
        if draft is None:
            raise HTTPException(status_code=404, detail="这个选题还没有文章草稿")
        return Response(
            draft["markdown"].encode("utf-8"),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''topic-{topic_id}.md", "Cache-Control": "no-store"},
        )

    @app.post("/api/topics/{topic_id}/handoff")
    def handoff(topic_id: int) -> dict[str, Any]:
        topic = store.topic(topic_id)
        if writer.read_draft(topic) is None:
            raise ValueError("还没有文章草稿，先写文章")
        if topic["status"] in ("todo", "drafting"):
            topic = store.update_topic(topic_id, status="ready")
        return {"topic": topic, "admin_url": store.settings()["yanxishi_admin_url"] or None}

    # -- processing board ------------------------------------------------------

    def shot_days() -> set[str]:
        days = set(store.checked_days("video_shot"))
        for account in store.accounts():
            if account["is_self"]:
                days.update(d for d in (today_plan._day(v["published_at"]) for v in store.videos(account["id"]) if not v["is_image_post"]) if d)
        return days

    @app.get("/api/board")
    def get_board(day: str | None = None) -> dict[str, Any]:
        from . import board, opening, qa

        target = parse_day(day)
        topics = store.topics()
        active = [t for t in topics if not board.is_shipped(t)]
        root = None
        try:
            root = video_root()
        except VideoProjectError:
            pass
        cards = []
        for topic in active:
            project = None
            if topic.get("video_project") and root is not None:
                try:
                    project = video_project.inspect(root, topic["video_project"])
                except VideoProjectError:
                    project = None
            cards.append(board.card(topic, project, opening.load(drafts_root, topic["id"]), qa.load(drafts_root, topic["id"])))
        today_key = target.isoformat()
        focus = next((c for c in cards if c["focus"] and c["mine"]), None)
        snoozed = [c for c in cards if c["snoozed_until"] and c["snoozed_until"] > today_key and c is not focus]
        pool = [c for c in cards if c["mine"] and c is not focus and c not in snoozed]
        machine = [c for c in cards if not c["mine"]]
        return {
            "stages": [{"key": k, "label": label} for k, label in board.STAGES],
            "milestones": [{"key": k, "label": label} for k, label in board.MILESTONES],
            "cards": cards,
            "focus": focus,
            "pool": pool,
            "machine": machine,
            "snoozed": snoozed,
            "streak": today_plan.shooting_streak(target, shot_days()),
            "project_root_ok": root is not None,
        }

    # -- 今天：用 KPI 驱动 Park，一次只给一件事（driver.py） ------------------------

    def posted_days() -> set[str]:
        days: set[str] = set()
        for account in store.my_accounts():
            if account["platform"] == PLATFORM_DOUYIN:
                days.update(d for d in (today_plan._day(v["published_at"]) for v in store.videos(account["id"]) if not v["is_image_post"]) if d)
        return days

    READ_DAILIES = (("ai_daily", "AI 日报", "ai_daily"), ("kline_daily", "K 线日报", "kline"))  # (key, 名字, 进项里的 tab)

    def posted_titles() -> dict[str, list[str]]:
        """哪天在抖音发了哪几条（周历上过去的日子写的就是这个）。"""
        out: dict[str, list[str]] = {}
        for account in store.my_accounts():
            if account["platform"] != PLATFORM_DOUYIN:
                continue
            for v in store.videos(account["id"]):
                day = today_plan._day(v["published_at"])
                if day and not v["is_image_post"]:
                    out.setdefault(day, []).append(" ".join((v.get("title") or "").split())[:40] or "（没有标题）")
        return out

    def _sent_by_day() -> dict[str, list[dict[str, str]]]:
        """哪天往哪个平台发了哪条（不含抖音的新视频）：月历每一格写的就是这个。"""
        from . import backfill, copypack

        out: dict[str, list[dict[str, str]]] = {}
        for r in store.sent_rows():
            when = _local(r["at"])
            if when is None:
                continue
            title = backfill.split_douyin_title(r["title"] or "")["title"] or (r["title"] or "")[:30]
            out.setdefault(when.date().isoformat(), []).append(
                {"platform": r["platform"], "label": (copypack.PLATFORMS.get(r["platform"]) or {}).get("label", r["platform"]), "title": title[:40],
                 "marked": r["kind"] == "mark"})
        return out

    def _month(anchor: date, today: date) -> dict[str, Any]:
        """月历：这个月每一周（周一到周日，头尾带上邻月的几天）。每一天的内容和周历一样，多一项 sent（那天往哪些平台发了什么）。"""
        from . import driver

        first = anchor.replace(day=1)
        nxt = (first + timedelta(days=32)).replace(day=1)
        weeks, start = [], driver.week_start(first)
        sent = _sent_by_day()
        while start < nxt:
            week = _week(start, today)
            for d in week["days"]:
                d["sent"] = sent.get(d["day"], [])
                d["in_month"] = d["day"][:7] == first.isoformat()[:7]
            weeks.append(week)
            start += timedelta(days=7)
        return {"month": first.isoformat()[:7], "prev": (first - timedelta(days=1)).replace(day=1).isoformat(), "next": nxt.isoformat(),
                "current": first.isoformat()[:7] == today.isoformat()[:7], "weeks": weeks}

    def _week(start: date, today: date) -> dict[str, Any]:
        """周历的一周（周一到周日）：过去每天算分的几项做没做到、减几分、发了哪条；今天和以后排了拍哪条、别的事。
        分数的规则和「今天」是同一套（driver.kpi_range）；排哪天拍哪条只读他自己排的，不自动排。"""
        from . import driver

        end = start + timedelta(days=6)
        since, until, tkey = start.isoformat(), end.isoformat(), today.isoformat()
        kpi = kpi_config()
        titles = posted_titles()
        reads: dict[str, bool] = {}
        for i in range(7):
            d = start + timedelta(days=i)
            if d <= today and d.isoformat() >= kpi["read_started"]:
                ok = read_state(d)[1]
                if ok is not None:
                    reads[d.isoformat()] = ok
        filled = backfilled_days()
        days = driver.kpi_range(start, end, today, posted=set(titles) | filled, dms=store.dm_entries(since), started=kpi["started"],
                                x_replies=store.kpi_counts(since, "x_replies"), x_target=int(kpi["x_replies_daily"]),
                                reads=reads, read_started=kpi["read_started"], ship_started=min(titles) if titles else "9999")
        notes = [n for n in store.shoot_list(include_done=True) if since <= (n.get("planned_day") or "") <= until]
        items = store.plan_items(since, until)
        skips = [r for r in store.driver_log(since, "skip") if r["day"] <= until]
        for d in days:
            key = d["day"]
            d["state"] = "today" if key == tkey else "past" if key < tkey else "future"
            d["demerits"] = driver.demerits([d])
            d["shipped"] = titles.get(key, [])
            d["backfilled"] = key in filled and not d["shipped"]  # 这天没发新的，补发了当天那几格
            d["planned"] = [{"id": n["id"], "text": n["text"], "topic_id": n["topic_id"], "done": bool(n["done_at"])} for n in notes if n["planned_day"] == key]
            d["items"] = [{"id": it["id"], "text": it["text"], "done": bool(it["done_at"])} for it in items if it["day"] == key]
            d["skips"] = [{"what": r["key"], "reason": r["reason"]} for r in skips if r["day"] == key]
        counted = [d for d in days if d["ship"] in ("ok", "miss")]
        # 每周下限：一周至少这么多条新视频，少一条减 1 分。周过完才扣；定规矩之前的周不倒扣。
        new_videos, new_target = sum(len(titles.get(d["day"], [])) for d in days), int(kpi["new_weekly"])
        counts = since >= kpi["new_weekly_started"]
        new_short = max(0, new_target - new_videos) if counts and end < today else 0
        return {"start": since, "end": until, "prev": (start - timedelta(days=7)).isoformat(), "next": (start + timedelta(days=7)).isoformat(),
                "current": start == driver.week_start(today), "days": days,
                "shipped": sum(d["ship"] == "ok" for d in days), "ship_days": len(counted), "demerits": driver.demerits(days) + new_short,
                "new_videos": new_videos, "new_target": new_target, "new_short": new_short, "new_counts": counts,
                "x_target": int(kpi["x_replies_daily"])}

    def read_state(day: date) -> tuple[list[dict[str, Any]], bool | None]:
        """那天要读的日报：出了的才要读。返回每份的状态，和是不是都读完了（一份都没出 → None）。"""
        from . import kline_board

        checks = store.daily_checks(day.isoformat())
        try:
            found = {d["key"]: d["path"] for d in vault.dailies(vault_path(), day)}
        except vault.VaultError:
            found = {}
        # K 线日报有自己的 tab（kline_board），profile 里不一定把它列成日报来源：直接看那天的文件在不在
        if not found.get("kline_daily") and kline_board.KLINE_DIR.is_dir():
            tokens = vault.date_tokens(day)
            found["kline_daily"] = next((str(f) for f in sorted(kline_board.KLINE_DIR.iterdir())
                                         if f.suffix == ".md" and "kline-daily-newsletter" in f.name and any(t in f.name for t in tokens)), None)
        items = [{"key": k, "label": label, "tab": tab, "exists": bool(found.get(k)), "read_at": checks.get(k)}
                 for k, label, tab in READ_DAILIES]
        due = [i for i in items if i["exists"]]
        return items, (all(i["read_at"] for i in due) if due else None)

    def kpi_config() -> dict[str, Any]:
        from .store import DEFAULT_SETTINGS

        return {**DEFAULT_SETTINGS["kpi"], **(store.settings().get("kpi") or {})}

    # -- 今天出摊的两条路（9/30 Park）：发一条新视频，或者补发当天那几格旧内容 ------------------
    OUT_KEY = "out"
    bw_lock = threading.Lock()
    bw_run: dict[str, Any] = {"day": "", "items": [], "running": False}  # 补发工作台今天这一批发到哪了

    def backfilled_days() -> set[str]:
        """没发新视频、但把当天排的补发格子都发完了的日子：也算出摊。"""
        return {r["day"] for r in store.driver_log("", "bfday")}

    def shipped_days() -> set[str]:
        """出摊了的日子 = 发了新视频的 ∪ 补发完成的。只给算分和连续天数用；
        「今天抖音发没发」「这一周几条新视频」还是只看 posted_days()。"""
        return posted_days() | backfilled_days()

    def _open_cells(sheet: dict[str, Any]) -> list[dict[str, Any]]:
        """现在就能发的格子（一条内容 × 一个平台）。不算：不补发的、发过的、还没打好包的、视频平台上没有成片的。"""
        from . import backfill, reach

        labels = {p["key"]: p["label"] for p in sheet["platforms"]}
        cells = []
        for r in sheet["videos"]:
            if r.get("cancelled") or not r["topic_id"] or not r["missing"]:
                continue
            try:
                if not _pack_view(r)["ready"]:
                    continue
            except StoreError:
                continue
            held = _evidence_pending(r["topic_id"])
            for k in r["missing"]:
                if backfill.KIND.get(k) == "视频" and not r.get("video"):
                    continue
                if held and k in EVIDENCE_HOLD:
                    continue
                cells.append({"video_id": r["video_id"], "topic_id": r["topic_id"], "platform": k, "label": labels.get(k, k),
                              "tier": "major" if k in reach.CORE else "minor", "title": r["headline"] or r["title"][:40]})
        return cells

    def _out_state(today_key: str, sheet: dict[str, Any]) -> dict[str, Any]:
        """今天不发新视频的话补哪几格：Park 在补发工作台自己挑（10/1 起，原来是每天随机抽 4 格）。
        一格发没发直接看全平台追踪（发布台、补发工作台发的有发布记录，外面发的他点「发了」）。
        挑够 4 格（kpi.backfill_cells）并且都发完，这一天记成出摊。"""
        from . import reach

        need = int(kpi_config()["backfill_cells"])
        labels = {p["key"]: p["label"] for p in sheet["platforms"]}
        rows = {r["video_id"]: r for r in sheet["videos"]}
        cells = []
        for row in store.backfill_plan(today_key):
            r = rows.get(row["video_id"])
            if r is None or r.get("cancelled"):
                continue
            cells.append({"slot": row["slot"], "video_id": row["video_id"], "topic_id": r["topic_id"], "platform": row["platform"],
                          "label": labels.get(row["platform"], row["platform"]), "tier": "major" if row["platform"] in reach.CORE else "minor",
                          "title": r["headline"] or r["title"][:40], "sent": row["platform"] not in r["missing"],
                          "marked": (r.get("done") or {}).get(row["platform"]) == "mark"})
        if len(cells) < need:
            # 追平到最后剩下的不够 4 格：有几格算几格，不能让他把能发的都发了还减分
            planned = {(c["video_id"], c["platform"]) for c in cells}
            avail = len(cells) + sum(1 for c in _open_cells(sheet) if (c["video_id"], c["platform"]) not in planned)
            need = min(need, avail) if avail else need
        done = len(cells) >= need and all(c["sent"] for c in cells)
        if done:
            store.driver_mark(today_key, OUT_KEY, "bfday")
        else:
            store.driver_unmark(today_key, OUT_KEY, "bfday")
        modes = [r for r in store.driver_log(today_key, "mode") if r["day"] == today_key]
        return {"mode": modes[-1]["reason"] if modes else None, "cells": cells, "sent": sum(c["sent"] for c in cells), "done": done,
                "need": need, "left": sum(len(r["missing"]) for r in sheet["videos"]),
                "running": bw_run["running"] and bw_run["day"] == today_key}

    def _ship_action(cards: list[dict[str, Any]], desk: dict[str, Any], notes: list[dict[str, Any]], rung: str) -> dict[str, Any] | None:
        """出摊这一格现在该做什么：手上快发出去的先做完，然后是他清单里的第一条，再是正在做的那条。"""
        from . import driver

        prefix = "明天出摊：" if rung == "tomorrow" else ""
        topic = desk.get("topic")
        if topic and not any(r["key"] == "douyin" and r["shipped"] for r in desk.get("platforms") or []):
            ap = desk.get("approvals") or {}
            missing = [label for k, label in (("copy", "标题和描述"), ("cover", "封面")) if not ((ap.get(k) or {}).get("approved") and (ap.get(k) or {}).get("valid"))]
            if missing:
                return driver.item(rung, f"pack:{topic['id']}", f"{prefix}打包《{topic['title'][:24]}》：先把{'、'.join(missing)}定稿",
                                   why="成片好了，定完稿就能发。", go=f"pack/{topic['id']}", button="去打包")
            return driver.item(rung, f"douyin:{topic['id']}", f"{prefix}把《{topic['title'][:24]}》发到抖音",
                               why="打包都定稿了。打开上传文件夹，视频和封面都在里面。", go=f"publish/{topic['id']}", button="去发布")
        by_id = {c["id"]: c for c in cards}
        near = [c for c in cards if c["stage"] in ("edit", "ready") and c["next"]["mine"]]
        if near:
            c = max(near, key=lambda c: c["milestone"])
            return driver.item(rung, f"card:{c['id']}", f"{prefix}{c['next']['text']}：《{c['title'][:24]}》", why="离发出最近的这条先做完。", go=f"work/{c['id']}")
        for note in notes:
            card = by_id.get(note.get("topic_id"))
            target = (date.today() + timedelta(days=1 if rung == "tomorrow" else 0)).isoformat()
            lead = f"你排在{'明天' if rung == 'tomorrow' else '今天'}的这一条。" if note.get("planned_day") == target else "你清单里的第一条。"
            if card is not None:
                return driver.item(rung, f"card:{card['id']}", f"{prefix}{card['next']['text']}：《{card['title'][:24]}》",
                                   why=lead, go=f"work/{card['id']}")
            if note.get("topic_id") is None:
                return driver.item(rung, f"note:{note['id']}", f"{prefix}拍「{note['text']}」", why=f"{lead}点「开始做」建成选题，接着写提纲。",
                                   button="开始做", inputs="start_note")
        focus = next((c for c in cards if c["focus"] and c["next"]["mine"]), None)
        if focus:
            return driver.item(rung, f"card:{focus['id']}", f"{prefix}{focus['next']['text']}：《{focus['title'][:24]}》", why="正在做的这条。", go=f"work/{focus['id']}")
        return driver.item(rung, "notes:empty", f"{prefix}写下接下来要拍的", why="清单是空的。写一条，或者点「我今天不知道拍什么」。", inputs="focus_notes")

    def _ship_state(today_key: str, posted: set[str], desk: dict[str, Any], cards: list[dict[str, Any]], notes: list[dict[str, Any]]) -> dict[str, Any]:
        """A 出摊：今天这条发到哪些平台了（发视频 / 发文字），下一步是什么。
        今天抖音发了就以那条为准；没发就是发布台手上那条（离发出最近的）。"""
        from . import copypack, driver, reach

        topic = None
        if today_key in posted:
            me = store.self_account()
            vids = {v["video_id"] for v in store.videos(me["id"]) if today_plan._day(v["published_at"]) == today_key} if me else set()
            topic = next((t for t in store.topics() if t.get("published_video_id") in vids), None)
            if topic is None:
                # 没对上视频号的（9/29 那条就是）：抖音链接里带着视频号，照它找
                from .links import post_id

                topic = next((t for t in store.topics() if post_id("douyin", (store.publish_records(t["id"]).get("douyin") or {}).get("url")) in vids), None)
        if topic is None and desk.get("topic"):
            topic = store.topic(desk["topic"]["id"])
        records = store.publish_records(topic["id"]) if topic else {}
        rows = {r["key"]: r for r in desk.get("platforms") or []} if desk.get("topic") and topic and desk["topic"]["id"] == topic["id"] else {}
        accounts = store.settings()["platform_accounts"] or {}
        platforms = []
        for key in publish_desk_mod.SEQUENCE:
            on = bool((accounts.get(key) or {}).get("on")) if key in accounts else key in reach.CORE or key in ("bilibili", "youtube", "wechat_mp")
            if not on:
                continue
            shipped = key in records or (key == "douyin" and topic is not None and bool(topic.get("published_video_id")))
            platforms.append({"key": key, "label": (copypack.PLATFORMS.get(key) or {}).get("label", key), "form": reach.form_of(key, accounts),
                              "core": key in reach.CORE, "shipped": shipped, "skipped": bool((rows.get(key) or {}).get("skipped")),
                              "draft": bool(((rows.get(key) or {}).get("job") or {}).get("draft")) and not shipped})
        done_today = today_key in posted
        nxt = _ship_action(cards, desk, notes, "tomorrow" if done_today else "ship")
        # 抖音发了、别的平台还没发完：下一步就是把剩下的发完（出摊 = send everything out）
        left = [p for p in platforms if not p["shipped"] and not p["skipped"]]
        if done_today and topic and left and desk.get("topic") and desk["topic"]["id"] == topic["id"]:
            first = left[0]
            text = f"去{first['label']}后台点发布，回来点「发出去了」" if first["draft"] else f"发完剩下的平台：下一个是{first['label']}"
            nxt = driver.item("ship", f"rest:{topic['id']}", text, why=f"《{topic['title'][:24]}》抖音已经发了，还差 {len(left)} 个平台。", go=f"publish/{topic['id']}", button="去发布")
        return {"done": done_today, "topic": {"id": topic["id"], "title": topic["title"]} if topic else None,
                "platforms": platforms, "next": nxt}

    @app.get("/api/today")
    def get_today() -> dict[str, Any]:
        from . import consult, copypack, driver

        today = date.today()
        tkey = today.isoformat()
        kpi = kpi_config()
        posted = posted_days()
        since = (today - timedelta(days=driver.WINDOW)).isoformat()
        dms = store.dm_entries(since)
        xr = store.kpi_counts(since, "x_replies")
        reads = {}
        for i in range(driver.WINDOW):
            d = today - timedelta(days=i)
            if d.isoformat() >= kpi["read_started"]:
                ok = read_state(d)[1]
                if ok is not None:
                    reads[d.isoformat()] = ok
        sheet = get_backfill()
        out = _out_state(tkey, sheet)  # 先算：补发完成的话，今天也算出摊
        shipped = shipped_days()
        days = driver.kpi_days(today, posted=shipped, dms=dms, started=kpi["started"], x_replies=xr, x_target=int(kpi["x_replies_daily"]),
                               reads=reads, read_started=kpi["read_started"])
        reach = get_reach(14)
        # 清单里那条的选题发出去了，这条就划掉
        for note in store.shoot_list():
            if note.get("topic_id"):
                try:
                    if board_mod.is_shipped(store.topic(note["topic_id"])):
                        store.update_shoot_item(note["id"], done_at=now_iso())
                except StoreError:
                    store.update_shoot_item(note["id"], topic_id=None)
        notes = store.shoot_list()
        cards = [c for c in get_board(None)["cards"] if not (c.get("snoozed_until") and c["snoozed_until"] > tkey)]
        desk = publish_desk(None)
        skipped = {r["key"] for r in store.driver_log(tkey, "skip") if r["day"] == tkey}
        done_keys = {r["key"] for r in store.driver_log("", "done")}

        # 先处理：机器卡住了、客户交付（有才出现）
        first: list[dict[str, Any]] = []
        try:
            load_cookie_file(cookie_path)
        except CookieFileError as exc:
            first.append(driver.item("blocker", "cookies", "抖音登录过期了：重新导出 cookies", why=str(exc)[:120], go="settings", button="去设置"))
        vs = vault_status(store.settings()["obsidian_vault"])
        if not vs["ok"]:
            first.append(driver.item("blocker", "vault", "Obsidian 连不上", why=vs["message"], go="settings", button="去设置"))
        stopped = (ops.last_full_sync or {}).get("stopped")
        if stopped:
            first.append(driver.item("blocker", "risk", "抖音要求验证：在你的浏览器里打开抖音完成验证", why=str(stopped)[:120], manual=True))
        topic = desk.get("topic")
        for row in desk.get("platforms") or []:
            if topic and (row.get("job") or {}).get("state") == "failed" and not row["shipped"]:
                first.append(driver.item("blocker", f"failed:{topic['id']}:{row['key']}", f"发{row['label']}失败了：去看一眼，点重试",
                                         why=((row["job"] or {}).get("message") or "")[:120], go=f"publish/{topic['id']}"))
        cutoff = (today - timedelta(days=14)).isoformat()
        for row in consult.jobs():
            c = _consult_row(row)
            if c["stage"] == "done" and c.get("pdf") and (c.get("day") or "") >= cutoff:
                first.append(driver.item("client", f"consult:{c['slug']}", f"把「{c['name']}」的客户版 PDF 发过去",
                                         why=f"{c['day']} 的咨询，纪要已经出来了。发没发工作台看不到，发完点「发了」。",
                                         url=c["pdf"], button="打开 PDF", manual=True))

        # 排在今天的那条先提；今天已经发了，就看排在明天的。没排日子的还是照清单顺序。
        target = (today + timedelta(days=1)).isoformat() if tkey in posted else tkey
        ship = _ship_state(tkey, posted, desk, cards, driver.plan_order(notes, target))
        if ship["next"] and ship["next"]["key"] in skipped:
            ship["next"] = None

        # 杂事：手填的平台今天的播放
        wrap: list[dict[str, Any]] = []
        manual = [p["label"] for p in reach.get("platforms") or [] if p["on"] and not p["auto"] and p.get("today") is None and p["key"] in copypack.PLATFORMS]
        if manual:
            wrap.append(driver.item("wrap", f"reach:{tkey}", f"填今天{'、'.join(manual)}的播放", why="1 分钟。概览页的格子里填。", go="output"))

        entry = dms.get(tkey)
        return {
            "day": tkey,
            "demerits": driver.demerits(days),
            "days": days,
            "first": driver.order(first, skipped=skipped, done=done_keys),
            "ship": {**ship, "notes": notes, "suggest": suggest_state()},
            "rd": {"items": read_state(today)[0]},
            "dm": {"entry": entry, "target": kpi["dm_daily"], "baseline_until": kpi["dm_baseline_until"]},
            "xr": {"count": xr.get(tkey), "target": int(kpi["x_replies_daily"])},
            "reach": {"avg7": reach.get("avg7"), "target": kpi["reach_daily"], "by": kpi["reach_by"]},
            "wrap": driver.order(wrap, skipped=skipped, done=done_keys),
            "skipped": [r for r in store.driver_log(tkey, "skip") if r["day"] == tkey],
            # 周历：这一周（周一到周日）和他现在连着几天出摊 / 没出摊。上面的 days、demerits 还是最近 7 天，含义不变。
            "week": _week(driver.week_start(today), today),
            "streak": driver.ship_streak(today, shipped),
            # 今天出摊的两条路：发新视频，或者补发这几格（mode 是他早上选的，只决定卡片先给他看哪条路；算分只看结果）
            "out": out,
            # 现在在哪个阶段（追平）：旧内容还剩几格、连续出摊几天、出关没有
            "stage": driver.stage(backlog=out["left"], streak=driver.ship_streak(today, shipped), streak_target=int(kpi["ship_streak_target"])),
        }

    @app.get("/api/today/month")
    def get_month(start: str | None = None) -> dict[str, Any]:
        """月历：start 是那个月里的任意一天，不传就是这个月。"""
        from . import driver

        today = date.today()
        return {**_month(parse_day(start), today), "streak": driver.ship_streak(today, shipped_days())}

    @app.post("/api/today/mode")
    def set_today_mode(body: ModeBody) -> dict[str, Any]:
        """早上那个问题的回答：今天发新视频，还是补发。只决定卡片先给他看哪条路，随时能改；算分只看结果。"""
        if body.mode not in ("new", "backfill"):
            raise ValueError("只能选「发新视频」或「补发」")
        store.driver_mark(date.today().isoformat(), "mode", "mode", body.mode)
        return {"mode": body.mode}

    def _plan_cell(slot: int) -> dict[str, Any]:
        row = next((r for r in store.backfill_plan(date.today().isoformat()) if r["slot"] == slot), None)
        if row is None:
            raise ValueError("今天没有排这一格")
        return row

    @app.post("/api/today/cells/{slot}/sent")
    def cell_sent(slot: int, body: CellSentBody) -> dict[str, Any]:
        """这一格他在外面发了（或者点错了撤回）：记在全平台追踪里，和那边的「标已发」是同一笔。"""
        row = _plan_cell(slot)
        store.set_backfill_mark(row["video_id"], row["platform"], body.sent)
        return {"ok": True}

    # -- 补发工作台（10/1 Park）-------------------------------------------------------------
    # 「我要每天看大家的情绪和 mood……自己想好今天最适合发什么」：在一张和全平台追踪一样的表上点格子，
    # 点的顺序就是发的顺序；换个样子再给他看一遍，他点确认，工作台按顺序一格一格现场发。
    # 证据图找到了、他还没挑：这几个文字平台先不让发（发出去就改不了图了，10/2 那篇就是这么漏的）
    EVIDENCE_HOLD = ("x", "wechat_mp", "miniprogram")

    # B 站、YouTube、X 自己发出去；公众号进草稿箱（9/27 他定的，群发他点）；视频号（腾讯封了自动发布）、
    # 小红书没有自动通道：上传文件夹备好，他传完点「发了」。
    BW_HOW = {"bilibili": ("auto", "自动投稿，B 站审核后公开"), "youtube": ("auto", "自动上传，直接公开"),
              "x": ("auto", "自动发 X 图文文章（被拒就存草稿）"), "wechat_mp": ("draft", "存进公众号草稿箱，群发你点"),
              "channels": ("hand", "视频号不让自动发：上传文件夹备好，你传"), "xiaohongshu": ("hand", "上传文件夹备好，你传")}
    BW_UPLOAD = {"channels": "https://channels.weixin.qq.com/platform/post/create",
                 "xiaohongshu": "https://creator.xiaohongshu.com/publish/publish"}

    def _bw_blocked(r: dict[str, Any], platform: str) -> str:
        from . import backfill

        if not r["topic_id"]:
            return "还没接上选题：在全平台追踪点「拿去补发」"
        if backfill.KIND.get(platform) == "视频" and not r.get("video"):
            return "作品库里没有成片"
        if platform in EVIDENCE_HOLD and _evidence_pending(r["topic_id"]):
            return "证据图还没挑：去打包页「插图」那一步，要哪几张、还是都不要"
        return "包还没定稿：去打包页定稿"

    def _bw_pick(cells: list[dict[str, Any]], sheet: dict[str, Any], *, again: bool = False) -> list[dict[str, Any]]:
        """他点的格子，按点的顺序；每一格都得是现在就能发的、今天还没排的（again：今天排了还没发出去的，再发一次）。"""
        ready = {(c["video_id"], c["platform"]): c for c in _open_cells(sheet)}
        planned = {(r["video_id"], r["platform"]) for r in store.backfill_plan(date.today().isoformat())}
        out, seen = [], set()
        for c in cells:
            key = (str(c.get("video_id") or ""), str(c.get("platform") or ""))
            if key in seen:
                continue
            seen.add(key)
            if key in planned and not again:
                raise ValueError(f"{ready.get(key, {}).get('title', '这一条')}·{key[1]} 今天已经排上了")
            if key not in ready:
                raise ValueError("有一格现在发不了（发过了，或者包还没定稿），刷新一下再挑")
            out.append(ready[key])
        if not out:
            raise ValueError("先在表里点几格")
        return out

    def _bw_item(c: dict[str, Any]) -> dict[str, Any]:
        return {"video_id": c["video_id"], "topic_id": c["topic_id"], "platform": c["platform"], "label": c["label"], "title": c["title"],
                "how": BW_HOW.get(c["platform"], ("hand", ""))[0], "upload_url": BW_UPLOAD.get(c["platform"]), "state": "waiting", "message": ""}

    def _bw_snapshot(sheet: dict[str, Any]) -> dict[str, Any]:
        """今天排上的每一格发到哪一步了。排了哪几格存在库里（重启也在）；正在发的进度只在内存里，
        重启以后没进度的格子显示「还没发出去」，能再点一次发。"""
        from . import publisher

        today_key = date.today().isoformat()
        out = _out_state(today_key, sheet)
        with bw_lock:
            if bw_run["day"] != today_key:
                bw_run.update(day=today_key, items=[], running=False)
            live = {(it["video_id"], it["platform"]): dict(it) for it in bw_run["items"]}
            running = bw_run["running"]
        rows = {r["video_id"]: r for r in sheet["videos"]}
        items = []
        for c in out["cells"]:
            it = live.get((c["video_id"], c["platform"]))
            if it is None:
                it = {**_bw_item(c), "state": "idle"}
                # 没有进度（服务重启过）：库里这一格最近一次发布还挂在「在发」，说明上次发到一半被打断——
                # 不给「现在发」，免得同一条发两遍（9/27 YouTube 上传被重启打断过）
                job = next((j for j in store.publish_jobs(c["topic_id"]) if j["platform"] == c["platform"]), None) if c["topic_id"] else None
                if job and job["state"] == "running" and not c["sent"]:
                    it.update(state="stuck", message="上次发到一半被打断了：先去平台后台看一眼有没有发出去")
                elif job and job["state"] == "failed" and not c["sent"]:
                    # 重启以后也要记得上次为什么没发出去——不然又是一句「还没发出去」，他不知道该干什么
                    it.update(state="failed", message=job.get("message") or "", failed_at=job.get("finished_at") or job.get("created_at"))
                elif job and job["state"] == "done" and (job.get("result") or {}).get("published") is False and not c["sent"]:
                    it.update(state="draft", message="")  # 公众号进了草稿箱：重启以后也说清，别让他再发一遍
            it["sent"] = c["sent"]
            if not it["sent"] and it["state"] in ("failed", "login"):
                can_login = bool((publisher_specs().get(c["platform"]) or {}).get("login_argv"))
                it["diag"] = publisher.login_fix(c["platform"]) if it["state"] == "login" else publisher.diagnose(c["platform"], it.get("message") or "", can_login=can_login)
                if it["diag"]["fix"] == "login":
                    it["login"] = _login_view(c["platform"])
                    if it["login"]["state"] == "ok" or (it["state"] == "failed" and _login_cached_ok(c["platform"], after=it.get("failed_at"))):
                        # 已经登好了：这一格是登录之前失败的，下一步是再发，不是再登一次
                        it["diag"] = {**publisher.diagnose(c["platform"], ""), "why": "登好了。这一格是登录之前没发出去的。", "todo": "点「再发一次」。"}
            if it["sent"] and c["topic_id"]:
                # 自动发出去的，链接在这儿就能点（10/3 Park）
                rec = store.publish_records(c["topic_id"]).get(c["platform"]) or {}
                it["url"] = rec.get("url") if str(rec.get("url") or "").startswith("http") else None
            # 他点「发了」记下的（不是工作台自己发出去的）：审核没过、发错了可以撤回
            it["marked"] = ((rows.get(c["video_id"]) or {}).get("done") or {}).get(c["platform"]) == "mark"
            items.append(it)
        return {"items": items, "running": running, "need": out["need"]}

    def _evidence_inputs(topic: dict[str, Any], video_id: str | None = None) -> dict[str, Any]:
        """找证据图要的三样：文章、视频（剪辑前的原片更清楚）、字幕。缺了说为什么。"""
        from . import cover

        art = _article_path(topic)
        video = final_video_path(topic)
        row: dict[str, Any] = {"article": str(art) if art else None, "video": None, "transcript": None, "skip": None}
        if art is None or not art.is_file():
            row["skip"] = "还没有文章"
        elif video is None or not video.is_file():
            row["skip"] = "找不到视频（作品库那块硬盘没插？）"
        else:
            if topic.get("video_project"):
                try:
                    video = cover.source_video(video_project.project_dir(video_root(), topic["video_project"]), video)
                except VideoProjectError:
                    pass
            row["video"] = str(video)
            vid = video_id or topic.get("published_video_id")
            found = sorted((downloads_dir / "douyin").glob(f"*/{vid}/transcript.json")) if vid else []
            row["transcript"] = str(found[0]) if found else None
        return row

    @app.get("/api/evidence/queue")
    def evidence_queue() -> dict[str, Any]:
        """命令行 `content-studio evidence` 一次跑一批用：还有平台没发的内容里，有文章、有视频的。
        提案比文章新（跑过了、文章没再改）或者文章里已经有证据图的，标 done，跳过。"""
        from . import evidence

        out = []
        for r in get_backfill()["videos"]:
            if r.get("cancelled") or not r["missing"] or not r["topic_id"]:
                continue
            topic = store.topic(r["topic_id"])
            row = {"topic_id": topic["id"], "title": r["headline"] or topic["title"], "done": False, **_evidence_inputs(topic, r["video_id"])}
            if not row["skip"]:
                art = Path(row["article"])
                proposal = art.parent / evidence.OUT / evidence.PROPOSAL
                row["done"] = (proposal.is_file() and proposal.stat().st_mtime >= art.stat().st_mtime) or bool(evidence.in_article(art.read_text(encoding="utf-8")))
            out.append(row)
        return {"topics": out}

    # 打包页「插图」那一步：要不要找证据图他点了才找；找完一张张挑（10/2 Park）
    evidence_errors: dict[int, str] = {}

    def _evidence_view(topic_id: int) -> dict[str, Any]:
        from urllib.parse import quote

        from . import evidence

        topic = store.topic(topic_id)
        with writing_lock:
            running = 60_000 + topic_id in writing
        art = _article_path(topic)
        st = evidence.status(art) if art is not None and art.is_file() else {"state": "none", "items": [], "rejected": 0, "used": []}
        for i in st["items"]:
            i["src"] = f"/api/topics/{topic_id}/article-file/{evidence.OUT}/{quote(i['file'])}"
        return {"running": running, "error": evidence_errors.get(topic_id), "skip": _evidence_inputs(topic)["skip"], **st}

    @app.get("/api/topics/{topic_id}/evidence")
    def evidence_state(topic_id: int) -> dict[str, Any]:
        return _evidence_view(topic_id)

    @app.post("/api/topics/{topic_id}/evidence")
    def evidence_start(topic_id: int) -> dict[str, Any]:
        """开始找证据图（后台跑，2–4 分钟）：视频里的笔记截图、名人原推。只出提案，文章不动。"""
        from . import evidence

        topic = store.topic(topic_id)
        inputs = _evidence_inputs(topic)
        if inputs["skip"]:
            raise ValueError(inputs["skip"])
        if evidence.in_article(Path(inputs["article"]).read_text(encoding="utf-8")):
            raise ValueError("文章里已经放着证据图了：要重新找，先点「撤回」")
        with writing_lock:
            if 60_000 + topic_id in writing:
                return {"started": False, "message": "正在找"}
            writing.add(60_000 + topic_id)
        evidence_errors.pop(topic_id, None)

        def run() -> None:
            try:
                segments = []
                if inputs["transcript"]:
                    try:
                        segments = json.loads(Path(inputs["transcript"]).read_text(encoding="utf-8")).get("segments") or []
                    except (OSError, ValueError):
                        segments = []
                res = evidence.run_topic(Path(inputs["article"]), Path(inputs["video"]), segments=segments)
                n = sum(1 for i in res["items"] if i.get("placed"))
                store.log_event("copy", f"《{topic['title'][:24]}》找了证据图：{n} 张等你挑", topic_id)
            except Exception as exc:  # noqa: BLE001 - 打包页显示
                logger.warning("evidence %s failed: %s", topic_id, exc)
                evidence_errors[topic_id] = str(exc)[:300] or type(exc).__name__
            finally:
                with writing_lock:
                    writing.discard(60_000 + topic_id)

        threading.Thread(target=run, name=f"evidence-{topic_id}", daemon=True).start()
        return {"started": True, "message": "开始找证据图：视频里的笔记截图、名人原推，一般 2–4 分钟"}

    @app.post("/api/topics/{topic_id}/evidence/apply")
    def evidence_apply(topic_id: int, body: dict[str, Any]) -> dict[str, Any]:
        """他挑的放进文章；files 为空就是「这篇不要证据图」。放进去之后公众号排版作废，要重排。"""
        from . import evidence

        art = _article_path(store.topic(topic_id))
        if art is None or not art.is_file():
            raise ValueError("还没有文章")
        files = [str(f) for f in body.get("files") or []]
        try:
            evidence.apply(art, files, now=now_iso())
        except evidence.EvidenceError as exc:
            raise ValueError(str(exc)) from None
        return _evidence_view(topic_id)

    @app.post("/api/topics/{topic_id}/evidence/undo")
    def evidence_undo(topic_id: int) -> dict[str, Any]:
        from . import evidence

        art = _article_path(store.topic(topic_id))
        if art is None or not art.is_file():
            raise ValueError("还没有文章")
        try:
            evidence.undo(art)
        except evidence.EvidenceError as exc:
            raise ValueError(str(exc)) from None
        return _evidence_view(topic_id)

    def _evidence_pending(topic_id: int | None) -> bool:
        from . import evidence

        if not topic_id:
            return False
        try:
            art = _article_path(store.topic(topic_id))
        except StoreError:
            return False
        return art is not None and art.is_file() and evidence.pending(art)

    @app.get("/api/backfill/desk")
    def backfill_desk() -> dict[str, Any]:
        """补发工作台那张表：一行一条还有平台没发的内容，一格一个平台——发过了 / 今天排上了 / 能挑 / 发不了（为什么）。"""
        sheet = get_backfill()
        today_key = date.today().isoformat()
        ready = {(c["video_id"], c["platform"]) for c in _open_cells(sheet)}
        planned = {(r["video_id"], r["platform"]) for r in store.backfill_plan(today_key)}
        cols = [p for p in sheet["platforms"] if p["key"] != "douyin"]
        on_keys = _on_keys()
        rows = []
        done_rows = []  # 10/3 Park：发齐了的别消失，折起来，展开能看到每条发在了哪
        for r in sheet["videos"]:
            if r.get("cancelled"):
                continue
            cells = {}
            for p in cols:
                k, key = p["key"], (r["video_id"], p["key"])
                if r["done"].get(k) == "skip":
                    cells[k] = {"state": "skipped"}
                elif k not in r["missing"]:
                    cells[k] = {"state": "sent", "url": (r.get("links") or {}).get(k)}
                elif key in planned:
                    cells[k] = {"state": "planned"}
                elif key in ready:
                    cells[k] = {"state": "open"}
                else:
                    cells[k] = {"state": "blocked", "why": _bw_blocked(r, k)}
            # 「发布完毕」只给打包、发布页还挂着的那几条（两周内、还没发完）——老的补发内容没有「结」这回事
            t = store.topic(r["topic_id"]) if r["topic_id"] else None
            closable = bool(t and _fresh(t) and _unfinished(t, on_keys))
            row = {"video_id": r["video_id"], "topic_id": r["topic_id"], "title": r["headline"] or r["title"][:40],
                   "published_at": r["published_at"], "likes": r.get("likes"), "multiple": r.get("multiple"), "cells": cells,
                   "closable": closable and bool(r["missing"]),
                   # 抖音这一格：每条都从抖音来（10/3 Park：抖音也放进表里，最左边）
                   "douyin": {"url": (r.get("links") or {}).get("douyin"), "hidden": bool(r.get("hidden_on_douyin"))}}
            (rows if r["missing"] else done_rows).append(row)
        run = _bw_snapshot(sheet)
        need = run.pop("need")
        return {"platforms": [{**p, "how": BW_HOW.get(p["key"], ("hand", ""))[0], "how_text": BW_HOW.get(p["key"], ("hand", ""))[1]} for p in cols],
                "rows": rows, "done_rows": done_rows, "need": need, "planned": len(planned), "run": run}

    @app.post("/api/backfill/desk/preview")
    def backfill_desk_preview(body: dict[str, Any]) -> dict[str, Any]:
        """确认之前换个样子再看一遍：按他点的顺序，每格发出去是什么样、怎么发。"""
        from . import copypack, publish_desk

        sheet = get_backfill()
        picked = _bw_pick(body.get("cells") or [], sheet)
        items = []
        for i, c in enumerate(picked, 1):
            topic = store.topic(c["topic_id"])
            rel = _release_for(topic) or {}
            urls = rel.get("cover_urls") or {}
            copy = copypack.read_copy(drafts_root, c["topic_id"]) or {}
            entry = publish_desk.own_entry(copy.get("platforms"), c["platform"], publish_desk.shared_entry(copy))
            how, how_text = BW_HOW.get(c["platform"], ("hand", ""))
            article = None
            if c["platform"] in ("x", "wechat_mp"):
                pv = backfill_preview(c["topic_id"])
                article = {"title": pv["article_title"], "head": pv["article_head"][:2], "layout_url": pv["layout_url"]}
            cover = urls.get("wide") or urls.get("landscape") if c["platform"] in ("youtube", "bilibili", "wechat_mp", "x") else urls.get("portrait")
            items.append({"n": i, "video_id": c["video_id"], "topic_id": c["topic_id"], "platform": c["platform"], "label": c["label"],
                          "title": c["title"], "how": how, "how_text": how_text, "cover": cover or urls.get("portrait") or urls.get("landscape"),
                          "copy": entry, "article": article})
        out = _out_state(date.today().isoformat(), sheet)
        short = max(0, out["need"] - len(out["cells"]) - len(items))
        return {"items": items, "need": out["need"], "short": short}

    def _bw_run(items: list[dict[str, Any]]) -> None:
        """一格一格按顺序发：前一格发完才发下一格（一次只开一个浏览器）。"""
        modes = {**BACKFILL_AUTO, **BACKFILL_DRAFT}
        for it in items:
            with bw_lock:
                it["state"] = "running"
            # 10/3：YouTube 登录早就过期了，工作台照样去发，回来一屏 traceback。先查一下，没登上就不发，等他点登录
            spec = publisher_specs().get(it["platform"]) or {}
            if it["platform"] in modes and spec.get("login_argv") and _login_ok(it["platform"], spec) is False:
                with bw_lock:
                    it.update(state="login", message="")
                continue
            try:
                if it["platform"] in modes:
                    job = prepare_publish(it["topic_id"], PublishJobBody(platform=it["platform"], mode=modes[it["platform"]], auto=True))["job"]
                    store.update_publish_job(job["id"], state="running", confirmed_at=now_iso())
                    _run_publish(job["id"])
                    job = store.publish_job(job["id"])
                    draft = (job.get("result") or {}).get("published") is False
                    state = "failed" if job["state"] != "done" else "draft" if draft else "done"
                    msg = job.get("message") or ("进了草稿箱，去后台点发布" if draft else "")
                else:
                    upload_folder(it["topic_id"], {"platform": it["platform"], "open": False})
                    state, msg = "hand", "文件夹备好了：视频、封面、文案.txt"
            except HTTPException as exc:
                state, msg = "failed", str(exc.detail)
            except Exception as exc:  # noqa: BLE001 - shown on the item
                state, msg = "failed", str(exc)
            with bw_lock:
                it.update(state=state, message=msg, failed_at=now_iso() if state == "failed" else None)
        with bw_lock:
            bw_run["running"] = False

    @app.post("/api/backfill/desk/drop")
    def backfill_desk_drop(body: dict[str, Any]) -> dict[str, Any]:
        """今天排了、还没发出去的一格，不发了：从今天的格子里拿掉（发出去的拿不掉）。"""
        today_key = date.today().isoformat()
        key = (str(body.get("video_id") or ""), str(body.get("platform") or ""))
        sheet = get_backfill()
        cell = next((c for c in _out_state(today_key, sheet)["cells"] if (c["video_id"], c["platform"]) == key), None)
        if cell is None:
            raise ValueError("今天没有排这一格")
        if cell["sent"]:
            raise ValueError("这一格已经发出去了")
        with bw_lock:
            if any((it["video_id"], it["platform"]) == key and it["state"] in ("waiting", "running") for it in bw_run["items"]):
                raise ValueError("这一格正在发")
            bw_run["items"] = [it for it in bw_run["items"] if (it["video_id"], it["platform"]) != key]
            store.set_backfill_plan(today_key, [(r["video_id"], r["platform"]) for r in store.backfill_plan(today_key) if (r["video_id"], r["platform"]) != key])
        return {"ok": True}

    @app.post("/api/backfill/desk/go")
    def backfill_desk_go(body: dict[str, Any]) -> dict[str, Any]:
        """他点了确认：这几格排进今天，马上按顺序发。"""
        return _bw_start(_bw_pick(body.get("cells") or [], get_backfill(), again=True))

    def _login_cached_ok(key: str, *, after: str | None) -> bool:
        """失败之后的那次探测（登录后会真探一次，存在缓存里，重启也在）说登着：报登录过期的那次是登录之前的事。"""
        from . import channel_probe
        from .paths import config_dir

        spec = publisher_specs().get(key) or {}
        if not spec.get("login_argv"):
            return False
        hit = channel_probe._read_cache(config_dir() / "channel-probes.json").get(key) or {}
        return hit.get("ok") is True and bool(after) and str(hit.get("checked_at") or "") > str(after)

    def _login_ok(key: str, spec: dict[str, Any]) -> bool | None:
        """现在登着没有（真跑一次探测，不看缓存）。没有探测命令的返回 None。"""
        from . import channel_probe
        from .paths import config_dir

        checked = channel_probe.probe(key, spec, force=True, cache_path=config_dir() / "channel-probes.json")
        return None if checked is None else checked.get("ok")

    # 10/3 Park：出了问题要能在这一页马上做、做完自己检测、自己再发。登录跑平台自己的登录命令（弹浏览器 / 扫码窗口），
    # 退出后真探测一次；登上了，就把这个平台今天没发出去的格子（发失败的、等登录的）再发一遍，只发一次。
    platform_logins: dict[str, dict[str, Any]] = {}
    LOGIN_TIMEOUT_SECONDS = 600

    def _login_view(key: str) -> dict[str, Any]:
        with bw_lock:
            cur = dict(platform_logins.get(key) or {"state": "idle", "message": ""})
        cur.pop("proc", None)
        return cur

    def _bw_resend(key: str) -> None:
        deadline = time.monotonic() + 1800
        while time.monotonic() < deadline:
            # 看「今天在发的」那张表本身（库里排的格子 + 上次的结果），不只看内存：服务重启过的话内存里是空的
            # （10/3 登好了 YouTube 却没再发——10:57 刚自动部署重启过）
            items = _bw_snapshot(get_backfill())["items"]
            with bw_lock:
                busy = bw_run["running"]
            cells = [{"video_id": it["video_id"], "platform": it["platform"]} for it in items
                     if it["platform"] == key and not it["sent"] and it["state"] in ("failed", "login")]
            if not cells:
                return
            if not busy:
                try:
                    _bw_start(_bw_pick(cells, get_backfill(), again=True))
                except Exception as exc:  # noqa: BLE001 - shown on the login status
                    with bw_lock:
                        platform_logins[key].update(message=f"登好了，但没能再发：{exc}")
                return
            time.sleep(2)

    def _login_watch(key: str, proc: subprocess.Popen, spec: dict[str, Any]) -> None:
        try:
            proc.wait(timeout=LOGIN_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            proc.kill()
            with bw_lock:
                platform_logins[key].update(state="failed", message=f"{LOGIN_TIMEOUT_SECONDS // 60} 分钟没登好，停了。再点一次登录")
            return
        ok = _login_ok(key, spec)
        with bw_lock:
            if ok is False:
                platform_logins[key].update(state="failed", message="登录窗口关了，但还没登上。再点一次登录")
                return
            platform_logins[key].update(state="ok", message="登好了，正在把没发出去的再发一遍")
        _bw_resend(key)

    @app.post("/api/platforms/{key}/login")
    def platform_login(key: str) -> dict[str, Any]:
        from . import publisher
        from .paths import config_dir

        spec = publisher_specs().get(key) or {}
        argv = list(spec.get("login_argv") or [])
        if not argv:
            raise ValueError("这个平台没法在工作台里登录")
        with bw_lock:
            if (platform_logins.get(key) or {}).get("state") == "running":
                return _login_view_unlocked(key)
        if argv[0] == "python3":
            argv[0] = publisher.python_with(tuple(spec.get("needs") or ()))
        log = config_dir() / f"login-{key}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        cwd = spec.get("login_cwd") or (str(publisher.CONTENT_OPS) if publisher.CONTENT_OPS.is_dir() else None)
        with log.open("w", encoding="utf-8") as out:
            proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, cwd=cwd)
        with bw_lock:
            platform_logins[key] = {"state": "running", "message": "等你在弹出的窗口里登录…", "proc": proc}
        store.log_event("publish", f"打开 {spec.get('label', key)} 登录")
        threading.Thread(target=_login_watch, args=(key, proc, spec), name=f"login-{key}", daemon=True).start()
        return _login_view(key)

    def _login_view_unlocked(key: str) -> dict[str, Any]:
        cur = dict(platform_logins.get(key) or {"state": "idle", "message": ""})
        cur.pop("proc", None)
        return cur

    @app.get("/api/platforms/{key}/login")
    def platform_login_state(key: str) -> dict[str, Any]:
        return _login_view(key)

    def _bw_start(picked: list[dict[str, Any]]) -> dict[str, Any]:
        today_key = date.today().isoformat()
        with bw_lock:
            # 重新发了：之前「登好了」那句作废，这次再要登录就重新给登录按钮
            for c in picked:
                if (platform_logins.get(c["platform"]) or {}).get("state") == "ok":
                    platform_logins.pop(c["platform"], None)
            if bw_run["running"] and bw_run["day"] == today_key:
                raise ValueError("上一批还在发，等它发完")
            if bw_run["day"] != today_key:
                bw_run.update(day=today_key, items=[])
            plan = [(r["video_id"], r["platform"]) for r in store.backfill_plan(today_key)]
            store.set_backfill_plan(today_key, plan + [(c["video_id"], c["platform"]) for c in picked if (c["video_id"], c["platform"]) not in plan])
            store.driver_mark(today_key, "mode", "mode", "backfill")
            items = [_bw_item(c) for c in picked]
            keys = {(c["video_id"], c["platform"]) for c in picked}
            bw_run["items"] = [it for it in bw_run["items"] if (it["video_id"], it["platform"]) not in keys] + items
            bw_run["running"] = True
        store.log_event("publish", "补发工作台：" + "、".join(f"《{c['title'][:16]}》→{c['label']}" for c in picked))
        threading.Thread(target=_bw_run, args=(items,), name="backfill-desk", daemon=True).start()
        return {"started": len(items)}

    @app.get("/api/today/week")
    def get_week(start: str | None = None) -> dict[str, Any]:
        """周历翻到别的周：start 是那一周里的任意一天。"""
        from . import driver

        today = date.today()
        return {**_week(driver.week_start(parse_day(start)), today), "streak": driver.ship_streak(today, shipped_days())}

    # -- Wendy：「今天」页最上面那张卡片（wendy.py）-------------------------------------
    wendy_state: dict[str, Any] = {"busy": False, "error": None}
    wendy_lock = threading.Lock()

    def _local(raw: str | None) -> datetime | None:
        """库里的时间（UTC 或带时区）→ 本机时间，好和「现在几点」比。"""
        if not raw:
            return None
        try:
            value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        return (value if value.tzinfo else value.astimezone()).astimezone().replace(tzinfo=None)

    def _wendy_brief() -> tuple[dict[str, Any], str]:
        from . import driver, wendy

        today = get_today()
        return today, wendy.brief(today, get_reach(14), driver.now_item(today))

    def _wendy_said() -> list[dict[str, Any]]:
        """她说过的话：微信那边定时发的（从 Hermes 的输出里读）和卡片里的对话，按时间排。"""
        from . import wendy

        desk = [{"who": m["who"], "source": m["source"], "label": "", "text": m["text"],
                 "at": _local(m["at"]).astimezone().isoformat(timespec="seconds")} for m in store.wendy_thread(40)]
        return sorted([*wendy.hermes_messages(), *desk], key=lambda m: m["at"])

    def _nudges(day: str) -> list[dict[str, Any]]:
        return [r for r in store.driver_log(day, "nudge") if r["day"] == day]

    @app.get("/api/wendy")
    def get_wendy() -> dict[str, Any]:
        from . import driver

        today = get_today()
        said = _wendy_said()
        with wendy_lock:
            state = dict(wendy_state)
        return {"now": driver.now_item(today), "messages": said[-12:], "busy": state["busy"], "error": state["error"],
                "nudges": [{"at": r["at"]} for r in _nudges(today["day"])]}

    def _wendy_turn(message: str, page: str = "today") -> None:
        from . import positioning, wendy

        try:
            _, brief_text = _wendy_brief()
            north = ""
            if page == "positioning":
                try:
                    north = positioning.read().get("markdown") or ""
                except Exception:  # noqa: BLE001 - 读不到定位就只按今天的账聊
                    north = ""
            text = wendy.run_turn(brief_text, _wendy_said()[:-1] if message else _wendy_said(), message, turn_fn=wendy_fn, north=north)
            store.add_wendy("wendy", text)
        except Exception as exc:  # noqa: BLE001 - 卡片里显示
            logger.warning("wendy turn failed: %s", exc)
            with wendy_lock:
                wendy_state["error"] = str(exc)[:300] or type(exc).__name__
        finally:
            with wendy_lock:
                wendy_state["busy"] = False

    @app.post("/api/wendy")
    def post_wendy(body: WendyBody) -> dict[str, Any]:
        """他在卡片里回她（空着发 = 让她看一眼现在）。工作台自己跑一轮，模型所有工具都关着。"""
        message = body.message.strip()
        if len(message) > 2000:
            raise ValueError("一次最多 2000 字")
        with wendy_lock:
            if wendy_state["busy"]:
                return {"started": False, "message": "Wendy 还在想上一条"}
            wendy_state.update(busy=True, error=None)
        if message:
            store.add_wendy("park", message)
        threading.Thread(target=_wendy_turn, args=(message, body.page), name="wendy", daemon=True).start()
        return {"started": True}

    @app.get("/api/wendy/brief")
    def wendy_brief(review: bool = False) -> dict[str, Any]:
        """此刻的账，一段文字。卡片里的她和微信那边的她读的是同一段，两边说的数对得上。"""
        from . import wendy

        _, text = _wendy_brief()
        parts = [text, wendy.thread_brief(_wendy_said()[-12:])]
        if review:
            parts.append(wendy.review_brief(get_review()))
        return {"text": "\n\n".join(parts)}

    @app.get("/api/wendy/nudge")
    def wendy_nudge(wechat_at: str | None = None) -> dict[str, Any]:
        """要不要去微信催他。微信那边每半小时来问一次；wechat_at 是他最后一次在微信里说话的时间（那边才知道）。"""
        from . import wendy

        today = get_today()
        cell = today["days"][-1]
        pending = [name for key, name in wendy.KPI if cell.get(key) == "pending"]
        nudges = _nudges(today["day"])
        activity = [t for t in (_local(store.last_touch(today["day"])), _local(wechat_at)) if t]
        said = [m for m in _wendy_said() if m["who"] == "wendy"]
        contact = [t for t in (_local(said[-1]["at"]) if said else None, _local(nudges[-1]["at"]) if nudges else None) if t]
        verdict = wendy.nudge_due(datetime.now(), pending=pending, last_activity=max(activity) if activity else None,
                                  last_contact=max(contact) if contact else None, nudges_today=len(nudges))
        return {**verdict, "pending": pending, "nudges_today": len(nudges)}

    @app.post("/api/wendy/nudge")
    def wendy_nudged() -> dict[str, Any]:
        """微信那边真去催了：记一笔（一天的次数和两次之间的间隔都靠它）。这是她自己的记录，不是 Park 的数据。"""
        now = datetime.now()
        store.driver_mark(now.date().isoformat(), f"nudge:{now:%H:%M}", "nudge")
        return {"ok": True, "nudges_today": len(_nudges(now.date().isoformat()))}

    @app.post("/api/today/plan")
    def add_plan(body: PlanBody) -> dict[str, Any]:
        """周历上加一件不算分的事（「约两个博主诊断」）。"""
        return {"item": store.add_plan_item(parse_day(body.day).isoformat(), body.text or "")}

    @app.patch("/api/today/plan/{item_id}")
    def patch_plan(item_id: int, body: PlanBody) -> dict[str, Any]:
        store.set_plan_item_done(item_id, bool(body.done))
        return {"ok": True}

    @app.delete("/api/today/plan/{item_id}")
    def delete_plan(item_id: int) -> dict[str, Any]:
        store.delete_plan_item(item_id)
        return {"ok": True}

    # -- 流量视频：看到就想复刻的单条视频，先存下来（swipe.py，9/30 Park） -----------

    swipe_root = data_dir / "swipe"
    # 上次服务停的时候还在下的：线程没了，标成失败让他点重试
    for _row in store.swipe_videos():
        if _row["state"] == "downloading":
            store.update_swipe(_row["id"], state="failed", error="下到一半服务重启了，点重试")

    def _swipe_view(row: dict[str, Any]) -> dict[str, Any]:
        from . import swipe

        info = row.get("info") or {}
        topic = None
        if row.get("topic_id"):
            try:
                t = store.topic(row["topic_id"])
                topic = {"id": t["id"], "title": t["title"], "shipped": board_mod.is_shipped(t), "archived": bool(t.get("archived_at"))}
            except StoreError:
                topic = None
        status = "downloading" if row["state"] == "downloading" else "failed" if row["state"] == "failed" \
            else "shipped" if topic and topic["shipped"] else "making" if topic and not topic["archived"] else "saved"
        return {
            "id": row["id"], "url": row["url"], "platform": row["platform"], "platform_label": swipe.LABELS.get(row["platform"], row["platform"]),
            "status": status, "error": row.get("error"), "note": row.get("note") or "", "collection": row.get("collection") or "",
            "created_at": row["created_at"], "topic": topic,
            **{k: info.get(k) for k in ("title", "author", "published_at", "likes", "comments", "shares", "collects", "views", "is_video")},
            "cover": f"/api/swipe/{row['id']}/cover" if info.get("cover") else None,
            "video": f"/api/swipe/{row['id']}/video" if info.get("video") else None,
        }

    def _swipe_download(swipe_id: int) -> None:
        from . import swipe

        row = store.swipe_video(swipe_id)
        try:
            folder = swipe.download(row["url"], row["platform"], out_dir=swipe_root, cookies=cookie_path if row["platform"] == "douyin" else None)
            store.update_swipe(swipe_id, state="ready", error=None, content_dir=str(folder), info=swipe.read_item(folder))
            store.log_event("swipe", f"流量视频存好了：{(store.swipe_video(swipe_id)['info'].get('title') or row['url'])[:40]}")
        except Exception as exc:  # noqa: BLE001 - 卡片上显示
            logger.warning("swipe %s failed: %s", swipe_id, exc)
            store.update_swipe(swipe_id, state="failed", error=str(exc)[:300] or type(exc).__name__)

    def _swipe_douyin_left() -> int:
        from . import swipe

        start = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat()
        return max(0, swipe.DOUYIN_DAILY_CAP - store.swipe_count_since("douyin", start))

    @app.get("/api/swipe")
    def list_swipe() -> dict[str, Any]:
        from . import swipe

        return {"videos": [_swipe_view(r) for r in store.swipe_videos()], "collections": list(swipe.COLLECTIONS),
                "douyin_left": _swipe_douyin_left(), "douyin_cap": swipe.DOUYIN_DAILY_CAP}

    @app.post("/api/swipe")
    def add_swipe(body: SwipeBody) -> dict[str, Any]:
        from . import swipe

        try:
            url, platform = swipe.clean_url(body.url or "")
        except swipe.SwipeError as exc:
            raise ValueError(str(exc)) from None
        if platform == "douyin" and _swipe_douyin_left() <= 0:
            raise ValueError(f"今天抖音的已经存了 {swipe.DOUYIN_DAILY_CAP} 条：用的是你的抖音登录，一天不多下，明天再存")
        row = store.add_swipe(url, platform, body.note)
        threading.Thread(target=_swipe_download, args=(row["id"],), name=f"swipe-{row['id']}", daemon=True).start()
        return {"video": _swipe_view(row)}

    @app.patch("/api/swipe/{swipe_id}")
    def patch_swipe(swipe_id: int, body: SwipeBody) -> dict[str, Any]:
        from . import swipe

        fields: dict[str, Any] = {}
        if body.note is not None:
            fields["note"] = body.note.strip()[:300] or None
        if body.collection is not None:
            if body.collection and body.collection not in swipe.COLLECTIONS:
                raise ValueError("没有这个合集")
            fields["collection"] = body.collection or None
        return {"video": _swipe_view(store.update_swipe(swipe_id, **fields))}

    @app.post("/api/swipe/{swipe_id}/retry")
    def retry_swipe(swipe_id: int) -> dict[str, Any]:
        row = store.swipe_video(swipe_id)
        if row["state"] != "failed":
            raise ValueError("这条不用重试")
        store.update_swipe(swipe_id, state="downloading", error=None)
        threading.Thread(target=_swipe_download, args=(swipe_id,), name=f"swipe-{swipe_id}", daemon=True).start()
        return {"video": _swipe_view(store.swipe_video(swipe_id))}

    @app.delete("/api/swipe/{swipe_id}")
    def delete_swipe(swipe_id: int) -> dict[str, Any]:
        import shutil

        row = store.swipe_video(swipe_id)
        folder = Path(row["content_dir"]) if row.get("content_dir") else None
        # 只删 swipe 目录里的东西
        if folder and folder.is_dir() and swipe_root.resolve() in folder.resolve().parents:
            shutil.rmtree(folder, ignore_errors=True)
        store.delete_swipe(swipe_id)
        return {"ok": True}

    @app.post("/api/swipe/{swipe_id}/start")
    def start_swipe(swipe_id: int) -> dict[str, Any]:
        """开始复刻：建一条选题、放到「接下来要拍的」最上面。是他点的，不自动加。"""
        row = store.swipe_video(swipe_id)
        if row["state"] != "ready":
            raise ValueError("还没下好")
        if row.get("topic_id"):
            try:
                return {"topic": store.topic(row["topic_id"])}
            except StoreError:
                pass
        info = row.get("info") or {}
        title = f"复刻：{(info.get('title') or row['url'])[:40]}"
        memo = "\n".join(x for x in (f"流量视频：{row['url']}", f"为什么想转：{row['note']}" if row.get("note") else "",
                                     f"归哪个合集：{row['collection']}" if row.get("collection") else "") if x)
        me = store.self_account()
        topic = store.create_topic(title, formats="video", account_id=me["id"] if me else None, memo=memo)
        store.update_swipe(swipe_id, topic_id=topic["id"])
        store.add_shoot_item(title, top=True, topic_id=topic["id"])
        store.log_event("pool", f"开始复刻《{title[:30]}》", topic["id"])
        return {"topic": topic}

    def _swipe_file(swipe_id: int, key: str) -> Path:
        row = store.swipe_video(swipe_id)
        rel = (row.get("info") or {}).get(key)
        folder = Path(row["content_dir"]) if row.get("content_dir") else None
        if not rel or folder is None:
            raise HTTPException(status_code=404, detail="没有这个文件")
        path = (folder / rel).resolve()
        if folder.resolve() not in path.parents or not path.is_file():
            raise HTTPException(status_code=404, detail="没有这个文件")
        return path

    @app.get("/api/swipe/{swipe_id}/cover")
    def swipe_cover(swipe_id: int) -> FileResponse:
        return FileResponse(_swipe_file(swipe_id, "cover"), headers={"Cache-Control": "private, max-age=86400"})

    @app.get("/api/swipe/{swipe_id}/video")
    def swipe_video_file(swipe_id: int) -> FileResponse:
        return FileResponse(_swipe_file(swipe_id, "video"), media_type="video/mp4")

    # -- 补发用到的：哪些平台自己发、哪些进草稿、哪些备文件夹（9/29 Park；10/1 起由补发工作台一格一格发） -------------------------
    # 自己发出去的：B 站（投稿，审核后公开）、YouTube（直接公开）、X（直接发，被拒就存草稿）。
    # 要 Park 点的：公众号（草稿，他群发才推送）、视频号、小红书（上传文件夹备好，他扫码传）。
    BACKFILL_AUTO = {"bilibili": "upload", "youtube": "public", "x": "article_publish"}
    BACKFILL_DRAFT = {"wechat_mp": "draft"}
    BACKFILL_FOLDER = ("channels", "xiaohongshu")
    PACK_KEYS = ("copy", "cover", "article", "figs", "wx")

    def _pack_view(row: dict[str, Any]) -> dict[str, Any]:
        from . import approvals

        topic = store.topic(row["topic_id"])
        rel = _release_for(topic) or {}
        st = _approval_state(topic, rel)
        ap = approvals.status(st["folder"], st["fps"])
        need = ("copy", "cover") if set(row["missing"]) <= {"xiaohongshu"} else PACK_KEYS
        steps = {k: ("lock" if ap[k]["approved"] and ap[k]["valid"] else "made" if ap[k]["made"] else "no") for k in need}
        return {"topic_id": row["topic_id"], "video_id": row["video_id"], "title": row["headline"] or row["title"][:40],
                "multiple": row["multiple"], "published_at": row["published_at"], "missing": row["missing"],
                "ready": all(v == "lock" for v in steps.values()), "steps": steps,
                "machine": any(ap[k].get("by") == "machine" for k in need if ap[k]["approved"]),
                "cover": (rel.get("cover_urls") or {}).get("portrait")}

    @app.get("/api/today/backfill/{topic_id}/preview")
    def backfill_preview(topic_id: int) -> dict[str, Any]:
        """在「今天」里就地看一眼：三张封面、标题描述话题、文章开头、插图，完整排版另开一页。"""
        from urllib.parse import quote

        from . import copypack, illustrate as il, publish_desk

        topic = store.topic(topic_id)
        rel = _release_for(topic) or {}
        entry = publish_desk.shared_entry(copypack.read_copy(drafts_root, topic_id))
        art = writer.read_draft(topic)
        paras = []
        art_title = None
        if art:
            head = re.search(r"^#\s+(.+)$", art["markdown"], re.M)
            art_title = head.group(1).strip() if head else entry["title"]
            for block in re.split(r"\n\s*\n", art["markdown"]):
                b = block.strip()
                if not b or b.startswith("![") or b.startswith("# "):
                    continue
                paras.append(re.sub(r"[*#>`]", "", b))
                if len(paras) >= 4:
                    break
        figs = il.state(_article_path(topic))["images"] if art else []
        return {
            "topic_id": topic_id, "title": entry["title"], "body": entry["body"], "tags": entry["tags"],
            "covers": {k: v for k, v in (rel.get("cover_urls") or {}).items() if v},
            "article_title": art_title, "article_head": paras,
            "figs": [f"/api/topics/{topic_id}/article-file/{il.FOLDER}/{quote(f['file'])}" for f in figs],
            "layout_url": f"/api/topics/{topic_id}/wechat-preview.html" if art else None,
        }

    @app.put("/api/today/x-replies")
    def put_x_replies(body: CountBody) -> dict[str, Any]:
        day = body.day or date.today().isoformat()
        store.set_kpi_count(day, "x_replies", body.value)
        store.log_event("xr", f"{day} X 回复：{body.value} 条")
        return {"ok": True}

    @app.post("/api/today/notes")
    def add_note(body: ShootBody) -> dict[str, Any]:
        store.add_shoot_item(body.text or "", top=body.top, planned_day=parse_day(body.planned_day).isoformat() if body.planned_day else None)
        return {"notes": store.shoot_list()}

    @app.patch("/api/today/notes/{item_id}")
    def patch_note(item_id: int, body: ShootBody) -> dict[str, Any]:
        if body.move:
            return {"notes": store.move_shoot_item(item_id, 1 if body.move > 0 else -1)}
        if body.text is not None:
            store.update_shoot_item(item_id, text=body.text.strip()[:200] or store.shoot_item(item_id)["text"])
        if body.planned_day is not None:  # 周历：排到某一天；空字符串 = 不排了
            store.update_shoot_item(item_id, planned_day=parse_day(body.planned_day).isoformat() if body.planned_day else None)
        return {"notes": store.shoot_list()}

    @app.delete("/api/today/notes/{item_id}")
    def delete_note(item_id: int) -> dict[str, Any]:
        store.delete_shoot_item(item_id)
        return {"notes": store.shoot_list()}

    @app.post("/api/today/notes/{item_id}/start")
    def start_note(item_id: int) -> dict[str, Any]:
        """他点了「开始做」：用这条建一个选题、设成正在做，接着写提纲。是他点的，不是自动加。"""
        note = store.shoot_item(item_id)
        topic = note.get("topic_id") and store.topic(note["topic_id"])
        if not topic:
            topic = store.create_topic(note["text"], formats="video")
            store.update_shoot_item(item_id, topic_id=topic["id"])
        store.set_focus(topic["id"])
        store.log_event("focus", f"开始做《{topic['title'][:30]}》（从「接下来要拍的」）", topic["id"])
        return {"topic": store.topic(topic["id"])}

    @app.put("/api/today/dm")
    def put_dm(body: DmBody) -> dict[str, Any]:
        day = body.day or date.today().isoformat()
        if body.replied > body.received:
            raise ValueError("回了的不能比收到的多")
        store.set_dm(day, body.received, body.replied)
        store.log_event("dm", f"{day} 私信：收到 {body.received}，回了 {body.replied}")
        return {"ok": True}

    @app.post("/api/today/done")
    def mark_done(body: DriverMarkBody) -> dict[str, Any]:
        store.driver_mark(date.today().isoformat(), body.key, "done")
        return {"ok": True}

    @app.post("/api/today/skip")
    def mark_skip(body: DriverMarkBody) -> dict[str, Any]:
        reason = (body.reason or "").strip()
        if not reason:
            raise ValueError("跳过要写一句为什么")
        store.driver_mark(date.today().isoformat(), body.key, "skip", reason[:200])
        store.log_event("skip", f"跳过「{body.key}」：{reason[:120]}")
        return {"ok": True}

    # 「我今天不知道拍什么」：只有他点了才建议，从他自己的选题里挑一条，说为什么
    suggest_box: dict[str, Any] = {"state": None}

    def suggest_state() -> dict[str, Any] | None:
        return suggest_box["state"]

    @app.post("/api/today/suggest")
    def post_suggest() -> dict[str, Any]:
        from . import driver_suggest

        if (suggest_box["state"] or {}).get("running"):
            return suggest_box["state"]
        cards = [c for c in get_board(None)["cards"] if c["next"]["mine"]]
        if not cards:
            raise ValueError("选题池是空的：先去进项挑几条放进选题池")
        suggest_box["state"] = {"running": True, "day": date.today().isoformat()}

        def run() -> None:
            try:
                pick = driver_suggest.suggest(cards, latest_adjustments(), write_fn=suggest_fn or writer.cli_write)
                suggest_box["state"] = {"running": False, "day": date.today().isoformat(), **pick}
            except Exception as exc:  # noqa: BLE001 - 一句话告诉他
                suggest_box["state"] = {"running": False, "day": date.today().isoformat(), "error": str(exc)[:200]}

        threading.Thread(target=run, name="today-suggest", daemon=True).start()
        return suggest_box["state"]

    @app.post("/api/today/suggest/take")
    def take_suggest() -> dict[str, Any]:
        st = suggest_box["state"] or {}
        if not st.get("topic_id"):
            raise ValueError("还没有建议")
        topic = store.topic(st["topic_id"])
        store.add_shoot_item(topic["title"], top=True, topic_id=topic["id"])
        suggest_box["state"] = None
        return {"notes": store.shoot_list()}

    # -- Anna 的标准 ----------------------------------------------------------

    @app.get("/api/standard")
    def get_standard() -> dict[str, Any]:
        from . import standard

        path = standard.guide_path()
        return {"path": str(path), "exists": path.exists(), "rules": standard.rules()}

    @app.post("/api/standard")
    def post_standard(body: StandardBody) -> dict[str, Any]:
        """Write one rule into Park's QA standard. The text comes from a teardown of someone
        else's video, so it is only ever written after Park clicks the button showing it."""
        from . import standard

        rule = standard.add_rule(body.text, source=body.source)
        return {"rule": rule, "rules": standard.rules()}

    # -- 定位：我是谁 / 怎么找到客户 / 卖什么 -------------------------------------

    # -- 对外简介：一个文件两段（国内版 / X 版），正本在 Obsidian（profiles.py） --------

    def _profile_view() -> dict[str, Any]:
        from . import profiles, reach

        prof = profiles.read(vault.vault_root(vault_path()))
        accounts = store.settings()["platform_accounts"] or {}
        on = {key: (bool((accounts.get(key) or {}).get("on")) if key in accounts else False) for key, *_ in profiles.PLATFORMS}
        on["douyin"] = True
        applied = {k: v for k, v in (store.settings().get("profiles") or {}).items() if isinstance(v, dict) and v.get("at")}
        return {"profile": prof, "platforms": profiles.platforms(prof, applied, on, reach.CORE),
                "variants": [{"key": k, "label": label, "limits": profiles.LIMITS[k]} for k, label in profiles.VARIANTS]}

    def _mark_applied(platform: str) -> None:
        from . import profiles

        spec = next((p for p in profiles.PLATFORMS if p[0] == platform), None)
        if spec is None:
            raise ValueError("没有这个平台")
        now = profiles.read(vault.vault_root(vault_path()))["variants"][spec[2]]
        if not now["name"] and not now["bio"]:
            raise ValueError("这一版还是空的")
        saved = dict(store.settings().get("profiles") or {})
        saved[platform] = {"name": now["name"], "bio": now["bio"], "at": now_iso()}
        store.update_settings({"profiles": saved})

    @app.get("/api/profile")
    def get_profile() -> dict[str, Any]:
        return _profile_view()

    @app.put("/api/profile/{variant}")
    def put_profile(variant: str, body: ProfileBody) -> dict[str, Any]:
        from . import profiles

        try:
            profiles.write(vault.vault_root(vault_path()), variant, name=body.name or "", bio=body.bio or "", mtime=body.mtime)
        except profiles.ProfileError as exc:
            raise ValueError(str(exc)) from None
        store.log_event("profile", f"对外简介（{dict(profiles.VARIANTS)[variant]}）改了")
        return _profile_view()

    @app.post("/api/profile/applied/{platform}")
    def profile_applied(platform: str) -> dict[str, Any]:
        """他已经把这一版贴到这个平台上了：记下哪天、哪一版。"""
        _mark_applied(platform)
        return _profile_view()

    @app.get("/api/profile/x/live")
    def x_profile_live() -> dict[str, Any]:
        """X 上现在的名字和简介（只读）。"""
        from . import x_profile
        from .x_post import XError

        try:
            return {"live": (x_profile_read_fn or x_profile.read)()}
        except XError as exc:
            raise ValueError(str(exc)) from None

    @app.post("/api/profile/x/push")
    def x_profile_push() -> dict[str, Any]:
        """把 X 版改到 X 上。改的是他公开的主页：只有他点了按钮（点两次）才调。"""
        from . import profiles, x_profile
        from .x_post import XError

        now = profiles.read(vault.vault_root(vault_path()))["variants"]["x"]
        if not now["name"] and not now["bio"]:
            raise ValueError("X 版还是空的")
        try:
            live = (x_profile_update_fn or x_profile.update)(name=now["name"], bio=now["bio"])
        except XError as exc:
            raise ValueError(str(exc)) from None
        _mark_applied("x")
        store.log_event("profile", "X 的主页改好了：" + now["bio"][:60])
        return {**_profile_view(), "live": live}

    @app.get("/api/positioning")
    def get_positioning() -> dict[str, Any]:
        from . import positioning

        return positioning.read()

    @app.post("/api/positioning")
    def post_positioning(body: StandardBody) -> dict[str, Any]:
        """Append one proposal to 「待拍板」. Anna wrote the sentence; Park clicked the
        button that shows it. His own text above the block is never touched."""
        from . import positioning

        item = positioning.add_proposal(body.text, source=body.source)
        return {"proposal": item, "proposals": positioning.proposals()}

    @app.delete("/api/positioning/{proposal_id}")
    def delete_positioning(proposal_id: str) -> dict[str, Any]:
        from . import positioning

        if not positioning.remove_proposal(proposal_id):
            raise ValueError("这一条已经不在待拍板里了")
        return {"proposals": positioning.proposals()}

    @app.delete("/api/standard/{rule_id}")
    def delete_standard(rule_id: str) -> dict[str, Any]:
        from . import standard

        if not standard.remove_rule(rule_id):
            raise ValueError("这条标准已经不在了")
        return {"rules": standard.rules()}

    @app.get("/api/kline/board")
    def kline_board_api() -> dict[str, Any]:
        """K 线日报 tab: every watchlist asset as a compact daily card (read-only)."""
        from . import kline_board
        return kline_board.board()

    @app.get("/api/vault/dailies")
    def vault_daily_history(key: str, limit: int = 30) -> dict[str, Any]:
        items = vault.daily_history(vault_path(), key, limit)
        checked = {d: True for d in store.checked_days(key)}
        return {"key": key, "items": [{**i, "checked": bool(checked.get(i["day"]))} for i in items]}

    # -- 补发队列：抖音发过、别的平台还没发的旧视频 ------------------------------

    backfill_dl: dict[str, dict[str, Any]] = {}
    backfill_lock = threading.Lock()

    def _backfill_file(video_id: str) -> Path | None:
        from . import archive

        return archive.video_file(archive_root(), video_id)

    archive_state: dict[str, Any] = {}
    archive_lock = threading.Lock()

    def start_archive(limit: int | None = None) -> bool:
        """后台把没存的抖音视频存下来，一次一条。已经在跑就不再起一个。"""
        from .cli import archive_new_videos

        with archive_lock:
            if archive_state.get("state") == "downloading":
                return False
            if archive_root() is None:
                return False
            archive_state.clear()
            archive_state.update({"state": "downloading", "done": 0, "total": None})

        def progress(p: dict[str, Any]) -> None:
            with archive_lock:
                archive_state.update(p)

        def run() -> None:
            try:
                archive_new_videos(store, cookie_path=cookie_path, limit=limit, on_progress=progress)
            except Exception as exc:  # noqa: BLE001 - shown on the queue
                logger.warning("archive failed: %s", exc)
                with archive_lock:
                    archive_state.update({"state": "failed", "failed": {"error": str(exc)[:200]}})

        threading.Thread(target=run, name="douyin-archive", daemon=True).start()
        return True

    @app.get("/api/archive")
    def get_archive() -> dict[str, Any]:
        from . import archive

        raw = store.settings().get("douyin_archive") or ""
        root = archive_root()
        me = store.self_account()
        videos = [v for v in (store.public_videos(me["id"]) if me else []) if not v["is_image_post"]]
        missing = archive.pending(videos, root)
        with archive_lock:
            progress = dict(archive_state)
        local = sum(1 for v in videos if archive.source_of(root, v["video_id"]) == "local") if root is not None else 0
        return {"path": raw, "available": root is not None, "total": len(videos), "local": local,
                "archived": len(videos) - len(missing) if root is not None else 0, "pending": len(missing), "progress": progress or None}

    @app.post("/api/archive/run")
    def run_archive() -> dict[str, Any]:
        """把没存的全部存下来（第一次补齐用）。之后每次同步会自己补新的。"""
        if archive_root() is None:
            raise ValueError("作品库没配置，或者那块硬盘没插")
        if not start_archive(limit=None):
            raise ValueError("正在存，等这一轮存完")
        return {"started": True}

    def _backfill_state() -> tuple[list[dict[str, Any]], dict[str, int], dict[int, dict[str, Any]]]:
        from . import backfill, copypack, publish_desk

        me = store.self_account()
        if me is None:
            return [], {}, {}
        keep = set(store.settings().get("tracker_keep") or [])
        public = {v["video_id"] for v in store.public_videos(me["id"])}
        # 抖音上藏起来的（私密）不在公开主页上；Park 点名要留的照样列（别的平台还要发）
        videos = [v for v in store.videos(me["id"]) if not v["is_image_post"] and (v["video_id"] in public or v["video_id"] in keep)]
        topics = store.topics(include_archived=True)
        records = {t["id"]: store.publish_records(t["id"]) for t in topics}
        copies = {}
        for t in topics:
            entry = publish_desk.shared_entry(copypack.read_copy(drafts_root, t["id"]))
            if entry["title"]:
                copies[t["id"]] = entry["title"]
        links = backfill.link_topics(videos, topics, records, copies)
        return videos, links, records

    @app.get("/api/backfill")
    def get_backfill() -> dict[str, Any]:
        from . import backfill, copypack, publish_desk

        videos, links, records = _backfill_state()
        me = store.self_account()
        median = store.account_median(me["id"]) if me else None
        rows_all = {p["key"]: p for p in _platform_rows()}
        on = {k: p for k, p in rows_all.items() if p.get("on") and k != "douyin"} or rows_all  # 除抖音外一个都没标开通时，全部列出
        # 列按发布顺序排（9/29：全平台追踪，和发布台同一个顺序）
        keys = tuple(k for k in publish_desk.SEQUENCE if k in backfill.PLATFORMS and k in on)
        rows = backfill.queue(videos, links=links, records=records, marks=store.backfill_marks(), median=median, platforms=keys, forms=platform_forms())
        keep = set(store.settings().get("tracker_keep") or [])
        cancelled = set(store.settings().get("tracker_cancel") or [])
        for r in rows:
            r["hidden_on_douyin"] = r["video_id"] in keep
            # 他说了不补发的：还列着（能点回来），但哪个平台都不算缺，不进补发、不算旧内容
            r["cancelled"] = r["video_id"] in cancelled
            if r["cancelled"]:
                r["missing"] = []
            # 10/3 Park：标了「不发」的格子（这一条这个平台以后也不发）不算缺
            for k in _skipped(r["video_id"], r["topic_id"]) & set(r["missing"]):
                r["missing"].remove(k)
                r["done"][k] = "skip"
        topics = {t["id"]: t for t in store.topics(include_archived=True)}
        for r in rows:
            t = topics.get(r["topic_id"]) if r["topic_id"] else None
            has_master = bool(t and final_video_path(t))
            with backfill_lock:
                dl = dict(backfill_dl.get(r["video_id"]) or {})
            r["video"] = "master" if has_master and t.get("video_project") else "download" if (has_master or _backfill_file(r["video_id"])) else None
            r["download"] = dl or None
        return {
            # 抖音排第一列：每条内容都从抖音来，这一列就是它在抖音上的链接
            "platforms": [{"key": "douyin", "label": "抖音", "kind": "视频", "missing": 0}]
            + [{"key": k, "label": on[k].get("label", k), "kind": backfill.KIND[k], "missing": sum(1 for r in rows if k in r["missing"])} for k in keys],
            "videos": rows,
            "order": "按发布时间从新到旧",
        }

    @app.get("/api/outbox/matrix")
    def outbox_matrix(limit: int = 8) -> dict[str, Any]:
        """已发出 · 概览：最近几条内容在每个平台的累计触达（9/29 改版）。
        抖音用同步到的播放；B 站、YouTube、X、小红书用每天读到的累计数，靠全平台追踪里存的链接对上帖子；
        视频号、公众号没有接口，只能说发没发。"""
        from . import links

        from . import backfill

        sheet = get_backfill()
        views = store.latest_post_views()
        xhs_titles: list[tuple[str, int]] | None = None
        vids = {v["video_id"]: v for v in (store.videos(store.self_account()["id"]) if store.self_account() else [])}
        rows = []
        for r in sheet["videos"][: max(1, min(limit, 30))]:
            cells = {}
            for p in sheet["platforms"]:
                key = p["key"]
                url = (r.get("links") or {}).get(key) or (r.get("old_links") or {}).get(key)
                if key == "douyin":
                    n = (vids.get(r["video_id"]) or {}).get("views")
                    cells[key] = {"state": "views", "views": n} if n is not None else {"state": "sent"}
                    continue
                if not r["done"].get(key) and key not in (r.get("old_links") or {}):
                    cells[key] = {"state": "none"}
                    continue
                pid = links.post_id(key, url)
                n = views.get((key, pid)) if pid else None
                if n is None and key == "xiaohongshu":
                    # 小红书的数是截图读的，存的是「时间|标题前几个字」，没有帖子编号：按标题最像的那条对
                    titles = xhs_titles if xhs_titles is not None else store.latest_post_titles("xiaohongshu")
                    xhs_titles = titles
                    scored = [(backfill.similarity(t.rstrip("…. "), r["headline"] or r["title"]), v) for t, v in titles]
                    best = max(scored, default=(0, None))
                    n = best[1] if best[0] >= 0.6 else None
                cells[key] = {"state": "views", "views": n} if n is not None else {"state": "sent", "no_api": key in ("channels", "wechat_mp")}
            total = sum(c["views"] for c in cells.values() if c.get("state") == "views" and c.get("views"))
            rows.append({"video_id": r["video_id"], "title": r["headline"] or r["title"][:30], "published_at": r["published_at"],
                         "multiple": r["multiple"], "cells": cells, "total": total})
        return {"platforms": sheet["platforms"], "rows": rows}

    @app.post("/api/backfill/{video_id}/mark")
    def mark_backfill(video_id: str, body: BackfillMarkBody) -> dict[str, Any]:
        """Park 在工作台之外已经发过这个平台：记一笔，不建选题。"""
        from . import backfill

        if body.platform not in backfill.PLATFORMS:
            raise ValueError("没有这个平台")
        if store.video(video_id) is None:
            raise ValueError("找不到这条抖音视频")
        store.set_backfill_mark(video_id, body.platform, body.done)
        return {"ok": True}

    @app.post("/api/backfill/{video_id}/skip")
    def skip_backfill(video_id: str, body: BackfillSkipBody) -> dict[str, Any]:
        """这一条这个平台不发（10/3 Park：从发布页搬到补发工作台）。不算缺，补发不再挑它；点回来就恢复。"""
        from . import backfill

        if body.platform not in backfill.PLATFORMS:
            raise ValueError("没有这个平台")
        if store.video(video_id) is None:
            raise ValueError("找不到这条抖音视频")
        if body.skip and (video_id, body.platform) in {(r["video_id"], r["platform"]) for r in store.backfill_plan(date.today().isoformat())}:
            raise ValueError("今天排了这一格，先在「今天在发的」里点「不发这格」")
        skips = {k: list(v) for k, v in (store.settings().get("tracker_skip") or {}).items()}
        current = [p for p in skips.get(video_id, []) if p != body.platform]
        if body.skip:
            current.append(body.platform)
        if current:
            skips[video_id] = current
        else:
            skips.pop(video_id, None)
        store.update_settings({"tracker_skip": skips})
        return {"ok": True, "skip": body.skip}

    @app.post("/api/backfill/{video_id}/cancel")
    def cancel_backfill(video_id: str, body: BackfillCancelBody) -> dict[str, Any]:
        """这条旧视频不补发了（没有时效性了）。只是不再往别的平台补，抖音上那条不动；点回来就恢复。"""
        if store.video(video_id) is None:
            raise ValueError("找不到这条抖音视频")
        current = [v for v in (store.settings().get("tracker_cancel") or []) if v != video_id]
        store.update_settings({"tracker_cancel": current + [video_id] if body.cancel else current})
        return {"ok": True, "cancelled": body.cancel}

    @app.post("/api/backfill/{video_id}/take")
    def take_backfill(video_id: str) -> dict[str, Any]:
        """拿这条旧视频去补发：接上（或新建）选题、种一份文案、接上成片，然后交给发布台。
        不发布任何东西——每个平台照旧在发布台上点确认。"""
        from . import backfill, copypack

        video = store.video(video_id)
        if video is None:
            raise ValueError("找不到这条抖音视频")
        _, links, _ = _backfill_state()
        tid = links.get(video_id)
        split = backfill.split_douyin_title(video.get("title") or "")
        me = store.self_account()
        if tid is None:
            topic = store.create_topic(split["title"] or "抖音旧视频", account_id=me["id"] if me else None, memo="补发：抖音发过的旧视频")
            tid = topic["id"]
            store.log_event("pool", f"《{topic['title'][:30]}》拿去补发", tid)
        topic = store.topic(tid)
        if not topic.get("published_video_id"):
            topic = store.update_topic(tid, published_video_id=video_id)
        if "douyin" not in store.publish_records(tid):
            store.set_publish_record(tid, "douyin", published=True, url=f"https://www.douyin.com/video/{video_id}")
        if copypack.read_copy(drafts_root, tid) is None:
            copypack.save_copy(drafts_root, tid, {"douyin": {"title": split["title"], "body": split["body"], "tags": split["tags"]}})
        if final_video_path(topic) is None:
            f = _backfill_file(video_id)
            if f is not None:
                topic = store.update_topic(tid, video_file=str(f))
        return {"topic_id": tid, "has_video": final_video_path(store.topic(tid)) is not None}

    def _run_backfill_download(video_id: str) -> None:
        from . import archive

        try:
            root = archive_root()
            if root is None:
                raise RuntimeError("作品库没配置，或者那块硬盘没插")
            search = [Path(p).expanduser() for p in store.settings().get("local_video_roots") or []]
            me = store.self_account()
            own = store.public_videos(me["id"]) if me else [store.video(video_id)]
            r = archive.archive_pending(own, root=root, cookie_path=cookie_path, search=search, delay=0, download=True, only={video_id})
            if r["failed"]:
                raise RuntimeError(r["failed"][0]["error"])
            f = archive.video_file(root, video_id)
            if f is None:
                raise RuntimeError("没找到这条的成片")
            for t in store.topics(include_archived=True):
                if t.get("published_video_id") == video_id and not t.get("video_project"):
                    store.update_topic(t["id"], video_file=str(f))
            with backfill_lock:
                backfill_dl[video_id] = {"state": "done"}
        except Exception as exc:  # noqa: BLE001 - shown on the queue
            logger.warning("backfill download %s failed: %s", video_id, exc)
            with backfill_lock:
                backfill_dl[video_id] = {"state": "failed", "error": str(exc)[:200] or type(exc).__name__}

    @app.post("/api/backfill/{video_id}/download")
    def download_backfill(video_id: str) -> dict[str, Any]:
        """Park 点了才下，一次只下一条：抖音风控的时候不能一口气抓一串。"""
        if store.video(video_id) is None:
            raise ValueError("找不到这条抖音视频")
        with backfill_lock:
            if any(v.get("state") == "downloading" for v in backfill_dl.values()):
                raise ValueError("正在下另一条，等它下完")
            backfill_dl[video_id] = {"state": "downloading"}
        threading.Thread(target=_run_backfill_download, args=(video_id,), name=f"backfill-{video_id}", daemon=True).start()
        return {"started": True}

    # -- 日报：一期一条条看，单条入选题池 ---------------------------------------

    def _daily_source(key: str) -> Any:
        source = next((s for s in vault.DAILY_SOURCES if s.key == key), None)
        if source is None:
            raise ValueError(f"没有这份日报：{key}")
        return source

    def _daily_issue(key: str, path: str | None) -> tuple[Any, dict[str, Any], dict[str, Any]]:
        from . import newsletter

        source = _daily_source(key)
        history = vault.daily_history(vault_path(), key, 60)
        if not history:
            raise ValueError("这份日报还没有出过")
        entry = next((h for h in history if h["path"] == path), None) if path else history[0]
        if entry is None:
            raise ValueError("找不到这一期日报")
        note = vault.read_note(vault_path(), entry["path"])
        return source, entry, newsletter.parse_issue(note.get("body") or "")

    @app.get("/api/vault/daily/issue")
    def daily_issue(key: str, path: str | None = None) -> dict[str, Any]:
        """One issue, item by item. Without `path` it is the newest issue (today's after 08:30)."""
        from . import newsletter

        source, entry, parsed = _daily_issue(key, path)
        picks = store.daily_picks()
        day = newsletter.issue_day(Path(entry["path"]).name)
        index = newsletter.originals_index(Path(source.items) if source.items else None, day) if day else {}
        topics = {t["id"]: t for t in store.topics(include_archived=True)}
        for section in parsed["sections"]:
            for item in section["items"]:
                keys = [newsletter.url_key(u) for u in item["urls"]]
                tid = next((picks[k] for k in keys if k in picks), None)
                t = topics.get(tid) if tid else None
                item["topic_id"] = tid if t else None
                item["topic_archived"] = bool(t and t.get("archived_at"))
                item["has_original"] = newsletter.find_original(item, index) is not None
                item["has_deep"] = any(k in parsed["deep"] for k in keys)
        return {"key": key, "label": source.label, "path": entry["path"], "day": entry["day"], "title": parsed["title"] or entry["title"],
                "is_today": entry["day"] == date.today().isoformat(), "sections": parsed["sections"],
                "history": [{"path": h["path"], "day": h["day"], "title": h["title"]} for h in vault.daily_history(vault_path(), key, 60)]}

    def _daily_item(key: str, path: str, item_id: str) -> tuple[Any, dict[str, Any], dict[str, Any], dict[str, Any], str]:
        source, entry, parsed = _daily_issue(key, path)
        item = next((i for s in parsed["sections"] for i in s["items"] if i["id"] == item_id), None)
        if item is None:
            raise ValueError("这一期里找不到这条快讯")
        return source, entry, parsed, item, entry["title"]

    @app.get("/api/vault/daily/original")
    def daily_original(key: str, path: str, item: str) -> dict[str, Any]:
        """The full text behind one 快讯, to read in place before taking it."""
        from . import newsletter

        source, entry, parsed, it, _ = _daily_item(key, path, item)
        day = newsletter.issue_day(Path(entry["path"]).name)
        found = newsletter.find_original(it, newsletter.originals_index(Path(source.items) if source.items else None, day)) if day else None
        deep = next((parsed["deep"][newsletter.url_key(u)] for u in it["urls"] if newsletter.url_key(u) in parsed["deep"]), None)
        original = newsletter.read_original(found) if found else None
        return {"item": it, "quality": "原文" if original else "只有摘要", "deep": deep["body"] if deep else "",
                "body": original["body"] if original else "", "meta": {k: str(v) for k, v in (original or {}).get("meta", {}).items() if k in ("source", "author", "url", "published_at", "platform")}}

    @app.post("/api/vault/daily/pick")
    def daily_pick(body: DailyPickBody) -> dict[str, Any]:
        """Take one 快讯 into 选题池. Its original text is snapshotted with the topic — the
        pipeline keeps only a few days — and nothing is written to the vault."""
        from . import newsletter

        source, entry, parsed, it, issue = _daily_item(body.key, body.path, body.item)
        keys = [newsletter.url_key(u) for u in it["urls"]]
        picks = store.daily_picks()
        existing = next((picks[k] for k in keys if k in picks), None)
        if existing is not None:
            try:
                topic = store.topic(existing)
            except StoreError:
                topic = None
            if topic is not None:
                if topic.get("archived_at"):
                    topic = store.update_topic(topic["id"], archived_at=None)
                    store.log_event("pool", f"《{topic['title'][:30]}》又捡回来了", topic["id"])
                return {"topic": topic, "quality": None, "again": True}
        day = newsletter.issue_day(Path(entry["path"]).name)
        found = newsletter.find_original(it, newsletter.originals_index(Path(source.items) if source.items else None, day)) if day else None
        original = newsletter.read_original(found) if found else None
        deep = next((parsed["deep"][k] for k in keys if k in parsed["deep"]), None)
        me = store.self_account()
        topic = store.create_topic(it["title"], account_id=me["id"] if me else None,
                                   memo=f"来自{issue} · {it['source']}" + ("" if original else "（只有摘要，原文已不在日报管道里）"))
        newsletter.save_snapshot(drafts_root, topic["id"], it, newsletter.snapshot_markdown(it, issue=issue, original=original, deep=deep))
        for k in keys:
            store.add_daily_pick(k, topic["id"], issue)
        store.log_event("pool", f"《{topic['title'][:30]}》从{source.label}进了选题池", topic["id"])
        return {"topic": topic, "quality": "原文" if original else "只有摘要", "again": False}

    @app.get("/api/vault/note")
    def vault_note(path: str) -> dict[str, Any]:
        return vault.read_note(vault_path(), path)

    @app.get("/api/vault/raw")
    def vault_raw(path: str) -> Response:
        target = vault.safe_path(vault.vault_root(vault_path()), path)
        media = "text/html; charset=utf-8" if target.suffix.lower() == ".html" else "text/markdown; charset=utf-8"
        # Sandboxed: vault HTML can render but cannot run scripts against this app's API.
        return Response(
            target.read_bytes(),
            media_type=media,
            headers={"Content-Security-Policy": "sandbox allow-popups", "Cache-Control": "no-store"},
        )

    # -- frontend -----------------------------------------------------------

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})

    @app.middleware("http")
    async def _block_cross_site_writes(request: Any, call_next: Any) -> Any:
        # The app is reachable through a password proxy, so a browser holding those credentials must not
        # let another site trigger writes (start an agent run, confirm a publish). A custom header forces a
        # CORS preflight that this app never grants; the Origin, when sent, must be this host.
        if request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
            if request.headers.get("x-content-studio") != "1":
                return JSONResponse(status_code=403, content={"error": "请求缺少工作台标识，已拒绝"})
            origin = request.headers.get("origin")
            if origin:
                from urllib.parse import urlparse

                if urlparse(origin).netloc != request.headers.get("host", ""):
                    return JSONResponse(status_code=403, content={"error": "跨站请求，已拒绝"})
        return await call_next(request)

    @app.middleware("http")
    async def _revalidate_static(request: Any, call_next: Any) -> Any:
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            # Local app that changes often: always revalidate so a restart never serves stale JS.
            response.headers["Cache-Control"] = "no-cache"
        return response

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.state.store = store
    try:
        store.normalize_publish_links()
    except Exception:  # noqa: BLE001 - 换不了就下次再换，不挡启动
        logger.warning("normalize publish links failed", exc_info=True)
    app.state.worker = worker
    app.state.ops = ops
    return app

