"""口播动效 v2（park-video-v2）项目：进度和动作都交给它自己的 pv2.py，工作台只读结果、转发按钮。

一个视频项目目录里有 v2/brief.yaml、根目录没有旧流程的 project.json，就按 v2 显示。
旧流程（14 步、project.json）的项目照旧，不受影响。
"""
from __future__ import annotations

import json
import os
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
