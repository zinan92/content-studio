"""What is hot in the last two days, from sources that need no extra scraping.

Douyin site search is deliberately absent: its search API answers with an
anti-spam block (see issue #20), and the product never works around risk control.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import re
from typing import Any

from . import vault
from .store import StudioStore

AI_ITEM = re.compile(r"^- \*\*(?P<source>.+?)\*\*\s*\|\s*\[(?P<title>.+?)\]\((?P<url>https?://[^)\s]+)\)")
DEEP_ITEM = re.compile(r"^###\s+\[(?P<title>.+?)\]\((?P<url>https?://[^)\s]+)\)")
FINANCE_ITEM = re.compile(r"^\d+\.\s+\*\*(?P<title>.+?)\*\*")
EN_TERM = re.compile(r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9.+-]*[A-Za-z0-9+])(?![A-Za-z0-9])")
ZH_QUOTED = re.compile(r"[「《“]([^」》”]{2,12})[」》”]")
STOP_TERMS = {
    "ai", "the", "and", "for", "with", "you", "your", "this", "that", "from", "how", "what", "why", "are", "can",
    "http", "https", "com", "www", "status", "news", "video", "new", "top", "one", "all", "not", "out", "use",
    "app", "api", "vs", "via", "its", "has", "was", "will", "more", "about", "into", "now", "just", "get",
    "youtube", "twitter", "x.com", "jpg", "png", "md", "html", "ceo", "pdf",
    "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec", "mins", "min",
}


def _same_story(title: str) -> str:
    return re.sub(r"[\s\W_]+", "", title.lower())[:16]


def benchmark_breakouts(store: StudioStore, *, threshold: float, hours: int = 48, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    recent, week = [], []
    for video in store.outliers(threshold):
        try:
            published = datetime.fromisoformat((video["published_at"] or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        if published >= cutoff:
            recent.append(video)
        elif published >= now - timedelta(days=7):
            week.append(video)
    synced = [a["last_synced_at"] for a in store.accounts() if not a["is_self"] and a["last_synced_at"]]
    key = lambda v: -v["multiple"]
    return {
        "items": sorted(recent, key=key),
        "fallback": sorted(week, key=key)[:3] if not recent else [],
        "last_synced_at": min(synced) if synced else None,
        "hours": hours,
    }


def daily_headlines(raw_root: str, day: date, limit: int = 8) -> list[dict[str, Any]]:
    root = vault.vault_root(raw_root)
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in vault.dailies(raw_root, day):
        if not item["path"] or item["kind"] != "md":
            continue
        text = (root / item["path"]).read_text(encoding="utf-8", errors="replace")
        count = 0
        for line in text.splitlines():
            match = AI_ITEM.match(line) or DEEP_ITEM.match(line) or FINANCE_ITEM.match(line)
            if not match:
                continue
            groups = match.groupdict()
            story = _same_story(groups["title"])
            if story in seen:
                continue
            seen.add(story)
            results.append(
                {
                    "daily": item["label"],
                    "daily_path": item["path"],
                    "source": groups.get("source") or ("深读" if line.startswith("###") else item["label"]),
                    "title": groups["title"].strip(),
                    "url": groups.get("url"),
                }
            )
            count += 1
            if count >= limit:
                break
    return results


def _terms(text: str) -> set[str]:
    found = set()
    for token in EN_TERM.findall(text):
        normalized = token.strip(".-+")
        if len(normalized) < 3 and normalized.upper() != normalized:
            continue
        if normalized.lower() in STOP_TERMS or normalized.isdigit() or len(normalized) < 2:
            continue
        found.add(normalized)
    found.update(term.strip() for term in ZH_QUOTED.findall(text))
    return found


def frequent_topics(raw_root: str, *, today: date, days: int = 7, headlines: list[dict[str, Any]] | None = None, limit: int = 10) -> list[dict[str, Any]]:
    """Terms that recur across recent clippings and newsletter headlines (no model calls)."""
    docs: list[dict[str, Any]] = []
    since = datetime.combine(today - timedelta(days=days), datetime.min.time())
    for item in vault.inbox(raw_root, since=since, sources=("clipping", "saved")):
        docs.append({"title": item["title"], "path": item["path"], "url": item["url"], "text": f"{item['title']} {item['summary']}"})
    for offset in range(2):
        for headline in headlines if (offset == 0 and headlines is not None) else daily_headlines(raw_root, today - timedelta(days=offset), limit=30):
            docs.append({"title": headline["title"], "path": headline["daily_path"], "url": headline["url"], "text": headline["title"]})
    canonical: dict[str, str] = {}
    hits: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for doc in docs:
        for term in _terms(doc["text"]):
            key = term.lower()
            canonical.setdefault(key, term)
            if all(_same_story(existing["title"]) != _same_story(doc["title"]) for existing in hits[key]):
                hits[key].append(doc)
    ranked = sorted(((k, v) for k, v in hits.items() if len(v) >= 2), key=lambda kv: (-len(kv[1]), kv[0]))
    return [
        {"term": canonical[key], "count": len(items), "examples": [{k: d[k] for k in ("title", "path", "url")} for d in items[:3]]}
        for key, items in ranked[:limit]
    ]
