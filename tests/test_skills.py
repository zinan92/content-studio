from __future__ import annotations

import json
from pathlib import Path

from content_studio.skills import REGISTRY_PATH, load_skills

REPO = Path(__file__).resolve().parents[1]


def test_registry_is_complete_and_honest() -> None:
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    names = [s["name"] for s in data["skills"]]
    assert len(names) == len(set(names))
    for skill in data["skills"]:
        assert skill["title"] and skill["use"] and skill["invoke"]
        if skill["repo"]:
            assert skill["repo"].startswith("https://github.com/")
        if skill["own"]:
            assert skill["author"] == "Park" and "zinan92" in skill["repo"]
    assert {"khazix-writer", "ask-park-video", "dbs-content", "video-shotcraft"} <= set(names)


def test_local_detection_reads_folded_description(tmp_path: Path) -> None:
    skill = tmp_path / "khazix-writer"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: khazix-writer\ndescription: |\n  公众号长文写作\n  第二行\n---\n正文", encoding="utf-8")
    other = tmp_path / "dbs-content"
    other.mkdir()
    (other / "SKILL.md").write_text("---\nname: dbs-content\ndescription: 诊断内容\n---\n", encoding="utf-8")
    result = load_skills(roots=(tmp_path,))
    by_name = {s["name"]: s for s in result["skills"]}
    assert by_name["khazix-writer"]["installed"] and by_name["khazix-writer"]["description"] == "公众号长文写作 第二行"
    assert by_name["dbs-content"]["description"] == "诊断内容"
    assert by_name["video-shotcraft"]["installed"] is False
    assert by_name["daily-news-caster"]["source_known"] is False


def test_no_third_party_skill_files_are_vendored() -> None:
    ignored = {".git", ".venv", "node_modules"}
    found = [p for p in REPO.rglob("SKILL.md") if not ignored & set(p.parts)]
    assert found == []


def test_edits_go_to_the_user_file_and_the_seed_stays_untouched(tmp_path: Path) -> None:
    import pytest
    from content_studio import skills

    user = tmp_path / "skills.json"
    seed_before = REGISTRY_PATH.read_text(encoding="utf-8")
    assert skills.load_skills(user=user, roots=(tmp_path,))["editable"] is True
    skills.upsert({"name": "my-frame", "title": "我的框架", "stage": "plan", "use": "写提纲用"}, user=user)
    assert REGISTRY_PATH.read_text(encoding="utf-8") == seed_before
    names = [s["name"] for s in skills.load_skills(user=user, roots=(tmp_path,))["skills"]]
    assert "my-frame" in names and "khazix-writer" in names  # the seed was copied, then added to
    skills.upsert({"name": "my-frame2", "title": "改名", "stage": "write", "use": "x"}, user=user, previous="my-frame")
    names = [s["name"] for s in skills.load_skills(user=user, roots=(tmp_path,))["skills"]]
    assert "my-frame" not in names and "my-frame2" in names
    with pytest.raises(skills.SkillsError):
        skills.upsert({"name": "bad name!", "stage": "plan", "use": "x"}, user=user)
    with pytest.raises(skills.SkillsError):
        skills.upsert({"name": "x", "stage": "nope", "use": "x"}, user=user)
    with pytest.raises(skills.SkillsError):
        skills.upsert({"name": "x", "stage": "plan", "use": "x", "repo": "javascript:alert(1)"}, user=user)
    with pytest.raises(skills.SkillsError):
        skills.upsert({"name": "khazix-writer", "stage": "plan", "use": "x"}, user=user, previous="my-frame2")
    assert skills.remove("my-frame2", user=user) and not skills.remove("my-frame2", user=user)


def test_doc_reads_only_listed_markdown_in_skill_folders_or_annas_folder(tmp_path: Path, monkeypatch) -> None:
    import pytest
    from content_studio import skills

    monkeypatch.setenv("HOME", str(tmp_path))
    role_dir = tmp_path / "vault" / "001_role" / "content_editor Anna"
    (role_dir / "workflows").mkdir(parents=True)
    (role_dir / "workflows" / "frame.md").write_text("---\nname: f\n---\n# 框架\n正文", encoding="utf-8")
    monkeypatch.setenv(skills.ANNA_ROLE_ENV, str(role_dir.with_suffix(".md")))
    (tmp_path / "vault" / "_secrets").mkdir()
    (tmp_path / "vault" / "_secrets" / "k.md").write_text("不该读到", encoding="utf-8")
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "n.md").write_text("家目录别处也不读", encoding="utf-8")
    user = tmp_path / "skills.json"
    skills.upsert({"name": "frame", "stage": "plan", "use": "x", "path": "~/vault/001_role/content_editor Anna/workflows/frame.md"}, user=user)
    skills.upsert({"name": "secret", "stage": "plan", "use": "x", "path": "~/vault/_secrets/k.md"}, user=user)
    skills.upsert({"name": "elsewhere", "stage": "plan", "use": "x", "path": "~/notes/n.md"}, user=user)
    assert "正文" in skills.read_doc("frame", user=user, roots=(tmp_path / "skills",))["body"]
    for name in ("secret", "elsewhere", "not-listed"):
        with pytest.raises(skills.SkillsError):
            skills.read_doc(name, user=user, roots=(tmp_path / "skills",))
