from __future__ import annotations

from pathlib import Path

import pytest

from content_studio import outline
from content_studio.writer import WriterError

GOOD = """# 为什么很多人看不到 AI 的影响力

## 主线
只看当下能力的人，会错过背后的迭代速度。

大多数人不是不懂 AI，是只看眼前那门炮。你上周还在用它改错别字，别人已经用它改了收入结构。
差距不在智商，在你把它当什么——当成一个工具，还是当成一条还在加速的曲线。

表面上看是能力问题。但仅靠能力解释不完一件事：同样的模型，有人一年换了行业，有人还在改错别字。
更关键的一层是，你把它放在自己流程的哪个位置。

我自己的判断是，往后看一眼就够了：你身边已经有这样的人了吗？如果有，今天就找他聊二十分钟。
"""


@pytest.fixture
def workflows(tmp_path: Path) -> Path:
    """测试不读 Park 真实 vault 里的框架——他随时会改，改一次测试就开始飘。"""
    root = tmp_path / "workflows"
    root.mkdir()
    for mode, spec in outline.MODES.items():
        (root / spec["file"]).write_text(
            f"---\nmode: {mode}\n---\n\n# {spec['label']}\n\n{spec['hint']}。第一分钟不摆结果。\n",
            encoding="utf-8",
        )
    return root


def test_extract_outline_needs_title_thesis_and_body() -> None:
    assert outline.extract_outline(f"<<<ARTICLE>>>\n{GOOD}\n<<<END>>>").startswith("# 为什么")
    with pytest.raises(WriterError, match="没有按格式"):
        outline.extract_outline("模型今天话很多，但没给我标记")
    with pytest.raises(WriterError, match="缺少标题"):
        outline.extract_outline(f"<<<ARTICLE>>>\n没有标题\n\n## 主线\na\n\n{'正文' * 200}\n<<<END>>>")
    # 主线 is the one section downstream really reads: 开头检查 and 三点评分 both parse it.
    with pytest.raises(WriterError, match="主线"):
        outline.extract_outline(f"<<<ARTICLE>>>\n{GOOD.replace('## 主线', '## 一句话')}\n<<<END>>>")
    with pytest.raises(WriterError, match="只有主线没有正文"):
        outline.extract_outline("<<<ARTICLE>>>\n# 标题\n\n## 主线\n只看当下能力的人会错过迭代速度。\n<<<END>>>")


def test_shape_of_the_body_is_not_checked_here(workflows: Path) -> None:
    """两版的形状本来就不一样；在代码里加结构检查等于把框架抄第二遍。"""
    prose = "# 标题\n\n## 主线\na\n\n" + "他昨天突然想到一件事，于是把整条推理又走了一遍。" * 20
    assert outline.extract_outline(f"<<<ARTICLE>>>\n{prose}\n<<<END>>>").startswith("# 标题")


def test_framework_drives_the_prompt(workflows: Path) -> None:
    for mode, spec in outline.MODES.items():
        text = outline.load_framework(mode, workflows)
        prompt = outline.build_prompt({"title": "t", "memo": "Hook：累的不是活"}, [], mode=mode, framework=text)
        assert spec["hint"] in prompt and spec["label"] in prompt
        assert "Hook：累的不是活" in prompt
        assert "不要写编辑说明" in prompt and "不要编造 Park 的经历" in prompt
    adjusted = outline.build_prompt({"title": "t"}, [], framework="F", adjustments=["前 15 秒说结论"])
    assert "最近一次每周复盘" in adjusted and "前 15 秒说结论" in adjusted
    assert "每周复盘" not in outline.build_prompt({"title": "t"}, [], framework="F")


def test_missing_framework_says_which_file_and_where(tmp_path: Path) -> None:
    """框架文件在 Obsidian 里。缺了要指名道姓，不能退回旧提示词假装没事。"""
    with pytest.raises(WriterError, match="找不到重构版框架"):
        outline.load_framework("restructured", tmp_path)
    with pytest.raises(WriterError, match="没有「乱填」这个版本"):
        outline.load_framework("乱填", tmp_path)
    (tmp_path / outline.MODES["faithful"]["file"]).write_text("---\nmode: faithful\n---\n", encoding="utf-8")
    with pytest.raises(WriterError, match="是空的"):
        outline.load_framework("faithful", tmp_path)


def test_two_versions_sit_side_by_side(tmp_path: Path, workflows: Path) -> None:
    """Park 要先都用一遍才知道接受哪个，所以写第二版不能盖掉第一版。"""
    calls = []

    def fake(prompt):
        calls.append(prompt)
        return "乱写" if len(calls) == 1 else f"<<<ARTICLE>>>\n{GOOD}\n<<<END>>>"

    topic = {"id": 3, "title": "t", "note_paths": []}
    a = outline.write_outline(topic, vault_raw=str(tmp_path), drafts_dir=tmp_path, write_fn=fake, workflows=workflows)
    assert "上一次输出有问题" in calls[1]
    assert a["mode"] == outline.DEFAULT_MODE == "restructured" and a["outline_path"].endswith("outline-restructured.md")

    b = outline.write_outline(topic, vault_raw=str(tmp_path), mode="faithful", drafts_dir=tmp_path, write_fn=fake, workflows=workflows)
    assert Path(a["outline_path"]).is_file() and Path(b["outline_path"]).is_file()

    current = {"outline_path": b["outline_path"], "outline_mode": "faithful"}
    assert outline.read_outline(current)["mode"] == "faithful"
    assert outline.read_outline(current, "restructured")["mode"] == "restructured"
    assert [v["mode"] for v in outline.available(current)] == ["restructured", "faithful"]
    assert outline.read_outline({}) is None and outline.available({}) == []


def test_old_outlines_still_open(tmp_path: Path) -> None:
    """换版本不该让以前写的提纲消失——老文件叫 outline.md，没有 mode 字段。"""
    legacy = tmp_path / "outline.md"
    legacy.write_text(GOOD, encoding="utf-8")
    data = outline.read_outline({"outline_path": str(legacy)})
    assert data["markdown"].startswith("# 为什么") and data.get("mode") is None
    assert outline.read_outline({"outline_path": str(legacy)}, "faithful") is None
