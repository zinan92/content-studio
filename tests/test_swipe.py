"""流量视频：贴链接就下到本机存一张卡片；「开始复刻」才变成选题（9/30 Park）。"""
from __future__ import annotations

import json
from pathlib import Path
import time

import pytest
from fastapi.testclient import TestClient

from content_studio import swipe
from tests.test_web import client  # noqa: F401 - fixture


def test_clean_url_knows_the_three_platforms_and_refuses_the_rest() -> None:
    assert swipe.clean_url("看这个 https://v.douyin.com/abc123/ 复制此链接")[1] == "douyin"
    assert swipe.clean_url("https://x.com/someone/status/1234567890")[1] == "x"
    assert swipe.clean_url("https://www.xiaohongshu.com/explore/abcdef")[1] == "xiaohongshu"
    # 在主页里点开的视频：账号主页 + modal_id → 换成单条视频的地址，不能把整个主页交给下载工具
    assert swipe.clean_url("https://www.douyin.com/user/MS4wLjABAAAAK1pk?from_tab_name=main&modal_id=7690973351082881939") == (
        "https://www.douyin.com/video/7690973351082881939", "douyin")
    assert swipe.clean_url("https://www.douyin.com/video/7690973351082881939?previous_page=app")[0] == "https://www.douyin.com/video/7690973351082881939"
    with pytest.raises(swipe.SwipeError, match="账号主页"):
        swipe.clean_url("https://www.douyin.com/user/MS4wLjABAAAA")
    with pytest.raises(swipe.SwipeError, match="认得的是"):
        swipe.clean_url("https://www.youtube.com/watch?v=abc")
    with pytest.raises(swipe.SwipeError, match="贴一个"):
        swipe.clean_url("  ")


def _fake_download(tmp_path: Path):
    def download(url: str, platform: str, *, out_dir: Path, cookies):
        folder = out_dir / platform / "author" / "vid1"
        (folder / "media").mkdir(parents=True, exist_ok=True)
        (folder / "media" / "video.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
        (folder / "media" / "cover.jpg").write_bytes(b"\xff\xd8\xff")
        (folder / "content_item.json").write_text(json.dumps({
            "platform": platform, "content_id": "vid1", "title": "Opus 5.5 做的 15 种风格", "author_name": "Vincent",
            "media_files": ["media/video.mp4"], "cover_file": "media/cover.jpg", "likes": "12000", "collects": 3400, "shares": "900",
        }), encoding="utf-8")
        return folder
    return download


def _wait(client: TestClient, swipe_id: int) -> dict:
    for _ in range(100):
        v = next(x for x in client.get("/api/swipe").json()["videos"] if x["id"] == swipe_id)
        if v["status"] != "downloading":
            return v
        time.sleep(0.02)
    raise AssertionError("download did not finish")


def test_paste_a_link_saves_a_card_and_start_makes_a_topic(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(swipe, "download", _fake_download(tmp_path))
    res = client.post("/api/swipe", json={"url": "https://x.com/vincent/status/1234567890"})
    assert res.status_code == 200
    v = _wait(client, res.json()["video"]["id"])
    assert v["status"] == "saved" and v["title"] == "Opus 5.5 做的 15 种风格" and v["likes"] == 12000 and v["collects"] == 3400
    assert client.get(v["cover"]).status_code == 200 and client.get(v["video"]).status_code == 200
    # 同一条不存两遍
    assert client.post("/api/swipe", json={"url": "https://x.com/vincent/status/1234567890"}).status_code == 400

    client.patch(f"/api/swipe/{v['id']}", json={"note": "一个人做出广告公司的片子", "collection": "一个人加 AI 做成的"})
    assert client.patch(f"/api/swipe/{v['id']}", json={"collection": "随便写的"}).status_code == 400

    topic = client.post(f"/api/swipe/{v['id']}/start").json()["topic"]
    assert topic["title"].startswith("复刻：Opus 5.5") and "一个人做出广告公司的片子" in topic["memo"]
    v = next(x for x in client.get("/api/swipe").json()["videos"] if x["id"] == v["id"])
    assert v["status"] == "making" and v["topic"]["id"] == topic["id"]
    # 出现在「今天」的「接下来要拍的」最上面；再点一次不会建第二条
    notes = client.get("/api/today").json()["ship"]["notes"]
    assert notes[0]["topic_id"] == topic["id"]
    assert client.post(f"/api/swipe/{v['id']}/start").json()["topic"]["id"] == topic["id"]

    assert client.delete(f"/api/swipe/{v['id']}").status_code == 200
    assert client.get("/api/swipe").json()["videos"] == []
    assert not (tmp_path / "data" / "swipe" / "x" / "author" / "vid1").exists()


def test_douyin_links_are_capped_per_day_and_failures_can_retry(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def flaky(url, platform, *, out_dir, cookies):
        calls["n"] += 1
        if calls["n"] == 1:
            raise swipe.SwipeError("没下下来：抖音拒绝了")
        return _fake_download(tmp_path)(url, platform, out_dir=out_dir, cookies=cookies)

    monkeypatch.setattr(swipe, "download", flaky)
    first = client.post("/api/swipe", json={"url": "https://www.douyin.com/video/7000000000000000001"}).json()["video"]
    v = _wait(client, first["id"])
    assert v["status"] == "failed" and "抖音拒绝了" in v["error"]
    client.post(f"/api/swipe/{v['id']}/retry")
    assert _wait(client, v["id"])["status"] == "saved"
    for i in range(2, swipe.DOUYIN_DAILY_CAP + 1):
        assert client.post("/api/swipe", json={"url": f"https://www.douyin.com/video/700000000000000000{i}"}).status_code == 200
    over = client.post("/api/swipe", json={"url": "https://www.douyin.com/video/7000000000000000099"})
    assert over.status_code == 400 and "明天再存" in over.json()["error"]
    assert client.get("/api/swipe").json()["douyin_left"] == 0
    # X 不走抖音登录，不受这个上限
    assert client.post("/api/swipe", json={"url": "https://x.com/a/status/1"}).status_code == 200


def test_stylesheet_still_has_every_page(tmp_path: Path) -> None:
    """9/30：另一个改动把 styles.css 后面 362 行截掉了，今天页、咨询、概览、打包的样式全没了，测试却全过。
    每一页挑一个选择器守着：少了哪个，就是样式文件又被截了。"""
    css = (Path(__file__).resolve().parents[1] / "src/content_studio/static/styles.css").read_text(encoding="utf-8")
    for selector in (".rail-today", ".td-row", ".td-pack", ".rail-consult", ".ov-core", ".pk-row", ".mx-wrap", ".pub-idle", ".k-svg path.l", ".sw-card"):
        assert selector in css, f"styles.css 里没有 {selector}"
    assert css.count("{") == css.count("}")
