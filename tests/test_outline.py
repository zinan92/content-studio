from __future__ import annotations

from pathlib import Path

import pytest

from content_studio import outline
from content_studio.writer import WriterError

# 一分钟口播大约 250–350 字，所以这条 fixture 用真实长度，不用示意性的短句。
OPENING = (
    "你的粉丝不值钱。真正值钱的是他们反复来问你的那同一个问题，而你现在把它做成了一门课——"
    "那是这个东西最便宜的一种卖法。我说的就是你：几千到几万粉，接过广告，带过货，或者开过一门课。"
    "但每一笔都是一次性的，这轮讲完，下个月从零再来。你很清楚这不是生意，这是你给自己打的一份工。"
    "我不是来教你做自媒体的，你做号肯定比我强。但我会另外一件事：我自己写代码，"
    "我给自己做了一个内容工作台，还做了一个小程序。所以我同时站在两边——"
    "一边是有人、不知道怎么变现；一边是做得出东西、没人看见。"
)
ENDING = "接下来那句话你带走就够了。我自己做了一个工作台，天天在用。你手里有人，我手里有产品，来找我聊聊。"
GOOD = f"""# 未来的分发者

## 主线
分发权正在从平台下沉到每一个有私域流量的人。

## 开头
{OPENING}

## 结尾
{ENDING}
"""


@pytest.fixture
def workflows(tmp_path: Path) -> Path:
    """测试不读 Park 真实 vault 里的框架——他随时会改，改一次测试就开始飘。"""
    root = tmp_path / "workflows"
    root.mkdir()
    (root / outline.FRAMEWORK_FILE).write_text(
        "---\nmode: bookend\n---\n\n# 一勾式开头和结尾\n\n前三句里必须有一个真实数字。结尾禁止稀缺性和催单。\n",
        encoding="utf-8",
    )
    return root


def test_only_the_two_ends_are_required() -> None:
    assert outline.extract_outline(f"<<<ARTICLE>>>\n{GOOD}\n<<<END>>>").startswith("# 未来的分发者")
    with pytest.raises(WriterError, match="没有按格式"):
        outline.extract_outline("模型今天话很多，但没给我标记")
    with pytest.raises(WriterError, match="缺少标题"):
        outline.extract_outline(f"<<<ARTICLE>>>\n没有标题\n\n## 主线\na\n\n## 开头\n{OPENING}\n\n## 结尾\n{ENDING}\n<<<END>>>")
    # 三节都是下游真会读的：主线给开头检查和三点评分，开头给痛点和反差，结尾给交付。
    for name in outline.SECTIONS:
        with pytest.raises(WriterError, match=f"缺少「{name}」"):
            outline.extract_outline(f"<<<ARTICLE>>>\n{GOOD.replace('## ' + name, '## 别的')}\n<<<END>>>")


def test_opening_must_be_speakable_not_bullets() -> None:
    thin = GOOD.replace(OPENING, "- 抛judgment\n- 圈人\n- 讲痛点")
    with pytest.raises(WriterError, match="开头太短"):
        outline.extract_outline(f"<<<ARTICLE>>>\n{thin}\n<<<END>>>")


def test_framework_drives_the_prompt_and_the_middle_is_excluded(workflows: Path) -> None:
    text = outline.load_framework(workflows)
    prompt = outline.build_prompt({"title": "t", "memo": "砸 62 分钟那条"}, [], framework=text)
    assert "前三句里必须有一个真实数字" in prompt and "结尾禁止稀缺性和催单" in prompt
    assert "砸 62 分钟那条" in prompt
    # 中间是 Park 自己的思考，模型不许碰。
    assert "中间不要写" in prompt and "不写中间正文" in prompt
    assert "不要编造 Park 的经历" in prompt
    adjusted = outline.build_prompt({"title": "t"}, [], framework="F", adjustments=["前 15 秒说结论"])
    assert "最近一次每周复盘" in adjusted and "前 15 秒说结论" in adjusted
    assert "每周复盘" not in outline.build_prompt({"title": "t"}, [], framework="F")


def test_missing_framework_says_which_file(tmp_path: Path) -> None:
    """框架在 Obsidian 里。缺了要指名道姓，不能退回旧提示词假装没事。"""
    with pytest.raises(WriterError, match="找不到框架文件"):
        outline.load_framework(tmp_path)
    (tmp_path / outline.FRAMEWORK_FILE).write_text("---\nmode: bookend\n---\n", encoding="utf-8")
    with pytest.raises(WriterError, match="是空的"):
        outline.load_framework(tmp_path)


def test_write_and_read_back(tmp_path: Path, workflows: Path) -> None:
    calls = []

    def fake(prompt):
        calls.append(prompt)
        return "乱写" if len(calls) == 1 else f"<<<ARTICLE>>>\n{GOOD}\n<<<END>>>"

    result = outline.write_outline({"id": 3, "title": "t", "note_paths": []},
                                   vault_raw=str(tmp_path), drafts_dir=tmp_path, write_fn=fake, workflows=workflows)
    assert "上一次输出有问题" in calls[1]
    assert result["outline_path"].endswith(outline.FILENAME) and result["mode_label"] == outline.LABEL
    data = outline.read_outline({"outline_path": result["outline_path"]})
    assert data["markdown"].startswith("# 未来的分发者") and data["topic_id"] == 3


def test_old_drafts_still_open(tmp_path: Path) -> None:
    """以前写的 outline.md / outline-restructured.md 还得能打开。"""
    for name in ("outline.md", "outline-restructured.md"):
        legacy = tmp_path / name
        legacy.write_text("# 老稿子\n\n## 主线\n一句话。\n", encoding="utf-8")
        assert outline.read_outline({"outline_path": str(legacy)})["markdown"].startswith("# 老稿子")
    assert outline.read_outline({}) is None
    assert outline.read_outline({"outline_path": str(tmp_path / "没有这个.md")}) is None
