"""Publish a finished video to a platform, only after Park confirms the exact payload.

Two steps: prepare (freeze video file, copy and mode) → confirm (run). The channels are
the content-ops scripts Park already uses; the workbench never logs in for him.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any

CONTENT_OPS = Path(os.environ.get("CONTENT_OPS_PATH", "~/work/content-ops")).expanduser()
PUBLISH_ROOT = Path("~/content-toolkit/capabilities/publish").expanduser()
CONFIRM_WINDOW_SECONDS = 30 * 60
RUN_TIMEOUT_SECONDS = 45 * 60

PUBLISHERS: dict[str, dict[str, Any]] = {
    "channels": {
        "label": "视频号",
        "copy_key": "channels",
        "credential": PUBLISH_ROOT / "cookies/tencent_uploader/account.json",
        # 2026-09-21 Park：腾讯最近两个月开始封自动发布，以前能用。重新登录治不好平台侧的限制，
        # 所以这里不是「登录过期」——通道留着（万一他记错了或者以后解封），但按钮由 blocked 状态挡住。
        "blocked": "视频号最近开始限制自动发布，先手动上传",
        "login_hint": f"python3 {CONTENT_OPS}/scripts/push_wechat_channels_draft.py --login-only",
        "modes": {
            "draft": {"label": "存为视频号草稿", "argv": ["python3", str(CONTENT_OPS / "scripts/push_wechat_channels_draft.py"), "--headless", "--video", "{video}", "--title", "{title}", "--description", "{body}"]},
            "publish": {"label": "直接发表", "argv": ["python3", str(CONTENT_OPS / "scripts/push_wechat_channels_draft.py"), "--headless", "--publish", "--video", "{video}", "--title", "{title}", "--description", "{body}"]},
        },
    },
    "bilibili": {
        "label": "B 站",
        "copy_key": "bilibili",
        "credential": PUBLISH_ROOT / "cookies/bilibili_creator.json",
        "login_hint": "在电脑上用 content-ops 工作台的「准备通道」重新登录 B 站",
        "modes": {
            "upload": {"label": "投稿（B 站审核后公开）", "argv": ["python3", str(CONTENT_OPS / "scripts/bilibili_web_upload.py"), "--headless", "upload", "--video", "{video}", "--title", "{title}", "--description", "{body}", "--tags", "{tags}"]},
        },
    },
    "youtube": {
        "label": "YouTube",
        "copy_key": "youtube",
        "credential": Path("~/.config/park/youtube-token.json").expanduser(),
        "login_hint": f"python3 {CONTENT_OPS}/scripts/youtube_channel.py auth",
        "modes": {
            "private": {"label": "上传为私享（自己先看）", "argv": ["python3", str(CONTENT_OPS / "scripts/youtube_channel.py"), "upload-private", "--video", "{video}", "--title", "{title}", "--description", "{body}", "--tags", "{tags}"]},
            "public": {"label": "公开发布", "argv": ["python3", str(CONTENT_OPS / "scripts/youtube_channel.py"), "upload", "--privacy-status", "public", "--video", "{video}", "--title", "{title}", "--description", "{body}", "--tags", "{tags}"]},
        },
    },
}


class PublishError(ValueError):
    """Publishing cannot proceed; the message is shown to Park."""


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def readiness(publishers: dict[str, dict[str, Any]] = PUBLISHERS, now: datetime | None = None) -> dict[str, dict[str, Any]]:
    now = now or now_utc()
    result = {}
    for key, spec in publishers.items():
        if spec.get("blocked"):
            # A platform-side block: the credential may be perfectly fine and re-scanning a QR
            # code fixes nothing. Saying 「要重新登录」 here would send Park off on a dead errand.
            result[key] = {"label": spec["label"], "credential": True, "age_days": None, "likely_expired": True,
                           "blocked": True, "note": spec["blocked"], "login_hint": "",
                           "modes": {m: v["label"] for m, v in spec["modes"].items()}}
            continue
        path = Path(spec["credential"])
        if path.is_file():
            updated = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            age = (now - updated).days
            note = f"登录信息更新于 {updated.astimezone().strftime('%m-%d')}" + ("，已超过 30 天，很可能需要重新登录" if age > 30 else "")
            result[key] = {"label": spec["label"], "credential": True, "age_days": age, "likely_expired": age > 30, "note": note, "login_hint": spec["login_hint"],
                           "modes": {m: v["label"] for m, v in spec["modes"].items()}}
        else:
            result[key] = {"label": spec["label"], "credential": False, "age_days": None, "likely_expired": True, "note": "还没有登录信息", "login_hint": spec["login_hint"],
                           "modes": {m: v["label"] for m, v in spec["modes"].items()}}
    return result


def build_payload(platform: str, mode: str, *, video: Path, copy: dict[str, Any] | None, publishers: dict[str, dict[str, Any]] = PUBLISHERS) -> dict[str, Any]:
    spec = publishers.get(platform)
    if spec is None:
        raise PublishError("这个平台还不能一键发布")
    if mode not in spec["modes"]:
        raise PublishError("发布方式无效")
    if not video.is_file():
        raise PublishError("找不到成片文件")
    entry = (copy or {}).get(spec["copy_key"]) or {}
    title = str(entry.get("title") or "").strip()
    body = str(entry.get("body") or "").strip()
    tags = [str(t).strip() for t in entry.get("tags") or [] if str(t).strip()]
    if not title:
        raise PublishError(f"先在「发布」页写好标题并保存")
    return {"platform": platform, "platform_label": spec["label"], "mode": mode, "mode_label": spec["modes"][mode]["label"],
            "video": str(video), "video_mb": round(video.stat().st_size / 1_048_576, 1), "title": title, "body": body, "tags": tags}


def command_for(payload: dict[str, Any], publishers: dict[str, dict[str, Any]] = PUBLISHERS) -> list[str]:
    template = publishers[payload["platform"]]["modes"][payload["mode"]]["argv"]
    values = {"video": payload["video"], "title": payload["title"], "body": payload["body"], "tags": ",".join(payload["tags"])}
    # Only whole-argument placeholders are substituted, so titles with braces never break the command.
    return [values[part[1:-1]] if part in ("{video}", "{title}", "{body}", "{tags}") else part for part in template]


def confirmable(job: dict[str, Any], now: datetime | None = None) -> None:
    if job["state"] != "awaiting_confirm":
        raise PublishError("这个发布任务不在等待确认")
    created = datetime.fromisoformat(job["created_at"].replace("Z", "+00:00"))
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    if ((now or now_utc()) - created).total_seconds() > CONFIRM_WINDOW_SECONDS:
        raise PublishError("确认已超过 30 分钟，请重新准备发布")


def parse_result(stdout: str) -> dict[str, Any]:
    """The scripts print one JSON object; take the last parseable one."""
    for match in reversed(list(re.finditer(r"\{", stdout))):
        try:
            value = json.loads(stdout[match.start():])
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return {}


def run(payload: dict[str, Any], *, publishers: dict[str, dict[str, Any]] = PUBLISHERS, timeout: float = RUN_TIMEOUT_SECONDS) -> dict[str, Any]:
    argv = command_for(payload, publishers)
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False, cwd=str(CONTENT_OPS) if CONTENT_OPS.is_dir() else None)
    except subprocess.TimeoutExpired:
        return {"ok": False, "status": "timeout", "message": "发布超时（45 分钟），去平台后台看看有没有上传成功"}
    except OSError as exc:
        return {"ok": False, "status": "command_missing", "message": f"找不到发布脚本：{exc}"}
    result = parse_result(completed.stdout)
    if not result:
        result = {"ok": False, "status": "no_result", "message": (completed.stderr or completed.stdout).strip()[-400:]}
    result.setdefault("ok", completed.returncode == 0)
    return result


def result_url(result: dict[str, Any]) -> str | None:
    for key in ("url", "video_url", "link", "watch_url"):
        if str(result.get(key) or "").startswith("http"):
            return result[key]
    if result.get("video_id") and str(result.get("platform") or "youtube") == "youtube":
        return f"https://www.youtube.com/watch?v={result['video_id']}"
    return None


STATUS_TEXT = {
    "cookie_missing": "还没有登录信息，需要先在电脑上登录",
    "cookie_invalid": "登录已过期，需要在电脑上重新扫码登录",
    "video_missing": "找不到视频文件",
}


def explain(result: dict[str, Any]) -> str:
    status = str(result.get("status") or "")
    return STATUS_TEXT.get(status) or str(result.get("message") or status or "发布失败")[:300]
