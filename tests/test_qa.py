from __future__ import annotations

from pathlib import Path

import pytest

from content_studio import qa
from content_studio.judge import JudgeError

OUTLINE = """# 为什么你盯盘 6 小时还跑输大盘

## 主线
盯盘时间和收益没有关系。

## 提纲
- 开头：你每天盯盘 6 小时，一年下来还是跑输大盘
- 大多数人以为盯得越久越安全，其实是在给情绪加杠杆
- 我用 AI 把盯盘换成两条提醒
- 结尾：你一天盯盘多久？
"""
MATERIAL = "备注：去年用两条提醒代替盯盘，回撤从 18% 降到 9%"


def _point(score, evidence):
    return {"score": score, "reason": "r", "evidence": evidence}


def _good():
    return {
        "pain": _point(5, "你每天盯盘 6 小时，一年下来还是跑输大盘"),
        "contrast": _point(4, "大多数人以为盯得越久越安全"),
        "delivery": _point(4, "回撤从 18% 降到 9%"),
        "thin": False, "fix": "把回撤数据提到第二句", "caution": "",
    }


def test_score_validates_evidence_and_computes_verdict() -> None:
    prompts = []

    def fake(prompt):
        prompts.append(prompt)
        if len(prompts) == 1:
            bad = _good()
            bad["delivery"] = _point(4, "学员三个月翻倍")  # not in the material
            return bad
        return _good()

    result = qa.score_topic("t", OUTLINE, MATERIAL, qa_fn=fake, guide="标准正文")
    assert "evidence 必须是提纲或素材里的原话" in prompts[1] and "标准正文" in prompts[0]
    assert result["total"] == 13 and result["verdict"] == "go" and result["guide"] == "private"


def test_no_evidence_caps_score_and_thin_material_is_reported() -> None:
    data = _good()
    data["delivery"] = _point(3, "")
    assert any("不能超过 2" in p for p in qa.validate(data, OUTLINE + MATERIAL))
    thin = {**_good(), "delivery": _point(1, ""), "thin": True}
    assert qa.validate(thin, OUTLINE + MATERIAL) == []
    result = qa.score_topic("t", OUTLINE, "", qa_fn=lambda p: {**_good(), "delivery": _point(2, ""), "thin": True}, guide=qa.RUBRIC)
    assert result["verdict"] == "thin" and result["guide"] == "rubric"
    weak = qa.score_topic("t", OUTLINE, MATERIAL, qa_fn=lambda p: {**_good(), "contrast": _point(2, "")}, guide="g")
    assert weak["verdict"] == "patch"


def test_errors_and_guide_loading(tmp_path: Path) -> None:
    with pytest.raises(qa.QAError, match="没法评"):
        qa.score_topic("t", " ", "", qa_fn=lambda p: _good(), guide="g")
    with pytest.raises(qa.QAError, match="连续 2 次"):
        qa.score_topic("t", OUTLINE, "", qa_fn=lambda p: (_ for _ in ()).throw(JudgeError("not json")), guide="g", attempts=2)
    guide = tmp_path / "SKILL.md"
    guide.write_text("---\nname: x\n---\n\n# 我的标准\n三点", encoding="utf-8")
    assert qa.load_guide(guide).startswith("# 我的标准")
    assert qa.load_guide(tmp_path / "missing.md") == qa.RUBRIC
    qa.save(tmp_path, 3, {"total": 9})
    assert qa.load(tmp_path, 3) == {"total": 9} and qa.load(tmp_path, 4) is None
