from __future__ import annotations

import pytest

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


def test_a_platform_block_is_not_reported_as_an_expired_login(tmp_path) -> None:
    """Park: 视频号腾讯最近两个月开始封。Re-scanning a QR code fixes nothing, so the tile
    must not send him off to log in again."""
    from content_studio import publisher

    cred = tmp_path / "account.json"
    cred.write_text("{}", encoding="utf-8")
    spec = {"label": "视频号", "credential": cred, "blocked": "平台限制了自动发布", "login_hint": "x", "modes": {"draft": {"label": "草稿"}}}
    got = publisher.readiness({"channels": spec})["channels"]
    assert got["blocked"] is True and got["note"] == "平台限制了自动发布" and got["login_hint"] == ""

    # a channel without the flag still reports on credential age as before
    ok = publisher.readiness({"bilibili": {"label": "B 站", "credential": cred, "login_hint": "y", "modes": {"upload": {"label": "投稿"}}}})["bilibili"]
    assert ok.get("blocked") is not True and ok["credential"] is True


def test_a_text_only_channel_does_not_demand_a_video_or_a_title(tmp_path) -> None:
    """X 发的是正文本身。Requiring a 成片 or a 标题 would block Park on fields that do not exist there."""
    from content_studio import publisher

    spec = {"label": "X", "copy_key": "x", "credential": tmp_path / "s.yaml", "login_hint": "",
            "no_video": True, "modes": {"post": {"label": "发一条推文（纯文字）", "argv": ["python3", "-m", "content_studio.x_post", "--text", "{body}"]}}}
    copy = {"x": {"title": "", "body": "大多数人以为合规只是流程", "tags": ["AI"]}}
    payload = publisher.build_payload("x", "post", video=None, copy=copy, publishers={"x": spec})
    assert payload["video"] == "" and payload["body"] == "大多数人以为合规只是流程"
    assert publisher.command_for(payload, {"x": spec})[-1] == "大多数人以为合规只是流程"

    with pytest.raises(publisher.PublishError, match="正文"):
        publisher.build_payload("x", "post", video=None, copy={"x": {"body": ""}}, publishers={"x": spec})
