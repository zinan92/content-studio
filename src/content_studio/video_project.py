"""Read the state of an ask-park-video (口播 workflow v2.6) project from its artifacts.

The workbench never runs the workflow and never edits a project. A status label in
project.json only counts where the workflow itself has no required artifact; for every
other step the artifact is the evidence (the skill's own rule).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any, Callable

DEFAULT_ROOTS = (Path("/Volumes/Phone SSD/视频/exports"), Path("~/Movies/口播项目"))
DONE_LABELS = {"pass", "approved", "skipped"}
STAGES = (
    ("A", "准备", (1, 2, 3, 4)),
    ("B", "Hook 与成品 A", (5, 6, 7, 8, 9)),
    ("C", "正文与视觉", (10, 11)),
    ("D", "声音与成品 B", (12, 13)),
    ("E", "合成交付", (14,)),
)
STEP_NAMES = {
    1: "项目设置", 2: "素材保全", 3: "媒体与字幕检查", 4: "字幕校准与 worktable",
    5: "选 Hook（H1）", 6: "正文 Content Map", 7: "Hook 精确截取", 8: "Hook 拼接与字幕",
    9: "成品 A 与 QA", 10: "正文 Picture Lock", 11: "视觉轨道（H2）", 12: "声音轨道",
    13: "成品 B 与 QA", 14: "合成、终审 QA（H3）",
}
LEGACY_FINALS = ("final/video.mp4", "final-video.mp4", "delivery/final-video.mp4")
READABLE = {".html", ".json", ".md", ".mp4", ".srt", ".txt", ".png", ".jpg"}


class VideoProjectError(ValueError):
    """Root missing or a path outside the projects root."""


def resolve_root(raw: str | None) -> Path:
    candidates = [Path(raw).expanduser()] if raw else [p.expanduser() for p in DEFAULT_ROOTS]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve()
    shown = raw or str(DEFAULT_ROOTS[0])
    hint = "（外接硬盘可能没接上）" if shown.startswith("/Volumes/") else ""
    raise VideoProjectError(f"找不到视频项目目录：{shown}{hint}")


def project_dir(root: Path, name: str) -> Path:
    if not name or "/" in name or name.startswith(".") or "\x00" in name:
        raise VideoProjectError("视频项目名无效")
    path = (root / name).resolve()
    if path.parent != root or not path.is_dir():
        raise VideoProjectError("视频项目不存在")
    return path


def safe_file(root: Path, name: str, relative: str) -> Path:
    base = project_dir(root, name)
    if not relative or relative.startswith("/") or "\x00" in relative:
        raise VideoProjectError("文件路径无效")
    path = (base / relative).resolve()
    if base not in path.parents or not path.is_file() or path.suffix.lower() not in READABLE:
        raise VideoProjectError("文件不存在")
    return path


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def qa_passed(path: Path) -> bool:
    data = _json(path)
    if not isinstance(data, dict):
        return False
    for key in ("pass", "passed", "ok"):
        if data.get(key) is True:
            return True
    for key in ("status", "verdict", "result"):
        if str(data.get(key) or "").lower() in {"pass", "passed", "ok", "通过"}:
            return True
    return False


def _nonempty_dir(path: Path) -> bool:
    return path.is_dir() and any(not p.name.startswith(".") for p in path.iterdir())


@dataclass
class Evidence:
    ok: bool
    note: str


def _step_checks(base: Path, contract: dict[str, Any]) -> dict[int, Callable[[], Evidence]]:
    exists = lambda rel: (base / rel).is_file()  # noqa: E731
    status = contract.get("step_status") or {}
    approvals = contract.get("approvals") or {}
    labelled = lambda n: str(status.get(str(n)) or status.get(n) or "").lower() in DONE_LABELS  # noqa: E731
    presets = contract.get("presets") or {}

    def presets_ok() -> Evidence:
        missing = [k for k in ("media", "audio", "caption_style", "caption_layout") if not presets.get(k)]
        return Evidence(bool(contract) and not missing, "project.json 与四个 preset" if not missing else f"project.json 缺 preset：{'、'.join(missing)}")

    return {
        1: presets_ok,
        2: lambda: Evidence(labelled(2), "素材清点记录（project.json step_status）"),
        3: lambda: Evidence(labelled(3), "媒体规格与硬字幕检查（project.json step_status）"),
        4: lambda: Evidence(
            exists("subtitles/source.srt") and exists("subtitles/transcript.sentences.json") and exists("analysis/worktable.html"),
            "subtitles/source.srt + transcript.sentences.json + analysis/worktable.html",
        ),
        5: lambda: Evidence(exists("analysis/worktable.json") and bool(approvals.get("hook")), "analysis/worktable.json + Hook 批准记录"),
        6: lambda: Evidence(exists("analysis/content-map.md") or exists("analysis/content-map.json"), "analysis/content-map"),
        7: lambda: Evidence(_nonempty_dir(base / "part-a-hook/individual"), "part-a-hook/individual/ 截好的 Hook 片段"),
        8: lambda: Evidence(exists("part-a-hook/edit.json") and exists("part-a-hook/subtitles.srt"), "part-a-hook/edit.json + subtitles.srt"),
        9: lambda: Evidence(exists("part-a-hook/video.mp4") and qa_passed(base / "part-a-hook/qa.json"), "part-a-hook/video.mp4 + QA A 通过"),
        10: lambda: Evidence(exists("part-b-body/clean-master.mp4") and exists("part-b-body/edit.json"), "part-b-body/clean-master.mp4 + edit.json"),
        11: lambda: Evidence(
            (exists("part-b-body/visual-plan.json") and bool(approvals.get("visual_spec"))) or str(status.get("11") or "").lower() == "skipped",
            "visual-plan.json + 视觉规格批准（或记录为不加视觉）",
        ),
        12: lambda: Evidence(labelled(12) or exists("part-b-body/audio-plan.json"), "声音 preset 已应用（step_status 或 audio-plan.json）"),
        13: lambda: Evidence(exists("part-b-body/video.mp4") and qa_passed(base / "part-b-body/qa.json"), "part-b-body/video.mp4 + QA B 通过"),
        14: lambda: Evidence(exists("final/video.mp4") and qa_passed(base / "final/qa.json") and bool(approvals.get("final")), "final/video.mp4 + QA Final + 终审批准"),
    }


def _gate(base: Path, step: int | None, contract: dict[str, Any]) -> dict[str, str] | None:
    approvals = contract.get("approvals") or {}
    if step == 5 and (base / "analysis/worktable.html").is_file() and not (base / "analysis/worktable.json").is_file():
        return {"key": "H1", "title": "等你在 worktable 里选 Hook", "action": "打开 worktable，选 Hook、写画面备注，导出后放到 analysis/worktable.json"}
    if step == 5 and (base / "analysis/worktable.json").is_file() and not approvals.get("hook"):
        return {"key": "H1", "title": "等你批准 Hook 的句子和顺序", "action": "在 Claude/Codex 里看 Hook 候选并批准"}
    if step == 11 and (base / "part-b-body/visual-plan.json").is_file() and not approvals.get("visual_spec"):
        return {"key": "H2", "title": "等你批准视觉规格表", "action": "看视觉规格表，逐条确认采纳/调整/拒绝"}
    if step == 14 and (base / "final/video.mp4").is_file() and qa_passed(base / "final/qa.json") and not approvals.get("final"):
        return {"key": "H3", "title": "等你终审成片", "action": "看成片，确认可以交付"}
    return None


def process_log_tail(base: Path, limit: int = 5) -> list[dict[str, str]]:
    path = base / "process-log.md"
    if not path.is_file():
        return []
    entries: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        heading = re.match(r"^##\s+(.+)$", line)
        if heading:
            current = {"title": heading.group(1).strip(), "status": ""}
            entries.append(current)
            continue
        found = re.match(r"^-\s*status:\s*(\S+)", line.strip())
        if found and current is not None and not current["status"]:
            current["status"] = found.group(1)
    return entries[-limit:]


def inspect(root: Path, name: str) -> dict[str, Any]:
    base = project_dir(root, name)
    contract_path = base / "project.json"
    contract = _json(contract_path) if contract_path.is_file() else None
    artifacts = {
        rel: (base / rel).is_file()
        for rel in (
            "analysis/worktable.html", "analysis/worktable.json", "part-a-hook/video.mp4",
            "part-b-body/video.mp4", "final/video.mp4", "process-log.md",
        )
    }
    common = {
        "name": name,
        "path": str(base),
        "modified_at": datetime.fromtimestamp(base.stat().st_mtime).isoformat(timespec="minutes"),
        "continue_command": f"用 ask-park-video 继续这个口播项目：{base}",
        "log": process_log_tail(base),
    }
    if not isinstance(contract, dict):
        final = next((rel for rel in LEGACY_FINALS if (base / rel).is_file()), None)
        entries = [p for p in base.iterdir() if not p.name.startswith(".")]
        fresh = all(p.name in ("README.md", "拍摄提纲.md") for p in entries)
        if final:
            summary = "旧版目录：已有成片"
        elif fresh:
            summary = "还没开始：放入粗剪视频和字幕后，在 Claude/Codex 里开始"
        else:
            summary = "没有 project.json，无法按 14 步判断进度"
        return {
            **common,
            "layout": "fresh" if fresh and not final else "legacy",
            "delivered": bool(final),
            "final_video": final,
            "summary": summary,
            "steps": [],
            "stages": [],
            "current_step": None,
            "gate": None,
            "artifacts": {k: v for k, v in artifacts.items() if v},
            "blocked_reason": None,
        }
    checks = _step_checks(base, contract)
    steps = []
    current = None
    for number in range(1, 15):
        evidence = checks[number]()
        if not evidence.ok and current is None:
            current = number
        steps.append({"step": number, "name": STEP_NAMES[number], "done": evidence.ok and (current is None or number < current), "evidence": evidence.note})
    stages = []
    for key, label, numbers in STAGES:
        passed = sum(1 for s in steps if s["step"] in numbers and s["done"])
        if passed == len(numbers):
            state = "done"
        elif current in numbers:
            state = "current"
        else:
            state = "todo"
        stages.append({"key": key, "label": label, "steps": list(numbers), "passed": passed, "total": len(numbers), "state": state})
    gate = _gate(base, current, contract)
    delivered = current is None
    return {
        **common,
        "layout": "v2.6",
        "delivered": delivered,
        "final_video": "final/video.mp4" if artifacts["final/video.mp4"] else None,
        "summary": "已交付" if delivered else (f"Step {current}：{STEP_NAMES[current]}" + (f" · {gate['title']}" if gate else "")),
        "steps": steps,
        "stages": stages,
        "current_step": current,
        "gate": gate,
        "artifacts": {k: v for k, v in artifacts.items() if v},
        "blocked_reason": contract.get("blocked_reason"),
    }


def list_projects(root: Path, limit: int = 40) -> list[dict[str, Any]]:
    dirs = sorted((p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")), key=lambda p: p.stat().st_mtime, reverse=True)
    results = []
    for path in dirs[:limit]:
        try:
            info = inspect(root, path.name)
        except (OSError, VideoProjectError):
            continue
        results.append({k: info[k] for k in ("name", "layout", "summary", "delivered", "current_step", "gate", "modified_at")})
    return results


def slug(title: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|#\s]+", "", title)[:24]
    return cleaned or "口播"


def create_project(root: Path, *, title: str, today: str, outline_markdown: str | None = None) -> str:
    name = f"{today}_{slug(title)}"
    candidate, n = name, 2
    while (root / candidate).exists():
        candidate, n = f"{name}-{n}", n + 1
    base = root / candidate
    base.mkdir()
    (base / "README.md").write_text(
        f"# {title}\n\n由内容工作台创建。\n\n1. 把剪映粗剪视频和剪映导出的 SRT 放进这个文件夹（原始录制视频也可以放一份只读备份）。\n"
        f"2. 在 Claude 或 Codex 里说：用 ask-park-video 开始这个口播项目：{base}\n"
        "3. 进度会自动显示在内容工作台的「视频 → 剪辑进度」里。\n",
        encoding="utf-8",
    )
    if outline_markdown:
        (base / "拍摄提纲.md").write_text(outline_markdown, encoding="utf-8")
    return candidate
