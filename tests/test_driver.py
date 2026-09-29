"""「今天」驱动页：KPI 怎么记分、一次只给哪一件（9/29 Park 拍板的顺序）。"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from content_studio import consult, driver
from tests.test_web import client  # noqa: F401 - fixture


def test_kpi_days_scores_only_what_he_controls_and_never_before_the_start() -> None:
    today = date(2026, 9, 29)
    days = driver.kpi_days(today, posted={"2026-09-24", "2026-09-29"},
                           dms={"2026-09-29": {"received": 3, "replied": 3}}, started="2026-09-29",
                           x_replies={"2026-09-29": 20}, x_target=20)
    assert [d["day"] for d in days] == [f"2026-09-{n}" for n in range(23, 30)]
    assert [d["ship"] for d in days] == ["miss", "ok", "miss", "miss", "miss", "miss", "ok"]
    # 私信、X 回复从 KPI 开始那天才算，之前没记过，不倒扣
    assert [d["dm"] for d in days[:-1]] == ["n/a"] * 6 and days[-1]["dm"] == "ok"
    assert [d["xr"] for d in days[:-1]] == ["n/a"] * 6 and days[-1]["xr"] == "ok"
    assert driver.demerits(days) == 5


def test_today_is_pending_not_a_miss_until_it_is_over() -> None:
    days = driver.kpi_days(date(2026, 10, 1), posted=set(), dms={"2026-09-30": {"received": 4, "replied": 2}}, started="2026-09-29",
                           x_replies={"2026-09-30": 12}, x_target=20)
    assert days[-1]["ship"] == "pending" and days[-1]["dm"] == "pending" and days[-1]["xr"] == "pending"
    by_day = {d["day"]: d for d in days}
    assert by_day["2026-09-30"]["dm"] == "miss"  # 没回完
    assert by_day["2026-09-30"]["xr"] == "miss"  # 12 < 20
    assert by_day["2026-09-29"]["dm"] == "miss"  # 没填
    assert driver.demerits(days) == 6 + 2 + 2


def test_order_follows_the_ladder_and_drops_skipped_and_done() -> None:
    items = [
        driver.item("wrap", "reach", "填数"),
        driver.item("dm", "dm", "回私信"),
        driver.item("ship", "ship", "拍"),
        driver.item("client", "c1", "发 PDF"),
        driver.item("blocker", "cookies", "登录过期"),
        driver.item("tomorrow", "tm", "明天出摊"),
    ]
    got = driver.order(items, skipped={"cookies"}, done={"c1"})
    assert [i["key"] for i in got] == ["ship", "dm", "tm", "reach"]
    assert got[0]["rung_label"] == "出摊"


def _today(client: TestClient) -> dict:
    return client.get("/api/today").json()


def test_today_is_three_things_and_the_top_note_is_what_he_shoots_next(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    d = _today(client)
    assert set(d) >= {"first", "ship", "dm", "xr", "days", "demerits"}
    assert d["ship"]["next"]["key"] == "notes:empty"  # 清单空：让他写，不替他挑
    assert [p["form"] for p in d["ship"]["platforms"] if p["key"] in ("douyin", "x")] == ["video", "text"]
    assert d["xr"] == {"count": None, "target": 20}
    client.post("/api/today/notes", json={"text": "内容工作台做完整了，拍出来"})
    client.post("/api/today/notes", json={"text": "接了一单咨询，拍出来", "top": True})
    d = _today(client)
    assert [n["text"] for n in d["ship"]["notes"]] == ["接了一单咨询，拍出来", "内容工作台做完整了，拍出来"]
    assert d["ship"]["next"]["text"] == "拍「接了一单咨询，拍出来」" and d["ship"]["next"]["rung"] == "ship"
    note_id = d["ship"]["notes"][0]["id"]
    topic = client.post(f"/api/today/notes/{note_id}/start").json()["topic"]
    assert topic["title"] == "接了一单咨询，拍出来" and topic["is_focus"]
    d = _today(client)
    assert d["ship"]["next"]["go"] == f"work/{topic['id']}"  # 接着是这条选题自己的下一步
    assert "写拍摄提纲" in d["ship"]["next"]["text"]


def test_skip_needs_a_reason_and_entries_count_toward_kpis(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    assert client.post("/api/today/skip", json={"key": "notes:empty", "reason": " "}).status_code == 400
    assert client.post("/api/today/skip", json={"key": "notes:empty", "reason": "今天状态不好"}).status_code == 200
    d = _today(client)
    assert d["ship"]["next"] is None and d["skipped"][0]["reason"] == "今天状态不好"
    assert client.put("/api/today/dm", json={"received": 2, "replied": 3}).status_code == 400
    client.put("/api/today/dm", json={"received": 5, "replied": 2})
    assert _today(client)["dm"]["entry"] == {"received": 5, "replied": 2}
    client.put("/api/today/dm", json={"received": 5, "replied": 5})
    client.put("/api/today/x-replies", json={"value": 20})
    d = _today(client)
    assert d["days"][-1]["dm"] == "ok" and d["days"][-1]["xr"] == "ok" and d["xr"]["count"] == 20
    assert client.put("/api/today/x-replies", json={"value": -1}).status_code == 400


def test_note_order_moves_and_suggestion_only_comes_from_his_pool(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    a = client.post("/api/today/notes", json={"text": "A"}).json()["notes"][0]
    client.post("/api/today/notes", json={"text": "B"})
    notes = client.patch(f"/api/today/notes/{a['id']}", json={"move": 1}).json()["notes"]
    assert [n["text"] for n in notes] == ["B", "A"]
    assert client.post("/api/today/suggest").status_code == 400  # 选题池空：不编新选题


def test_weekly_review_prompt_puts_the_demerits_and_repeated_excuses_in_front_of_him() -> None:
    from content_studio import review

    kpi = {"posted": 2, "dm_missed": 1, "demerits": 6, "skips": [{"day": "2026-10-01", "what": "ship", "reason": "没灵感"}, {"day": "2026-10-02", "what": "ship", "reason": "没灵感"}]}
    inputs = {"week": "2026-W40", "since": "2026-09-26", "until": "2026-10-03", "videos": [], "median_likes": 100, "topics_done": [], "breakouts": [], "kpi": kpi}
    prompt = review.build_prompt(inputs)
    assert "一共减 6 分" in prompt and prompt.count("理由：没灵感") == 2
    # 说执行分的那条没有视频可引，video_ids 给空也算过
    raw = {"summary": "s", "wins": [], "problems": [{"text": "减了 6 分，「没灵感」出现 2 次", "video_ids": []}], "next_week": ["每天出摊"]}
    assert review.validate(raw, inputs) == []
    assert review.validate(raw, {**inputs, "kpi": None}) != []


def test_xiaohongshu_form_is_a_setting_that_changes_pack_and_today(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """给客户选发什么：小红书默认发视频；设置里改成图文，打包多一步、今天那行分到「发图文」。"""
    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    r = client.get("/api/reach").json()
    xhs = next(p for p in r["platforms"] if p["key"] == "xiaohongshu")
    assert xhs["form"] == "video" and [c["key"] for c in xhs["form_choices"]] == ["video", "cards"]
    assert next(p for p in r["platforms"] if p["key"] == "douyin")["form_choices"] == []
    assert client.get("/api/publish/desk").json()["forms"]["xiaohongshu"] == "video"
    client.put("/api/settings", json={"platform_accounts": {"xiaohongshu": {"on": True, "handle": "Park", "form": "cards"}}})
    assert client.get("/api/publish/desk").json()["forms"]["xiaohongshu"] == "cards"
    forms = {p["key"]: p["form"] for p in _today(client)["ship"]["platforms"]}
    assert forms["xiaohongshu"] == "cards" and forms["douyin"] == "video"
    # 选了图文，视频的上传文件夹就不给
    topic = client.post("/api/topics", json={"title": "t"}).json()
    assert client.post(f"/api/topics/{topic['id']}/upload-folder", json={"platform": "xiaohongshu"}).status_code == 400
    # 认不出的值按默认
    client.put("/api/settings", json={"platform_accounts": {"xiaohongshu": {"on": True, "handle": "Park", "form": "hologram"}}})
    assert client.get("/api/publish/desk").json()["forms"]["xiaohongshu"] == "video"
