"""Today's production line: which steps of Park's content day are done.

Every rule reads stored facts (checks, triage, topics, reports) so the page never
asks Park to tick something the workbench can already see.
"""
from __future__ import annotations

from datetime import date, datetime
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
) -> list[dict[str, Any]]:
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
    steps.append(
        {
            "key": "video",
            "title": "拍视频 → 抖音",
            "done": bool(shot),
            "manual": True,
            "detail": "今天拍完了" if shot else (f"可以拍：{video_topics[0]['title'][:24]}" if video_topics else "拍完手动勾上"),
            "go": "topics",
        }
    )

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
