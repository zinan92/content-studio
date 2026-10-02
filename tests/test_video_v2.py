"""口播动效 v2 项目在工作台里的显示和按钮。pv2.py 用一个假的脚本代替，只记下被怎么调用。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from content_studio import video_project, video_v2

from test_web import client  # noqa: F401  (fixture)

FAKE = '''import json, sys, pathlib
log = pathlib.Path(__file__).with_name("calls.log")
log.open("a").write(json.dumps(sys.argv[1:], ensure_ascii=False) + "\\n")
cmd = sys.argv[1]
if cmd == "status":
    print(json.dumps({"step": "方案", "percent": None, "waiting_for": "Park 看样片", "failed": False, "detail": "",
                      "sample": "v2/sample.mp4", "final": None}, ensure_ascii=False))
elif cmd == "approve":
    print(json.dumps({"by": "Park", "message": sys.argv[sys.argv.index("-m") + 1]}, ensure_ascii=False))
elif cmd in ("sample", "render"):
    print("已在后台启动")
else:
    sys.exit("unknown")
'''


@pytest.fixture
def pv2_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "pv2"
    (home / "scripts").mkdir(parents=True)
    (home / "scripts" / "pv2.py").write_text(FAKE, encoding="utf-8")
    monkeypatch.setenv(video_v2.HOME_ENV, str(home))
    return home


def calls(home: Path) -> list[list[str]]:
    path = home / "scripts" / "calls.log"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def _v2_project(root: Path, name: str) -> Path:
    base = root / name
    (base / "v2").mkdir(parents=True)
    (base / "v2" / "brief.yaml").write_text("video_type: 横屏口播\n", encoding="utf-8")
    return base


def test_v2_project_shows_four_steps_and_real_status(tmp_path: Path, pv2_home: Path) -> None:
    root = tmp_path / "videos"
    _v2_project(root, "2026-10-03_new")
    info = video_project.inspect(root, "2026-10-03_new")
    assert info["layout"] == "v2"
    assert info["v2"]["waiting_for"] == "Park 看样片" and info["v2"]["sample"] == "v2/sample.mp4"
    assert [s["state"] for s in info["stages"]] == ["done", "current", "todo", "todo"]
    assert info["summary"] == "方案 · 等 Park 看样片" and info["delivered"] is False and info["gate"] is None
    assert "park-video-v2" in info["continue_command"]


def test_old_project_with_a_v2_folder_stays_on_the_old_flow(tmp_path: Path, pv2_home: Path) -> None:
    root = tmp_path / "videos"
    base = _v2_project(root, "2026-10-02_old")
    (base / "project.json").write_text(json.dumps({"workflow": "ask-park-video/v1", "presets": {}}), encoding="utf-8")
    assert video_project.inspect(root, "2026-10-02_old")["layout"] != "v2"


def test_missing_pv2_is_reported_not_crashing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(video_v2.HOME_ENV, str(tmp_path / "nowhere"))
    root = tmp_path / "videos"
    _v2_project(root, "p")
    st = video_project.inspect(root, "p")["v2"]
    assert st["failed"] is True and "找不到 park-video-v2" in st["detail"]


def test_buttons_go_through_to_pv2(client: TestClient, tmp_path: Path, pv2_home: Path) -> None:  # noqa: F811
    root = tmp_path / "videos"
    base = _v2_project(root, "2026-10-03_new")
    client.put("/api/settings", json={"video_projects_root": str(root)})
    topic = client.post("/api/topics", json={"title": "拍这条", "formats": "video"}).json()
    client.put(f"/api/topics/{topic['id']}/video-project", json={"name": base.name})
    assert client.get(f"/api/topics/{topic['id']}/video-project").json()["layout"] == "v2"

    r = client.post(f"/api/topics/{topic['id']}/video-project/v2/approve", json={"gate": "sample", "message": "可以，全部渲染"})
    assert r.status_code == 200 and r.json()["approval"]["message"] == "可以，全部渲染"
    assert ["approve", str(base), "sample", "-m", "可以，全部渲染"] in calls(pv2_home)

    assert client.post(f"/api/topics/{topic['id']}/video-project/v2/approve", json={"gate": "sample", "message": " "}).status_code == 400
    assert client.post(f"/api/topics/{topic['id']}/video-project/v2/approve", json={"gate": "H2", "message": "x"}).status_code == 400

    r = client.post(f"/api/topics/{topic['id']}/video-project/v2/start", json={"job": "render"})
    assert r.status_code == 200 and ["render", str(base), "--detach"] in calls(pv2_home)
    assert client.post(f"/api/topics/{topic['id']}/video-project/v2/start", json={"job": "rm"}).status_code == 400


def test_v2_buttons_refuse_old_projects(client: TestClient, tmp_path: Path, pv2_home: Path) -> None:  # noqa: F811
    root = tmp_path / "videos"
    (root / "2026-01-01_old" / "delivery").mkdir(parents=True)
    client.put("/api/settings", json={"video_projects_root": str(root)})
    topic = client.post("/api/topics", json={"title": "旧的", "formats": "video"}).json()
    client.put(f"/api/topics/{topic['id']}/video-project", json={"name": "2026-01-01_old"})
    assert client.post(f"/api/topics/{topic['id']}/video-project/v2/start", json={"job": "sample"}).status_code == 400
