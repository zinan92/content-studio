from __future__ import annotations

import json
from pathlib import Path

import pytest

from content_studio import illustrate as il

ARTICLE = "# 看懂加息\n\n那天是9月17号。\n\n前一天晚上，美联储正式加息了。\n\n第一个真正让我触动的点，是9月4号那天。\n"


def fake_runner(plan):
    def run(text: str, cwd: Path) -> None:
        assert "ian-xiaohei-illustrations" in text and "不要改" in text
        folder = cwd / il.FOLDER
        for item in plan:
            if item.get("draw", True):
                (folder / item["file"]).write_bytes(b"png")
        (folder / il.PLAN).write_text(json.dumps([{k: v for k, v in i.items() if k != "draw"} for i in plan], ensure_ascii=False), encoding="utf-8")
    return run


def test_images_go_after_their_paragraph_and_redo_replaces_them(tmp_path: Path) -> None:
    article = tmp_path / "article.md"
    article.write_text(ARTICLE, encoding="utf-8")
    plan = [{"file": "01-hike.png", "after": "前一天晚上，美联储正式", "caption": "小黑推加息的球"},
            {"file": "02-jobs.png", "after": "第一个真正让我触动", "caption": "非农数据"},
            {"file": "03-lost.png", "after": "文章里没有这一段", "caption": "x"},
            {"file": "04-none.png", "after": "那天是9月17号", "caption": "y", "draw": False}]
    r = il.illustrate(article, runner=fake_runner(plan))
    text = article.read_text(encoding="utf-8")
    assert "美联储正式加息了。\n\n![小黑推加息的球](illustrations/01-hike.png)\n\n第一个" in text
    assert text.rstrip().endswith("![非农数据](illustrations/02-jobs.png)")
    assert [s["why"] for s in r["skipped"]] == ["找不到它该放的那一段", "图没画出来"]
    assert il.state(article)["count"] == 2
    il.illustrate(article, runner=fake_runner(plan[:1]))
    assert article.read_text(encoding="utf-8").count("![") == 1 and not (tmp_path / "illustrations" / "02-jobs.png").exists()


def test_no_plan_is_an_error(tmp_path: Path) -> None:
    article = tmp_path / "article.md"
    article.write_text(ARTICLE, encoding="utf-8")
    with pytest.raises(il.IllustrateError, match="plan.json"):
        il.illustrate(article, runner=lambda text, cwd: None)


def test_codex_model_is_pinned_not_taken_from_the_machine_default(monkeypatch) -> None:
    """10/1：本机 Codex 默认模型被改成账号用不了的那个，出封面、配插图全挂。命令里写死模型。"""
    from content_studio import illustrate

    monkeypatch.setattr(illustrate, "codex_bin", lambda: "/bin/codex")
    monkeypatch.delenv("CONTENT_STUDIO_CODEX_MODEL", raising=False)
    cmd = illustrate.codex_exec("画")
    assert cmd[:4] == ["/bin/codex", "exec", "-m", "gpt-6.1-sol"] and cmd[-1] == "画"
    monkeypatch.setenv("CONTENT_STUDIO_CODEX_MODEL", "gpt-6-astra")
    assert illustrate.codex_exec("画")[3] == "gpt-6-astra"
