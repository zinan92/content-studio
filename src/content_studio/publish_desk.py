"""发布台：一条内容 × 每个平台，一眼看出哪个发了、哪个没发、哪个要你动手。

Park 的比喻是「把每个平台的上传页截个图铺开，没发的是灰的，发了的变彩色」。
这里只算数据；每个平台长什么样在前端画。三种对待方式（treatment）来自通道本身：

- manual   没有通道：复制文案、打开平台、发完回来记一笔（抖音、小红书、小宇宙…）
- scan     有通道但靠扫码登录的 cookie：登录还在就机器发，过期了就要重扫（B 站、YouTube、视频号）
- auto     密钥在文件里、不用登录：直接发（X）
- handoff  工作台只负责到正文，交给既有管线（公众号）
"""
from __future__ import annotations

from typing import Any

TREATMENT_LABEL = {"manual": "手动上传", "scan": "扫码后机器发", "auto": "全自动", "handoff": "交给流水线"}
# 待发 → 剪辑 → 录制 → 提纲：越接近能发的越靠前；已发出的排最后，只留最近的。
STAGE_ORDER = {"ready": 0, "edit": 1, "record": 2, "outline": 3, "shipped": 9}
SHARED_KEYS = ("douyin", "channels", "bilibili", "youtube")


def treatment(key: str, spec: dict[str, Any] | None) -> str:
    if spec is None:
        return "manual"
    if spec.get("needs_keys"):
        return "auto"
    return "scan"


def shared_entry(copy: dict[str, Any] | None) -> dict[str, Any]:
    """标题和简介所有平台共用：取第一个写了东西的平台。"""
    platforms = (copy or {}).get("platforms") or {}
    for key in [*SHARED_KEYS, *platforms]:
        entry = platforms.get(key)
        if entry and (entry.get("title") or entry.get("body")):
            return {"title": entry.get("title") or "", "body": entry.get("body") or "", "tags": list(entry.get("tags") or [])}
    return {"title": "", "body": "", "tags": []}


def fill_for(spec: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    """按这个平台的上限裁好，前端每个空一个「复制」。"""
    from .copypack import title_units

    cap_title = int(spec.get("title") or 0)
    units = title_units(entry["title"], spec)
    keep = spec.get("no_trim")  # 小红书：不替他截，超了提醒他自己删
    return {
        "title": (entry["title"] if keep else entry["title"][:cap_title]) if cap_title else "",
        "body": entry["body"][: int(spec.get("body") or 0)],
        "tags": entry["tags"][: int(spec.get("tags") or 0)],
        "title_over": bool(cap_title) and units > cap_title,
        "title_units": units,
        "title_trimmed": bool(cap_title) and not keep and len(entry["title"]) > cap_title,
    }


def latest_job(jobs: list[dict[str, Any]], platform: str) -> dict[str, Any] | None:
    for job in jobs:
        if job.get("platform") == platform and job.get("state") not in ("cancelled", "superseded"):
            return job
    return None


def _job_view(job: dict[str, Any]) -> dict[str, Any]:
    payload = job.get("payload") or {}
    return {
        "id": job["id"], "state": job["state"], "message": job.get("message"), "created_at": job.get("created_at"),
        "mode_label": payload.get("mode_label", ""),
        "payload": {k: payload.get(k) for k in ("platform_label", "mode_label", "title", "body", "tags", "video", "video_mb")},
    }


def rows(platform_rows: list[dict[str, Any]], *, specs: dict[str, dict[str, Any]], publishers: dict[str, dict[str, Any]],
         readiness: dict[str, dict[str, Any]], records: dict[str, dict[str, Any]], jobs: list[dict[str, Any]],
         entry: dict[str, Any], douyin_linked: bool = False, handoff_done: bool = False) -> list[dict[str, Any]]:
    out = []
    for p in platform_rows:
        key = p["key"]
        spec = specs.get(key) or {}
        channel = readiness.get(key) or {}
        how = treatment(key, publishers.get(key))
        record = records.get(key)
        job = latest_job(jobs, key)
        shipped = bool(record) or (key == "douyin" and douyin_linked)
        # 通道能不能真的走：有通道、登录没过期、不是被平台挡着、不是缺配置。
        can_auto = how in ("scan", "auto") and p["state"] in ("linked", "ready")
        out.append({
            **{k: p.get(k) for k in ("key", "label", "mark", "hue", "handle", "on", "state", "note", "admin", "login_hint")},
            "treatment": how,
            "treatment_label": TREATMENT_LABEL[how],
            "caps": {"title": spec.get("title", 0), "body": spec.get("body", 0), "tags": spec.get("tags", 0)},
            "fill": fill_for(spec, entry),
            "shipped": shipped,
            "record": {"url": record.get("url"), "published_at": record.get("published_at")} if record else None,
            "job": _job_view(job) if job else None,
            "modes": channel.get("modes") or {},
            "no_video": bool(channel.get("no_video")),
            "needs_article": bool(channel.get("needs_article")),
            "can_auto": can_auto,
            "handoff_done": handoff_done if how == "handoff" else None,
        })
    return out


def order_candidates(cards: list[dict[str, Any]], shipped: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """加工中的卡按离「能发」多近排；已发出的跟在后面（最近更新的在前）。"""
    active = sorted(cards, key=lambda c: (STAGE_ORDER.get(c.get("stage"), 5), not c.get("focus"), -(c.get("id") or 0)))
    done = sorted(shipped, key=lambda t: (t.get("updated_at") or "", t.get("id") or 0), reverse=True)
    return [*active, *done]


def ready_to_publish(ordered: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """能发的只有两种：成片已经出来的，和已经发出去的（还要补记别的平台）。

    Park：「通常我只会有一条视频在这个环节中」。还在写提纲、还在录的不该出现在发布页——
    它们在加工中。列一排选不了的东西，等于让人每次都重新判断一遍哪条才是真的能发。
    """
    return [c for c in ordered if c.get("stage") in ("ready", "shipped")]


def waiting_for(ordered: list[dict[str, Any]]) -> dict[str, Any] | None:
    """一条都不能发时，指出最接近的那条卡在哪——空页面不该只说「没有」。"""
    nearest = next((c for c in ordered if c.get("stage") not in ("ready", "shipped")), None)
    return {k: nearest[k] for k in ("id", "title", "stage", "stage_label")} if nearest else None
