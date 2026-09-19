from __future__ import annotations

from datetime import date

from content_studio import reach


def test_daily_views_counts_gains_per_video_per_day() -> None:
    today = date(2026, 9, 19)
    snaps = [
        {"video_id": "a", "fetched_at": "2026-09-17T09:30:00", "views": 1000, "published_at": "2026-09-16T20:00:00"},  # published yesterday: first snapshot counts
        {"video_id": "old", "fetched_at": "2026-09-17T09:30:00", "views": 90000, "published_at": "2026-03-01T00:00:00"},  # baseline only
        {"video_id": "old", "fetched_at": "2026-09-18T09:30:00", "views": 90010},
        {"video_id": "a", "fetched_at": "2026-09-18T09:30:00", "views": 1300},
        {"video_id": "a", "fetched_at": "2026-09-18T20:00:00", "views": 1400},  # last of the day wins
        {"video_id": "a", "fetched_at": "2026-09-19T09:30:00", "views": 1350},  # a drop never goes negative
        {"video_id": "b", "fetched_at": "2026-09-19T09:30:00", "views": 50},
        {"video_id": "c", "fetched_at": "2026-09-19T09:30:00", "views": None},
    ]
    got = reach.daily_views(snaps, 3, today)
    assert got == {"2026-09-17": 1000, "2026-09-18": 410, "2026-09-19": 50}


def test_summary_adds_platforms_and_projects_the_pace() -> None:
    today = date(2026, 9, 19)
    totals = {"2026-09-18": {"douyin": 400, "x": 100}, "2026-09-19": {"douyin": 50}}
    s = reach.summary(totals, today)
    assert [d["total"] for d in s["days"]] == [500, 50]
    assert s["today"] == 50 and s["avg7"] == 275 and s["pace30"] == 275 * 30
    assert reach.PLATFORMS[0] == ("douyin", "抖音", True) and "xiaoyuzhou" in reach.PLATFORM_KEYS
