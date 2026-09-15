from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from content_studio import hot
from content_studio.store import StudioStore

def test_benchmark_breakouts_split_recent_and_week(tmp_path: Path) -> None:
    store = StudioStore(tmp_path / "s.sqlite3")
    account = store.add_account(platform="抖音", profile_url="https://www.douyin.com/user/x", external_id="x", status="ok")
    now = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)
    def iso(delta):
        return (now - delta).isoformat()
    base = dict(platform="抖音", duration_seconds=60, is_top=0, is_image_post=0, comments=0, shares=0, collects=0, views=None)
    videos = [dict(base, video_id=str(i), title=f"v{i}", published_at=iso(timedelta(days=20 + i)), likes=100) for i in range(5)]
    videos.append(dict(base, video_id="hot1", title="hot", published_at=iso(timedelta(hours=10)), likes=5000))
    videos.append(dict(base, video_id="hot2", title="old", published_at=iso(timedelta(days=4)), likes=3000))
    store.upsert_videos(account["id"], videos)
    result = hot.benchmark_breakouts(store, threshold=5, now=now)
    assert [v["video_id"] for v in result["items"]] == ["hot1"]
    assert result["fallback"] == []
    assert [v["video_id"] for v in hot.benchmark_breakouts(store, threshold=5, now=now + timedelta(days=2))["fallback"]] == ["hot1", "hot2"]
    store.close()
