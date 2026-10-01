"""Wendy 卡片（#338）：现在做哪一件、她说过的话、在卡片里回她、什么时候去微信催。"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import json
import time

import pytest
from fastapi.testclient import TestClient

from content_studio import consult, driver, wendy
from tests.test_web import client  # noqa: F401 - fixture

NOON = datetime(2026, 10, 1, 13, 0)


@pytest.mark.parametrize(
    ("kw", "due"),
    [
        # 算分的事还没做完，他和她都三小时以上没动静：催
        ({"pending": ["出摊"], "last_activity": NOON - timedelta(hours=4), "last_contact": NOON - timedelta(hours=3, minutes=15), "nudges_today": 0}, True),
        # 今天一点动静都没有，她也没找过他：催
        ({"pending": ["出摊"], "last_activity": None, "last_contact": None, "nudges_today": 0}, True),
        # 都做完了：不催
        ({"pending": [], "last_activity": None, "last_contact": None, "nudges_today": 0}, False),
        # 他一小时前刚动过：不催
        ({"pending": ["出摊"], "last_activity": NOON - timedelta(hours=1), "last_contact": NOON - timedelta(hours=5), "nudges_today": 0}, False),
        # 她半小时前刚催过（他一直没动）：不连着催，一个钟头把三次用完就没意义了
        ({"pending": ["出摊"], "last_activity": NOON - timedelta(hours=6), "last_contact": NOON - timedelta(minutes=30), "nudges_today": 1}, False),
        # 一天最多三次
        ({"pending": ["出摊"], "last_activity": NOON - timedelta(hours=9), "last_contact": NOON - timedelta(hours=4), "nudges_today": 3}, False),
    ],
)
def test_nudge_only_after_three_quiet_hours_and_at_most_three_a_day(kw: dict, due: bool) -> None:
    assert wendy.nudge_due(NOON, **kw)["due"] is due


def test_no_nudge_outside_ten_to_ten() -> None:
    quiet = {"pending": ["出摊"], "last_activity": None, "last_contact": None, "nudges_today": 0}
    assert wendy.nudge_due(datetime(2026, 10, 1, 9, 59), **quiet)["due"] is False
    assert wendy.nudge_due(datetime(2026, 10, 1, 10, 0), **quiet)["due"] is True
    assert wendy.nudge_due(datetime(2026, 10, 1, 21, 59), **quiet)["due"] is True
    assert wendy.nudge_due(datetime(2026, 10, 1, 22, 0), **quiet)["due"] is False


def test_now_item_is_the_first_unfinished_thing_in_page_order() -> None:
    base = {"first": [], "rd": {"items": [{"label": "AI 日报", "exists": True, "read_at": None}, {"label": "K 线日报", "exists": False, "read_at": None}]},
            "ship": {"done": False, "next": driver.item("ship", "note:1", "拍「接了一单咨询」")}, "days": [{"dm": "pending", "xr": "pending"}],
            "dm": {"entry": None}, "xr": {"count": 4, "target": 10}, "wrap": [driver.item("wrap", "reach", "填播放")]}
    assert driver.now_item({**base, "first": [driver.item("blocker", "cookies", "抖音登录过期了")]})["row"] == "first"
    now = driver.now_item(base)
    assert now["row"] == "rd" and "AI 日报" in now["text"] and "K 线" not in now["text"]  # 没出的那份不用读
    read = {**base, "rd": {"items": [{"label": "AI 日报", "exists": True, "read_at": "x"}]}}
    assert driver.now_item(read)["text"] == "拍「接了一单咨询」"
    shipped = {**read, "ship": {"done": True, "next": None}}
    assert driver.now_item(shipped)["row"] == "dm" and "填上" in driver.now_item(shipped)["text"]
    replied = {**shipped, "days": [{"dm": "ok", "xr": "pending"}]}
    assert driver.now_item(replied)["text"] == "X 互动：还差 6 条"
    done = {**replied, "days": [{"dm": "ok", "xr": "ok"}]}
    assert driver.now_item(done)["row"] == "wrap"
    assert driver.now_item({**done, "wrap": []}) is None  # 都做完了：没有在等他的事


def _hermes(home, job_name: str, stamp: str, response: str) -> None:
    (home / "cron" / "output" / "j1").mkdir(parents=True, exist_ok=True)
    (home / "cron" / "jobs.json").write_text(json.dumps({"jobs": [{"id": "j1", "name": job_name}, {"id": "j2", "name": "别人的任务"}]}), encoding="utf-8")
    (home / "cron" / "output" / "j1" / f"{stamp}.md").write_text(f"# Cron Job: {job_name}\n\n## Prompt\n\n……\n\n## Response\n\n{response}\n", encoding="utf-8")


def test_what_she_said_on_wechat_is_read_not_rewritten(tmp_path) -> None:
    now = datetime(2026, 10, 1, 10, 0)
    assert wendy.hermes_messages(tmp_path, now=now) == []  # 没装 Hermes：空的，不报错
    _hermes(tmp_path, "wendy-morning", "2026-10-01_09-45-03", "连续出摊 2 天。今天拍的是「接了一单咨询」。")
    _hermes(tmp_path, "wendy-morning", "2026-09-20_09-45-03", "太早的不读")
    _hermes(tmp_path, "wendy-morning", "2026-10-01_09-50-00", "[SILENT]")
    said = wendy.hermes_messages(tmp_path, now=now)
    assert [(m["label"], m["text"]) for m in said] == [("早上", "连续出摊 2 天。今天拍的是「接了一单咨询」。")]
    assert said[0]["at"].startswith("2026-10-01T09:45:03")


def test_card_shows_now_and_answers_in_place(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    client.post("/api/today/notes", json={"text": "接了一单咨询，拍出来", "planned_day": date.today().isoformat()})
    stamp = datetime.now().replace(hour=0, minute=1, second=0).strftime("%Y-%m-%d_%H-%M-%S")
    _hermes(tmp_path / "hermes", "wendy-morning", stamp, "今天拍的是「接了一单咨询」。")
    for i in client.get("/api/today").json()["rd"]["items"]:  # 今天出了的日报先读完，才轮到出摊
        if i["exists"]:
            client.put("/api/today/checks", json={"day": date.today().isoformat(), "key": i["key"], "checked": True})
    card = client.get("/api/wendy").json()
    assert card["now"]["text"] == "拍「接了一单咨询，拍出来」" and card["now"]["row"] == "ship"
    assert [m["text"] for m in card["messages"]] == ["今天拍的是「接了一单咨询」。"] and card["messages"][0]["source"] == "wendy-morning"

    assert client.post("/api/wendy", json={"message": "下午三点拍"}).json()["started"]
    for _ in range(50):
        card = client.get("/api/wendy").json()
        if not card["busy"]:
            break
        time.sleep(0.05)
    assert [(m["who"], m["text"]) for m in card["messages"][-2:]] == [("park", "下午三点拍"), ("wendy", "连续 1 天没出摊。今天几点拍？")]
    assert client.post("/api/wendy", json={"message": "x" * 2001}).status_code == 400

    brief = client.get("/api/wendy/brief").json()["text"]
    assert "[现在做这一件] 拍「接了一单咨询，拍出来」" in brief and "这一周（周一起）" in brief
    assert "Park：下午三点拍" in brief  # 微信那边的她读这一段，才知道他在卡片里回过什么
    assert "周复盘" in client.get("/api/wendy/brief", params={"review": True}).json()["text"]


def test_a_reply_on_the_card_counts_as_activity_and_nudges_are_counted(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    store = client.app.state.store
    today = date.today().isoformat()
    assert store.last_touch(today) is None  # 打开页面不算动静
    verdict = client.get("/api/wendy/nudge").json()
    assert "出摊" in verdict["pending"] and verdict["nudges_today"] == 0
    store.add_wendy("park", "三点拍")
    assert store.last_touch(today) is not None
    assert client.get("/api/wendy/nudge").json()["due"] is False  # 他刚回过：不催
    assert client.post("/api/wendy/nudge").json()["nudges_today"] == 1
    assert client.get("/api/wendy").json()["nudges"] and client.get("/api/wendy/nudge").json()["nudges_today"] == 1
    # 微信里刚说过话也算动静（那边传过来的时间）
    quiet = client.get("/api/wendy/nudge", params={"wechat_at": datetime.now().isoformat()}).json()
    assert quiet["due"] is False
def test_card_asks_first_then_walks_him_through_the_path_he_chose() -> None:
    cells = [{"slot": 0, "title": "how to be successful", "label": "小红书", "topic_id": 36, "sent": True},
             {"slot": 1, "title": "为什么AI重度用户劝你考公", "label": "X", "topic_id": 37, "sent": False}]
    t = {"first": [], "rd": {"items": []}, "ship": {"done": False, "next": driver.item("ship", "note:1", "拍「接了一单咨询」")},
         "days": [{"ship": "pending", "dm": "ok", "xr": "ok"}], "dm": {}, "xr": {}, "wrap": [], "out": {"mode": None, "cells": cells}}
    ask = driver.now_item(t)
    assert ask["inputs"] == "mode" and "发不发新视频" in ask["text"]  # 早上先问
    fill = driver.now_item({**t, "out": {"mode": "backfill", "cells": cells}})
    assert fill["inputs"] == "cell" and fill["slot"] == 1 and "考公" in fill["text"] and "X" in fill["text"] and fill["go"] == "publish/37"
    assert driver.now_item({**t, "out": {"mode": "new", "cells": cells}})["text"] == "拍「接了一单咨询」"
    assert driver.now_item({**t, "out": {"mode": None, "cells": []}})["text"] == "拍「接了一单咨询」"  # 没有能补的：只有一条路
    # 补发的格子都发完了：今天算出摊，不再让他去拍
    assert driver.now_item({**t, "days": [{"ship": "ok", "dm": "ok", "xr": "ok"}], "out": {"mode": "backfill", "cells": cells}}) is None


def test_on_the_positioning_page_she_gets_his_positioning_and_talks_direction() -> None:
    today_talk = wendy.compose("今天的账", [], "今晚不拍了")
    assert "<定位>" not in today_talk and "Park：今晚不拍了" in today_talk
    north_talk = wendy.compose("今天的账", [], "我到底卖什么", north="## 三、我卖给客户什么\n商业诊断，然后由我做出来。")
    assert north_talk.index("<定位>") < north_talk.index("<工作台>") and "商业诊断" in north_talk and "定方向模式" in north_talk
    assert "哪一问现在最不清楚" in wendy.compose("账", [], "", north="三问")  # 没说话点「让她看一眼」：说定位，不说今天做哪件


def test_a_reply_from_the_positioning_page_reaches_her_with_the_page(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    assert client.post("/api/wendy", json={"message": "我到底卖什么", "page": "positioning"}).json()["started"]
    for _ in range(50):
        card = client.get("/api/wendy").json()
        if not card["busy"]:
            break
        time.sleep(0.05)
    assert card["error"] is None and [m["who"] for m in card["messages"][-2:]] == ["park", "wendy"]
