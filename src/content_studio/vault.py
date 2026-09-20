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


# Park reads all three dailies in the morning (2026-09-19: he asked for 财经 and K 线 back).
# 晨报 is a digest of these three, so it stays out to avoid showing the same thing twice.
DAILY_SOURCES = (
    DailySource("ai_daily", "AI 日报", "006_ai daily newsletter", (".md",)),
    DailySource("finance_daily", "财经日报", "007_finance daily newsletter", (".md",)),
    DailySource("kline_daily", "K 线日报", "007_kline daily newsletter", (".md",)),
)

INBOX_SOURCES = (
    # 对标内容 is the one folder the workbench writes to: transcripts of what the accounts Park
    # follows just posted, so he can read them in 进项 and attach them to a topic as 素材.
    InboxSource("benchmark", "对标内容", "002_对标内容"),
    InboxSource("clipping", "Clippings", "002_clippings"),
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


def daily_history(raw_root: str, key: str, limit: int = 30) -> list[dict[str, Any]]:
    """Recent issues of one newsletter, newest first — one tab per daily in 进项."""
    source = next((s for s in DAILY_SOURCES if s.key == key), None)
    if source is None:
        raise VaultError(f"没有这份日报：{key}")
    root = vault_root(raw_root)
    folder = root / source.folder
    if not folder.is_dir():
        return []
    # Only dated issues: the folder also holds a README and the tooling's scratch files, and a
    # README listed as if it were an issue is noise in a list Park reads every morning.
    files = [
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in source.suffixes and not p.name.startswith(".") and _daily_day(p.name)
    ]
    # Newest first, and a day's second issue (…-晚) above that day's first one — sorting on the
    # raw file name puts them the other way round, because '.' sorts after '-'.
    files.sort(key=lambda p: (_daily_day(p.name) or "", _edition(p.name)), reverse=True)
    return [
        {"key": source.key, "label": source.label, "path": str(p.relative_to(root)),
         "kind": p.suffix.lstrip("."), "title": f"{source.label} · {_daily_day(p.name)}{_edition(p.name)}",
         "day": _daily_day(p.name), "modified_at": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="minutes")}
        for p in files[:limit]
    ]


_DAILY_DAY = re.compile(r"(20\d{2})-(\d{2})-(\d{2})|(\d{2})-(\d{2})-(\d{2})")


def _edition(name: str) -> str:
    """Some days have a second issue (26-09-16-晚.md); without this both rows read the same."""
    tail = _DAILY_DAY.sub("", Path(name).stem, count=1).strip("-_ ")
    return f" {tail}" if tail else ""


def _daily_day(name: str) -> str | None:
    """The issue date from the file name — both 2026-09-20-… and 26-09-20… are in use."""
    m = _DAILY_DAY.search(name)
    if not m:
        return None
    y, mo, d = (m.group(1), m.group(2), m.group(3)) if m.group(1) else ("20" + m.group(4), m.group(5), m.group(6))
    return f"{y}-{mo}-{d}"


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
                    "author": str(meta.get("author") or "").strip() or None,
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
