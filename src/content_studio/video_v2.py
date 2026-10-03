"""口播动效 v2（park-video-v2）项目：进度和动作都交给它自己的 pv2.py，工作台只读结果、转发按钮。

设置（密度、动效努力……）和动效图鉴也都来自 pv2.py：工作台照它给的清单画滑杆，不写死任何视频设置。

一个视频项目目录里有 v2/brief.yaml、根目录没有旧流程的 project.json，就按 v2 显示。
旧流程（14 步、project.json）的项目照旧，不受影响。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

HOME_ENV = "CONTENT_STUDIO_PV2_HOME"
DEFAULT_HOME = Path("~/work/park-video-v2")
STEPS = ("准备", "方案", "渲染", "终审")
GATES = ("sample", "final")
JOBS = ("sample", "render")


class VideoV2Error(ValueError):
    """pv2.py 调用失败；message 直接给 Park 看。"""


def home() -> Path:
    return Path(os.environ.get(HOME_ENV) or DEFAULT_HOME).expanduser()


def is_v2(base: Path) -> bool:
    return (base / "v2" / "brief.yaml").is_file() and not (base / "project.json").is_file()


def _pv2(*args: str, timeout: int = 30) -> str:
    script = home() / "scripts" / "pv2.py"
    if not script.is_file():
        raise VideoV2Error(f"找不到 park-video-v2：{script}（可用环境变量 {HOME_ENV} 指定）")
    r = subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True, timeout=timeout, cwd=str(home()))
    if r.returncode != 0:
        raise VideoV2Error((r.stderr or r.stdout).strip().splitlines()[-1] if (r.stderr or r.stdout).strip() else "pv2.py 失败")
    return r.stdout


def status(base: Path) -> dict[str, Any]:
    try:
        return json.loads(_pv2("status", str(base)))
    except (VideoV2Error, ValueError, subprocess.TimeoutExpired) as exc:
        return {"step": "准备", "percent": None, "waiting_for": None, "failed": True, "detail": f"读不到进度：{exc}",
                "sample": None, "final": None}


def stages(st: dict[str, Any]) -> list[dict[str, Any]]:
    step = st.get("step")
    idx = len(STEPS) if step == "已交付" else (STEPS.index(step) if step in STEPS else 0)
    return [{"key": s, "label": s, "state": "done" if i < idx else ("current" if i == idx else "todo")} for i, s in enumerate(STEPS)]


def approve(base: Path, gate: str, message: str) -> dict[str, Any]:
    if gate not in GATES:
        raise VideoV2Error("只能批准 sample（样片）或 final（成片）")
    if not message.strip():
        raise VideoV2Error("写一句你的话再批准（会记进 v2/approvals.json）")
    return json.loads(_pv2("approve", str(base), gate, "-m", message.strip()))


def start(base: Path, job: str) -> str:
    if job not in JOBS:
        raise VideoV2Error("只能开始 sample（10 秒样片）或 render（整条）")
    return _pv2(job, str(base), "--detach").strip()


def settings(base: Path | None = None) -> dict[str, Any]:
    """设置清单 + 当前取值和来源（项目 / 你的默认 / 仓库默认）。base 为空时只看默认值。"""
    return json.loads(_pv2("settings", *([str(base)] if base else [])))


def save_settings(base: Path | None, values: dict[str, Any]) -> dict[str, Any]:
    """base 为空写 Park 的默认值，否则写进这个项目的 v2/brief.yaml。pv2.py 先校验，还没做的档位会被拒。"""
    if not isinstance(values, dict) or not values:
        raise VideoV2Error("没有要改的设置")
    try:
        out = _pv2("set", str(base) if base else "default", "--json", json.dumps(values, ensure_ascii=False))
    except VideoV2Error as exc:
        try:
            raise VideoV2Error(json.loads(str(exc))["error"]) from exc
        except (ValueError, KeyError, TypeError):
            raise exc from None
    return json.loads(out)


_MEDIA = re.compile(r"^[A-Za-z0-9_-]+\.(mp4|jpg)$")


def catalog() -> dict[str, Any]:
    """动效图鉴：我们库里能用的组件（带演示片段）+ ShotCraft 全部样式卡（可以叫 AI 改编）。只给网址，不给本机路径。"""
    comps = json.loads(_pv2("catalog"))
    cards = json.loads(_pv2("shotcraft"))
    for c in comps:
        c["video_url"] = f"/api/video-v2/media/gallery/{c['key']}.mp4" if c.pop("video", None) else None
        c["poster_url"] = f"/api/video-v2/media/gallery/{c['key']}.jpg" if c.pop("poster", None) else None
    for c in cards:
        c["poster_url"] = f"/api/video-v2/media/shotcraft/{c['name']}.jpg" if c.pop("poster", None) else None
    return {"components": comps, "shotcraft": cards}


def media_path(kind: str, file: str) -> Path:
    if not _MEDIA.match(file):
        raise VideoV2Error("文件名不对")
    if kind == "gallery":
        path = home() / "gallery" / file
    elif kind == "shotcraft":
        name = file.rsplit(".", 1)[0]
        hit = next((c for c in json.loads(_pv2("shotcraft")) if c["name"] == name and c.get("poster")), None)
        if not hit:
            raise VideoV2Error("没有这张海报")
        path = Path(hit["poster"])
    else:
        raise VideoV2Error("只有 gallery / shotcraft")
    if not path.is_file():
        raise VideoV2Error("文件不在了")
    return path
