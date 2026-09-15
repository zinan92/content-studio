from __future__ import annotations

from datetime import date, datetime, timezone
import os
from pathlib import Path

import pytest

from content_studio import briefing
from content_studio.judge import JudgeError, JudgeLoginError

DAY = date(2026, 9, 14)


def _vault(tmp_path: Path) -> Path:
    (tmp_path / "006_ai daily newsletter").mkdir(parents=True)
    (tmp_path / "006_ai daily newsletter" / "26-09-14.md").write_text("- **A** | [Codex 新功能](https://x.com/1)\n", encoding="utf-8")
    (tmp_path / "009_morning brief").mkdir()
    (tmp_path / "009_morning brief" / "2026-09-14.html").write_text("<style>x{}</style><h1>晨报</h1><p>黄金</p>", encoding="utf-8")
    (tmp_path / "Clippings").mkdir()
    (tmp_path / "Clippings" / "c.md").write_text("---\ntitle: 剪藏\nsource: https://y.com/2\ncreated: 2026-09-13\n---\n正文", encoding="utf-8")
    (tmp_path / "003_park原始输出").mkdir()
    (tmp_path / "003_park原始输出" / "r.md").write_text("# 原始输出\n想法", encoding="utf-8")
    _pin_mtimes(tmp_path)
    return tmp_path


def _pin_mtimes(root: Path) -> None:
    # Notes written "today" must look like they existed on DAY, whatever day the suite runs.
    stamp = datetime(2026, 9, 14, 9, 0).timestamp()
    for path in root.rglob("*"):
        os.utime(path, (stamp, stamp))


def _good(inputs):
    return {
        "known": ["a"], "unknown": ["b"],
        "reads": [{"title": "t", "why": "w", "source": {"url": "https://x.com/1"}}],
        "videos": [
            {"title": "v", "hook": "h", "claim": "c", "outline": ["1", "2", "3"], "sources": [{"path": "003_park原始输出/r.md"}],
             "why_today": "y", "effort": "低", "caution": "", "primary": True},
            {"title": "v2", "hook": "h", "claim": "c", "outline": ["1", "2", "3"], "sources": [{"url": "https://y.com/2", "title": "剪藏"}],
             "why_today": "y", "effort": "中", "caution": "", "primary": False},
        ],
        "prep": "p",
    }


def test_inputs_collect_dailies_notes_and_allowed_sources(tmp_path: Path) -> None:
    _vault(tmp_path)
    (tmp_path / "003_park原始输出" / "已发 老观点.md").write_text("# 老观点\n讲过了", encoding="utf-8")
    _pin_mtimes(tmp_path)
    inputs = briefing.gather_inputs(str(tmp_path), DAY, own_videos=[{"title": "我的", "likes": 10, "multiple": 1.2}],
                                    existing_topics=[{"title": "为什么用了 AI 更累", "status": "published"}], adjustments=["开头直接说结论"],
                                    breakouts=[{"title": "对标爆款标题", "account_nickname": "千雪", "multiple": 12.0}])
    assert [d["label"] for d in inputs["dailies"]] == ["AI 日报", "晨报"]
    assert "黄金" in inputs["dailies"][1]["text"] and "x{}" not in inputs["dailies"][1]["text"]
    assert {n["path"] for n in inputs["notes"]} == {"Clippings/c.md", "003_park原始输出/r.md", "003_park原始输出/已发 老观点.md"}
    assert "https://x.com/1" in inputs["allowed_urls"] and "https://y.com/2" in inputs["allowed_urls"]
    prompt = briefing.build_prompt(inputs)
    assert "千雪｜对标爆款标题｜12.0×" in prompt
    assert "AI + 金融" in prompt and "我的" in prompt and "003_park原始输出/r.md" in prompt
    assert "- 开头直接说结论" in prompt
    assert "[原始输出·已发] 老观点" in prompt and "为什么用了 AI 更累（已发出）" in prompt and "不要重复推荐" in prompt


def test_generate_fills_source_titles_and_validates(tmp_path: Path) -> None:
    inputs = briefing.gather_inputs(str(_vault(tmp_path)), DAY)
    result = briefing.generate_briefing(inputs, brief_fn=lambda p: _good(inputs), now=datetime(2026, 9, 14, tzinfo=timezone.utc))
    assert result["videos"][0]["sources"][0]["title"] == "原始输出"
    assert result["day"] == "2026-09-14"


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda d: d["videos"][0]["sources"].__setitem__(0, {"path": "003_park原始输出/编的.md"}), "材料里没有"),
        (lambda d: d["videos"][1].__setitem__("primary", True), "恰好 1 条"),
        (lambda d: d["videos"][0].__setitem__("outline", ["1"]), "3–5"),
        (lambda d: d["reads"][0].__setitem__("source", {"url": "https://fake"}), "reads[0].source"),
        (lambda d: d["videos"][0].__setitem__("effort", "很低"), "effort"),
    ],
)
def test_validation_rejects_invented_or_malformed_output(tmp_path: Path, mutate, message) -> None:
    inputs = briefing.gather_inputs(str(_vault(tmp_path)), DAY)
    data = _good(inputs)
    mutate(data)
    assert any(message in p for p in briefing.validate(data, inputs))


def test_retry_then_fail_and_login_passthrough(tmp_path: Path) -> None:
    inputs = briefing.gather_inputs(str(_vault(tmp_path)), DAY)
    prompts = []

    def flaky(prompt):
        prompts.append(prompt)
        if len(prompts) == 1:
            raise JudgeError("not json")
        return _good(inputs)

    briefing.generate_briefing(inputs, brief_fn=flaky)
    assert "上一次输出没有通过校验：not json" in prompts[1]
    with pytest.raises(briefing.BriefingError, match="连续 3 次"):
        briefing.generate_briefing(inputs, brief_fn=lambda p: {"videos": []})

    def logged_out(prompt):
        raise JudgeLoginError("登录已过期")

    with pytest.raises(JudgeLoginError):
        briefing.generate_briefing(inputs, brief_fn=logged_out)


def test_empty_material_is_explained(tmp_path: Path) -> None:
    (tmp_path / "Clippings").mkdir()
    inputs = briefing.gather_inputs(str(tmp_path), DAY)
    with pytest.raises(briefing.BriefingError, match="没有可统筹"):
        briefing.generate_briefing(inputs, brief_fn=lambda p: {})
