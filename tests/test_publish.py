from __future__ import annotations

from datetime import datetime, timedelta, timezone

from content_studio import publish

NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)


def iso(dt):
    return dt.isoformat()


def test_similarity_prefers_same_story() -> None:
    assert publish.title_similarity("为什么这么多人看不到 AI 的影响力", "为什么这么多人，到今天还感觉不到AI？#AI #认知") > 0.4
    assert publish.title_similarity("为什么这么多人看不到 AI 的影响力", "黄金今天怎么走") < 0.25


def test_suggestions_respect_time_taken_and_image_posts() -> None:
    topic = {"title": "为什么这么多人看不到 AI 的影响力", "created_at": iso(NOW - timedelta(days=3))}
    videos = [
        {"video_id": "1", "title": "为什么这么多人看不到AI的影响力？", "published_at": iso(NOW - timedelta(days=1)), "is_image_post": 0},
        {"video_id": "2", "title": "为什么这么多人看不到AI的影响力", "published_at": iso(NOW - timedelta(days=30)), "is_image_post": 0},
        {"video_id": "3", "title": "为什么这么多人看不到AI的影响力", "published_at": iso(NOW - timedelta(days=1)), "is_image_post": 1},
        {"video_id": "4", "title": "为什么很多人看不到 AI 影响力", "published_at": iso(NOW), "is_image_post": 0},
    ]
    assert [v["video_id"] for v in publish.suggest_matches(topic, videos, taken={"4"})] == ["1"]


def test_performance_milestones_and_teardown_hint() -> None:
    published = NOW - timedelta(hours=80)
    video = {"video_id": "9", "title": "t", "published_at": iso(published), "likes": 3000, "collects": 600, "views": None}
    snaps = [
        {"fetched_at": iso(published + timedelta(hours=5)), "likes": 500, "views": None},
        {"fetched_at": iso(published + timedelta(hours=26)), "likes": 1800, "views": None},
        {"fetched_at": iso(published + timedelta(hours=79)), "likes": 3000, "views": None},
    ]
    perf = publish.performance(video, median_likes=600, snapshots=snaps, creator={"fan_increment": 40, "avg_view_second": 21}, has_report=False, now=NOW)
    assert perf["multiple"] == 5.0 and perf["collect_per_like"] == 0.2
    m = {x["hours"]: x for x in perf["milestones"]}
    assert m[24]["likes"] == 1800 and m[72]["likes"] == 3000 and m[168]["reached"] is False
    assert perf["suggest_teardown"] is True and perf["creator"]["fan_increment"] == 40
    assert publish.performance(video, median_likes=None, snapshots=[], creator=None, has_report=True, now=NOW)["suggest_teardown"] is False


def test_sync_staleness() -> None:
    assert publish.sync_is_stale(None)
    assert publish.sync_is_stale(iso(NOW - timedelta(hours=7)), now=NOW)
    assert not publish.sync_is_stale(iso(NOW - timedelta(hours=1)), now=NOW)
