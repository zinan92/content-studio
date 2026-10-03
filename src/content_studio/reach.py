"""触达 (reach): how many people Park's content reached each day, across every platform.

Park's first KPI is reach, not conversion. Douyin reach is computed from the view
snapshots the daily sync already records (views gained per day, summed over his
videos). Every other platform has no data connector yet, so its daily views are
typed in by hand until one exists; the numbers are stored per day and platform and
added into the same total.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

# key, label, auto (the workbench pulls the numbers itself), mark (the tile letter), hue.
# Park has an account on all nine. `auto` is about *data*, not publishing — 抖音 from its own
# sync, B站 / X / 研习室 from platform_stats (9/25); for the rest he types them in. Brand logos are deliberately not bundled: they are other companies' trademarks,
# so each platform gets a letter tile in its own hue instead.
PLATFORMS: tuple[tuple[str, str, bool], ...] = (
    ("douyin", "抖音", True),
    ("channels", "视频号", False),
    ("xiaohongshu", "小红书", False),
    ("wechat_mp", "公众号", False),
    ("miniprogram", "研习室", True),
    ("x", "X", True),
    ("bilibili", "B 站", True),
    ("youtube", "YouTube", False),
    ("xiaoyuzhou", "小宇宙", False),
)
PLATFORM_KEYS = tuple(k for k, _, _ in PLATFORMS)
# 手填的平台去哪看今天的数（9/29：视频号没有开放接口、公众号没认证，只能 Park 每天看一眼填一个数）
STATS_URLS = {
    "channels": "https://channels.weixin.qq.com/platform/statistic/post",
    "wechat_mp": "https://mp.weixin.qq.com/",
}
AUTO_KEYS = tuple(k for k, _, auto in PLATFORMS if auto)
# 9/29 Park：注意力分层。主攻 抖音、视频号、小红书（发视频）和 X（发文字 + 每天回复）；
# 公众号、B 站、YouTube 零成本照发，不投入、不看数。页面上主攻的放左边，其余放右边淡一点。
CORE = ("douyin", "channels", "xiaohongshu", "x")
# 出摊时每个平台发的是什么：视频 / 文字 / 图文（默认值；能选的平台在 FORM_CHOICES，选了存在 platform_accounts[key]["form"]）
# 9/29 Park：「如果未来我们做给客户的话，我们要给客户一个选择，让他决定究竟想发什么。」
FORM = {"douyin": "video", "channels": "video", "xiaohongshu": "video", "bilibili": "video", "youtube": "video",
        "x": "text", "wechat_mp": "text", "miniprogram": "text", "xiaoyuzhou": "audio"}
FORM_LABEL = {"video": "视频", "text": "文字", "cards": "图文", "audio": "音频"}
FORM_CHOICES = {"xiaohongshu": ("video", "cards")}


def form_of(key: str, accounts: dict | None) -> str:
    """这个平台现在发什么：设置里选过的优先，没选按默认。"""
    chosen = ((accounts or {}).get(key) or {}).get("form")
    return chosen if chosen in FORM_CHOICES.get(key, ()) else FORM.get(key, "video")
PLATFORM_STYLE: dict[str, dict[str, str]] = {
    "douyin": {"mark": "抖", "hue": "#111111"},  # 9/29 Park：抖音黑，和 X 一样是黑底品牌色
    "channels": {"mark": "视", "hue": "#07C160"},
    "xiaohongshu": {"mark": "红", "hue": "#FF2442"},
    "wechat_mp": {"mark": "公", "hue": "#07C160"},
    "miniprogram": {"mark": "研", "hue": "#5B8FF9"},
    "x": {"mark": "X", "hue": "#111111"},
    "bilibili": {"mark": "B", "hue": "#00A1D6"},
    "youtube": {"mark": "Y", "hue": "#FF0000"},
    "xiaoyuzhou": {"mark": "宇", "hue": "#FA4D3C"},
}


def local_day(stamp: Any) -> str:
    """一次读数（或发布时间）算哪一天：本机时区（北京）的日历日。

    10/3 Park：「概览晚上 12 点就归零，现在到底怎么算的？」——以前拿 UTC 字符串的前 10 位当日期，
    北京时间早上 8 点才换日：半夜 0–8 点的读数记到前一天，页面上的「今天」（本地日期）又 0 点就换了。
    没带时区的时间按字面日期。"""
    text = str(stamp or "")
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text[:10]
    if moment.tzinfo is None:
        return moment.date().isoformat()
    return moment.astimezone().date().isoformat()


def utc_bound(day: date) -> str:
    """本地 day 的 0 点，写成库里读数时间的样子（UTC），给 SQL 的 fetched_at >= ? 用。"""
    return datetime.combine(day, time.min).astimezone().astimezone(timezone.utc).isoformat(timespec="seconds")


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
        by_video.setdefault(row["video_id"], []).append((row["fetched_at"], int(row["views"])))
        if row.get("published_at"):
            published[row["video_id"]] = local_day(row["published_at"])
    start = today - timedelta(days=days - 1)
    totals = {(start + timedelta(days=i)).isoformat(): 0 for i in range(days)}
    for video_id, rows in by_video.items():
        rows.sort()
        last_day_value: dict[str, int] = {}
        for stamp, views in rows:
            last_day_value[local_day(stamp)] = views  # the last snapshot of each (local) day wins
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
