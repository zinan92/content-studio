from __future__ import annotations

from pathlib import Path

import pytest

from content_studio import copypack


def _good():
    return {
        "douyin": {"title": "为什么很多人感觉不到 AI", "body": "只看今天的射程。", "tags": ["AI", "认知"]},
        "channels": {"title": "看不到AI的人", "body": "b", "tags": ["AI"]},
        "xiaohongshu": {"title": "为什么你感觉不到AI", "body": "b", "tags": ["AI"]},
        "bilibili": {"title": "t", "body": "b", "tags": ["AI"]},
        "youtube": {"title": "t", "body": "b", "tags": ["AI"]},
        "x": {"title": "", "body": "大多数人感觉不到 AI，是因为只看它今天能打多远。", "tags": ["AI"]},
        "yanxishi": {"title": "t", "body": "一句话摘要", "tags": []},
    }


def test_measure_limits_and_x_weighting() -> None:
    assert copypack.measure("douyin", {"title": "字" * 31, "body": "b", "tags": []})[0].startswith("抖音标题 31")
    assert copypack.measure("xiaohongshu", {"title": "t", "body": "b", "tags": ["#AI"]})
    assert copypack.x_length("中文ab") == 6
    assert copypack.measure("x", {"title": "", "body": "中" * 141, "tags": []})
    assert copypack.measure("x", {"title": "有标题", "body": "b", "tags": []})
    assert copypack.measure("douyin", _good()["douyin"]) == []


def test_generate_retries_with_length_errors_then_succeeds(tmp_path: Path) -> None:
    calls = []

    def fake(prompt):
        calls.append(prompt)
        data = _good()
        if len(calls) == 1:
            data["channels"]["title"] = "这是一个明显超过十六个字的视频号标题所以会被拦下"
        return data

    result = copypack.generate_copy({"title": "t"}, "提纲", copy_fn=fake)
    # Only the three platforms Park publishes to are generated; the others are not even asked for.
    assert "视频号标题" in calls[1] and set(result) == {"douyin", "channels", "yanxishi"}
    assert "xiaohongshu" not in calls[0] and "douyin" in calls[0]
    path = copypack.save_copy(tmp_path, 1, result)
    data = copypack.read_copy(tmp_path, 1)
    assert path.is_file() and data["checks"]["douyin"] == []


def test_generate_requires_basis_and_gives_up() -> None:
    with pytest.raises(copypack.CopyError, match="先写"):
        copypack.generate_copy({"title": "t"}, " ", copy_fn=lambda p: {})
    with pytest.raises(copypack.CopyError, match="连续 3 次"):
        copypack.generate_copy({"title": "t"}, "提纲", copy_fn=lambda p: {"douyin": {}})
