from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import statistics
import threading
from typing import Any, Iterator


DEFAULT_STORE_PATH = Path("~/.config/content-studio/data/studio.sqlite3")

JOB_STAGES = ("queued", "downloading", "transcribing", "analyzing", "done", "failed")
ACTIVE_STAGES = ("downloading", "transcribing", "analyzing")
TOPIC_STATUSES = ("todo", "drafting", "ready", "published")
TOPIC_FORMATS = ("article", "video", "both")

DEFAULT_SETTINGS: dict[str, Any] = {
    "threshold": 5.0,
    "auto_enqueue_limit": 8,
    "sync_pages": 3,
    "sync_delay_seconds": 1.5,
    "obsidian_vault": "~/park-hands",
    "yanxishi_admin_url": "",
    "video_projects_root": "",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    profile_url TEXT NOT NULL,
    external_id TEXT,
    nickname TEXT,
    follower_count INTEGER,
    total_favorited INTEGER,
    signature TEXT,
    is_self INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    last_error TEXT,
    added_at TEXT NOT NULL,
    last_synced_at TEXT,
    UNIQUE(platform, external_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS accounts_profile_url ON accounts(profile_url);
CREATE TABLE IF NOT EXISTS videos (
    platform TEXT NOT NULL,
    video_id TEXT NOT NULL,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    published_at TEXT,
    duration_seconds REAL,
    is_top INTEGER NOT NULL DEFAULT 0,
    is_image_post INTEGER NOT NULL DEFAULT 0,
    likes INTEGER,
    comments INTEGER,
    shares INTEGER,
    collects INTEGER,
    views INTEGER,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (platform, video_id)
);
CREATE INDEX IF NOT EXISTS videos_account ON videos(account_id, published_at);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    video_id TEXT,
    source TEXT NOT NULL,
    stage TEXT NOT NULL,
    error TEXT,
    report_path TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_stage ON jobs(stage, id);
CREATE TABLE IF NOT EXISTS report_archive (
    video_id TEXT PRIMARY KEY,
    archived_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS daily_checks (
    day TEXT NOT NULL,
    key TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    PRIMARY KEY (day, key)
);
CREATE TABLE IF NOT EXISTS inbox_triage (
    path TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    note_paths TEXT NOT NULL DEFAULT '[]',
    formats TEXT NOT NULL DEFAULT 'both',
    status TEXT NOT NULL DEFAULT 'todo',
    memo TEXT,
    article_path TEXT,
    published_url TEXT,
    published_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_at TEXT
);
CREATE TABLE IF NOT EXISTS briefings (
    day TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    error TEXT,
    data TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS video_snapshots (
    video_id TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    likes INTEGER,
    comments INTEGER,
    shares INTEGER,
    collects INTEGER,
    views INTEGER,
    PRIMARY KEY (video_id, fetched_at)
);
CREATE TABLE IF NOT EXISTS publish_records (
    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    platform TEXT NOT NULL,
    url TEXT,
    published_at TEXT NOT NULL,
    PRIMARY KEY (topic_id, platform)
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class StoreError(RuntimeError):
    """A store operation violated a product rule (duplicate, missing row...)."""


class StudioStore:
    """SQLite-backed state for accounts, videos, teardown jobs and settings."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.path.parent.chmod(0o700)
        except OSError:
            pass
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._conn.commit()
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def _migrate(self) -> None:
        """Add columns introduced after a table was first created (SQLite has no IF NOT EXISTS for columns)."""
        wanted = {"topics": {"write_state": "TEXT", "write_error": "TEXT", "outline_path": "TEXT", "outline_state": "TEXT", "outline_error": "TEXT", "video_project": "TEXT", "published_video_id": "TEXT", "copy_state": "TEXT", "copy_error": "TEXT"}}
        for table, columns in wanted.items():
            existing = {row[1] for row in self._conn.execute(f"PRAGMA table_info({table})")}
            for name, kind in columns.items():
                if name not in existing:
                    self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def _rows(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self._conn.execute(sql, params).fetchall()]

    def _row(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        rows = self._rows(sql, params)
        return rows[0] if rows else None

    # -- report archive ---------------------------------------------------

    def archived_reports(self) -> dict[str, str]:
        return {row["video_id"]: row["archived_at"] for row in self._rows("SELECT video_id, archived_at FROM report_archive")}

    def archive_report(self, video_id: str) -> str:
        archived_at = now_iso()
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO report_archive(video_id, archived_at) VALUES (?, ?) ON CONFLICT(video_id) DO NOTHING",
                (video_id, archived_at),
            )
        return self.archived_reports()[video_id]

    def unarchive_report(self, video_id: str) -> None:
        with self.tx() as conn:
            conn.execute("DELETE FROM report_archive WHERE video_id = ?", (video_id,))

    # -- daily checks & inbox triage --------------------------------------

    def daily_checks(self, day: str) -> dict[str, str]:
        return {row["key"]: row["checked_at"] for row in self._rows("SELECT key, checked_at FROM daily_checks WHERE day = ?", (day,))}

    def set_daily_check(self, day: str, key: str, checked: bool) -> dict[str, str]:
        with self.tx() as conn:
            if checked:
                conn.execute(
                    "INSERT INTO daily_checks(day, key, checked_at) VALUES (?, ?, ?) ON CONFLICT(day, key) DO NOTHING",
                    (day, key, now_iso()),
                )
            else:
                conn.execute("DELETE FROM daily_checks WHERE day = ? AND key = ?", (day, key))
        return self.daily_checks(day)

    def triage(self) -> dict[str, dict[str, str]]:
        return {row["path"]: dict(row) for row in self._rows("SELECT path, status, updated_at FROM inbox_triage")}

    def set_triage(self, path: str, status: str | None) -> None:
        if status not in (None, "topic", "ignored"):
            raise StoreError("处理状态只能是 做成选题 或 忽略")
        with self.tx() as conn:
            if status is None:
                conn.execute("DELETE FROM inbox_triage WHERE path = ?", (path,))
            else:
                conn.execute(
                    "INSERT INTO inbox_triage(path, status, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(path) DO UPDATE SET status = excluded.status, updated_at = excluded.updated_at",
                    (path, status, now_iso()),
                )

    # -- topics -----------------------------------------------------------

    def _topic_row(self, row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {**row, "note_paths": json.loads(row["note_paths"] or "[]")}

    def topic(self, topic_id: int) -> dict[str, Any]:
        row = self._topic_row(self._row("SELECT * FROM topics WHERE id = ?", (topic_id,)))
        if row is None:
            raise StoreError("选题不存在")
        return row

    def topics(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        where = "" if include_archived else "WHERE archived_at IS NULL"
        return [self._topic_row(r) for r in self._rows(f"SELECT * FROM topics {where} ORDER BY updated_at DESC, id DESC")]

    def recover_interrupted_writes(self) -> int:
        with self.tx() as conn:
            cursor = conn.execute(
                "UPDATE topics SET write_state = 'failed', write_error = '上次写作被中断（服务重启），点重试' WHERE write_state = 'running'"
            )
            count = cursor.rowcount
            cursor = conn.execute(
                "UPDATE topics SET outline_state = 'failed', outline_error = '上次生成被中断（服务重启），点重试' WHERE outline_state = 'running'"
            )
            count += cursor.rowcount
            cursor = conn.execute(
                "UPDATE topics SET copy_state = 'failed', copy_error = '上次生成被中断（服务重启），点重试' WHERE copy_state = 'running'"
            )
        return count + cursor.rowcount

    def briefing(self, day: str) -> dict[str, Any] | None:
        row = self._row("SELECT * FROM briefings WHERE day = ?", (day,))
        if row is None:
            return None
        return {**row, "data": json.loads(row["data"]) if row["data"] else None}

    def set_briefing(self, day: str, *, state: str, error: str | None = None, data: dict[str, Any] | None = None) -> dict[str, Any]:
        current = self.briefing(day)
        payload = json.dumps(data, ensure_ascii=False) if data is not None else (json.dumps(current["data"], ensure_ascii=False) if current and current["data"] else None)
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO briefings(day, state, error, data, updated_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(day) DO UPDATE SET state = excluded.state, error = excluded.error, data = excluded.data, updated_at = excluded.updated_at",
                (day, state, error, payload, now_iso()),
            )
        return self.briefing(day)

    def recover_interrupted_briefings(self) -> int:
        with self.tx() as conn:
            cursor = conn.execute("UPDATE briefings SET state = 'failed', error = '上次生成被中断（服务重启），点重新生成' WHERE state = 'running'")
        return cursor.rowcount

    def publish_records(self, topic_id: int) -> dict[str, dict[str, Any]]:
        return {r["platform"]: r for r in self._rows("SELECT * FROM publish_records WHERE topic_id = ?", (topic_id,))}

    def set_publish_record(self, topic_id: int, platform: str, *, published: bool, url: str | None = None) -> dict[str, dict[str, Any]]:
        with self.tx() as conn:
            if published:
                conn.execute(
                    "INSERT INTO publish_records(topic_id, platform, url, published_at) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(topic_id, platform) DO UPDATE SET url = excluded.url",
                    (topic_id, platform, url, now_iso()),
                )
            else:
                conn.execute("DELETE FROM publish_records WHERE topic_id = ? AND platform = ?", (topic_id, platform))
        return self.publish_records(topic_id)

    def topic_for_note(self, path: str) -> dict[str, Any] | None:
        for topic in self.topics(include_archived=True):
            if path in topic["note_paths"]:
                return topic
        return None

    def create_topic(
        self,
        title: str,
        *,
        note_paths: list[str] | None = None,
        formats: str = "both",
        account_id: int | None = None,
        memo: str | None = None,
    ) -> dict[str, Any]:
        title = (title or "").strip()
        if not title:
            raise StoreError("选题标题不能为空")
        if formats not in TOPIC_FORMATS:
            raise StoreError("形式只能是 文章、视频 或 两者")
        stamp = now_iso()
        with self.tx() as conn:
            cursor = conn.execute(
                "INSERT INTO topics(account_id, title, note_paths, formats, memo, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (account_id, title[:200], json.dumps(note_paths or [], ensure_ascii=False), formats, memo, stamp, stamp),
            )
            topic_id = cursor.lastrowid
        return self.topic(topic_id)

    def update_topic(self, topic_id: int, **fields: Any) -> dict[str, Any]:
        allowed = {"title", "formats", "status", "memo", "article_path", "published_url", "account_id", "archived_at", "note_paths", "write_state", "write_error", "outline_path", "outline_state", "outline_error", "video_project", "published_video_id", "copy_state", "copy_error"}
        unknown = set(fields) - allowed
        if unknown:
            raise StoreError(f"不可更新的选题字段：{sorted(unknown)}")
        current = self.topic(topic_id)
        if "status" in fields:
            if fields["status"] not in TOPIC_STATUSES:
                raise StoreError("状态只能是 待写、草稿、待发、已发")
            if fields["status"] == "published" and current["status"] != "published":
                fields["published_at"] = now_iso()
            if fields["status"] != "published":
                fields["published_at"] = None
        if "formats" in fields and fields["formats"] not in TOPIC_FORMATS:
            raise StoreError("形式只能是 文章、视频 或 两者")
        if "title" in fields and not str(fields["title"] or "").strip():
            raise StoreError("选题标题不能为空")
        if "note_paths" in fields:
            fields["note_paths"] = json.dumps(fields["note_paths"] or [], ensure_ascii=False)
        fields["updated_at"] = now_iso()
        assignments = ", ".join(f"{key} = ?" for key in fields)
        with self.tx() as conn:
            conn.execute(f"UPDATE topics SET {assignments} WHERE id = ?", (*fields.values(), topic_id))
        return self.topic(topic_id)

    # -- settings ---------------------------------------------------------

    def settings(self) -> dict[str, Any]:
        values = dict(DEFAULT_SETTINGS)
        for row in self._rows("SELECT key, value FROM settings"):
            if row["key"] in values:
                values[row["key"]] = json.loads(row["value"])
        return values

    def update_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        current = self.settings()
        cleaned: dict[str, Any] = {}
        for key, value in changes.items():
            if key not in DEFAULT_SETTINGS:
                raise StoreError(f"未知设置项：{key}")
            kind = type(DEFAULT_SETTINGS[key])
            try:
                cleaned[key] = kind(value)
            except (TypeError, ValueError) as exc:
                raise StoreError(f"设置项 {key} 的值无效") from exc
        if cleaned.get("yanxishi_admin_url"):
            cleaned["yanxishi_admin_url"] = cleaned["yanxishi_admin_url"].strip()
            if not cleaned["yanxishi_admin_url"].startswith("https://"):
                raise StoreError("研习室后台地址需要以 https:// 开头")
        if "obsidian_vault" in cleaned:
            cleaned["obsidian_vault"] = cleaned["obsidian_vault"].strip()
            if not cleaned["obsidian_vault"]:
                raise StoreError("Obsidian 库路径不能为空")
        if "threshold" in cleaned and not 1 <= cleaned["threshold"] <= 100:
            raise StoreError("爆款门槛需在 1× 到 100× 之间")
        if "auto_enqueue_limit" in cleaned and not 0 <= cleaned["auto_enqueue_limit"] <= 50:
            raise StoreError("自动入队上限需在 0 到 50 之间")
        if "sync_pages" in cleaned and not 1 <= cleaned["sync_pages"] <= 5:
            raise StoreError("同步页数需在 1 到 5 之间")
        if "sync_delay_seconds" in cleaned and cleaned["sync_delay_seconds"] < 1.5:
            raise StoreError("页间间隔不得小于 1.5 秒")
        with self.tx() as conn:
            for key, value in cleaned.items():
                conn.execute(
                    "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, json.dumps(value)),
                )
        current.update(cleaned)
        return current

    # -- accounts ---------------------------------------------------------

    def add_account(
        self,
        *,
        platform: str,
        profile_url: str,
        external_id: str | None,
        status: str,
        is_self: bool = False,
    ) -> dict[str, Any]:
        duplicate = self._row("SELECT id FROM accounts WHERE profile_url = ?", (profile_url,))
        if duplicate is None and external_id:
            duplicate = self._row(
                "SELECT id FROM accounts WHERE platform = ? AND external_id = ?", (platform, external_id)
            )
        if duplicate is not None:
            raise StoreError("这个账号已经在库里了")
        with self.tx() as conn:
            cursor = conn.execute(
                "INSERT INTO accounts(platform, profile_url, external_id, is_self, status, added_at) VALUES(?, ?, ?, ?, ?, ?)",
                (platform, profile_url, external_id, int(is_self), status, now_iso()),
            )
            account_id = cursor.lastrowid
        return self.account(account_id)

    def account(self, account_id: int) -> dict[str, Any]:
        row = self._row("SELECT * FROM accounts WHERE id = ?", (account_id,))
        if row is None:
            raise StoreError("账号不存在")
        return row

    def accounts(self) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM accounts ORDER BY is_self DESC, id")

    def self_account(self, account_id: int | None = None) -> dict[str, Any] | None:
        if account_id is not None:
            return self._row("SELECT * FROM accounts WHERE is_self = 1 AND id = ?", (account_id,))
        return self._row("SELECT * FROM accounts WHERE is_self = 1 ORDER BY id LIMIT 1")

    def my_accounts(self) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM accounts WHERE is_self = 1 ORDER BY id")

    def update_account(self, account_id: int, **fields: Any) -> dict[str, Any]:
        allowed = {"nickname", "follower_count", "total_favorited", "signature", "status", "last_error", "last_synced_at", "external_id"}
        unknown = set(fields) - allowed
        if unknown:
            raise StoreError(f"不可更新的账号字段：{sorted(unknown)}")
        if fields:
            assignments = ", ".join(f"{key} = ?" for key in fields)
            with self.tx() as conn:
                conn.execute(f"UPDATE accounts SET {assignments} WHERE id = ?", (*fields.values(), account_id))
        return self.account(account_id)

    def delete_account(self, account_id: int) -> None:
        account = self.account(account_id)
        if account["is_self"]:
            raise StoreError("不能移除自己的账号")
        with self.tx() as conn:
            conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))

    # -- videos -----------------------------------------------------------

    def upsert_videos(self, account_id: int, videos: list[dict[str, Any]]) -> int:
        fetched_at = now_iso()
        with self.tx() as conn:
            for video in videos:
                conn.execute(
                    """
                    INSERT INTO videos(platform, video_id, account_id, title, published_at, duration_seconds, is_top,
                                       is_image_post, likes, comments, shares, collects, views, fetched_at)
                    VALUES(:platform, :video_id, :account_id, :title, :published_at, :duration_seconds, :is_top,
                           :is_image_post, :likes, :comments, :shares, :collects, :views, :fetched_at)
                    ON CONFLICT(platform, video_id) DO UPDATE SET
                        account_id = excluded.account_id, title = excluded.title, published_at = excluded.published_at,
                        duration_seconds = excluded.duration_seconds, is_top = excluded.is_top,
                        is_image_post = excluded.is_image_post, likes = excluded.likes, comments = excluded.comments,
                        shares = excluded.shares, collects = excluded.collects,
                        views = COALESCE(NULLIF(excluded.views, 0), videos.views), fetched_at = excluded.fetched_at
                    """,
                    {**video, "account_id": account_id, "fetched_at": fetched_at},
                )
                conn.execute(
                    "INSERT OR IGNORE INTO video_snapshots(video_id, fetched_at, likes, comments, shares, collects, views) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (video["video_id"], fetched_at, video.get("likes"), video.get("comments"), video.get("shares"), video.get("collects"), video.get("views")),
                )
        return len(videos)

    def videos(self, account_id: int) -> list[dict[str, Any]]:
        return self._rows(
            "SELECT * FROM videos WHERE account_id = ? ORDER BY published_at DESC", (account_id,)
        )

    def snapshots(self, video_id: str) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM video_snapshots WHERE video_id = ? ORDER BY fetched_at", (video_id,))

    def video(self, video_id: str) -> dict[str, Any] | None:
        return self._row("SELECT * FROM videos WHERE video_id = ?", (video_id,))

    def account_median(self, account_id: int) -> float | None:
        likes = [
            row["likes"]
            for row in self._rows(
                "SELECT likes FROM videos WHERE account_id = ? AND is_top = 0 AND likes IS NOT NULL", (account_id,)
            )
        ]
        return float(statistics.median(likes)) if likes else None

    def outliers(self, threshold: float) -> list[dict[str, Any]]:
        results = []
        for account in self.accounts():
            if account["is_self"]:
                continue
            median = self.account_median(account["id"])
            if not median:
                continue
            for video in self.videos(account["id"]):
                if video["likes"] is None or video["is_image_post"]:
                    continue
                multiple = video["likes"] / median
                if multiple >= threshold:
                    results.append({**video, "multiple": round(multiple, 1), "account_nickname": account["nickname"], "account_median": median})
        results.sort(key=lambda item: item["multiple"], reverse=True)
        return results

    # -- jobs -------------------------------------------------------------

    def enqueue(self, *, url: str, video_id: str | None, source: str) -> tuple[dict[str, Any], bool]:
        """Queue a teardown unless the same video is already queued, running or done."""
        if video_id:
            existing = self._row(
                "SELECT * FROM jobs WHERE video_id = ? AND stage != 'failed' ORDER BY id DESC LIMIT 1", (video_id,)
            )
            if existing is not None:
                return existing, False
        stamp = now_iso()
        with self.tx() as conn:
            cursor = conn.execute(
                "INSERT INTO jobs(url, video_id, source, stage, created_at, updated_at) VALUES(?, ?, ?, 'queued', ?, ?)",
                (url, video_id, source, stamp, stamp),
            )
            job_id = cursor.lastrowid
        return self.job(job_id), True

    def job(self, job_id: int) -> dict[str, Any]:
        row = self._row("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if row is None:
            raise StoreError("任务不存在")
        return row

    def jobs(self, limit: int = 200) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,))

    def job_for_video(self, video_id: str) -> dict[str, Any] | None:
        return self._row("SELECT * FROM jobs WHERE video_id = ? ORDER BY id DESC LIMIT 1", (video_id,))

    def update_job(self, job_id: int, **fields: Any) -> dict[str, Any]:
        allowed = {"stage", "error", "report_path", "video_id"}
        unknown = set(fields) - allowed
        if unknown:
            raise StoreError(f"不可更新的任务字段：{sorted(unknown)}")
        if "stage" in fields and fields["stage"] not in JOB_STAGES:
            raise StoreError(f"未知任务阶段：{fields['stage']}")
        assignments = ", ".join(f"{key} = ?" for key in fields)
        with self.tx() as conn:
            conn.execute(
                f"UPDATE jobs SET {assignments}, updated_at = ? WHERE id = ?", (*fields.values(), now_iso(), job_id)
            )
        return self.job(job_id)

    def next_queued_job(self) -> dict[str, Any] | None:
        return self._row("SELECT * FROM jobs WHERE stage = 'queued' ORDER BY id LIMIT 1")

    def recover_interrupted_jobs(self) -> int:
        """Jobs left mid-stage by a crash go back to the queue; finished work is kept."""
        placeholders = ",".join("?" for _ in ACTIVE_STAGES)
        with self.tx() as conn:
            cursor = conn.execute(
                f"UPDATE jobs SET stage = 'queued', updated_at = ? WHERE stage IN ({placeholders})",
                (now_iso(), *ACTIVE_STAGES),
            )
        return cursor.rowcount

    def cancel_job(self, job_id: int) -> None:
        job = self.job(job_id)
        if job["stage"] != "queued":
            raise StoreError("只能取消还在排队的任务")
        with self.tx() as conn:
            conn.execute("DELETE FROM jobs WHERE id = ? AND stage = 'queued'", (job_id,))

    def retry_job(self, job_id: int) -> dict[str, Any]:
        job = self.job(job_id)
        if job["stage"] != "failed":
            raise StoreError("只有失败的任务可以重试")
        return self.update_job(job_id, stage="queued", error=None)
