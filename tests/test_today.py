from __future__ import annotations

from datetime import date

from content_studio.today import build_plan

DAY = date(2026, 9, 14)


def _topic(**overrides):
    base = {"id": 1, "title": "AI 越强越瞎忙", "formats": "both", "status": "todo", "article_path": None,
            "published_at": None, "created_at": "2026-09-14T01:00:00+00:00", "archived_at": None}
    base.update(overrides)
    return base


def _plan(**kw):
    args = dict(today=DAY, dailies=[], inbox=[], topics=[], reports=[], checks={})
    args.update(kw)
    return {s["key"]: s for s in build_plan(**args)}


def test_empty_day_is_all_open_with_guidance() -> None:
    plan = _plan()
    assert list(plan) == ["read", "brief", "triage", "pick", "article", "video", "data", "review"]
    assert plan["brief"]["done"] is False and plan["data"]["done"] is True
    assert plan["read"]["done"] is False and "还没出" in plan["read"]["detail"]
    assert plan["triage"]["done"] is True
    assert plan["pick"]["done"] is False
    assert plan["review"]["done"] is True


def test_reading_requires_every_existing_daily_checked() -> None:
    dailies = [{"key": "a", "label": "AI 日报", "path": "x.md", "checked_at": "t"}, {"key": "b", "label": "晨报", "path": "y.html", "checked_at": None},
               {"key": "c", "label": "财经日报", "path": None, "checked_at": None}]
    assert "晨报" in _plan(dailies=dailies)["read"]["detail"]
    dailies[1]["checked_at"] = "t"
    assert _plan(dailies=dailies)["read"]["done"] is True


def test_triage_counts_pending_items() -> None:
    plan = _plan(inbox=[{"triage": None}, {"triage": "ignored"}, {"triage": "topic"}])
    assert plan["triage"]["done"] is False and "还有 1 条" in plan["triage"]["detail"]


def test_topics_carry_over_and_article_progress() -> None:
    old = _topic(created_at="2026-09-12T01:00:00+00:00")
    plan = _plan(topics=[old])
    assert plan["pick"]["done"] is True and "之前留下" in plan["pick"]["detail"]
    assert plan["article"]["done"] is False and "还没写" in plan["article"]["detail"]
    drafted = _topic(status="ready", article_path="/tmp/a.md")
    assert "草稿写好了" in _plan(topics=[drafted])["article"]["detail"]
    published = _topic(status="published", published_at="2026-09-14T08:00:00+00:00")
    plan = _plan(topics=[published])
    assert plan["article"]["done"] is True and plan["pick"]["done"] is True


def test_video_is_manual_and_review_follows_reports() -> None:
    assert _plan(checks={"video_shot": "t"})["video"]["done"] is True
    plan = _plan(reports=[{"archived_at": None}, {"archived_at": None}])
    assert plan["review"]["done"] is False and "2 份" in plan["review"]["detail"]
    assert _plan(reports=[{"archived_at": None}, {"archived_at": "2026-09-14T03:00:00+00:00"}])["review"]["done"] is True


def test_missing_vault_points_to_settings() -> None:
    plan = _plan(dailies=None, inbox=None)
    assert plan["read"]["go"] == "settings" and plan["triage"]["done"] is False


def test_briefing_step_reflects_state() -> None:
    done = {"state": "done", "data": {"videos": [{"title": "首选这条", "primary": True}]}}
    assert _plan(briefing=done)["brief"]["detail"] == "首选：首选这条"
    assert "失败" in _plan(briefing={"state": "failed", "error": "boom"})["brief"]["detail"]


def test_video_step_walks_the_video_line() -> None:
    base = _topic(formats="video")
    assert "先写拍摄提纲" in _plan(topics=[base])["video"]["detail"]
    assert "可以录" in _plan(topics=[_topic(formats="video", outline_path="/o.md")])["video"]["detail"]
    linked = _topic(formats="video", outline_path="/o.md", video_project="p")
    assert "粗剪" in _plan(topics=[linked])["video"]["detail"]
    gate = {"gate": {"key": "H1", "title": "等你在 worktable 里选 Hook"}, "summary": "Step 5", "current_step": 5}
    plan = _plan(topics=[linked], video_states={1: gate})
    assert plan["video"]["attention"] is True and "H1" in plan["video"]["detail"]
    assert "剪辑中" in _plan(topics=[linked], video_states={1: {"summary": "Step 9：成品 A 与 QA", "current_step": 9, "gate": None}})["video"]["detail"]
    assert "成片好了" in _plan(topics=[linked], video_states={1: {"delivered": True, "gate": None}})["video"]["detail"]
    published = _topic(formats="video", status="published", published_video_id="9", published_at="2026-09-14T08:00:00+00:00")
    assert _plan(topics=[published])["video"]["done"] is True


def test_data_step_prioritises_teardown() -> None:
    followups = [{"title": "刚发的", "hours_since": 10, "likes": 300, "multiple": 1.2, "suggest_teardown": False},
                 {"title": "发了三天", "hours_since": 70, "likes": 900, "multiple": 3.1, "suggest_teardown": True}]
    step = _plan(followups=followups)["data"]
    assert step["done"] is False and "满 48 小时" in step["detail"] and "发了三天" in step["detail"]
    assert "10 小时" in _plan(followups=followups[:1])["data"]["detail"]


def test_plan_groups_into_read_shoot_ship_with_attention_first() -> None:
    from content_studio.today import group_plan

    steps = build_plan(today=DAY, dailies=[], inbox=[], topics=[_topic(formats="video", video_project="p")], reports=[], checks={},
                       video_states={1: {"gate": {"key": "H1", "title": "选 Hook"}}})
    groups = group_plan(steps)
    assert [g["title"] for g in groups] == ["读", "拍", "发"]
    shoot = groups[1]
    assert shoot["attention"] and "H1" in shoot["detail"] and shoot["go"] == "video"
    assert {s["key"] for s in shoot["sub"]} == {"pick"}
    assert sum(len(g["sub"]) + 1 for g in groups) == len(steps)


def test_shooting_streak_counts_back_and_flags_a_broken_chain() -> None:
    from content_studio.today import shooting_streak

    days = {"2026-09-12", "2026-09-13", "2026-09-14"}
    assert shooting_streak(DAY, days) == {"days": 3, "today_done": True, "broken": False, "last_day": "2026-09-14", "days_since_last": 0}
    open_today = shooting_streak(date(2026, 9, 15), days)
    assert open_today["days"] == 3 and not open_today["broken"]
    broken = shooting_streak(date(2026, 9, 17), days)
    assert broken["days"] == 0 and broken["broken"] and broken["days_since_last"] == 3
    assert shooting_streak(DAY, set())["last_day"] is None
