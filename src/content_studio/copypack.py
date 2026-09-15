"""Publishing title and 简介 for one topic, plus where it has been published.

Park writes one title and one short 简介 shared by every platform (the page saves the
same entry under each platform key, which the publisher reads). Nothing here
generates copy or publishes. Limits are conservative caps; X counts CJK as two.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

PLATFORMS: dict[str, dict[str, Any]] = {
    "douyin": {"label": "抖音", "title": 30, "body": 1000, "tags": 5, "admin": "https://creator.douyin.com/creator-micro/content/upload"},
    "channels": {"label": "视频号", "title": 16, "body": 1000, "tags": 5, "admin": "https://channels.weixin.qq.com/platform/post/create"},
    "xiaohongshu": {"label": "小红书", "title": 20, "body": 1000, "tags": 10, "admin": "https://creator.xiaohongshu.com/publish/publish"},
    "bilibili": {"label": "B 站", "title": 80, "body": 2000, "tags": 10, "admin": "https://member.bilibili.com/platform/upload/video/frame"},
    "youtube": {"label": "YouTube", "title": 100, "body": 5000, "tags": 15, "admin": "https://studio.youtube.com/"},
    "x": {"label": "X", "title": 0, "body": 280, "tags": 3, "admin": "https://x.com/compose/post", "weighted": True},
    "yanxishi": {"label": "研习室", "title": 64, "body": 200, "tags": 5, "admin": None},
}


def x_length(text: str) -> int:
    return sum(2 if re.match(r"[⺀-鿿＀-￯　-〿]", ch) else 1 for ch in text)


def measure(platform: str, entry: dict[str, Any]) -> list[str]:
    spec = PLATFORMS[platform]
    problems = []
    title = str(entry.get("title") or "")
    body = str(entry.get("body") or "")
    tags = entry.get("tags") or []
    if spec["title"] and not title.strip():
        problems.append(f"{spec['label']}缺标题")
    if spec["title"] and len(title) > spec["title"]:
        problems.append(f"{spec['label']}标题 {len(title)} 字，超过 {spec['title']}")
    if not spec["title"] and title:
        problems.append(f"{spec['label']}不需要标题")
    length = x_length(body + " " + " ".join(f"#{t}" for t in tags)) if spec.get("weighted") else len(body)
    if not body.strip():
        problems.append(f"{spec['label']}缺正文")
    elif length > spec["body"]:
        problems.append(f"{spec['label']}正文长度 {length}，超过 {spec['body']}")
    if not isinstance(tags, list) or len(tags) > spec["tags"] or any(not str(t).strip() or "#" in str(t) for t in tags):
        problems.append(f"{spec['label']}话题最多 {spec['tags']} 个，不带 #")
    return problems


def save_copy(drafts_dir: Path, topic_id: int, copy: dict[str, Any]) -> Path:
    folder = drafts_dir.expanduser() / f"topic-{topic_id}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "copy.json"
    payload = {"updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "platforms": copy}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_copy(drafts_dir: Path, topic_id: int) -> dict[str, Any] | None:
    path = drafts_dir.expanduser() / f"topic-{topic_id}" / "copy.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    data["checks"] = {key: measure(key, entry) for key, entry in data["platforms"].items() if key in PLATFORMS}
    return data
