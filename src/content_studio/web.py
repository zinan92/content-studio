from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import sqlite3
import threading
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .accounts import (
    PENDING_NOTES,
    PLATFORM_DOUYIN,
    AccountError,
    ContentDownloaderClient,
    add_account,
    auto_enqueue_new_posts,
    auto_enqueue_outliers,
    sync_account,
)
from .creator_metrics import CookieFileError, load_cookie_file
from . import today as today_plan
from . import vault
from . import video_project
from . import copypack
from . import outline as outline_mod
from .video_project import VideoProjectError
from .store import StoreError, StudioStore, now_iso
from .worker import TeardownWorker, WorkerConfig, normalize_video_url


logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent / "static"
REPORT_STALE_DAYS = 7
LEGACY_REPORT_DIRS = (Path("~/.config/content-studio/m1"),)


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


class ApproveBody(BaseModel):
    gate: str
    note: str | None = None


class WorktableBody(BaseModel):
    text: str
    filename: str | None = None
    overwrite: bool = False


class PublishBody(BaseModel):
    video_id: str | None = None


class CopyBody(BaseModel):
    platforms: dict[str, dict[str, Any]]


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
    platform_accounts: dict[str, dict[str, Any]] | None = None


class ReachBody(BaseModel):
    day: str
    platform: str
    views: int | None = None  # None clears the entry


class BackgroundOps:
    """Single-flight background syncs so the UI never blocks and never double-fetches."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.syncing: set[int] = set()
        self.full_sync_running = False
        self.last_full_sync: dict[str, Any] | None = None

    def run(self, key: int | str, fn: Callable[[], Any]) -> bool:
        with self._lock:
            if self.full_sync_running or (isinstance(key, int) and key in self.syncing):
                return False
            if key == "all":
                self.full_sync_running = True
            else:
                self.syncing.add(key)  # type: ignore[arg-type]

        def target() -> None:
            try:
                result = fn()
                if key == "all":
                    self.last_full_sync = result
            except Exception as exc:  # noqa: BLE001 - surfaced through account status
                logger.warning("background sync %s failed: %s", key, exc)
                if key == "all":
                    self.last_full_sync = {"error": str(exc)}
            finally:
                with self._lock:
                    if key == "all":
                        self.full_sync_running = False
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
    from . import profile as profile_mod
    from .accounts import AccountError, add_account

    current = store.settings()
    patch: dict[str, Any] = {}
    vault_path_cfg = str((data.get("vault") or {}).get("path") or "").strip()
    if vault_path_cfg and current.get("obsidian_vault") in ("", None, "~/park-hands"):
        patch["obsidian_vault"] = vault_path_cfg
    root = str(data.get("video_projects_root") or "").strip()
    if root and not current.get("video_projects_root"):
        patch["video_projects_root"] = root
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
    review_fn: Callable[[str], dict] | None = None,
    opening_fn: Callable[[str], dict] | None = None,
    qa_fn: Callable[[str], dict] | None = None,
    anna_fn: Callable[[str, str, str | None], dict] | None = None,
    runs_dir: Path | None = None,
    runner_command: str | None = None,
    publishers: dict[str, dict[str, Any]] | None = None,
    profile: dict[str, Any] | None = None,
) -> FastAPI:
    from . import writer
    from . import board as board_mod

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

            result = sync_everything(
                store,
                cookie_path=cookie_path,
                creator_db=creator_db or Path("/nonexistent"),
                has_report=lambda vid: report_file(vid) is not None,
            )
        worker.notify()
        return result

    stop_auto = threading.Event()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if start_worker:
            worker.start()
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
            "syncing": account["id"] in ops.syncing or (ops.full_sync_running and account["platform"] == PLATFORM_DOUYIN),
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

    @app.get("/api/state")
    def state() -> dict[str, Any]:
        try:
            load_cookie_file(cookie_path)
            cookies = {"ok": True, "message": None}
        except CookieFileError as exc:
            cookies = {"ok": False, "message": str(exc)}
        jobs = store.jobs(500)
        return {
            "settings": store.settings(),
            "self_account": store.self_account(),
            "my_accounts": [
                {k: a[k] for k in ("id", "platform", "nickname", "profile_url", "follower_count")} for a in store.my_accounts()
            ],
            "setup": _setup_state(),
            "vault": vault_status(store.settings()["obsidian_vault"]),
            "cookies": cookies,
            "creator_metrics_available": bool(_creator_rows(creator_db)),
            "full_sync_running": ops.full_sync_running,
            "last_full_sync": ops.last_full_sync,
            "active_jobs": sum(1 for j in jobs if j["stage"] not in ("done", "failed")),
            "account_count": len(store.accounts()),
        }

    @app.put("/api/settings")
    def put_settings(body: SettingsBody) -> dict[str, Any]:
        return store.update_settings({k: v for k, v in body.model_dump().items() if v is not None})

    @app.post("/api/sync")
    def sync_all() -> dict[str, Any]:
        started = ops.run("all", full_sync)
        return {"started": started, "message": "开始同步全部账号" if started else "同步已经在进行中"}

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
            syncing = ops.run(account["id"], lambda: _sync_and_queue(account["id"]))
        threshold = float(store.settings()["threshold"])
        return {"account": {**account_view(account, threshold), "syncing": syncing}}

    def _sync_and_queue(account_id: int) -> dict:
        result = sync_account(store, account_id, client_factory=factory)
        acct = store.account(account_id)
        store.log_event("sync", f"同步完 {acct.get('nickname') or '账号'}，共 {result.get('video_count', '?')} 条作品")
        if store.account(account_id)["is_self"]:
            if creator_sync_fn is not None:
                result["creator_metrics"] = creator_sync_fn()
        else:
            has_report = lambda vid: report_file(vid) is not None  # noqa: E731
            auto_enqueue_new_posts(store, has_report=has_report)
            auto_enqueue_outliers(store, has_report=has_report)
            worker.notify()
        return result

    @app.post("/api/accounts/{account_id}/sync")
    def post_sync(account_id: int) -> dict[str, Any]:
        account = store.account(account_id)
        if account["platform"] != PLATFORM_DOUYIN:
            raise AccountError(PENDING_NOTES.get(account["platform"], "该平台抓取待接入"))
        started = ops.run(account_id, lambda: _sync_and_queue(account_id))
        return {"started": started, "message": "开始同步" if started else "这个账号正在同步中"}

    @app.delete("/api/accounts/{account_id}")
    def delete_account(account_id: int) -> dict[str, Any]:
        store.delete_account(account_id)
        return {"ok": True}

    @app.get("/api/outliers")
    def outliers(threshold: float | None = None) -> list[dict[str, Any]]:
        value = threshold if threshold is not None else float(store.settings()["threshold"])
        return [{**video, **teardown_state(video["video_id"])} for video in store.outliers(value)]

    # -- jobs ---------------------------------------------------------------

    @app.get("/api/jobs")
    def jobs() -> list[dict[str, Any]]:
        results = []
        for job in store.jobs():
            video = store.video(job["video_id"]) if job["video_id"] else None
            results.append(
                {
                    **job_view(job),
                    "title": video["title"] if video else None,
                    "has_report": bool(job["video_id"] and report_file(job["video_id"])),
                    "running": worker.current_job_id == job["id"],
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
        job, created = store.enqueue(url=url, video_id=video_id, source=body.source or "手动添加")
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
        if body.key not in {s.key for s in vault.DAILY_SOURCES} | {"video_shot"}:
            raise ValueError("未知的勾选项")
        return {"day": body.day, "checks": store.set_daily_check(body.day, body.key, body.checked)}

    @app.get("/api/vault/inbox")
    def vault_inbox(days: int = 1, source: str | None = None) -> dict[str, Any]:
        since = vault.window_start(min(max(days, 1), 30))
        triage = store.triage()
        items = vault.inbox(vault_path(), since=since, sources=(source,) if source else None)
        # A note that already became a video should not look like fresh material.
        used: dict[str, dict[str, Any]] = {}
        for topic in store.topics(include_archived=True):
            shipped = bool(topic.get("published_video_id"))
            dropped = bool(topic.get("archived_at")) and not shipped
            for path in topic["note_paths"]:
                row = {"topic_id": topic["id"], "title": topic["title"], "shipped": shipped, "dropped": dropped}
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
            store.log_event("triage", f"进项里「{body.path.split('/')[-1][:30]}」标成了{ {'shot': '拍过了', 'ignored': '忽略'}.get(body.status, body.status) }")
        return {"path": body.path, "triage": body.status, "topic": topic}

    # -- skills -----------------------------------------------------------

    @app.get("/api/skills")
    def list_skills() -> dict[str, Any]:
        from .skills import load_skills

        return load_skills()

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
            data = review.generate_review(inputs, **({"review_fn": review_fn} if review_fn else {}))
            store.set_review(key, state="done", data=data)
        except Exception as exc:  # noqa: BLE001 - shown on the review page
            logger.warning("review %s failed: %s", key, exc)
            store.set_review(key, state="failed", error=str(exc)[:300] or type(exc).__name__)
        finally:
            review_lock.release()

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

    @app.get("/api/publish/desk")
    def publish_desk(topic_id: int | None = None) -> dict[str, Any]:
        """发布台：一条内容铺在所有平台上。哪条内容由 topic_id 定，没给就取最接近能发的那条。"""
        from . import board, copypack, handoff as handoff_mod, publish_desk, publisher

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
        chosen = next((c for c in candidates if c["id"] == topic_id), None) if topic_id is not None else (sendable[0] if sendable else None)
        if topic_id is not None and chosen is None:
            # 不在候选里（归档了、或者太老）也允许直接打开——链接可能是从别处带过来的。
            t = store.topic(topic_id)
            chosen = {"id": t["id"], "title": t["title"], "stage": "shipped" if board.is_shipped(t) else "outline", "stage_label": "", "shipped_count": len(store.publish_records(t["id"]))}
        ready = publisher.readiness(publisher_specs())
        platform_rows = _platform_rows(ready)
        if chosen is None:
            empty = {"title": "", "body": "", "tags": []}
            return {"candidates": [], "waiting": waiting, "others": candidates, "topic": None, "video": None, "has_copy": False, "has_article": False, "entry": empty,
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
                                 douyin_linked=board.is_shipped(topic), handoff_done=handoff_done)
        return {
            # 能发的才列出来；其余的留在 others 里，页面上折起来。
            "candidates": sendable,
            "waiting": waiting,
            "others": [c for c in candidates if c["id"] not in {s["id"] for s in sendable}],
            "topic": {**chosen, "published_video_id": topic.get("published_video_id"), "published_url": topic.get("published_url")},
            "video": {"path": str(video), "name": video.name, "mb": round(video.stat().st_size / 1_048_576, 1)} if video else None,
            "has_copy": bool(entry["title"] or entry["body"]),
            "has_article": article is not None,
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
        for row in store.reach_entries(since):
            if row["day"] in totals:
                totals[row["day"]][row["platform"]] = int(row["views"])
        accounts = store.settings()["platform_accounts"] or {}
        today_key = today.isoformat()
        return {
            **reach.summary(totals, today),
            "platforms": [
                {"key": key, "label": label, "auto": auto_flag, "on": bool((accounts.get(key) or {}).get("on")) or auto_flag,
                 "handle": (accounts.get(key) or {}).get("handle") or "", "today": totals[today_key].get(key)}
                for key, label, auto_flag in reach.PLATFORMS
            ],
            "douyin_synced_at": me["last_synced_at"] if me else None,
        }

    @app.put("/api/reach")
    def put_reach(body: ReachBody) -> dict[str, Any]:
        from . import reach

        if body.platform not in reach.PLATFORM_KEYS or body.platform == "douyin":
            raise ValueError("这个平台不能手填")
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

    def _write_topic(topic_id: int) -> None:
        try:
            topic = store.topic(topic_id)
            result = writer.write_article(
                topic,
                vault_raw=vault_path(),
                drafts_dir=drafts_root,
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
        except Exception as exc:  # noqa: BLE001 - shown on the topic card
            logger.warning("writing topic %s failed: %s", topic_id, exc)
            store.update_topic(topic_id, write_state="failed", write_error=str(exc)[:300] or type(exc).__name__)
        finally:
            with writing_lock:
                writing.discard(topic_id)

    @app.post("/api/topics/{topic_id}/write")
    def start_write(topic_id: int) -> dict[str, Any]:
        topic = store.topic(topic_id)
        if topic["formats"] == "video":
            raise ValueError("这个选题只做视频；先把形式改成「文章」或「文章 + 视频」")
        with writing_lock:
            if topic_id in writing:
                return {"started": False, "message": "这篇正在写"}
            writing.add(topic_id)
        store.update_topic(topic_id, write_state="running", write_error=None)
        threading.Thread(target=_write_topic, args=(topic_id,), name=f"write-{topic_id}", daemon=True).start()
        return {"started": True, "message": "开始写了，一般 1–5 分钟"}

    def _outline_topic(topic_id: int) -> None:
        from . import outline

        try:
            result = outline.write_outline(
                store.topic(topic_id), vault_raw=vault_path(), drafts_dir=drafts_root,
                adjustments=latest_adjustments(), **({"write_fn": outline_fn} if outline_fn else {})
            )
            store.update_topic(topic_id, outline_path=result["outline_path"], outline_state=None, outline_error=None, manual_stage=None)
            store.log_event("outline", f"《{store.topic(topic_id)['title'][:30]}》的开头和结尾写好了", topic_id)
            _run_qa(topic_id)
        except Exception as exc:  # noqa: BLE001 - shown on the topic card
            logger.warning("bookend topic %s failed: %s", topic_id, exc)
            store.update_topic(topic_id, outline_state="failed", outline_error=str(exc)[:300] or type(exc).__name__)
            store.log_event("outline", f"《{store.topic(topic_id)['title'][:24]}》开头结尾生成失败：{str(exc)[:60]}", topic_id)
        finally:
            with writing_lock:
                writing.discard(-topic_id)

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
        return {"started": True, "message": "开始写开头和结尾，一般 1–2 分钟"}

    @app.get("/api/topics/{topic_id}/outline")
    def get_outline(topic_id: int) -> dict[str, Any]:
        from . import outline

        data = outline.read_outline(store.topic(topic_id))
        if data is None:
            raise HTTPException(status_code=404, detail="这个选题还没有开头和结尾")
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
                if not i.get("triage") and not i.get("used_by"):
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
                state = "已进加工中" if i["path"] in used else {"topic": "已拿来做", "shot": "拍过了", "ignored": "已忽略"}.get((triage.get(i["path"]) or {}).get("status"), "还没处理")
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
            sources = writer.gather_sources(vault_path(), topic.get("note_paths") or [])
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

    def _anna_turn(scope: str, kind: str, label: str, topic_id: int | None, message: str, note_path: str | None, report_id: str | None = None) -> None:
        try:
            context = _anna_context(kind, topic_id, note_path, report_id)
            chat = store.anna_chat(ANNA_THREAD)
            if topic_id is not None:
                label = f"{label}《{store.topic(topic_id)['title']}》"
            reply = anna_mod.run_turn(scope=scope, scope_label=label, context=context, message=message, session_id=chat["session_id"], **({"turn_fn": anna_fn} if anna_fn else {}))
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
        parts += [f"### {s['title']}\n{s['body']}" for s in writer.gather_sources(vault_path(), topic.get("note_paths") or [])]
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

    # -- one-click publishing (Park confirms every job) --------------------

    def publisher_specs() -> dict[str, dict[str, Any]]:
        from . import publisher

        return publishers if publishers is not None else publisher.PUBLISHERS

    def final_video_path(topic: dict[str, Any]) -> Path | None:
        if not topic.get("video_project"):
            return None
        try:
            root = video_root()
            info = video_project.inspect(root, topic["video_project"])
        except VideoProjectError:
            return None
        if not info.get("final_video"):
            return None
        return video_project.safe_file(root, topic["video_project"], info["final_video"])

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

    @app.post("/api/topics/{topic_id}/publish-jobs")
    def prepare_publish(topic_id: int, body: PublishJobBody) -> dict[str, Any]:
        from . import copypack, publisher

        topic = store.topic(topic_id)
        video = final_video_path(topic)
        text_only = bool(publisher_specs().get(body.platform, {}).get("no_video"))
        if video is None and not text_only:
            raise publisher.PublishError("这个选题还没有成片：先关联视频项目并完成剪辑")
        copy = (copypack.read_copy(drafts_root, topic_id) or {}).get("platforms")
        payload = publisher.build_payload(body.platform, body.mode, video=video, copy=copy, publishers=publisher_specs())
        return {"job": store.create_publish_job(topic_id, payload)}

    def _run_publish(job_id: int) -> None:
        from . import publisher

        job = store.publish_job(job_id)
        try:
            result = publisher.run(job["payload"], publishers=publisher_specs())
        except Exception as exc:  # noqa: BLE001 - shown on the job
            result = {"ok": False, "status": "error", "message": str(exc)}
        ok = bool(result.get("ok"))
        store.update_publish_job(job_id, state="done" if ok else "failed", result=result, message=None if ok else publisher.explain(result), finished_at=now_iso())
        if ok:
            copy_platform = publisher_specs()[job["platform"]]["copy_key"]
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

    @app.delete("/api/standard/{rule_id}")
    def delete_standard(rule_id: str) -> dict[str, Any]:
        from . import standard

        if not standard.remove_rule(rule_id):
            raise ValueError("这条标准已经不在了")
        return {"rules": standard.rules()}

    @app.get("/api/vault/dailies")
    def vault_daily_history(key: str, limit: int = 30) -> dict[str, Any]:
        items = vault.daily_history(vault_path(), key, limit)
        checked = {d: True for d in store.checked_days(key)}
        return {"key": key, "items": [{**i, "checked": bool(checked.get(i["day"]))} for i in items]}

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
    app.state.worker = worker
    app.state.ops = ops
    return app

