from __future__ import annotations

from pathlib import Path

import pytest

from content_studio import outline
from content_studio.writer import WriterError

GOOD = """# 为什么很多人看不到 AI 的影响力

## 主线
只看当下能力的人，会错过背后的迭代速度。

## 提纲
- 开头：大多数人不是不懂 AI，是只看眼前那门炮
- 一门炮：只看当下能力
- 背后的体系：迭代速度才是重点
- 今天的反驳：有人说 AI 被高估
- 结尾：往后看一眼，你身边有这样的人吗

## 不要讲过头
- 历史细节来自节目转述
"""


def test_extract_outline_checks_structure() -> None:
    assert outline.extract_outline(f"<<<ARTICLE>>>\n{GOOD}\n<<<END>>>").startswith("# 为什么")
    with pytest.raises(WriterError, match="提纲"):
        outline.extract_outline(f"<<<ARTICLE>>>\n{GOOD.replace('## 提纲', '## 要点')}\n<<<END>>>")
    with pytest.raises(WriterError, match="4–8 条"):
        outline.extract_outline(f"<<<ARTICLE>>>\n{GOOD.replace('- 今天的反驳：有人说 AI 被高估\n', '').replace('- 一门炮：只看当下能力\n', '')}\n<<<END>>>")


def test_prompt_carries_constraints_and_memo(tmp_path: Path) -> None:
    prompt = outline.build_prompt({"title": "t", "memo": "Hook：累的不是活"}, [])
    assert "14–26 秒" in prompt and "删掉这一条" in prompt and "Hook：累的不是活" in prompt
    assert "每周复盘" not in prompt
    adjusted = outline.build_prompt({"title": "t"}, [], adjustments=["前 15 秒说结论", "跑题控制在 8% 以下"])
    assert "最近一次每周复盘" in adjusted and "跑题控制在 8% 以下" in adjusted


def test_write_outline_saves_and_reads_back(tmp_path: Path) -> None:
    calls = []

    def fake(prompt):
        calls.append(prompt)
        return "乱写" if len(calls) == 1 else f"<<<ARTICLE>>>\n{GOOD}\n<<<END>>>"

    result = outline.write_outline({"id": 3, "title": "t", "note_paths": []}, vault_raw=str(tmp_path), drafts_dir=tmp_path, write_fn=fake)
    assert "上一次输出有问题" in calls[1]
    data = outline.read_outline({"outline_path": result["outline_path"]})
    assert data["markdown"].startswith("# 为什么") and data["topic_id"] == 3
