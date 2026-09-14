from __future__ import annotations

from contextlib import asynccontextmanager
import json
import logging
from pathlib import Path
import sqlite3
import threading
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .accounts import (
    PENDING_NOTES,
    PLATFORM_DOUYIN,
    AccountError,
    ContentDownloaderClient,
    add_account,
    auto_enqueue_outliers,
    sync_account,
)
from .creator_metrics import CookieFileError, load_cookie_file
from .store import StoreError, StudioStore
from .worker import TeardownWorker, WorkerConfig, normalize_video_url


logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent / "static"
LEGACY_REPORT_DIRS = (Path("~/.config/content-studio/m1"),)


class UrlBody(BaseModel):
    url: str
    is_self: bool = False


class JobBody(BaseModel):
    url: str | None = None
    video_id: str | None = None
    source: str | None = None


class SettingsBody(BaseModel):
    threshold: float | None = None
    auto_enqueue_limit: int | None = None
    sync_pages: int | None = None
    sync_delay_seconds: float | None = None


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
) -> FastAPI:
    store = StudioStore(store_path)
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

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if start_worker:
            worker.start()
        yield
        worker.stop()

    app = FastAPI(title="内容拆解台", docs_url=None, redoc_url=None, lifespan=lifespan)

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
            "median_likes": median,
            "breakout_count": sum(1 for v in chronological if median and v["likes"] / median >= threshold),
            "spark": [v["likes"] for v in chronological][-60:],
        }

    # -- state --------------------------------------------------------------

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
    def mine() -> dict[str, Any]:
        me = store.self_account()
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
        return [account_view(a, threshold) for a in store.accounts() if not a["is_self"]]

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
        if store.account(account_id)["is_self"]:
            if creator_sync_fn is not None:
                result["creator_metrics"] = creator_sync_fn()
        else:
            auto_enqueue_outliers(store, has_report=lambda vid: report_file(vid) is not None)
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

    # -- frontend -----------------------------------------------------------

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.state.store = store
    app.state.worker = worker
    app.state.ops = ops
    return app

