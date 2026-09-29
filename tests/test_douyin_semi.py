"""抖音半自动：机器开 Chrome 填好，停在「发布」前，最后一下 Park 点。

真浏览器不在测试里开（会弹窗口、要登录）；这里测的是：脚本从不点发布、通道怎么拼命令、
边跑边报的进度怎么落到任务上、Park 点了发布怎么记、关了窗口怎么算。
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import time

from fastapi.testclient import TestClient

from content_studio import douyin_fill, publish_desk, publisher as pub
from test_web import FakeClient


FILL_SOURCE = Path(douyin_fill.__file__).read_text(encoding="utf-8")


def test_fill_script_never_clicks_publish() -> None:
    """最后一下永远是 Park：脚本里一个 click 都没有，也不碰工具箱那个会自己点发布的 upload()。"""
    code = re.sub(r'"""[\s\S]*?"""', "", FILL_SOURCE)  # 文档字符串里提到「发布」不算
    assert ".click(" not in code
    assert not re.search(r"\.upload\(", code)
    used = set(re.findall(r"uploader\.(\w+)\(", code))
    assert used <= {"fill_title_and_description", "set_thumbnail", "handle_upload_error"}
    for forbidden in ("handle_auto_video_cover", "set_schedule_time_douyin", "定时发布", 'name="发布"', "has-text(\"发布\")"):
        assert forbidden not in code


def test_fill_helpers() -> None:
    assert douyin_fill.is_published("https://creator.douyin.com/creator-micro/content/manage?enter_from=publish")
    assert not douyin_fill.is_published("https://creator.douyin.com/creator-micro/content/post/video?enter_from=publish_page")
    assert douyin_fill.on_publish_page("https://creator.douyin.com/creator-micro/content/post/video?enter_from=publish_page")
    # 描述里已经有 #AI 了，不再敲一遍；重复的、带 # 的都理顺
    assert douyin_fill.tags_to_type("讲清楚 #AI 的事", ["AI", "#交易", "交易", " "]) == ["交易"]
    # 描述太长时先给话题留位置，别让抖音把 #话题 截掉
    fitted = douyin_fill.fit_description("字" * 1200, ["金融", "交易"])
    assert len(fitted) + len(" #金融 ") + len(" #交易 ") == 1000
    assert douyin_fill.fit_description("短", ["AI"]) == "短"


def test_only_jpg_png_covers_go_to_douyin(tmp_path: Path) -> None:
    png, svg = tmp_path / "竖.png", tmp_path / "横.svg"
    png.write_bytes(b"x")
    svg.write_text("<svg/>")
    assert douyin_fill.usable_cover(str(png)) == str(png)
    assert douyin_fill.usable_cover(str(svg)) is None
    assert douyin_fill.usable_cover("") is None and douyin_fill.usable_cover(str(tmp_path / "没有.jpg")) is None


def test_missing_video_is_reported_before_any_browser(tmp_path: Path, capsys) -> None:
    code = douyin_fill.main(["--toolkit", str(tmp_path), "--profile", str(tmp_path / "p"), "--video", str(tmp_path / "no.mp4"), "--title", "t"])
    assert code == 2
    assert pub.parse_result(capsys.readouterr().out)["status"] == "video_missing"


def test_douyin_channel_is_semi_and_logs_in_inside_the_window(tmp_path: Path) -> None:
    spec = pub.PUBLISHERS["douyin"]
    assert publish_desk.treatment("douyin", spec) == "semi" and list(spec["modes"]) == ["fill"]
    runner = tmp_path / "python"
    profile = tmp_path / "profile"
    local = {**spec, "credential": profile, "modes": {"fill": {**spec["modes"]["fill"], "argv": [str(runner), *spec["modes"]["fill"]["argv"][1:]]}}}
    missing = pub.readiness({"douyin": local})["douyin"]
    assert missing["setup"] and "没装好" in missing["note"]
    runner.write_text("")
    first = pub.readiness({"douyin": local})["douyin"]
    # 没有 cookie 文件也算能用：登录就在弹出的窗口里扫
    assert first["credential"] and not first["likely_expired"] and "第一次" in first["note"]
    (profile / "Default").mkdir(parents=True)
    assert "记在" in pub.readiness({"douyin": local})["douyin"]["note"]


def test_douyin_command_carries_video_copy_and_both_covers(tmp_path: Path) -> None:
    video, land, port = tmp_path / "final.mp4", tmp_path / "横.jpg", tmp_path / "竖.jpg"
    for f in (video, land, port):
        f.write_bytes(b"0" * 1024)
    copy = {"douyin": {"title": "看懂加息", "body": "底层逻辑", "tags": ["金融", "交易"]}}
    payload = pub.build_payload("douyin", "fill", video=video, copy=copy, cover=land, cover_portrait=port)
    argv = pub.command_for(payload)
    after = lambda flag: argv[argv.index(flag) + 1]  # noqa: E731
    assert argv[1].endswith("douyin_fill.py")
    assert after("--video") == str(video) and after("--title") == "看懂加息" and after("--description") == "底层逻辑"
    assert after("--tags") == "金融,交易" and after("--cover-landscape") == str(land) and after("--cover-portrait") == str(port)
    assert after("--profile").endswith("douyin-publish-chrome")


def _interactive(script: str) -> dict:
    return {"douyin": {"label": "抖音", "copy_key": "douyin", "semi": True, "interactive": True, "credential": "/x", "login_hint": "",
                       "modes": {"fill": {"label": "填好", "argv": [sys.executable, "-c", script, "{title}"]}}}}


def test_streaming_run_hands_over_progress_and_keeps_the_last_line_as_result(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"0")
    script = ("import json,sys\n"
              "for e in ({'progress': '正在上传视频'}, {'progress': '窗口已打开，等你在抖音点发布'}, {'progress': '已发出', 'published': True}):\n"
              "    print(json.dumps(e, ensure_ascii=False), flush=True)\n"
              "sys.stderr.write('log\\n' * 20000)\n"
              "print(json.dumps({'ok': True, 'published': True, 'status': 'published'}))\n")
    specs = _interactive(script)
    payload = pub.build_payload("douyin", "fill", video=video, copy={"douyin": {"title": "T"}}, publishers=specs)
    seen: list[dict] = []
    result = pub.run(payload, publishers=specs, on_progress=seen.append)
    assert [e["progress"] for e in seen][:2] == ["正在上传视频", "窗口已打开，等你在抖音点发布"] and seen[-1]["published"]
    assert result == {"ok": True, "published": True, "status": "published"}
    # 只打了进度就崩了：进度那行不能被当成结果
    crashed = pub.run(payload, publishers=_interactive("import json; print(json.dumps({'progress': '正在上传视频'}), flush=True); raise SystemExit('boom')"))
    assert crashed["ok"] is False and crashed["status"] == "no_result" and "boom" in crashed["message"]
    slow = pub.run(payload, publishers=_interactive("import time; time.sleep(30)"), timeout=0.5)
    assert slow["status"] == "timeout"


def _app(tmp_path: Path, script: str):
    from content_studio import web as web_module

    root = tmp_path / "videos"
    (root / "p" / "final").mkdir(parents=True)
    (root / "p" / "final" / "video.mp4").write_bytes(b"0" * 1024)
    cookie = tmp_path / "cookies.json"
    cookie.write_text(json.dumps({"sessionid": "x"}))
    cookie.chmod(0o600)
    return web_module.create_app(store_path=tmp_path / "s.sqlite3", cookie_path=cookie, creator_db=None, data_dir=tmp_path / "d",
                                 downloads_dir=tmp_path / "dl", client_factory=FakeClient, start_worker=False, drafts_dir=tmp_path / "drafts",
                                 publishers=_interactive(script))


def _finish(c: TestClient, topic_id: int) -> dict:
    for _ in range(200):
        job = c.get(f"/api/topics/{topic_id}/publish-jobs").json()["jobs"][0]
        if job["state"] != "running":
            return job
        time.sleep(0.05)
    return job


def _start(c: TestClient, root: Path) -> int:
    c.put("/api/settings", json={"video_projects_root": str(root)})
    topic = c.post("/api/topics", json={"title": "t", "formats": "video"}).json()
    c.put(f"/api/topics/{topic['id']}/video-project", json={"name": "p"})
    c.put(f"/api/topics/{topic['id']}/copy", json={"platforms": {"douyin": {"title": "抖音标题", "body": "b", "tags": ["AI"]}}})
    job = c.post(f"/api/topics/{topic['id']}/publish-jobs", json={"platform": "douyin", "mode": "fill"}).json()["job"]
    c.post(f"/api/publish-jobs/{job['id']}/confirm")
    return topic["id"]


def test_park_clicking_publish_marks_douyin_sent(tmp_path: Path) -> None:
    gate = tmp_path / "go"
    script = ("import json,pathlib,time\n"
              f"gate = pathlib.Path({str(gate)!r})\n"
              "print(json.dumps({'progress': '窗口已打开，等你在抖音点发布'}, ensure_ascii=False), flush=True)\n"
              "while not gate.exists(): time.sleep(0.02)\n"
              "print(json.dumps({'progress': '已发出，窗口可以关了', 'published': True}, ensure_ascii=False), flush=True)\n"
              "time.sleep(0.3)\n"
              "print(json.dumps({'ok': True, 'published': True, 'platform': 'douyin', 'status': 'published'}))\n")
    app = _app(tmp_path, script)
    with TestClient(app, headers={"X-Content-Studio": "1"}) as c:
        topic_id = _start(c, tmp_path / "videos")
        for _ in range(200):
            job = c.get(f"/api/topics/{topic_id}/publish-jobs").json()["jobs"][0]
            if job["message"]:
                break
            time.sleep(0.05)
        assert job["state"] == "running" and job["message"] == "窗口已打开，等你在抖音点发布"
        row = next(r for r in c.get(f"/api/publish/desk?topic_id={topic_id}").json()["platforms"] if r["key"] == "douyin")
        assert row["treatment"] == "semi" and row["shipped"] is False and row["job"]["message"].startswith("窗口已打开")
        gate.write_text("1")
        # 点了发布就当场记一笔，不等窗口关
        for _ in range(200):
            if "douyin" in c.get(f"/api/topics/{topic_id}/copy").json()["records"]:
                break
            time.sleep(0.05)
        assert "douyin" in c.get(f"/api/topics/{topic_id}/copy").json()["records"]
        assert _finish(c, topic_id)["state"] == "done"
    app.state.store.close()


def test_closing_the_window_without_publishing_cancels_quietly(tmp_path: Path) -> None:
    script = "import json; print(json.dumps({'ok': False, 'status': 'window_closed', 'message': '窗口关了，没发'}, ensure_ascii=False))"
    app = _app(tmp_path, script)
    with TestClient(app, headers={"X-Content-Studio": "1"}) as c:
        topic_id = _start(c, tmp_path / "videos")
        job = _finish(c, topic_id)
        assert job["state"] == "cancelled" and job["message"] == "窗口关了，没发"
        assert "douyin" not in c.get(f"/api/topics/{topic_id}/copy").json()["records"]
        row = next(r for r in c.get(f"/api/publish/desk?topic_id={topic_id}").json()["platforms"] if r["key"] == "douyin")
        assert row["job"] is None and row["shipped"] is False  # 瓦片回到原样，不挂「上次失败」
    app.state.store.close()
