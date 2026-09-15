"""Benchmark breakouts from the last two days; the daily recommendation reads them as context.

Douyin site search is deliberately absent: its search API answers with an
anti-spam block (see issue #20), and the product never works around risk control.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .store import StudioStore


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
