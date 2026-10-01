from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from .paths import config_dir
import sqlite3
import statistics
import threading
from typing import Any, Iterator


DEFAULT_STORE_PATH = config_dir() / "data/studio.sqlite3"

JOB_STAGES = ("queued", "downloading", "transcribing", "analyzing", "done", "failed")
ACTIVE_STAGES = ("downloading", "transcribing", "analyzing")
TOPIC_STATUSES = ("todo", "drafting", "ready", "published")
TOPIC_FORMATS = ("article", "video", "both")

DEFAULT_SETTINGS: dict[str, Any] = {
    "threshold": 5.0,
    "auto_enqueue_limit": 2,
    "auto_enqueue_threshold": 2.0,  # 9/29 Park：点赞到自己中位数 2 倍才自动拆
    "sync_pages": 3,
    "sync_delay_seconds": 1.5,
    "obsidian_vault": "",
    "yanxishi_admin_url": "",
    "video_projects_root": "",
    # 作品库：自己发过的每条抖音视频一个文件夹（通常在外接硬盘上）。
    "douyin_archive": "",
    # 在本机找原片时扫哪些目录（按时长和日期配对，找到就不用从抖音下）。
    "local_video_roots": [],
    # {platform: {"on": bool, "handle": str}} — which platforms Park has opened accounts on.
    "platform_accounts": {},
    # {platform: [话题]} — 各平台的流量话题（活动、扶持计划），每条视频自动带上、排在内容话题前面。
    # 9/29 Park：抖音那四个是他每条都带的；别的平台他还不知道，在打包页里填一次就记住。
    "traffic_tags": {},
    # 抖音上设成私密（比如被判违规藏起来）但别的平台还要发的视频：全平台追踪照样列出来（9/29 Park）。
    "tracker_keep": [],
    # 不补发的旧视频（9/30 Park：半年前的实操、没有时效性的，不再往别的平台补）：全平台追踪里划掉，不算旧内容。
    "tracker_cancel": [],
    # 各平台主页的名字、简介、链接（profiles.py）：{platform: {name, bio, link, applied: {name, bio, link, at}}}
    "profiles": {},
    # 9/29 Park：KPI 由 Claude 定，Park 照做。出摊和回私信算他的分；触达和收到私信是结果。
    # reach_daily 是 7 天平均的目标，reach_by 之前要到；dm_daily 在 dm_baseline_until 摸底完再定（0 = 还没定）。
    "kpi": {"started": "2026-09-29", "reach_daily": 10000, "reach_by": "2026-10-31", "reach_next": 20000,
            "dm_daily": 0, "dm_baseline_until": "2026-10-06",
            # X 互动：每天在别人的帖子下面回这么多条（9/29 Park 先定 20；9/30 降到 10）
            "x_replies_daily": 10,
            # 读日报从这天起算分（9/30 Park）
            "read_started": "2026-09-30",
            # 追平阶段（9/30 Park）：出关要连续出摊这么多天；不发新视频的日子补发这么多格
            "ship_streak_target": 14, "backfill_cells": 4,
            # 每周至少这么多条新视频，少一条减 1 分；从这一周（周一）起算，之前不倒扣
            "new_weekly": 3, "new_weekly_started": "2026-10-05"},
}

# 9/20 Park 把对标和老师合成一类；9/30 又分开：老师是学理念的，对标是看要不要复刻的。
# 处理方式一样（新发的他都自己看），但进项里分两栏；一个人只有一个身份，两样都是的算对标。
KIND_SELF = "self"
KIND_BENCHMARK = "benchmark"
KIND_TEACHER = "teacher"
ACCOUNT_KINDS = (KIND_SELF, KIND_BENCHMARK, KIND_TEACHER)

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
    kind TEXT NOT NULL DEFAULT 'benchmark',
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
CREATE TABLE IF NOT EXISTS backfill_marks (
    video_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    marked_at TEXT NOT NULL,
    PRIMARY KEY (video_id, platform)
);
CREATE TABLE IF NOT EXISTS daily_picks (
    item_key TEXT PRIMARY KEY,
    topic_id INTEGER NOT NULL,
    issue TEXT NOT NULL,
    created_at TEXT NOT NULL
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
CREATE TABLE IF NOT EXISTS publish_skips (
    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    platform TEXT NOT NULL,
    skipped_at TEXT NOT NULL,
    PRIMARY KEY (topic_id, platform)
);
CREATE TABLE IF NOT EXISTS reviews (
    week TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    error TEXT,
    data TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS post_snapshots (
    platform TEXT NOT NULL,
    post_id TEXT NOT NULL,
    title TEXT,
    published_at TEXT,
    fetched_at TEXT NOT NULL,
    views INTEGER NOT NULL,
    PRIMARY KEY (platform, post_id, fetched_at)
);
CREATE TABLE IF NOT EXISTS reach_entries (
    day TEXT NOT NULL,
    platform TEXT NOT NULL,
    views INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (day, platform)
);
CREATE TABLE IF NOT EXISTS shoot_list (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    position REAL NOT NULL,
    topic_id INTEGER,
    created_at TEXT NOT NULL,
    done_at TEXT,
    planned_day TEXT
);
CREATE TABLE IF NOT EXISTS plan_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    done_at TEXT
);
CREATE TABLE IF NOT EXISTS backfill_plan (
    day TEXT NOT NULL,
    slot INTEGER NOT NULL,
    video_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    PRIMARY KEY (day, slot)
);
CREATE TABLE IF NOT EXISTS wendy_thread (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    who TEXT NOT NULL,
    source TEXT NOT NULL,
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dm_entries (
    day TEXT PRIMARY KEY,
    received INTEGER NOT NULL,
    replied INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feed_marks (
    video_id TEXT PRIMARY KEY,
    seen_at TEXT,
    note TEXT
);
CREATE TABLE IF NOT EXISTS swipe_videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    platform TEXT NOT NULL,
    state TEXT NOT NULL,
    error TEXT,
    content_dir TEXT,
    info TEXT,
    note TEXT,
    collection TEXT,
    topic_id INTEGER,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kpi_counts (
    day TEXT NOT NULL,
    key TEXT NOT NULL,
    value INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (day, key)
);
CREATE TABLE IF NOT EXISTS driver_log (
    day TEXT NOT NULL,
    key TEXT NOT NULL,
    kind TEXT NOT NULL,
    reason TEXT,
    at TEXT NOT NULL,
    PRIMARY KEY (day, key, kind)
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    topic_id INTEGER
);
CREATE INDEX IF NOT EXISTS events_at ON events(at DESC);
CREATE TABLE IF NOT EXISTS anna_chats (
    scope TEXT PRIMARY KEY,
    session_id TEXT,
    messages TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workflow_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id INTEGER NOT NULL,
    project TEXT NOT NULL,
    pid INTEGER,
    state TEXT NOT NULL,
    log_path TEXT,
    exit_path TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS publish_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id INTEGER NOT NULL,
    platform TEXT NOT NULL,
    mode TEXT NOT NULL,
    payload TEXT NOT NULL,
    state TEXT NOT NULL,
    result TEXT,
    message TEXT,
    created_at TEXT NOT NULL,
    confirmed_at TEXT,
    finished_at TEXT
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
        wanted = {"shoot_list": {"planned_day": "TEXT"}, "feed_marks": {"opened_at": "TEXT"}, "publish_records": {"form": "TEXT"}, "accounts": {"kind": "TEXT NOT NULL DEFAULT 'benchmark'"}, "topics": {"write_state": "TEXT", "write_error": "TEXT", "outline_path": "TEXT", "outline_state": "TEXT", "outline_error": "TEXT", "video_project": "TEXT", "published_video_id": "TEXT", "copy_state": "TEXT", "copy_error": "TEXT", "is_focus": "INTEGER NOT NULL DEFAULT 0", "snoozed_until": "TEXT", "manual_stage": "TEXT", "closed_at": "TEXT", "video_file": "TEXT"}}
        for table, columns in wanted.items():
            existing = {row[1] for row in self._conn.execute(f"PRAGMA table_info({table})")}
            for name, kind in columns.items():
                if name not in existing:
                    self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
                    if (table, name) == ("accounts", "kind"):
                        # Rows written before kinds existed: Park's own account, everything else 对标.
                        self._conn.execute("UPDATE accounts SET kind = CASE is_self WHEN 1 THEN 'self' ELSE 'benchmark' END")

    # -- events: what happened in the workbench, so Anna is not told only about one page ----

    def log_event(self, kind: str, text: str, topic_id: int | None = None) -> None:
        """One line of history. Anna reads these so she knows a topic just moved, a sync
        finished, a teardown landed — none of which is visible in the page Park happens to
        be looking at. Never let logging break the action it describes."""
        try:
            with self.tx() as conn:
                conn.execute(
                    "INSERT INTO events(at, kind, text, topic_id) VALUES(?, ?, ?, ?)",
                    (now_iso(), kind, text[:300], topic_id),
                )
        except sqlite3.Error:
            pass

    def events(self, limit: int = 25) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM events ORDER BY at DESC, id DESC LIMIT ?", (limit,))

    def prune_events(self, keep: int = 500) -> None:
        with self.tx() as conn:
            conn.execute("DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT ?)", (keep,))

    # -- Anna (resident editor) chats, one thread per page ---------------------

    def anna_chat(self, scope: str) -> dict[str, Any]:
        row = self._row("SELECT * FROM anna_chats WHERE scope = ?", (scope,))
        if row is None:
            return {"scope": scope, "session_id": None, "messages": [], "updated_at": None}
        return {**row, "messages": json.loads(row["messages"] or "[]")}

    def append_anna(self, scope: str, message: dict[str, Any], *, session_id: str | None = None, keep: int = 60) -> dict[str, Any]:
        chat = self.anna_chat(scope)
        messages = (chat["messages"] + [message])[-keep:]
        sid = session_id if session_id is not None else chat["session_id"]
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO anna_chats(scope, session_id, messages, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(scope) DO UPDATE SET session_id = excluded.session_id, messages = excluded.messages, updated_at = excluded.updated_at",
                (scope, sid, json.dumps(messages, ensure_ascii=False), now_iso()),
            )
        return self.anna_chat(scope)

    def merge_anna_threads(self, into: str = "main") -> int:
        """Fold the old one-thread-per-page chats into one conversation, oldest first.

        Each message keeps the page it was said on (`scope`) so its action buttons still
        point at the right video. The CLI session starts fresh: the old ones each only
        knew one page.
        """
        rows = self._rows("SELECT scope, messages FROM anna_chats WHERE scope != ?", (into,))
        if not rows:
            return 0
        merged = list(self.anna_chat(into)["messages"])
        for row in rows:
            for message in json.loads(row["messages"] or "[]"):
                merged.append({**message, "scope": message.get("scope") or row["scope"]})
        merged.sort(key=lambda m: m.get("at") or "")
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO anna_chats(scope, session_id, messages, updated_at) VALUES (?, NULL, ?, ?) "
                "ON CONFLICT(scope) DO UPDATE SET messages = excluded.messages, updated_at = excluded.updated_at",
                (into, json.dumps(merged[-60:], ensure_ascii=False), now_iso()),
            )
            conn.execute("DELETE FROM anna_chats WHERE scope != ?", (into,))
        return len(rows)

    def clear_anna(self, scope: str) -> None:
        with self.tx() as conn:
            conn.execute("DELETE FROM anna_chats WHERE scope = ?", (scope,))

    def rename_note_prefix(self, old_prefix: str, new_prefix: str) -> int:
        """Follow a renamed vault folder: triage rows and topic note_paths keep pointing at the notes."""
        changed = 0
        with self.tx() as conn:
            cursor = conn.execute(
                "UPDATE inbox_triage SET path = ? || substr(path, ?) WHERE path LIKE ? || '/%'",
                (new_prefix, len(old_prefix) + 1, old_prefix),
            )
            changed += cursor.rowcount
            for row in conn.execute("SELECT id, note_paths FROM topics").fetchall():
                paths = json.loads(row["note_paths"] or "[]")
                moved = [f"{new_prefix}/{p[len(old_prefix) + 1:]}" if p.startswith(f"{old_prefix}/") else p for p in paths]
                if moved != paths:
                    conn.execute("UPDATE topics SET note_paths = ? WHERE id = ?", (json.dumps(moved, ensure_ascii=False), row["id"]))
                    changed += 1
        return changed

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

    def checked_days(self, key: str) -> set[str]:
        return {row["day"] for row in self._rows("SELECT day FROM daily_checks WHERE key = ?", (key,))}

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

    def backfill_marks(self) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for r in self._rows("SELECT video_id, platform FROM backfill_marks"):
            out.setdefault(r["video_id"], set()).add(r["platform"])
        return out

    def set_backfill_mark(self, video_id: str, platform: str, done: bool) -> None:
        with self.tx() as conn:
            if done:
                conn.execute("INSERT OR REPLACE INTO backfill_marks(video_id, platform, marked_at) VALUES (?, ?, ?)", (video_id, platform, now_iso()))
            else:
                conn.execute("DELETE FROM backfill_marks WHERE video_id = ? AND platform = ?", (video_id, platform))

    def daily_picks(self) -> dict[str, int]:
        return {r["item_key"]: r["topic_id"] for r in self._rows("SELECT item_key, topic_id FROM daily_picks")}

    def add_daily_pick(self, item_key: str, topic_id: int, issue: str) -> None:
        with self.tx() as conn:
            conn.execute("INSERT OR REPLACE INTO daily_picks(item_key, topic_id, issue, created_at) VALUES (?, ?, ?, ?)",
                         (item_key, topic_id, issue, now_iso()))

    def set_triage(self, path: str, status: str | None) -> None:
        # back = 捡回来：从「暂不拍 / 拍过了」回到还没处理。标过「不做了」的选题占着这篇笔记时，
        # 光清掉状态它还会落回暂不拍，所以要一个明确的「捡回来」。
        if status not in (None, "topic", "ignored", "shot", "back"):
            raise StoreError("处理状态只能是 拿来做、拍过了、暂不拍 或 捡回来")
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

    def review(self, week: str) -> dict[str, Any] | None:
        row = self._row("SELECT * FROM reviews WHERE week = ?", (week,))
        return {**row, "data": json.loads(row["data"]) if row["data"] else None} if row else None

    def set_review(self, week: str, *, state: str, error: str | None = None, data: dict[str, Any] | None = None) -> dict[str, Any]:
        current = self.review(week)
        payload = json.dumps(data, ensure_ascii=False) if data is not None else (json.dumps(current["data"], ensure_ascii=False) if current and current["data"] else None)
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO reviews(week, state, error, data, updated_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(week) DO UPDATE SET state = excluded.state, error = excluded.error, data = excluded.data, updated_at = excluded.updated_at",
                (week, state, error, payload, now_iso()),
            )
        return self.review(week)

    def normalize_publish_links(self) -> int:
        """已经存下的后台链接一次换成公开链接（9/29 以前 YouTube 存的是 Studio 编辑页、抖音存的是创作者中心）。"""
        from .links import public_url

        changed = 0
        with self.tx() as conn:
            for r in conn.execute("SELECT topic_id, platform, url FROM publish_records WHERE url IS NOT NULL").fetchall():
                fixed = public_url(r["platform"], r["url"])
                if fixed != r["url"]:
                    conn.execute("UPDATE publish_records SET url = ? WHERE topic_id = ? AND platform = ?", (fixed, r["topic_id"], r["platform"]))
                    changed += 1
        return changed

    def latest_post_titles(self, platform: str) -> list[tuple[str, int]]:
        """某个平台每条帖子最近一次的（标题，累计数）。小红书是截图读的，没有帖子编号，只能按标题对。"""
        rows = self._rows(
            "SELECT title, views FROM post_snapshots s WHERE platform = ? AND fetched_at = "
            "(SELECT MAX(fetched_at) FROM post_snapshots t WHERE t.platform = s.platform AND t.post_id = s.post_id)", (platform,))
        return [(r["title"] or "", r["views"]) for r in rows if r["views"] is not None]

    def latest_post_views(self) -> dict[tuple[str, str], int]:
        """每个平台每条帖子最近一次读到的累计播放 / 曝光 / 阅读。"""
        rows = self._rows(
            "SELECT platform, post_id, views FROM post_snapshots s WHERE fetched_at = "
            "(SELECT MAX(fetched_at) FROM post_snapshots t WHERE t.platform = s.platform AND t.post_id = s.post_id)"
        )
        return {(r["platform"], r["post_id"]): r["views"] for r in rows if r["views"] is not None}

    def sent_rows(self) -> list[dict[str, Any]]:
        """每一格是哪天发出去的（月历用）：发布台记的（选题 × 平台），和当天补发的格子里他点了「发了」的。
        全平台追踪里补记的「以前在外面发过」不算——那不是这一天发的。抖音不算，那是新视频。"""
        return self._rows(
            """SELECT r.platform AS platform, r.published_at AS at, t.title AS title, 'record' AS kind
                 FROM publish_records r JOIN topics t ON t.id = r.topic_id WHERE r.platform != 'douyin'
               UNION ALL
               SELECT m.platform, m.marked_at, v.title, 'mark' FROM backfill_marks m JOIN videos v ON v.video_id = m.video_id
                WHERE EXISTS (SELECT 1 FROM backfill_plan p WHERE p.video_id = m.video_id AND p.platform = m.platform)"""
        )

    def publish_records(self, topic_id: int) -> dict[str, dict[str, Any]]:
        return {r["platform"]: r for r in self._rows("SELECT * FROM publish_records WHERE topic_id = ?", (topic_id,))}

    def set_publish_record(self, topic_id: int, platform: str, *, published: bool, url: str | None = None) -> dict[str, dict[str, Any]]:
        from .links import public_url
        from .reach import form_of

        url = public_url(platform, url)  # 后台页换成别人点得开的公开链接（links.py）
        # 记下发的是什么形式（视频 / 图文 / 文字）：平台改了发什么以后，旧形式的那条不算这一格发过了
        form = form_of(platform, self.settings().get("platform_accounts"))
        with self.tx() as conn:
            if published:
                conn.execute(
                    "INSERT INTO publish_records(topic_id, platform, url, published_at, form) VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(topic_id, platform) DO UPDATE SET url = excluded.url, form = excluded.form",
                    (topic_id, platform, url, now_iso(), form),
                )
            else:
                conn.execute("DELETE FROM publish_records WHERE topic_id = ? AND platform = ?", (topic_id, platform))
        return self.publish_records(topic_id)

    def publish_skips(self, topic_id: int) -> set[str]:
        """这一条决定不发的平台（发布台的顺序里跳过它）。"""
        return {r["platform"] for r in self._rows("SELECT platform FROM publish_skips WHERE topic_id = ?", (topic_id,))}

    def set_publish_skip(self, topic_id: int, platform: str, *, skip: bool) -> set[str]:
        with self.tx() as conn:
            if skip:
                conn.execute("INSERT OR IGNORE INTO publish_skips(topic_id, platform, skipped_at) VALUES (?, ?, ?)", (topic_id, platform, now_iso()))
            else:
                conn.execute("DELETE FROM publish_skips WHERE topic_id = ? AND platform = ?", (topic_id, platform))
        return self.publish_skips(topic_id)

    def create_run(self, topic_id: int, project: str) -> int:
        with self.tx() as conn:
            cursor = conn.execute(
                "INSERT INTO workflow_runs(topic_id, project, state, started_at) VALUES (?, ?, 'starting', ?)", (topic_id, project, now_iso())
            )
        return int(cursor.lastrowid)

    def update_run(self, run_id: int, **fields: Any) -> dict[str, Any]:
        allowed = {"pid", "state", "log_path", "exit_path", "started_at", "finished_at"}
        if set(fields) - allowed:
            raise StoreError("不可更新的运行字段")
        if fields:
            assignments = ", ".join(f"{k} = ?" for k in fields)
            with self.tx() as conn:
                conn.execute(f"UPDATE workflow_runs SET {assignments} WHERE id = ?", (*fields.values(), run_id))
        return self._row("SELECT * FROM workflow_runs WHERE id = ?", (run_id,)) or {}

    def runs(self, *, topic_id: int | None = None, active_only: bool = False) -> list[dict[str, Any]]:
        where, params = [], []
        if topic_id is not None:
            where.append("topic_id = ?")
            params.append(topic_id)
        if active_only:
            where.append("state IN ('starting', 'running')")
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        return self._rows(f"SELECT * FROM workflow_runs {clause} ORDER BY id DESC", tuple(params))

    def _publish_job(self, row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {**row, "payload": json.loads(row["payload"]), "result": json.loads(row["result"]) if row["result"] else None}

    def create_publish_job(self, topic_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        with self.tx() as conn:
            conn.execute("UPDATE publish_jobs SET state = 'superseded' WHERE topic_id = ? AND platform = ? AND state = 'awaiting_confirm'", (topic_id, payload["platform"]))
            cursor = conn.execute(
                "INSERT INTO publish_jobs(topic_id, platform, mode, payload, state, created_at) VALUES (?, ?, ?, ?, 'awaiting_confirm', ?)",
                (topic_id, payload["platform"], payload["mode"], json.dumps(payload, ensure_ascii=False), now_iso()),
            )
        return self.publish_job(int(cursor.lastrowid))

    def publish_job(self, job_id: int) -> dict[str, Any]:
        job = self._publish_job(self._row("SELECT * FROM publish_jobs WHERE id = ?", (job_id,)))
        if job is None:
            raise StoreError("发布任务不存在")
        return job

    def publish_jobs(self, topic_id: int) -> list[dict[str, Any]]:
        return [self._publish_job(r) for r in self._rows("SELECT * FROM publish_jobs WHERE topic_id = ? AND state != 'superseded' ORDER BY id DESC LIMIT 20", (topic_id,))]

    def update_publish_job(self, job_id: int, **fields: Any) -> dict[str, Any]:
        if set(fields) - {"state", "result", "message", "confirmed_at", "finished_at"}:
            raise StoreError("不可更新的发布字段")
        if "result" in fields and fields["result"] is not None:
            fields["result"] = json.dumps(fields["result"], ensure_ascii=False)
        assignments = ", ".join(f"{k} = ?" for k in fields)
        with self.tx() as conn:
            conn.execute(f"UPDATE publish_jobs SET {assignments} WHERE id = ?", (*fields.values(), job_id))
        return self.publish_job(job_id)

    def recover_interrupted_publishes(self) -> int:
        with self.tx() as conn:
            cursor = conn.execute(
                "UPDATE publish_jobs SET state = 'unknown', message = '服务重启时发布还在进行，结果不确定：去平台后台确认' WHERE state = 'running'"
            )
        return cursor.rowcount

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
        allowed = {"title", "formats", "status", "memo", "article_path", "published_url", "account_id", "archived_at", "note_paths", "write_state", "write_error", "outline_path", "outline_state", "outline_error", "video_project", "published_video_id", "copy_state", "copy_error", "is_focus", "snoozed_until", "manual_stage", "closed_at", "video_file"}
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

    def set_focus(self, topic_id: int | None) -> None:
        """At most one topic is in focus: the single video Park is writing or recording right now."""
        with self.tx() as conn:
            conn.execute("UPDATE topics SET is_focus = 0 WHERE is_focus = 1")
            if topic_id is not None:
                conn.execute("UPDATE topics SET is_focus = 1, snoozed_until = NULL, updated_at = ? WHERE id = ?", (now_iso(), topic_id))

    def focus_topic(self) -> dict[str, Any] | None:
        return self._row("SELECT * FROM topics WHERE is_focus = 1 AND archived_at IS NULL ORDER BY updated_at DESC LIMIT 1")

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
        if "traffic_tags" in cleaned:
            cleaned["traffic_tags"] = {
                str(k): list(dict.fromkeys(str(t).strip().lstrip("#").strip() for t in (v or []) if str(t).strip().lstrip("#").strip()))
                for k, v in cleaned["traffic_tags"].items()
            }
        if "threshold" in cleaned and not 1 <= cleaned["threshold"] <= 100:
            raise StoreError("爆款门槛需在 1× 到 100× 之间")
        if "auto_enqueue_limit" in cleaned and not 0 <= cleaned["auto_enqueue_limit"] <= 50:
            raise StoreError("自动入队上限需在 0 到 50 之间")
        if "auto_enqueue_threshold" in cleaned and not 1 <= cleaned["auto_enqueue_threshold"] <= 100:
            raise StoreError("自动拆解门槛需在 1× 到 100× 之间")
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
        kind: str | None = None,
    ) -> dict[str, Any]:
        duplicate = self._row("SELECT id FROM accounts WHERE profile_url = ?", (profile_url,))
        if duplicate is None and external_id:
            duplicate = self._row(
                "SELECT id FROM accounts WHERE platform = ? AND external_id = ?", (platform, external_id)
            )
        if duplicate is not None:
            raise StoreError("这个账号已经在库里了")
        kind = KIND_SELF if is_self else (kind or KIND_BENCHMARK)
        if kind not in ACCOUNT_KINDS:
            raise StoreError(f"不认识的账号类型：{kind}")
        with self.tx() as conn:
            cursor = conn.execute(
                "INSERT INTO accounts(platform, profile_url, external_id, is_self, kind, status, added_at) VALUES(?, ?, ?, ?, ?, ?, ?)",
                (platform, profile_url, external_id, int(is_self), kind, status, now_iso()),
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

    def followed_accounts(self) -> list[dict[str, Any]]:
        """Everyone Park follows. 2026-09-20: 对标 and 老师 collapsed back into one category —
        he treats them the same, and the reason to split them (keeping 老师 breakouts out of the
        daily recommendation) went away when the recommendation itself was removed."""
        return [a for a in self.accounts() if not a["is_self"]]

    def self_account(self, account_id: int | None = None) -> dict[str, Any] | None:
        if account_id is not None:
            return self._row("SELECT * FROM accounts WHERE is_self = 1 AND id = ?", (account_id,))
        return self._row("SELECT * FROM accounts WHERE is_self = 1 ORDER BY id LIMIT 1")

    def my_accounts(self) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM accounts WHERE is_self = 1 ORDER BY id")

    def update_account(self, account_id: int, **fields: Any) -> dict[str, Any]:
        allowed = {"nickname", "follower_count", "total_favorited", "signature", "status", "last_error", "last_synced_at", "external_id", "kind"}
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

    PUBLIC_WINDOW_SECONDS = 3600

    def public_videos(self, account_id: int) -> list[dict[str, Any]]:
        """还挂在公开主页上的作品。同步读的是公开主页，每次把看到的都刷新 fetched_at；
        设成私密或删掉的，从此停在最后一次被看到的时间（Park 9/27：只看公开的作品）。"""
        rows = self.videos(account_id)
        stamps = [r["fetched_at"] for r in rows if r.get("fetched_at")]
        if not stamps:
            return rows
        latest = datetime.fromisoformat(max(stamps))
        return [r for r in rows if r.get("fetched_at")
                and (latest - datetime.fromisoformat(r["fetched_at"])).total_seconds() <= self.PUBLIC_WINDOW_SECONDS]

    def account_snapshots(self, account_id: int, since_day: str) -> list[dict[str, Any]]:
        return self._rows(
            "SELECT s.video_id, s.fetched_at, s.views, v.published_at FROM video_snapshots s JOIN videos v ON v.video_id = s.video_id "
            "WHERE v.account_id = ? AND v.is_image_post = 0 AND s.fetched_at >= ? ORDER BY s.fetched_at",
            (account_id, since_day),
        )

    def add_post_snapshots(self, platform: str, posts: list[dict[str, Any]], fetched_at: str) -> None:
        """B站 / X / 研习室 每条内容这一次读到的累计数（platform_stats.sync 写）。"""
        with self.tx() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO post_snapshots(platform, post_id, title, published_at, fetched_at, views) VALUES (?, ?, ?, ?, ?, ?)",
                [(platform, str(p["post_id"]), p.get("title"), p.get("published_at"), fetched_at, int(p["views"])) for p in posts],
            )

    def post_snapshots(self, platform: str, since_day: str) -> list[dict[str, Any]]:
        """Same shape as account_snapshots, so reach.daily_views works on both."""
        return self._rows(
            "SELECT post_id AS video_id, fetched_at, views, published_at FROM post_snapshots WHERE platform = ? AND fetched_at >= ? ORDER BY fetched_at",
            (platform, since_day),
        )

    def post_synced_at(self) -> dict[str, str]:
        return {row["platform"]: row["at"] for row in self._rows("SELECT platform, MAX(fetched_at) AS at FROM post_snapshots GROUP BY platform")}

    def reach_entries(self, since_day: str) -> list[dict[str, Any]]:
        return self._rows("SELECT day, platform, views FROM reach_entries WHERE day >= ? ORDER BY day", (since_day,))

    def set_reach(self, day: str, platform: str, views: int | None) -> None:
        with self.tx() as conn:
            if views is None:
                conn.execute("DELETE FROM reach_entries WHERE day = ? AND platform = ?", (day, platform))
            else:
                conn.execute(
                    "INSERT INTO reach_entries(day, platform, views, updated_at) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(day, platform) DO UPDATE SET views = excluded.views, updated_at = excluded.updated_at",
                    (day, platform, int(views), now_iso()),
                )

    # -- 今天：接下来要拍的、私信数、跳过和做完 ------------------------------

    def shoot_list(self, include_done: bool = False) -> list[dict[str, Any]]:
        where = "" if include_done else "WHERE done_at IS NULL"
        return self._rows(f"SELECT * FROM shoot_list {where} ORDER BY done_at IS NOT NULL, position, id")

    def shoot_item(self, item_id: int) -> dict[str, Any]:
        row = self._row("SELECT * FROM shoot_list WHERE id = ?", (item_id,))
        if row is None:
            raise StoreError("这一条已经不在清单里了")
        return row

    def add_shoot_item(self, text: str, *, top: bool = False, topic_id: int | None = None, planned_day: str | None = None) -> dict[str, Any]:
        text = (text or "").strip()
        if not text:
            raise StoreError("写一句要拍什么")
        edge = self._row(f"SELECT {'MIN' if top else 'MAX'}(position) AS p FROM shoot_list WHERE done_at IS NULL")
        base = edge["p"] if edge and edge["p"] is not None else 0.0
        with self.tx() as conn:
            cur = conn.execute("INSERT INTO shoot_list(text, position, topic_id, created_at, planned_day) VALUES (?, ?, ?, ?, ?)",
                               (text[:200], base - 1 if top else base + 1, topic_id, now_iso(), planned_day))
        return self.shoot_item(cur.lastrowid)

    def update_shoot_item(self, item_id: int, **fields: Any) -> dict[str, Any]:
        allowed = {"text", "position", "topic_id", "done_at", "planned_day"}
        if set(fields) - allowed:
            raise StoreError(f"不可更新的字段：{sorted(set(fields) - allowed)}")
        self.shoot_item(item_id)
        if fields:
            cols = ", ".join(f"{k} = ?" for k in fields)
            with self.tx() as conn:
                conn.execute(f"UPDATE shoot_list SET {cols} WHERE id = ?", (*fields.values(), item_id))
        return self.shoot_item(item_id)

    def move_shoot_item(self, item_id: int, step: int) -> list[dict[str, Any]]:
        """上移（-1）或下移（+1）一格：和相邻那条交换位置。"""
        items = self.shoot_list()
        idx = next((i for i, it in enumerate(items) if it["id"] == item_id), None)
        if idx is None:
            raise StoreError("这一条已经不在清单里了")
        other = idx + step
        if 0 <= other < len(items):
            a, b = items[idx], items[other]
            with self.tx() as conn:
                conn.execute("UPDATE shoot_list SET position = ? WHERE id = ?", (b["position"], a["id"]))
                conn.execute("UPDATE shoot_list SET position = ? WHERE id = ?", (a["position"], b["id"]))
        return self.shoot_list()

    def delete_shoot_item(self, item_id: int) -> None:
        with self.tx() as conn:
            conn.execute("DELETE FROM shoot_list WHERE id = ?", (item_id,))

    # -- Wendy 卡片里的对话（不放进 anna_chats：那张表启动时会把别的线程并进 Anna 的）------

    def wendy_thread(self, limit: int = 40) -> list[dict[str, Any]]:
        rows = self._rows("SELECT * FROM wendy_thread ORDER BY id DESC LIMIT ?", (limit,))
        return list(reversed(rows))

    def add_wendy(self, who: str, text: str, *, source: str = "desk") -> dict[str, Any]:
        with self.tx() as conn:
            cur = conn.execute("INSERT INTO wendy_thread(at, who, source, text) VALUES (?, ?, ?, ?)", (now_iso(), who, source, text[:4000]))
        return self._row("SELECT * FROM wendy_thread WHERE id = ?", (cur.lastrowid,))

    def last_touch(self, day: str) -> str | None:
        """他这一天在工作台里最后一次动静是几点：勾了日报、填了私信或 X 的数、写了跳过理由或做完了、
        勾了周历上的事、在卡片里回了 Wendy。都没有就是 None。（Wendy 催不催看这个。）"""
        row = self._row(
            """SELECT MAX(t) AS t FROM (
                 SELECT MAX(checked_at) AS t FROM daily_checks WHERE day = :day
                 UNION ALL SELECT MAX(updated_at) FROM dm_entries WHERE day = :day
                 UNION ALL SELECT MAX(updated_at) FROM kpi_counts WHERE day = :day
                 UNION ALL SELECT MAX(at) FROM driver_log WHERE day = :day AND kind != 'nudge'
                 UNION ALL SELECT MAX(done_at) FROM plan_items WHERE substr(done_at, 1, 10) >= :prev
                 UNION ALL SELECT MAX(at) FROM wendy_thread WHERE who = 'park' AND substr(at, 1, 10) >= :prev
               )""",
            {"day": day, "prev": (datetime.fromisoformat(day) - timedelta(days=1)).date().isoformat()},
        )
        return row["t"] if row else None

    # -- 周历上不算分的事（「约两个博主诊断」这种）：哪天、做什么、做完没有 --------------

    def plan_items(self, since_day: str, until_day: str) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM plan_items WHERE day >= ? AND day <= ? ORDER BY day, id", (since_day, until_day))

    def add_plan_item(self, day: str, text: str) -> dict[str, Any]:
        text = (text or "").strip()
        if not text:
            raise StoreError("写一句这天要做什么")
        with self.tx() as conn:
            cur = conn.execute("INSERT INTO plan_items(day, text, created_at) VALUES (?, ?, ?)", (day, text[:200], now_iso()))
        return self._row("SELECT * FROM plan_items WHERE id = ?", (cur.lastrowid,))

    def set_plan_item_done(self, item_id: int, done: bool) -> None:
        with self.tx() as conn:
            conn.execute("UPDATE plan_items SET done_at = ? WHERE id = ?", (now_iso() if done else None, item_id))

    def delete_plan_item(self, item_id: int) -> None:
        with self.tx() as conn:
            conn.execute("DELETE FROM plan_items WHERE id = ?", (item_id,))

    def dm_entries(self, since_day: str) -> dict[str, dict[str, int]]:
        return {r["day"]: {"received": r["received"], "replied": r["replied"]}
                for r in self._rows("SELECT * FROM dm_entries WHERE day >= ?", (since_day,))}

    def set_dm(self, day: str, received: int, replied: int) -> None:
        if received < 0 or replied < 0:
            raise StoreError("私信数不能是负数")
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO dm_entries(day, received, replied, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(day) DO UPDATE SET received = excluded.received, replied = excluded.replied, updated_at = excluded.updated_at",
                (day, int(received), int(replied), now_iso()),
            )

    # -- 老师和对标新发的视频：看过了没有、记了一句什么 --------------------------

    def feed_marks(self) -> dict[str, dict[str, Any]]:
        return {r["video_id"]: r for r in self._rows("SELECT * FROM feed_marks")}

    def set_feed_mark(self, video_id: str, *, seen: bool | None = None, note: str | None = None, opened: bool | None = None) -> None:
        """只有他点「看过了」才算看过。点「去看」只记成点开过（9/30 Park：看完觉得好，接下来要复刻或拆解，
        这一条不能自己消失；觉得没用他再点看过了）。记一句也不算看过。"""
        with self.tx() as conn:
            conn.execute("INSERT OR IGNORE INTO feed_marks(video_id) VALUES (?)", (video_id,))
            if opened:
                conn.execute("UPDATE feed_marks SET opened_at = ? WHERE video_id = ?", (now_iso(), video_id))
            if seen is not None:
                conn.execute("UPDATE feed_marks SET seen_at = ? WHERE video_id = ?", (now_iso() if seen else None, video_id))
            if note is not None:
                conn.execute("UPDATE feed_marks SET note = ? WHERE video_id = ?", (note.strip()[:300] or None, video_id))

    # -- 流量视频（swipe.py） -------------------------------------------------

    def _swipe(self, row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {**row, "info": json.loads(row["info"]) if row.get("info") else {}}

    def swipe_videos(self) -> list[dict[str, Any]]:
        return [self._swipe(r) for r in self._rows("SELECT * FROM swipe_videos ORDER BY id DESC")]

    def swipe_video(self, swipe_id: int) -> dict[str, Any]:
        row = self._swipe(self._row("SELECT * FROM swipe_videos WHERE id = ?", (swipe_id,)))
        if row is None:
            raise StoreError("这条流量视频已经不在了")
        return row

    def add_swipe(self, url: str, platform: str, note: str | None = None) -> dict[str, Any]:
        dup = self._row("SELECT id FROM swipe_videos WHERE url = ?", (url,))
        if dup:
            raise StoreError("这条已经存过了")
        with self.tx() as conn:
            cur = conn.execute("INSERT INTO swipe_videos(url, platform, state, note, created_at) VALUES (?, ?, 'downloading', ?, ?)",
                               (url, platform, (note or "").strip()[:300] or None, now_iso()))
        return self.swipe_video(cur.lastrowid)

    def update_swipe(self, swipe_id: int, **fields: Any) -> dict[str, Any]:
        allowed = {"state", "error", "content_dir", "info", "note", "collection", "topic_id"}
        if set(fields) - allowed:
            raise StoreError(f"不可更新的字段：{sorted(set(fields) - allowed)}")
        if "info" in fields and fields["info"] is not None:
            fields["info"] = json.dumps(fields["info"], ensure_ascii=False)
        if fields:
            cols = ", ".join(f"{k} = ?" for k in fields)
            with self.tx() as conn:
                conn.execute(f"UPDATE swipe_videos SET {cols} WHERE id = ?", (*fields.values(), swipe_id))
        return self.swipe_video(swipe_id)

    def delete_swipe(self, swipe_id: int) -> None:
        with self.tx() as conn:
            conn.execute("DELETE FROM swipe_videos WHERE id = ?", (swipe_id,))

    def swipe_count_since(self, platform: str, since_iso: str) -> int:
        row = self._row("SELECT COUNT(*) AS n FROM swipe_videos WHERE platform = ? AND created_at >= ?", (platform, since_iso))
        return int(row["n"]) if row else 0

    def kpi_counts(self, since_day: str, key: str) -> dict[str, int]:
        return {r["day"]: int(r["value"]) for r in self._rows("SELECT day, value FROM kpi_counts WHERE key = ? AND day >= ?", (key, since_day))}

    def set_kpi_count(self, day: str, key: str, value: int) -> None:
        if value < 0:
            raise StoreError("数不能是负数")
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO kpi_counts(day, key, value, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(day, key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                (day, key, int(value), now_iso()),
            )

    def driver_mark(self, day: str, key: str, kind: str, reason: str | None = None) -> None:
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO driver_log(day, key, kind, reason, at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(day, key, kind) DO UPDATE SET reason = excluded.reason, at = excluded.at",
                (day, key, kind, reason, now_iso()),
            )

    def driver_unmark(self, day: str, key: str, kind: str) -> None:
        with self.tx() as conn:
            conn.execute("DELETE FROM driver_log WHERE day = ? AND key = ? AND kind = ?", (day, key, kind))

    # -- 当天补发哪几格：早上抽一次存下来，当天不再变（换一格只换那一格）--------------------

    def backfill_plan(self, day: str) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM backfill_plan WHERE day = ? ORDER BY slot", (day,))

    def set_backfill_plan(self, day: str, cells: list[tuple[str, str]]) -> None:
        with self.tx() as conn:
            conn.execute("DELETE FROM backfill_plan WHERE day = ?", (day,))
            conn.executemany("INSERT INTO backfill_plan(day, slot, video_id, platform) VALUES (?, ?, ?, ?)",
                             [(day, i, v, p) for i, (v, p) in enumerate(cells)])

    def replace_backfill_cell(self, day: str, slot: int, video_id: str, platform: str) -> None:
        with self.tx() as conn:
            conn.execute("UPDATE backfill_plan SET video_id = ?, platform = ? WHERE day = ? AND slot = ?", (video_id, platform, day, slot))

    def driver_log(self, since_day: str = "", kind: str | None = None) -> list[dict[str, Any]]:
        if kind:
            return self._rows("SELECT * FROM driver_log WHERE day >= ? AND kind = ? ORDER BY at", (since_day, kind))
        return self._rows("SELECT * FROM driver_log WHERE day >= ? ORDER BY at", (since_day,))

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

    def followed_posts(self, days: int = 7, now: datetime | None = None) -> list[dict[str, Any]]:
        """What the accounts Park follows published recently, newest first.

        Keyed on published_at, never on when the workbench first saw the video: a newly added
        teacher's first sync pulls their whole back catalogue, and that must not land in 进项.
        """
        cutoff = ((now or datetime.now(timezone.utc)) - timedelta(days=days)).isoformat()
        posts = []
        for account in self.followed_accounts():
            for video in self.videos(account["id"]):
                if (video["published_at"] or "") >= cutoff:
                    posts.append({**video, "account_nickname": account["nickname"], "account_id": account["id"]})
        posts.sort(key=lambda v: v["published_at"] or "", reverse=True)
        return posts

    def outliers(self, threshold: float) -> list[dict[str, Any]]:
        results = []
        for account in self.followed_accounts():
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

    def enqueue(self, *, url: str, video_id: str | None, source: str, retry_failed: bool = False) -> tuple[dict[str, Any], bool]:
        """Queue a teardown unless the same video is already queued, running or done.

        9/29：以前失败过的视频，自动同步每次都当新爆款再排一次——同一条（没有人声，转写永远是空的）
        10 天里用 Park 的抖音登录下载了 37 次。自动入队（retry_failed=False）碰到失败过的就不再排；
        只有 Park 手动加、手动点重试才会再跑。"""
        if video_id:
            existing = self._row(
                "SELECT * FROM jobs WHERE video_id = ? AND stage != 'failed' ORDER BY id DESC LIMIT 1", (video_id,)
            )
            if existing is not None:
                return existing, False
            if not retry_failed:
                failed = self._row("SELECT * FROM jobs WHERE video_id = ? AND stage = 'failed' ORDER BY id DESC LIMIT 1", (video_id,))
                if failed is not None:
                    return failed, False
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
