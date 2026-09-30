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
    assert d["xr"] == {"count": None, "target": 10}
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


def test_backfill_section_is_in_today(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    b = _today(client)["backfill"]
    assert b == {"today": None, "ready": [], "ready_count": 0, "waiting_count": 0}
    assert client.post("/api/today/backfill/999/go").status_code in (400, 404)


def test_backfill_preview_shows_what_would_go_out(client: TestClient, tmp_path) -> None:
    topic = client.post("/api/topics", json={"title": "旧视频"}).json()
    art = tmp_path / "drafts" / f"topic-{topic['id']}" / "article.md"
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_text("# 文章标题\n\n第一段。\n\n![图](figs/01.png)\n\n第二段**加粗**。\n", encoding="utf-8")
    client.app.state.store.update_topic(topic["id"], article_path=str(art))
    v = client.get(f"/api/today/backfill/{topic['id']}/preview").json()
    assert v["article_title"] == "文章标题"
    assert v["article_head"] == ["第一段。", "第二段加粗。"]
    assert v["layout_url"].endswith("/wechat-preview.html")


def test_reading_the_dailies_is_scored_from_the_start_day_and_only_when_one_came_out() -> None:
    days = driver.kpi_days(date(2026, 10, 2), posted=set(), dms={}, started="2099-01-01",
                           reads={"2026-09-30": True, "2026-10-01": False, "2026-10-02": False}, read_started="2026-09-30")
    by = {d["day"]: d["rd"] for d in days}
    assert by["2026-09-29"] == "n/a"  # 开始之前不倒扣
    assert by["2026-09-30"] == "ok" and by["2026-10-01"] == "miss" and by["2026-10-02"] == "pending"
    # 那天一份日报都没出（reads 里没有这天）：不算
    days = driver.kpi_days(date(2026, 10, 2), posted=set(), dms={}, started="2099-01-01", reads={}, read_started="2026-09-30")
    assert all(d["rd"] == "n/a" for d in days)


def test_today_lists_both_dailies_and_marks_them_read(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from content_studio import kline_board

    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    monkeypatch.setattr(kline_board, "KLINE_DIR", tmp_path / "kline")
    root = tmp_path / "vault-default"
    today = date.today()
    (root / "006_ai daily newsletter").mkdir(parents=True, exist_ok=True)
    (root / "006_ai daily newsletter" / f"{today:%y-%m-%d}.md").write_text("# AI 日报", encoding="utf-8")
    client.app.state.store.update_settings({"kpi": {"read_started": "2000-01-01"}})
    d = _today(client)
    items = {i["key"]: i for i in d["rd"]["items"]}
    assert items["ai_daily"]["exists"] and not items["kline_daily"]["exists"]  # K 线日报今天没出，不要求
    assert d["days"][-1]["rd"] == "pending"
    client.put("/api/today/checks", json={"day": today.isoformat(), "key": "ai_daily", "checked": True})
    assert _today(client)["days"][-1]["rd"] == "ok"
    # K 线日报出了（它自己的文件夹），就也要读
    (tmp_path / "kline").mkdir()
    (tmp_path / "kline" / f"{today:%Y-%m-%d}-kline-daily-newsletter.md").write_text("# K", encoding="utf-8")
    d = _today(client)
    assert {i["key"]: i["exists"] for i in d["rd"]["items"]}["kline_daily"] and d["days"][-1]["rd"] == "pending"
    assert client.put("/api/today/checks", json={"day": today.isoformat(), "key": "kline_daily", "checked": True}).status_code == 200
    assert _today(client)["days"][-1]["rd"] == "ok"


# -- 周历（#334）：能排一整周，能看每天做没做到、减了几分 ---------------------------------

def test_a_week_is_scored_with_the_same_rules_and_never_before_he_started() -> None:
    today = date(2026, 9, 30)  # 周三
    days = driver.kpi_range(driver.week_start(today), date(2026, 10, 4), today, posted={"2026-09-29"}, started="2026-09-29",
                            dms={"2026-09-30": {"received": 0, "replied": 0}}, x_replies={"2026-09-30": 10}, x_target=10,
                            reads={"2026-09-30": True}, read_started="2026-09-30", ship_started="2026-09-29")
    assert [d["day"][-2:] for d in days] == ["28", "29", "30", "01", "02", "03", "04"]  # 周一到周日
    by = {d["day"][-2:]: d for d in days}
    assert by["28"]["ship"] == "n/a" and by["28"]["dm"] == "n/a"  # 开始算之前：不倒扣
    assert (by["29"]["ship"], by["29"]["dm"], by["29"]["xr"], by["29"]["rd"]) == ("ok", "miss", "miss", "n/a")
    assert (by["30"]["ship"], by["30"]["dm"], by["30"]["xr"], by["30"]["rd"]) == ("pending", "ok", "ok", "ok")  # 今天没发不算减分
    assert all(by[k][f] == "future" for k in ("01", "04") for f in ("rd", "ship", "dm", "xr"))
    assert driver.demerits(days) == 2


def test_streak_says_which_line_he_is_on() -> None:
    posted = {"2026-09-24", "2026-09-29"}
    assert driver.ship_streak(date(2026, 9, 30), posted) == {"kind": "ok", "days": 1}  # 今天还没发不算断
    assert driver.ship_streak(date(2026, 9, 29), posted) == {"kind": "ok", "days": 1}
    assert driver.ship_streak(date(2026, 9, 29), {"2026-09-24"}) == {"kind": "miss", "days": 4}  # 25–28 四天没发
    assert driver.ship_streak(date(2026, 9, 30), {"2026-09-27", "2026-09-28", "2026-09-29", "2026-09-30"}) == {"kind": "ok", "days": 4}
    assert driver.ship_streak(date(2026, 9, 30), set()) == {"kind": "none", "days": 0}


def test_what_he_planned_for_the_day_comes_before_the_top_of_the_list() -> None:
    notes = [{"id": 1, "planned_day": None}, {"id": 2, "planned_day": "2026-10-03"}, {"id": 3, "planned_day": "2026-10-01"},
             {"id": 4, "planned_day": "2026-09-29"}, {"id": 5, "planned_day": None}]
    assert [n["id"] for n in driver.plan_order(notes, "2026-10-01")] == [3, 4, 1, 5, 2]  # 今天的 → 过期的 → 没排的 → 以后的
    assert [n["id"] for n in driver.plan_order(notes[:1] + notes[4:], "2026-10-01")] == [1, 5]  # 都没排：照清单顺序


def test_week_calendar_holds_the_plan_and_the_score(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import timedelta

    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    today = date.today()
    tomorrow = (today + timedelta(days=1)).isoformat()
    client.post("/api/today/notes", json={"text": "清单第一条"})
    client.post("/api/today/notes", json={"text": "排在今天的这条", "planned_day": today.isoformat()})
    d = _today(client)
    week = d["week"]
    assert week["current"] and len(week["days"]) == 7 and date.fromisoformat(week["start"]).weekday() == 0
    assert set(d) >= {"days", "demerits", "week", "streak"}  # 原来的字段还在，含义没变
    cell = next(c for c in week["days"] if c["state"] == "today")
    assert [p["text"] for p in cell["planned"]] == ["排在今天的这条"]
    assert d["ship"]["next"]["text"] == "拍「排在今天的这条」" and "排在今天" in d["ship"]["next"]["why"]
    assert [n["text"] for n in d["ship"]["notes"]] == ["清单第一条", "排在今天的这条"]  # 清单自己的顺序不动

    # 把清单第一条排到明天；再加一件不算分的事，做完勾掉
    first = d["ship"]["notes"][0]["id"]
    client.patch(f"/api/today/notes/{first}", json={"planned_day": tomorrow})
    item = client.post("/api/today/plan", json={"day": tomorrow, "text": "约两个博主诊断"}).json()["item"]
    wk = client.get("/api/today/week", params={"start": tomorrow}).json()
    cell = next(c for c in wk["days"] if c["day"] == tomorrow)
    assert [p["text"] for p in cell["planned"]] == ["清单第一条"] and cell["items"] == [{"id": item["id"], "text": "约两个博主诊断", "done": False}]
    if cell["state"] == "future":
        assert cell["ship"] == "future" and cell["demerits"] == 0
    client.patch(f"/api/today/plan/{item['id']}", json={"done": True})
    client.patch(f"/api/today/notes/{first}", json={"planned_day": ""})  # 不排了
    cell = next(c for c in client.get("/api/today/week", params={"start": tomorrow}).json()["days"] if c["day"] == tomorrow)
    assert cell["planned"] == [] and cell["items"][0]["done"] is True
    client.delete(f"/api/today/plan/{item['id']}")
    assert all(c["items"] == [] for c in client.get("/api/today/week", params={"start": tomorrow}).json()["days"])

    # 翻到上一周、下一周：都是周一开头的七天；没发过视频的时候，过去的日子不倒扣
    prev = client.get("/api/today/week", params={"start": week["prev"]}).json()
    nxt = client.get("/api/today/week", params={"start": week["next"]}).json()
    assert prev["next"] == week["start"] and nxt["prev"] == week["start"] and not prev["current"]
    assert all(c["state"] == "past" and c["ship"] == "n/a" and c["demerits"] == 0 for c in prev["days"])
    assert all(c["state"] == "future" for c in nxt["days"])
    assert client.patch(f"/api/today/notes/{first}", json={"planned_day": "下周三"}).status_code == 400


def test_past_days_show_what_went_out_and_the_demerits(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import timedelta

    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    store = client.app.state.store
    today = date.today()
    two_ago, yesterday = today - timedelta(days=2), today - timedelta(days=1)
    me = store.add_account(platform="抖音", profile_url="https://www.douyin.com/user/me", external_id="me", status="ok", is_self=True)
    store.upsert_videos(me["id"], [{"platform": "抖音", "video_id": "v1", "title": "接了一单咨询\n把这件事拍出来", "published_at": f"{two_ago.isoformat()}T10:00:00+08:00",
                                    "duration_seconds": 600, "is_top": 0, "is_image_post": 0, "likes": 1, "comments": 0, "shares": 0, "collects": 0, "views": 10}])
    d = _today(client)
    cells = {c["day"]: c for wk in (d["week"], client.get("/api/today/week", params={"start": two_ago.isoformat()}).json()) for c in wk["days"]}
    assert cells[two_ago.isoformat()]["ship"] == "ok" and cells[two_ago.isoformat()]["shipped"] == ["接了一单咨询 把这件事拍出来"]
    assert cells[yesterday.isoformat()]["ship"] == "miss" and cells[yesterday.isoformat()]["demerits"] >= 1  # 昨天没发：减分
    assert d["streak"] == {"kind": "miss", "days": 1}
    week = client.get("/api/today/week", params={"start": yesterday.isoformat()}).json()
    assert week["demerits"] == sum(c["demerits"] for c in week["days"]) and week["ship_days"] >= 1


# -- 追平阶段（9/30 Park）：每天发一条新视频，或者补发当天那几格；每周至少 3 条新的；出关 = 旧内容清完 + 连续出摊 14 天 --

def _cells(major: int, minor: int) -> list[dict]:
    return [{"video_id": f"v{i}", "platform": "x", "tier": "major"} for i in range(major)] + \
           [{"video_id": f"v{i}", "platform": "bilibili", "tier": "minor"} for i in range(minor)]


@pytest.mark.parametrize(("major", "minor", "want"), [
    (10, 10, ["major", "major", "minor", "minor"]),  # 两格重要平台 + 两格次要平台
    (1, 10, ["major", "minor", "minor", "minor"]),   # 重要的不够：次要的补齐
    (10, 0, ["major"] * 4),                          # 次要的发完了：全用重要的
    (1, 1, ["major", "minor"]),                      # 一共不到 4 格：有几格排几格
    (0, 0, []),
])
def test_pick_is_two_major_two_minor_and_fills_from_the_other_tier(major: int, minor: int, want: list[str]) -> None:
    import random

    picked = driver.pick_cells(_cells(major, minor), random.Random("2026-10-01"))
    assert sorted(c["tier"] for c in picked) == sorted(want)
    assert len({(c["video_id"], c["platform"]) for c in picked}) == len(picked)  # 同一格不会排两次


def test_pick_is_random_but_the_same_for_the_same_day_and_skips_what_is_taken() -> None:
    import random

    cells = _cells(8, 8)
    a = driver.pick_cells(cells, random.Random("2026-10-01"))
    assert a == driver.pick_cells(cells, random.Random("2026-10-01"))  # 同一天抽出来一样（存下来以后本来也不再抽）
    assert any(driver.pick_cells(cells, random.Random(f"2026-10-{d:02d}")) != a for d in range(2, 12))  # 不是固定按某个顺序
    # 同一档里尽量发到不同的平台：重要的三个平台里挑两个不同的，次要的也是
    mixed = [{"video_id": f"v{i}", "platform": pf, "tier": "major" if pf in ("x", "channels", "xiaohongshu") else "minor"}
             for i in range(6) for pf in ("x", "channels", "xiaohongshu", "bilibili", "youtube", "wechat_mp")]
    for seed in range(20):
        got = driver.pick_cells(mixed, random.Random(seed))
        assert len({c["platform"] for c in got}) == 4
    taken = {(c["video_id"], c["platform"]) for c in a}
    assert not taken & {(c["video_id"], c["platform"]) for c in driver.pick_cells(cells, random.Random(1), taken=taken)}


def test_a_backfill_day_counts_as_shipping_and_keeps_the_streak() -> None:
    today = date(2026, 10, 4)
    new_video, backfilled = {"2026-10-01", "2026-10-03"}, {"2026-10-02"}
    days = driver.kpi_range(date(2026, 9, 30), today, today, posted=new_video | backfilled, dms={}, started="9999", ship_started="2026-09-30")
    assert [(d["day"][-2:], d["ship"]) for d in days] == [("30", "miss"), ("01", "ok"), ("02", "ok"), ("03", "ok"), ("04", "pending")]
    assert driver.demerits(days) == 1 and all("bf" not in d for d in days)  # 补发不再单独算一项
    assert driver.ship_streak(today, new_video | backfilled) == {"kind": "ok", "days": 3}  # 新视频和补发交替，连续天数接着算
    assert driver.ship_streak(today, new_video) == {"kind": "ok", "days": 1}


def test_stage_is_catchup_until_backlog_is_clear_and_the_streak_is_long_enough() -> None:
    st = driver.stage(backlog=71, streak={"kind": "ok", "days": 1}, streak_target=14)
    assert (st["key"], st["backlog"], st["streak"], st["done"]) == ("catchup", 71, 1, False)
    assert driver.stage(backlog=0, streak={"kind": "ok", "days": 13}, streak_target=14)["done"] is False
    assert driver.stage(backlog=3, streak={"kind": "ok", "days": 20}, streak_target=14)["done"] is False
    assert driver.stage(backlog=0, streak={"kind": "miss", "days": 2}, streak_target=14)["streak"] == 0  # 断了就从头数
    assert driver.stage(backlog=0, streak={"kind": "ok", "days": 14}, streak_target=14)["done"] is True


def test_todays_cells_are_drawn_once_and_sending_them_all_counts_as_shipping(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_web import SEC, _wait_sync

    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    client.post("/api/accounts", json={"url": f"https://www.douyin.com/user/{SEC}", "is_self": True})
    _wait_sync(client)
    store = client.app.state.store
    today = date.today().isoformat()
    sheet = client.get("/api/backfill").json()
    old = [v for v in sheet["videos"] if not v["published_at"].startswith(today)][:2]
    keys = [p["key"] for p in sheet["platforms"]][1:]
    for i in _today(client)["rd"]["items"]:  # 今天出了的日报先读完，才轮到出摊
        if i["exists"]:
            client.put("/api/today/checks", json={"day": today, "key": i["key"], "checked": True})
    d = _today(client)
    assert d["out"]["cells"] == [] and d["out"]["mode"] is None  # 没有打好包的旧内容：今天没有能补的格子
    assert d["stage"]["backlog"] == sum(len(v["missing"]) for v in sheet["videos"])  # 旧内容按格数
    assert client.post("/api/today/cells/0/sent", json={"sent": True}).status_code == 400

    # 今天排了两格（测试里直接排上；线上是每天第一次读的时候随机抽、存下来）
    store.set_backfill_plan(today, [(old[0]["video_id"], keys[0]), (old[1]["video_id"], keys[1])])
    d = _today(client)
    assert [(c["slot"], c["platform"], c["sent"]) for c in d["out"]["cells"]] == [(0, keys[0], False), (1, keys[1], False)]
    assert _today(client)["out"]["cells"] == d["out"]["cells"]  # 再读一次：还是这两格，不重抽
    was = d["days"][-1]["ship"]
    assert driver.now_item(d)["inputs"] == "mode"  # 还没说今天发不发新的：先问

    assert client.post("/api/today/mode", json={"mode": "maybe"}).status_code == 400
    assert client.post("/api/today/mode", json={"mode": "backfill"}).json() == {"mode": "backfill"}
    d = _today(client)
    now = driver.now_item(d)
    assert d["out"]["mode"] == "backfill" and now["inputs"] == "cell" and now["slot"] == 0 and keys[0] in (now["go"] or "") + keys[0]

    client.post("/api/today/cells/0/sent", json={"sent": True})
    d = _today(client)
    assert d["out"]["sent"] == 1 and not d["out"]["done"] and d["days"][-1]["ship"] == was  # 只发了一格：还不算
    assert driver.now_item(d)["slot"] == 1
    client.post("/api/today/cells/1/sent", json={"sent": True})
    d = _today(client)
    if was != "ok":  # 今天没发新视频：补发的格子都发完，就算出摊，连续天数接着算
        assert d["out"]["done"] and d["days"][-1]["ship"] == "ok" and d["streak"]["kind"] == "ok"
        assert next(c for c in d["week"]["days"] if c["state"] == "today")["backfilled"] is True
        assert "补发的 2 格都发完了" in client.get("/api/wendy/brief").json()["text"]
    # 点错了撤回：这一天又不算了
    client.post("/api/today/cells/1/sent", json={"sent": False})
    d = _today(client)
    assert d["out"]["sent"] == 1 and not d["out"]["done"] and d["days"][-1]["ship"] == was


def test_three_new_videos_a_week_is_only_charged_after_the_week_ends_and_never_backdated(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    store = client.app.state.store
    d = _today(client)
    week = d["week"]
    assert (week["new_videos"], week["new_target"], week["new_short"]) == (0, 3, 0)  # 这一周还没过完：只看进度，不扣
    prev = client.get("/api/today/week", params={"start": week["prev"]}).json()
    assert prev["new_short"] == 0 and not prev["new_counts"]  # 定规矩之前的周：不倒扣
    cur = store.settings()["kpi"]
    store.update_settings({"kpi": {**cur, "new_weekly_started": "2000-01-03"}})
    prev = client.get("/api/today/week", params={"start": week["prev"]}).json()
    assert prev["new_counts"] and prev["new_short"] == 3 and prev["demerits"] == sum(c["demerits"] for c in prev["days"]) + 3
    assert client.get("/api/today/week", params={"start": week["start"]}).json()["new_short"] == 0
    brief = client.get("/api/wendy/brief").json()["text"]
    assert "[本周新视频] 0/3 条，周日前还差 3 条" in brief and "[现在在哪个阶段] 追平" in brief
