"""剪辑规格：Park 手动选，写进 project.json 的 spec，换好对应 preset；runner 的提示词带上这些规则。"""
import json
from pathlib import Path

import pytest

from content_studio import koubo, workflow_runner


SKILL: list[Path] = [Path()]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    skill = tmp_path / "skill"
    for folder, names in {"media": [("park-talking-head-4x3-v1", "default"), ("park-talking-head-9x16-full-v1", "override")],
                          "audio": [("park-voice-v1", "default")],
                          "captions": [("park-caption-4x3-v1", "default"), ("park-caption-burned-in-v1", "override"), ("park-caption-layout-v1", "default")]}.items():
        (skill / "presets" / folder).mkdir(parents=True)
        for name, status in names:
            (skill / "presets" / folder / f"{name}.json").write_text(json.dumps({"id": name, "status": status}))
    base = tmp_path / "proj"
    base.mkdir()
    koubo.init_project(base, skill=skill)
    SKILL[0] = skill
    return base


def _contract(base: Path) -> dict:
    return json.loads((base / "project.json").read_text(encoding="utf-8"))


def test_overrides_are_never_picked_as_defaults(project: Path) -> None:
    assert _contract(project)["presets"] == {"media": "park-talking-head-4x3-v1", "audio": "park-voice-v1",
                                             "caption_style": "park-caption-4x3-v1", "caption_layout": "park-caption-layout-v1"}


def test_vertical_burned_in_no_hook(project: Path) -> None:
    koubo.set_spec(project, {"layout": "vertical-full-overlay", "captions": "burned_in", "hook": "no", "bgm": "none"}, skill=SKILL[0])
    c = _contract(project)
    assert c["spec"] == {"layout": "vertical-full-overlay", "captions": "burned_in", "hook": "no", "bgm": "none"}
    assert c["presets"]["media"] == "park-talking-head-9x16-full-v1" and c["presets"]["caption_style"] == "park-caption-burned-in-v1"
    assert all(c["step_status"][str(n)] == "skipped" for n in (5, 7, 8, 9)) and c["approvals"]["hook"] == "skipped"
    prompt = workflow_runner.build_prompt(project)
    assert "不要再渲染字幕" in prompt and "竖屏纯口播" in prompt and "不做 Hook" in prompt and "不加背景音乐" in prompt


def test_switching_back_restores_defaults(project: Path) -> None:
    koubo.set_spec(project, {"layout": "vertical-full-overlay", "hook": "no"}, skill=SKILL[0])
    koubo.set_spec(project, {"layout": "split-4x3", "hook": "yes"}, skill=SKILL[0])
    c = _contract(project)
    assert c["presets"]["media"] == "park-talking-head-4x3-v1"
    assert "5" not in c["step_status"] and c["approvals"]["hook"] is None


def test_no_spec_means_the_same_prompt_as_before(project: Path) -> None:
    assert "剪辑规格" not in workflow_runner.build_prompt(project)
    with pytest.raises(koubo.KouboError):
        koubo.set_spec(project, {"layout": "diagonal"}, skill=SKILL[0])
