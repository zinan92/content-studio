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
    assert list(plan) == ["read", "triage", "pick", "article", "video", "review"]
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
