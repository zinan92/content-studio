from __future__ import annotations

from pathlib import Path

import pytest

from content_studio import writer
from content_studio.judge import JudgeLoginError
from content_studio.store import StudioStore

BODY = "# 标题\n\n" + "正文内容。" * 60


def _topic(**kw):
    base = {"id": 7, "title": "选题", "memo": None, "note_paths": []}
    base.update(kw)
    return base


def test_extract_article_requires_block_title_and_no_foreign_signature() -> None:
    assert writer.extract_article(f"前言\n<<<ARTICLE>>>\n{BODY}\n<<<END>>>").startswith("# 标题")
    with pytest.raises(writer.WriterError, match="格式"):
        writer.extract_article(BODY)
    with pytest.raises(writer.WriterError, match="太短"):
        writer.extract_article("<<<ARTICLE>>>\n# 短\n<<<END>>>")
    with pytest.raises(writer.WriterError, match="卡兹克"):
        writer.extract_article(f"<<<ARTICLE>>>\n{BODY}\n> / 作者：卡兹克\n<<<END>>>")


def test_retry_passes_the_error_back_then_saves_draft(tmp_path: Path) -> None:
    prompts = []

    def fake(prompt):
        prompts.append(prompt)
        return "没按格式" if len(prompts) == 1 else f"<<<ARTICLE>>>\n{BODY}\n<<<END>>>"

    result = writer.write_article(_topic(), vault_raw=str(tmp_path), drafts_dir=tmp_path / "d", write_fn=fake)
    assert "上一次输出有问题" in prompts[1]
    assert Path(result["article_path"]).read_text(encoding="utf-8").startswith("# 标题")
    assert writer.read_draft({"article_path": result["article_path"]})["skill"] == "khazix-writer"


def test_gives_up_after_attempts_and_login_errors_are_not_retried(tmp_path: Path) -> None:
    with pytest.raises(writer.WriterError, match="连续 2 次"):
        writer.write_article(_topic(), vault_raw=str(tmp_path), drafts_dir=tmp_path, write_fn=lambda p: "x")
    calls = []

    def logged_out(prompt):
        calls.append(1)
        raise JudgeLoginError("登录已过期")

    with pytest.raises(JudgeLoginError):
        writer.write_article(_topic(), vault_raw=str(tmp_path), drafts_dir=tmp_path, write_fn=logged_out)
    assert len(calls) == 1


def test_prompt_uses_sources_and_keeps_park_as_author(tmp_path: Path) -> None:
    (tmp_path / "002_clippings").mkdir()
    (tmp_path / "002_clippings" / "a.md").write_text("---\ntitle: 剪藏\nsource: https://x.com/1\n---\n别人的观点", encoding="utf-8")
    sources = writer.gather_sources(str(tmp_path), ["002_clippings/a.md", "_secrets/x.md"])
    prompt = writer.build_prompt(_topic(memo="写给小白"), sources)
    assert "khazix-writer" in prompt and "作者是 Park" in prompt and "别人的观点" in prompt and "写给小白" in prompt
    assert len(sources) == 1


def test_cli_write_reports_missing_command() -> None:
    with pytest.raises(writer.WriterError, match="找不到"):
        writer.cli_write("x", command="definitely-not-a-command-xyz")


def test_interrupted_writes_are_recovered(tmp_path: Path) -> None:
    store = StudioStore(tmp_path / "s.sqlite3")
    topic = store.create_topic("t")
    store.update_topic(topic["id"], write_state="running")
    assert store.recover_interrupted_writes() == 1
    assert store.topic(topic["id"])["write_state"] == "failed"
    store.close()
