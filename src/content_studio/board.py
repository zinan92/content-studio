"""The processing board: where each video in progress sits, derived from facts on disk.

Stages follow the shoot: 提纲 → 录制 → 剪辑 → 待发. Nothing asks Park to move a card;
the outline file, the linked project and its 14-step evidence decide the column.
"""
from __future__ import annotations

from typing import Any

STAGES = (
    ("outline", "提纲"),
    ("record", "录制"),
    ("edit", "剪辑"),
    ("ready", "待发"),
)


def is_shipped(topic: dict[str, Any]) -> bool:
    # Only a linked Douyin video ships a card; status=published can mean the article went out first.
    return bool(topic.get("published_video_id"))


def stage_for(topic: dict[str, Any], project: dict[str, Any] | None) -> str:
    if project and project.get("delivered"):
        return "ready"
    if project and (project.get("current_step") or 0) >= 3:
        return "edit"
    if project and project.get("layout") == "legacy":
        return "edit"
    if topic.get("outline_path") or project:
        return "record"
    return "outline"


def next_action(topic: dict[str, Any], stage: str, project: dict[str, Any] | None, opening: dict[str, Any] | None, qa: dict[str, Any] | None = None) -> dict[str, Any]:
    """One line telling Park what this card is waiting for, and whether it is waiting on him."""
    if topic.get("outline_state") == "running":
        return {"text": "提纲生成中", "mine": False}
    if topic.get("outline_state") == "failed":
        return {"text": "提纲生成失败，点开重试", "mine": True}
    if stage == "outline":
        return {"text": "写拍摄提纲", "mine": True}
    if stage == "record":
        if not project:
            # A verdict of thin/patch means the outline exists but the QA gate hasn't cleared it —
            # "提纲好了" would tell Park it's ready when the QA panel right below says the opposite.
            if qa and qa.get("verdict") == "thin":
                return {"text": "素材太薄，先补一处再录", "mine": True}
            if qa and qa.get("verdict") == "patch":
                return {"text": "三点没过，先补再录", "mine": True}
            return {"text": "提纲好了，可以录", "mine": True}
        return {"text": "录完把粗剪和字幕放进项目文件夹", "mine": True}
    if project and project.get("gate"):
        gate = project["gate"]
        return {"text": f"等你拍板：{gate['key']} {gate['title']}", "mine": True}
    if stage == "edit":
        return {"text": project.get("summary") or "剪辑中", "mine": False}
    if opening is not None and not opening.get("passed"):
        return {"text": "开头 15 秒没过，发之前看一眼", "mine": True}
    return {"text": "成片好了，去发", "mine": True}


def card(topic: dict[str, Any], project: dict[str, Any] | None, opening: dict[str, Any] | None = None, qa: dict[str, Any] | None = None) -> dict[str, Any]:
    stage = stage_for(topic, project)
    return {
        "id": topic["id"],
        "title": topic["title"],
        "stage": stage,
        "created_at": topic["created_at"],
        "updated_at": topic.get("updated_at"),
        "has_outline": bool(topic.get("outline_path")),
        "has_article": bool(topic.get("article_path")),
        "project": {k: project.get(k) for k in ("name", "summary", "current_step", "delivered")} if project else None,
        "gate": project.get("gate") if project else None,
        "opening": {"passed": opening.get("passed"), "stated_at": opening.get("stated_at")} if opening else None,
        "qa": {"total": qa.get("total"), "verdict": qa.get("verdict")} if qa else None,
        "next": next_action(topic, stage, project, opening, qa),
    }
