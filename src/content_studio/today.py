"""Today's production line: which steps of Park's content day are done.

Every rule reads stored facts (checks, triage, topics, reports) so the page never
asks Park to tick something the workbench can already see.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any


def _day(iso: str | None) -> str | None:
    if not iso:
        return None
    try:
        parsed = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso[:10]
    return parsed.astimezone().date().isoformat() if parsed.tzinfo else parsed.date().isoformat()


def build_plan(
    *,
    today: date,
    dailies: list[dict[str, Any]] | None,
    inbox: list[dict[str, Any]] | None,
    topics: list[dict[str, Any]],
    reports: list[dict[str, Any]],
    checks: dict[str, str],
    briefing: dict[str, Any] | None = None,
    video_states: dict[int, dict[str, Any]] | None = None,
    followups: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """video_states: topic_id → inspected project summary; followups: published videos needing attention."""
    video_states = video_states or {}
    day = today.isoformat()
    steps: list[dict[str, Any]] = []

    if dailies is None:
        steps.append({"key": "read", "title": "看日报", "done": False, "detail": "没连上 Obsidian 库，去设置里填路径", "go": "settings"})
    else:
        ready = [d for d in dailies if d.get("path")]
        unread = [d["label"] for d in ready if not d.get("checked_at")]
        if not ready:
            detail = "今天的日报还没出"
        elif unread:
            detail = f"还没看：{'、'.join(unread)}"
        else:
            detail = f"{len(ready)} 份都看完了"
        steps.append({"key": "read", "title": "看日报", "done": bool(ready) and not unread, "detail": detail, "go": "today"})

    record = briefing or {}
    if record.get("state") == "done" and record.get("data"):
        primary = next((v for v in record["data"].get("videos", []) if v.get("primary")), None)
        steps.append({"key": "brief", "title": "看今日统筹", "done": True, "detail": f"首选：{primary['title'][:28]}" if primary else "今天的统筹已生成", "go": "brief"})
    elif record.get("state") == "running":
        steps.append({"key": "brief", "title": "看今日统筹", "done": False, "detail": "正在统筹今天的内容", "go": "brief"})
    else:
        detail = f"上次生成失败：{(record.get('error') or '')[:40]}" if record.get("state") == "failed" else "还没生成：读日报和笔记，告诉你今天拍什么"
        steps.append({"key": "brief", "title": "看今日统筹", "done": False, "detail": detail, "go": "brief"})

    if inbox is None:
        steps.append({"key": "triage", "title": "回顾进项", "done": False, "detail": "没连上 Obsidian 库", "go": "settings"})
    else:
        pending = [i for i in inbox if not i.get("triage")]
        detail = f"昨天到现在新进 {len(inbox)} 条，还有 {len(pending)} 条没处理" if pending else (f"{len(inbox)} 条都处理完了" if inbox else "昨天到现在没有新进项")
        steps.append({"key": "triage", "title": "回顾进项", "done": not pending, "detail": detail, "go": "collect"})

    active = [t for t in topics if t["status"] != "published" and not t.get("archived_at")]
    carried = [t for t in active if (_day(t["created_at"]) or day) < day]
    if active:
        detail = f"进行中 {len(active)} 个" + (f"（{len(carried)} 个是之前留下的）" if carried else "") + f"：{active[0]['title'][:24]}"
    else:
        detail = "还没有选题：从进项或热点里挑一条"
    steps.append({"key": "pick", "title": "选今天做的", "done": bool(active) or any(_day(t.get("published_at")) == day for t in topics), "detail": detail, "go": "topics"})

    article_topics = [t for t in topics if t["formats"] in ("article", "both") and not t.get("archived_at")]
    published_today = [t for t in article_topics if _day(t.get("published_at")) == day]
    drafted = [t for t in article_topics if t["status"] in ("drafting", "ready") and t.get("article_path")]
    if published_today:
        detail, done = f"今天已发出：{published_today[0]['title'][:24]}", True
    elif drafted:
        detail, done = f"草稿写好了，待你看完交给研习室：{drafted[0]['title'][:24]}", False
    elif article_topics:
        detail, done = "有选题还没写：点「写文章」让卡兹克写作出草稿", False
    else:
        detail, done = "先选一个要写成文章的选题", False
    steps.append({"key": "article", "title": "写文章 → 研习室", "done": done, "detail": detail, "go": "topics"})

    shot = checks.get("video_shot")
    video_topics = [t for t in active if t["formats"] in ("video", "both")]
    video_published_today = [t for t in topics if t["formats"] in ("video", "both") and t.get("published_video_id") and _day(t.get("published_at")) == day]
    gated = [(t, video_states[t["id"]]) for t in video_topics if video_states.get(t["id"], {}).get("gate")]
    video_step: dict[str, Any] = {"key": "video", "title": "拍视频 → 剪辑", "manual": True, "go": "video", "done": bool(shot) or bool(video_published_today)}
    if gated:
        topic, state = gated[0]
        video_step.update(detail=f"需要你：{state['gate']['key']} {state['gate']['title']}（{topic['title'][:16]}）", attention=True, done=False)
    elif video_published_today:
        video_step["detail"] = f"今天已发出：{video_published_today[0]['title'][:24]}"
    elif shot:
        video_step["detail"] = "今天拍完了"
    elif not video_topics:
        video_step["detail"] = "还没有视频选题：从今日统筹里挑一条"
    else:
        topic = video_topics[0]
        state = video_states.get(topic["id"])
        if state and state.get("delivered"):
            video_step["detail"] = f"成片好了，去发：{topic['title'][:24]}"
        elif state and state.get("current_step"):
            video_step["detail"] = f"剪辑中 · {state['summary']}（{topic['title'][:14]}）"
        elif topic.get("video_project"):
            video_step["detail"] = f"录完把粗剪和字幕放进项目文件夹：{topic['title'][:20]}"
        elif topic.get("outline_path"):
            video_step["detail"] = f"提纲写好了，可以录：{topic['title'][:24]}"
        else:
            video_step["detail"] = f"先写拍摄提纲：{topic['title'][:24]}"
    steps.append(video_step)

    pending = [f for f in (followups or []) if f.get("suggest_teardown")]
    watching = [f for f in (followups or []) if not f.get("suggest_teardown")]
    if pending:
        steps.append({"key": "data", "title": "发出后看数据", "done": False, "go": "video", "attention": False,
                      "detail": f"《{pending[0]['title'][:18]}》发出满 48 小时，拆解看看为什么好 / 不好"})
    elif watching:
        f = watching[0]
        steps.append({"key": "data", "title": "发出后看数据", "done": False, "go": "video",
                      "detail": f"《{f['title'][:18]}》发出 {int(f['hours_since'] or 0)} 小时，{f['likes'] or 0} 赞" + (f"，{f['multiple']}×" if f.get("multiple") else "")})
    else:
        steps.append({"key": "data", "title": "发出后看数据", "done": True, "go": "video", "detail": "没有待跟进的已发视频"})

    unread = [r for r in reports if not r.get("archived_at")]
    archived_today = [r for r in reports if _day(r.get("archived_at")) == day]
    steps.append(
        {
            "key": "review",
            "title": "复盘",
            "done": not unread or bool(archived_today),
            "detail": (f"今天看完 {len(archived_today)} 份报告" if archived_today else f"有 {len(unread)} 份拆解报告没看") if unread else "拆解报告都看完了",
            "go": "report",
        }
    )
    return steps


# Three things decide Park's day: read, shoot, ship. Every other step is shown under one of them.
GROUPS = (
    ("read", "读", "brief", ("read", "brief", "triage")),
    ("shoot", "拍", "video", ("pick", "video")),
    ("ship", "发", "data", ("data", "article", "review")),
)


def group_plan(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {s["key"]: s for s in steps}
    groups = []
    for key, title, core_key, members in GROUPS:
        sub = [by_key[k] for k in members if k in by_key]
        core = by_key.get(core_key) or sub[0]
        lead = next((s for s in sub if s.get("attention")), None) or core
        groups.append({"key": key, "title": title, "done": core["done"], "detail": lead["detail"], "go": lead.get("go"),
                       "attention": any(s.get("attention") for s in sub), "manual": core.get("manual", False), "manual_key": core_key if core.get("manual") else None,
                       "sub": [{"key": s["key"], "title": s["title"], "done": s["done"], "detail": s["detail"], "go": s.get("go")} for s in sub if s is not lead]})
    return groups


def shooting_streak(today: date, shot_days: set[str]) -> dict[str, Any]:
    """Consecutive days with a shoot or a published video, counting back from today (or yesterday if today is still open)."""
    today_done = today.isoformat() in shot_days
    cursor = today if today_done else today - timedelta(days=1)
    days = 0
    while cursor.isoformat() in shot_days:
        days += 1
        cursor -= timedelta(days=1)
    last = max((d for d in shot_days if d <= today.isoformat()), default=None)
    gap = (today - date.fromisoformat(last)).days if last else None
    return {"days": days, "today_done": today_done, "broken": not today_done and days == 0, "last_day": last, "days_since_last": gap}
