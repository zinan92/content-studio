"""触达 (reach): how many people Park's content reached each day, across every platform.

Park's first KPI is reach, not conversion. Douyin reach is computed from the view
snapshots the daily sync already records (views gained per day, summed over his
videos). Every other platform has no data connector yet, so its daily views are
typed in by hand until one exists; the numbers are stored per day and platform and
added into the same total.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

# key, label, auto (the workbench pulls the numbers itself), mark (the tile letter), hue.
# Park has an account on all nine. `auto` is about *data*, not publishing — only 抖音 reports
# its own numbers today; for the rest he types them in, or the nightly Obsidian read picks
# them up. Brand logos are deliberately not bundled: they are other companies' trademarks,
# so each platform gets a letter tile in its own hue instead.
PLATFORMS: tuple[tuple[str, str, bool], ...] = (
    ("douyin", "抖音", True),
    ("channels", "视频号", False),
    ("xiaohongshu", "小红书", False),
    ("wechat_mp", "公众号", False),
    ("miniprogram", "小程序", False),
    ("x", "X", False),
    ("bilibili", "B 站", False),
    ("youtube", "YouTube", False),
    ("xiaoyuzhou", "小宇宙", False),
)
PLATFORM_KEYS = tuple(k for k, _, _ in PLATFORMS)
PLATFORM_STYLE: dict[str, dict[str, str]] = {
    "douyin": {"mark": "抖", "hue": "#FE2C55"},
    "channels": {"mark": "视", "hue": "#07C160"},
    "xiaohongshu": {"mark": "红", "hue": "#FF2442"},
    "wechat_mp": {"mark": "公", "hue": "#07C160"},
    "miniprogram": {"mark": "小", "hue": "#5B8FF9"},
    "x": {"mark": "X", "hue": "#111111"},
    "bilibili": {"mark": "B", "hue": "#00A1D6"},
    "youtube": {"mark": "Y", "hue": "#FF0000"},
    "xiaoyuzhou": {"mark": "宇", "hue": "#FA4D3C"},
}


def daily_views(snapshots: list[dict[str, Any]], days: int, today: date) -> dict[str, int]:
    """Views gained per day from snapshots (video_id, fetched_at, views).

    For each video, the views on a day = last snapshot that day minus the last snapshot
    before that day. A video's first snapshot counts fully only if it was published within
    the previous day; for an older video it is just the baseline.
    Days with no snapshot for a video contribute nothing for it, so a missed sync shows
    up as a low day rather than being smeared over the week.
    """
    by_video: dict[str, list[tuple[str, int]]] = {}
    published: dict[str, str] = {}
    for row in snapshots:
        if row.get("views") is None:
            continue
        by_video.setdefault(row["video_id"], []).append((row["fetched_at"][:10], int(row["views"])))
        if row.get("published_at"):
            published[row["video_id"]] = str(row["published_at"])[:10]
    start = today - timedelta(days=days - 1)
    totals = {(start + timedelta(days=i)).isoformat(): 0 for i in range(days)}
    for video_id, rows in by_video.items():
        rows.sort()
        last_day_value: dict[str, int] = {}
        for day, views in rows:
            last_day_value[day] = views  # the last snapshot of each day wins
        previous: int | None = None
        for day in sorted(last_day_value):
            views = last_day_value[day]
            if previous is None:
                # First snapshot: only a video published within the last day is "new reach";
                # an old video's first snapshot is a baseline, not views gained today.
                fresh = published.get(video_id) is None or published[video_id] >= (date.fromisoformat(day) - timedelta(days=1)).isoformat()
                gained = views if fresh else 0
            else:
                gained = max(0, views - previous)
            if day in totals:
                totals[day] += gained
            previous = views
    return totals


def summary(days_total: dict[str, dict[str, int]], today: date) -> dict[str, Any]:
    """Totals per day, 7-day average and the pace projected over 30 days."""
    ordered = sorted(days_total)
    per_day = [{"day": d, "total": sum(days_total[d].values()), "by_platform": days_total[d]} for d in ordered]
    last7 = [p["total"] for p in per_day[-7:]]
    avg7 = round(sum(last7) / len(last7)) if last7 else 0
    today_key = today.isoformat()
    today_total = next((p["total"] for p in per_day if p["day"] == today_key), 0)
    return {"days": per_day, "today": today_total, "avg7": avg7, "pace30": avg7 * 30}
