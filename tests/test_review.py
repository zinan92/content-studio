from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from content_studio import review

NOW = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)


def _inputs():
    own = [
        {"video_id": "a", "title": "AI越强", "published_at": (NOW - timedelta(days=6)).isoformat(), "likes": 1729, "collects": 900, "is_image_post": 0},
        {"video_id": "b", "title": "盯盘", "published_at": (NOW - timedelta(days=5)).isoformat(), "likes": 338, "collects": 50, "is_image_post": 0},
        {"video_id": "old", "title": "旧", "published_at": (NOW - timedelta(days=30)).isoformat(), "likes": 5, "is_image_post": 0},
    ]
    reports = {"a": {"thesis": {"text": "主线"}, "why_boom": [{"text": "开头直给"}], "why_scatter": [{"text": "中段推荐别人"}], "drift": {"share": 0.2}}}
    breakouts = [{"video_id": "x", "title": "对标爆款", "account_nickname": "千雪", "multiple": 12.0, "published_at": (NOW - timedelta(days=2)).isoformat()}]
    topics = [{"title": "已发选题", "published_at": (NOW - timedelta(days=1)).isoformat()}, {"title": "没发", "published_at": None}]
    return review.gather_inputs(own_videos=own, median_likes=266, creator={"a": {"fan_increment": 430, "avg_view_second": 25.3, "bounce_rate_2s": 0.38}},
                                reports=reports, topics=topics, breakouts=breakouts, now=NOW)


def _good():
    return {"summary": "s", "wins": [{"text": "6.5 倍", "video_ids": ["a"]}], "problems": [{"text": "盯盘开头慢", "video_ids": ["b"]}],
            "patterns": ["样本不足"], "next_week": ["一", "二"], "experiment": {"hypothesis": "h", "how": "w", "measure": "m"}}


def test_inputs_keep_last_week_with_computed_numbers() -> None:
    inputs = _inputs()
    assert [v["video_id"] for v in inputs["videos"]] == ["a", "b"]
    a = inputs["videos"][0]
    assert a["multiple"] == 6.5 and a["fans"] == 430 and a["avg_watch_seconds"] == 25 and a["report"]["why_scatter"] == ["中段推荐别人"]
    assert inputs["topics_done"] == ["已发选题"] and inputs["breakouts"][0]["account"] == "千雪"
    prompt = review.build_prompt(inputs)
    assert "id a｜AI越强" in prompt and "中段推荐别人" in prompt and "千雪" in prompt


def test_generate_attaches_titles_and_rejects_unknown_ids() -> None:
    inputs = _inputs()
    result = review.generate_review(inputs, review_fn=lambda p: _good(), now=NOW)
    assert result["wins"][0]["videos"] == [{"video_id": "a", "title": "AI越强"}] and result["week"] == "2026-W38"
    bad = _good()
    bad["wins"][0]["video_ids"] = ["invented"]
    assert any("video_ids" in p for p in review.validate(bad, inputs))
    with pytest.raises(review.ReviewError, match="连续 3 次"):
        review.generate_review(inputs, review_fn=lambda p: bad)


def test_empty_week_is_explained() -> None:
    inputs = review.gather_inputs(own_videos=[], median_likes=None, creator={}, reports={}, topics=[], breakouts=[], now=NOW)
    with pytest.raises(review.ReviewError, match="没有发视频"):
        review.generate_review(inputs, review_fn=lambda p: _good())
