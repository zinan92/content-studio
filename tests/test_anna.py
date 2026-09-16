from __future__ import annotations

from pathlib import Path

import pytest

from content_studio import anna


def test_parse_reply_splits_actions_from_prose() -> None:
    text = "这条素材太薄。\n\n[动作] 存进备注：补一张收益截图\n[动作] 重写提纲\n[动作] 拿来做：\n[动作] 重写提纲\n[动作] 发布"
    parsed = anna.parse_reply(text)
    assert parsed["text"] == "这条素材太薄。\n\n[动作] 发布"
    assert parsed["actions"] == [
        {"kind": "memo", "label": "存进备注", "arg": "补一张收益截图"},
        {"kind": "outline", "label": "重写提纲", "arg": ""},
    ]


def test_soul_reads_role_knowledge_and_skill(tmp_path: Path) -> None:
    role = tmp_path / "content_editor Anna.md"
    role.write_text("---\nx: 1\n---\n# Anna\n第一目标：让对的人看得更久。", encoding="utf-8")
    know = tmp_path / "content_editor Anna" / "knowledge"
    know.mkdir(parents=True)
    (know / "定位.md").write_text("吸引想跟你学的人", encoding="utf-8")
    (know / "课件.pdf").write_bytes(b"%PDF")
    skill = tmp_path / "SKILL.md"
    skill.write_text("---\nname: qa\n---\n三点评分", encoding="utf-8")
    soul = anna.load_soul(role, skill)
    assert soul["text"].startswith("# Anna") and "吸引想跟你学的人" in soul["text"] and "三点评分" in soul["text"]
    assert [Path(p).name for p in soul["sources"]] == ["content_editor Anna.md", "定位.md", "SKILL.md"]
    assert "x: 1" not in soul["text"]
    fallback = anna.load_soul(tmp_path / "missing.md", tmp_path / "missing-skill.md")
    assert "让对的人看得更久" in fallback["text"] and fallback["sources"] == []


def test_run_turn_composes_context_and_resumes_session() -> None:
    seen = []

    def fake(system: str, user: str, session_id: str | None) -> dict:
        seen.append((system, user, session_id))
        return {"text": "先补交付。\n[动作] 按三点评分", "session_id": "s-2"}

    reply = anna.run_turn(scope="work:3", scope_label="这条视频", context="## 拍摄提纲\n- 开头", message="能拍吗", session_id="s-1", turn_fn=fake, soul={"text": "# Anna", "sources": []})
    system, user, sid = seen[0]
    assert system.startswith("# Anna") and "[动作] 存进备注" in system and sid == "s-1"
    assert user.startswith('<工作台 页面="这条视频">') and "## 拍摄提纲" in user and user.endswith("Park：能拍吗")
    assert reply["text"] == "先补交付。" and reply["actions"][0]["kind"] == "qa" and reply["session_id"] == "s-2"


def test_context_is_truncated_and_cli_errors_are_explained(tmp_path: Path) -> None:
    long = anna.compose_user_message("x" * (anna.MAX_CONTEXT_CHARS + 10), "hi", scope_label="进项")
    assert "已截断" in long and len(long) < anna.MAX_CONTEXT_CHARS + 200
    with pytest.raises(anna.AnnaError, match="找不到本机的 Claude 命令"):
        anna.cli_turn("s", "u", None, command=str(tmp_path / "no-such-binary"))
    script = tmp_path / "fake.sh"
    script.write_text('#!/bin/sh\necho \'{"result": "好的", "session_id": "abc"}\'\n', encoding="utf-8")
    script.chmod(0o755)
    assert anna.cli_turn("s", "u", None, command=str(script)) == {"text": "好的", "session_id": "abc"}
    login = tmp_path / "login.sh"
    login.write_text('#!/bin/sh\necho "please log in" >&2\nexit 1\n', encoding="utf-8")
    login.chmod(0o755)
    with pytest.raises(anna.AnnaLoginError):
        anna.cli_turn("s", "u", None, command=str(login))
