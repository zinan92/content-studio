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
