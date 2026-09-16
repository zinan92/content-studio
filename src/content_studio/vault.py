"""Read-only access to Park's Obsidian vault.

Only the folders listed in DAILY_SOURCES and INBOX_SOURCES are visible; every other
folder in the vault (including secrets) is unreachable through this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
import re
from typing import Any


@dataclass(frozen=True)
class DailySource:
    key: str
    label: str
    folder: str
    suffixes: tuple[str, ...]


@dataclass(frozen=True)
class InboxSource:
    key: str
    label: str
    folder: str


# Only the AI daily feeds video topics. 财经日报 / K 线日报 / 晨报 serve trading decisions,
# never a video so far, so they stay out of the workbench and out of the recommendation prompt.
DAILY_SOURCES = (
    DailySource("ai_daily", "AI 日报", "006_ai daily newsletter", (".md",)),
)

INBOX_SOURCES = (
    InboxSource("clipping", "Clippings", "Clippings"),
    InboxSource("saved", "我收藏的", "002_个人收藏"),
    InboxSource("raw", "我写的", "003_park原始输出"),
)

READABLE_SUFFIXES = (".md", ".html")
FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


class VaultError(ValueError):
    """The vault path is missing or a requested file is outside the allowed folders."""


def _allowed_folders() -> tuple[str, ...]:
    return tuple(s.folder for s in DAILY_SOURCES) + tuple(s.folder for s in INBOX_SOURCES)


def vault_root(raw: str) -> Path:
    root = Path(raw).expanduser()
    if not root.is_dir():
        raise VaultError(f"找不到 Obsidian 库：{raw}")
    return root.resolve()


def safe_path(root: Path, relative: str) -> Path:
    """Resolve a vault-relative path, refusing anything outside the allowed folders."""
    if not relative or relative.startswith("/") or "\x00" in relative:
        raise VaultError("文件路径无效")
    candidate = (root / relative).resolve()
    for folder in _allowed_folders():
        base = (root / folder).resolve()
        if candidate == base or base in candidate.parents:
            if candidate.suffix.lower() not in READABLE_SUFFIXES or not candidate.is_file():
                raise VaultError("文件不存在")
            return candidate
    raise VaultError("文件不存在")


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    match = FRONTMATTER.match(text)
    if not match:
        return {}, text
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        found = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if found:
            meta[found.group(1)] = found.group(2).strip().strip('"').strip("'")
    return meta, text[match.end():]


def plain_summary(body: str, limit: int = 120) -> str:
    text = re.sub(r"```.*?```", " ", body, flags=re.DOTALL)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)|!\[\[[^\]]*\]\]", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[\[([^\]|]*\|)?([^\]]*)\]\]", r"\2", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"^[#>\-*+\s]+|[*_`~]", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def _title(path: Path, meta: dict[str, str], body: str) -> str:
    if meta.get("title"):
        return meta["title"]
    heading = re.search(r"^#\s+(.+)$", body, flags=re.MULTILINE)
    if heading:
        return heading.group(1).strip()
    return path.stem


def _created(path: Path, meta: dict[str, str]) -> datetime:
    raw = meta.get("created") or ""
    try:
        if raw:
            return datetime.fromisoformat(raw[:19]) if "T" in raw else datetime.combine(date.fromisoformat(raw[:10]), datetime.min.time())
    except ValueError:
        pass
    stat = path.stat()
    return datetime.fromtimestamp(getattr(stat, "st_birthtime", stat.st_mtime))


def date_tokens(day: date) -> tuple[str, ...]:
    return (day.isoformat(), day.strftime("%y-%m-%d"))


def dailies(raw_root: str, day: date) -> list[dict[str, Any]]:
    """Today's newsletter files, found by the date in their file name."""
    root = vault_root(raw_root)
    results = []
    for source in DAILY_SOURCES:
        folder = root / source.folder
        found = None
        if folder.is_dir():
            for path in sorted(folder.iterdir()):
                if path.suffix.lower() in source.suffixes and any(path.name.startswith(t) or t in path.name for t in date_tokens(day)):
                    found = path
                    break
        results.append(
            {
                "key": source.key,
                "label": source.label,
                "path": str(found.relative_to(root)) if found else None,
                "kind": found.suffix.lstrip(".") if found else None,
            }
        )
    return results


def inbox(raw_root: str, *, since: datetime, sources: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    """Notes created or modified since `since`, newest first."""
    root = vault_root(raw_root)
    items = []
    for source in INBOX_SOURCES:
        if sources and source.key not in sources:
            continue
        folder = root / source.folder
        if not folder.is_dir():
            continue
        for path in folder.rglob("*.md"):
            if any(part.startswith(".") for part in path.relative_to(root).parts):
                continue
            modified = datetime.fromtimestamp(path.stat().st_mtime)
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            meta, body = parse_frontmatter(text)
            created = _created(path, meta)
            if max(created, modified) < since:
                continue
            items.append(
                {
                    "path": str(path.relative_to(root)),
                    "source": source.key,
                    "source_label": source.label,
                    "title": _title(path, meta, body),
                    "summary": plain_summary(body),
                    "url": meta.get("source") or meta.get("url") or None,
                    "created_at": created.isoformat(timespec="minutes"),
                    "modified_at": modified.isoformat(timespec="minutes"),
                    "is_new": created >= since,
                    "chars": len(body),
                }
            )
    return sorted(items, key=lambda item: max(item["created_at"], item["modified_at"]), reverse=True)


def read_note(raw_root: str, relative: str) -> dict[str, Any]:
    root = vault_root(raw_root)
    path = safe_path(root, relative)
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".html":
        return {"path": relative, "kind": "html", "title": path.stem, "meta": {}, "body": None}
    meta, body = parse_frontmatter(text)
    return {"path": relative, "kind": "md", "title": _title(path, meta, body), "meta": meta, "body": body}


def window_start(days: int, now: datetime | None = None) -> datetime:
    """Start of the window: `days` = 1 means since yesterday 00:00."""
    now = now or datetime.now()
    return datetime.combine(now.date() - timedelta(days=max(1, days)), datetime.min.time())
