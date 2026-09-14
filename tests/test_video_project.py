from __future__ import annotations

import json
from pathlib import Path

import pytest

from content_studio import video_project as vp

PRESETS = {"media": "park-talking-head-4x3-v1", "audio": "park-voice-v1", "caption_style": "park-caption-4x3-v1", "caption_layout": "park-caption-layout-v1"}


def _touch(base: Path, rel: str, text: str = "x") -> None:
    path = base / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _project(root: Path, name: str, **contract) -> Path:
    base = root / name
    base.mkdir(parents=True)
    data = {"workflow": "ask-park-video/v1", "presets": PRESETS, "step_status": {"2": "pass", "3": "pass"}, "approvals": {"hook": None, "visual_spec": None, "final": None}}
    data.update(contract)
    (base / "project.json").write_text(json.dumps(data), encoding="utf-8")
    return base


def test_step_4_worktable_ready_points_to_h1(tmp_path: Path) -> None:
    base = _project(tmp_path, "p")
    for rel in ("subtitles/source.srt", "subtitles/transcript.sentences.json", "analysis/worktable.html"):
        _touch(base, rel)
    info = vp.inspect(tmp_path.resolve(), "p")
    assert info["current_step"] == 5 and info["gate"]["key"] == "H1" and "worktable" in info["gate"]["title"]
    assert [s["state"] for s in info["stages"]] == ["done", "current", "todo", "todo", "todo"]
    _touch(base, "analysis/worktable.json", "{}")
    assert "批准" in vp.inspect(tmp_path.resolve(), "p")["gate"]["title"]


def test_status_label_without_artifact_does_not_count(tmp_path: Path) -> None:
    _project(tmp_path, "p", step_status={"2": "pass", "3": "pass", "4": "pass", "9": "pass"})
    info = vp.inspect(tmp_path.resolve(), "p")
    assert info["current_step"] == 4 and info["gate"] is None


def test_missing_preset_blocks_step_1(tmp_path: Path) -> None:
    _project(tmp_path, "p", presets={"media": "x"})
    info = vp.inspect(tmp_path.resolve(), "p")
    assert info["current_step"] == 1 and "缺 preset" in info["steps"][0]["evidence"]


def test_full_delivery_and_h3_gate(tmp_path: Path) -> None:
    base = _project(tmp_path, "p", approvals={"hook": "2026-09-14", "visual_spec": "2026-09-14", "final": None}, step_status={"2": "pass", "3": "pass", "12": "pass"})
    for rel in ("subtitles/source.srt", "subtitles/transcript.sentences.json", "analysis/worktable.html", "analysis/worktable.json",
                "analysis/content-map.md", "part-a-hook/individual/h1.mp4", "part-a-hook/edit.json", "part-a-hook/subtitles.srt",
                "part-a-hook/video.mp4", "part-b-body/clean-master.mp4", "part-b-body/edit.json", "part-b-body/visual-plan.json",
                "part-b-body/video.mp4", "final/video.mp4"):
        _touch(base, rel)
    for rel in ("part-a-hook/qa.json", "part-b-body/qa.json", "final/qa.json"):
        _touch(base, rel, json.dumps({"status": "pass"}))
    info = vp.inspect(tmp_path.resolve(), "p")
    assert info["current_step"] == 14 and info["gate"]["key"] == "H3"
    data = json.loads((base / "project.json").read_text())
    data["approvals"]["final"] = "ok"
    (base / "project.json").write_text(json.dumps(data))
    info = vp.inspect(tmp_path.resolve(), "p")
    assert info["delivered"] is True and info["summary"] == "已交付"


def test_failed_qa_is_not_pass(tmp_path: Path) -> None:
    _touch(tmp_path, "qa.json", json.dumps({"status": "fail"}))
    assert vp.qa_passed(tmp_path / "qa.json") is False
    _touch(tmp_path, "qa2.json", json.dumps({"pass": True}))
    assert vp.qa_passed(tmp_path / "qa2.json") is True


def test_legacy_and_fresh_layouts_and_log(tmp_path: Path) -> None:
    _touch(tmp_path, "old/delivery/final-video.mp4")
    _touch(tmp_path, "old/process-log.md", "# log\n## Step 5–9：Product A\n- status: pass\n## Step 10\n- status: pass\n")
    info = vp.inspect(tmp_path.resolve(), "old")
    assert info["layout"] == "legacy" and info["delivered"] and info["final_video"] == "delivery/final-video.mp4"
    assert [e["status"] for e in info["log"]] == ["pass", "pass"]
    name = vp.create_project(tmp_path.resolve(), title="为什么/看不到 AI", today="2026-09-14", outline_markdown="# 提纲")
    assert name == "2026-09-14_为什么看不到AI"
    fresh = vp.inspect(tmp_path.resolve(), name)
    assert fresh["layout"] == "fresh" and "还没开始" in fresh["summary"]
    assert (tmp_path / name / "拍摄提纲.md").read_text(encoding="utf-8") == "# 提纲"
    assert vp.create_project(tmp_path.resolve(), title="为什么/看不到 AI", today="2026-09-14").endswith("-2")


@pytest.mark.parametrize("name, rel", [("../x", "a.md"), ("p", "../../etc/passwd"), ("p", "/etc/hosts"), ("p", "secret.key")])
def test_paths_are_confined(tmp_path: Path, name: str, rel: str) -> None:
    _touch(tmp_path, "p/secret.key")
    with pytest.raises(vp.VideoProjectError):
        vp.safe_file(tmp_path.resolve(), name, rel)


def test_missing_root_explains_external_drive(tmp_path: Path) -> None:
    with pytest.raises(vp.VideoProjectError, match="外接硬盘"):
        vp.resolve_root("/Volumes/Nope/视频")


def _worktable(project="demo", **extra):
    data = {"schema": "park-video-worktable/v1", "project": project,
            "hooks": [{"slot": 1, "order": 1, "text": "h", "anchor_status": "ok"}, {"slot": 2, "order": 2, "text": "h2", "anchor_status": "stale"}],
            "visual_notes": [{"marker": 1, "intent": "图", "anchor_status": "ok"}]}
    data.update(extra)
    return json.dumps(data)


def test_import_worktable_validates_and_saves(tmp_path: Path) -> None:
    root = tmp_path / "videos"
    base = _project(root, "p", project="demo")
    _touch(base, "analysis/worktable.html")
    result = vp.import_worktable(root.resolve(), "p", text=_worktable(), source="worktable (1).json")
    assert result["hooks"] == 2 and result["needs_review"] == 1 and result["source"] == "worktable (1).json"
    assert json.loads((base / "analysis/worktable.json").read_text())["project"] == "demo"
    with pytest.raises(ValueError, match="已经存在"):
        vp.import_worktable(root.resolve(), "p", text=_worktable())
    assert vp.import_worktable(root.resolve(), "p", text=_worktable(), overwrite=True)["source"] == "粘贴"
    with pytest.raises(ValueError, match="属于"):
        vp.import_worktable(root.resolve(), "p", text=_worktable(project="other"), overwrite=True)
    with pytest.raises(ValueError, match="schema"):
        vp.import_worktable(root.resolve(), "p", text=json.dumps({"hooks": []}), overwrite=True)
    with pytest.raises(ValueError, match="有效的 JSON"):
        vp.import_worktable(root.resolve(), "p", text="{", overwrite=True)


def test_import_requires_worktable_page(tmp_path: Path) -> None:
    _project(tmp_path, "p")
    with pytest.raises(vp.VideoProjectError, match="还没有 worktable"):
        vp.import_worktable(tmp_path.resolve(), "p", text="{}")
