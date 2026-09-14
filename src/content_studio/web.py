from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
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
    auto_enqueue_outliers,
    sync_account,
)
from .creator_metrics import CookieFileError, load_cookie_file
from . import today as today_plan
from . import vault
from . import video_project
from .video_project import VideoProjectError
from .store import StoreError, StudioStore, now_iso
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


class BriefingBody(BaseModel):
    day: str | None = None


class BriefTopicBody(BaseModel):
    day: str
    index: int


class VideoLinkBody(BaseModel):
    name: str | None = None


class PublishBody(BaseModel):
    video_id: str | None = None


class ArticleBody(BaseModel):
    markdown: str


class SettingsBody(BaseModel):
    threshold: float | None = None
    auto_enqueue_limit: int | None = None
    sync_pages: int | None = None
    sync_delay_seconds: float | None = None
    obsidian_vault: str | None = None
    yanxishi_admin_url: str | None = None
    video_projects_root: str | None = None


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
) -> FastAPI:
    from . import writer

    store = StudioStore(store_path)
    store.recover_interrupted_writes()
    store.recover_interrupted_briefings()
    briefing_lock = threading.Lock()
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

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if start_worker:
            worker.start()
        yield
        worker.stop()

    app = FastAPI(title="内容拆解台", docs_url=None, redoc_url=None, lifespan=lifespan)

    @app.exception_handler(VideoProjectError)
    async def _video_missing(_request: Any, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=404, content={"error": str(exc)})

    @app.exception_handler(vault.VaultError)
    async def _vault_missing(_request: Any, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=404, content={"error": str(exc)})

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
            "my_accounts": [
                {k: a[k] for k in ("id", "platform", "nickname", "profile_url", "follower_count")} for a in store.my_accounts()
            ],
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
        return {
            "since": since.isoformat(timespec="minutes"),
            "items": [{**item, "triage": (triage.get(item["path"]) or {}).get("status")} for item in items],
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
        return {"path": body.path, "triage": body.status, "topic": topic}

    # -- hot ----------------------------------------------------------------

    @app.get("/api/hot")
    def hot_now() -> dict[str, Any]:
        from . import hot

        threshold = float(store.settings()["threshold"])
        result: dict[str, Any] = {
            "benchmarks": {
                **hot.benchmark_breakouts(store, threshold=threshold),
                "items": [{**v, **teardown_state(v["video_id"])} for v in hot.benchmark_breakouts(store, threshold=threshold)["items"]],
            },
            "threshold": threshold,
            "douyin_search": {"available": False, "reason": "抖音站内搜索接口返回反作弊拦截，按规则不绕过"},
        }
        try:
            today = date.today()
            headlines = hot.daily_headlines(vault_path(), today)
            result["headlines"] = headlines
            result["topics"] = hot.frequent_topics(vault_path(), today=today)
            result["vault_error"] = None
        except vault.VaultError as exc:
            result.update(headlines=[], topics=[], vault_error=str(exc))
        return result

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
        return store.update_topic(topic_id, **fields)

    # -- daily briefing ----------------------------------------------------

    def own_recent_videos() -> list[dict[str, Any]]:
        me = store.self_account()
        if me is None:
            return []
        median = store.account_median(me["id"])
        rows = [v for v in store.videos(me["id"]) if not v["is_image_post"]][:8]
        return [
            {"title": v["title"] or "", "published_at": v["published_at"] or "", "likes": v["likes"],
             "multiple": round(v["likes"] / median, 1) if median and v["likes"] is not None else None}
            for v in rows
        ]

    def _run_briefing(day_value: date) -> None:
        from . import briefing

        key = day_value.isoformat()
        try:
            inputs = briefing.gather_inputs(vault_path(), day_value, own_videos=own_recent_videos())
            data = briefing.generate_briefing(inputs, **({"brief_fn": brief_fn} if brief_fn else {}))
            store.set_briefing(key, state="done", data=data)
        except Exception as exc:  # noqa: BLE001 - shown on the briefing card
            logger.warning("briefing %s failed: %s", key, exc)
            store.set_briefing(key, state="failed", error=str(exc)[:300] or type(exc).__name__)
        finally:
            briefing_lock.release()

    @app.get("/api/briefing")
    def get_briefing(day: str | None = None) -> dict[str, Any]:
        target = parse_day(day)
        return store.briefing(target.isoformat()) or {"day": target.isoformat(), "state": "missing", "error": None, "data": None}

    @app.post("/api/briefing/generate")
    def post_briefing(body: BriefingBody) -> dict[str, Any]:
        target = parse_day(body.day)
        vault.vault_root(vault_path())
        if not briefing_lock.acquire(blocking=False):
            return {"started": False, "message": "统筹正在生成"}
        store.set_briefing(target.isoformat(), state="running")
        threading.Thread(target=_run_briefing, args=(target,), name="briefing", daemon=True).start()
        return {"started": True, "message": "开始统筹，一般 1–3 分钟"}

    @app.post("/api/briefing/topic")
    def briefing_topic(body: BriefTopicBody) -> dict[str, Any]:
        record = store.briefing(parse_day(body.day).isoformat())
        videos = ((record or {}).get("data") or {}).get("videos") or []
        if not 0 <= body.index < len(videos):
            raise ValueError("这条视频建议不存在")
        video = videos[body.index]
        memo = "\n".join(
            [f"Hook：{video['hook']}", f"主张：{video['claim']}", "骨架：", *[f"{i + 1}. {line}" for i, line in enumerate(video["outline"])]]
            + ([f"注意：{video['caution']}"] if video.get("caution") else [])
        )
        note_paths = [s["path"] for s in video.get("sources", []) if s.get("path") and not s["path"].startswith(("006_", "007_", "009_"))]
        me = store.self_account()
        topic = store.create_topic(video["title"], note_paths=note_paths, formats="video", memo=memo, account_id=me["id"] if me else None)
        return {"topic": topic}

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
                store.topic(topic_id), vault_raw=vault_path(), drafts_dir=drafts_root, **({"write_fn": outline_fn} if outline_fn else {})
            )
            store.update_topic(topic_id, outline_path=result["outline_path"], outline_state=None, outline_error=None)
        except Exception as exc:  # noqa: BLE001 - shown on the topic card
            logger.warning("outline topic %s failed: %s", topic_id, exc)
            store.update_topic(topic_id, outline_state="failed", outline_error=str(exc)[:300] or type(exc).__name__)
        finally:
            with writing_lock:
                writing.discard(-topic_id)

    @app.post("/api/topics/{topic_id}/outline")
    def start_outline(topic_id: int) -> dict[str, Any]:
        topic = store.topic(topic_id)
        if topic["formats"] == "article":
            raise ValueError("这个选题只写文章；先把形式改成「视频」或「文章 + 视频」")
        with writing_lock:
            if -topic_id in writing:
                return {"started": False, "message": "提纲正在写"}
            writing.add(-topic_id)
        store.update_topic(topic_id, outline_state="running", outline_error=None)
        threading.Thread(target=_outline_topic, args=(topic_id,), name=f"outline-{topic_id}", daemon=True).start()
        return {"started": True, "message": "开始写拍摄提纲，一般 1–2 分钟"}

    @app.get("/api/topics/{topic_id}/outline")
    def get_outline(topic_id: int) -> dict[str, Any]:
        from . import outline

        data = outline.read_outline(store.topic(topic_id))
        if data is None:
            raise HTTPException(status_code=404, detail="这个选题还没有拍摄提纲")
        return data

    @app.put("/api/topics/{topic_id}/outline")
    def put_outline(topic_id: int, body: ArticleBody) -> dict[str, Any]:
        from . import outline

        topic = store.topic(topic_id)
        if not body.markdown.strip():
            raise ValueError("提纲不能为空")
        path = Path(topic["outline_path"]) if topic.get("outline_path") else drafts_root / f"topic-{topic_id}" / "outline.md"
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

    @app.get("/api/video-projects/{name}/file")
    def video_project_file(name: str, path: str) -> Response:
        target = video_project.safe_file(video_root(), name, path)
        headers = {"Cache-Control": "no-store"}
        if target.suffix.lower() == ".html":
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

    @app.get("/api/today/plan")
    def get_plan(day: str | None = None) -> dict[str, Any]:
        target = parse_day(day)
        try:
            dailies = [{**d, "checked_at": store.daily_checks(target.isoformat()).get(d["key"])} for d in vault.dailies(vault_path(), target)]
            triage = store.triage()
            inbox = [{**i, "triage": (triage.get(i["path"]) or {}).get("status")} for i in vault.inbox(vault_path(), since=vault.window_start(1))]
        except vault.VaultError:
            dailies = inbox = None
        steps = today_plan.build_plan(
            today=target,
            dailies=dailies,
            inbox=inbox,
            topics=store.topics(include_archived=True),
            reports=reports(),
            checks=store.daily_checks(target.isoformat()),
        )
        return {"day": target.isoformat(), "steps": steps, "done": sum(1 for s in steps if s["done"])}

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

