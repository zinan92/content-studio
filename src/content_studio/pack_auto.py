"""打包的自动档：Park 只定标题，剩下的（封面、X 图文、插图、公众号排版、小红书图文）机器一步接一步做完、自动定稿。

10/2 Park：「真正需要我 input 的就是标题……封面、插图、排版我都不需要审核。」
以前每一步要他点「定稿」才开始下一步，还常常看不出在不在跑。现在：

- 只有他点了「用这个标题，开始准备」才启动（armed）。光打开页面不花钱。
- 每一步做完自动定稿（by="auto"），接着开始下一步；顺序照 approvals.DEPENDS。
- 哪一步失败就停在那一步，等他点「重试」，不自己反复跑（封面一轮就是几分钟的 image_gen）。
- 每一步的状态写在草稿目录的 pack-auto.json：服务重启（每次合 PR 都会自动部署重启）后，
  「记着在跑、其实没有线程」的那一步当作被打断，自动再起一次；再断就停下报错。

这里只做判断（plan），真正启动任务、写定稿由 web.py 照着做。
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
from typing import Any

FILE = "pack-auto.json"
ORDER = ("cover", "article", "figs", "wx", "xhs")
DEPENDS = {"cover": "copy", "figs": "article", "wx": "figs", "xhs": "figs"}
LABEL = {"cover": "封面", "article": "X 图文文章", "figs": "插图", "wx": "公众号排版", "xhs": "小红书图文"}
MAX_TRIES = 2  # 被重启打断的，自动再起一次；第二次还断就停下
# 任务线程收尾和页面请求会同时改这份文件：读改写整个锁住，写的时候先写临时文件再换名，
# 不让谁读到写了一半的文件（读到空的就当没 armed，自动档会悄悄停掉）
_LOCK = threading.RLock()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load(folder: Path) -> dict[str, Any]:
    try:
        data = json.loads((folder / FILE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(folder: Path, state: dict[str, Any]) -> dict[str, Any]:
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f".{FILE}.{os.getpid()}.{threading.get_ident()}"
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, folder / FILE)
    return state


def arm(folder: Path, title: str) -> dict[str, Any]:
    """Park 定了标题：打开自动档。换了标题，之前失败的步骤清掉重来（封面要按新标题重出）。"""
    with _LOCK:
        state = load(folder)
        if state.get("title") != title:
            state["steps"] = {k: v for k, v in (state.get("steps") or {}).items() if v.get("state") != "error"}
        state.update({"armed": True, "title": title, "armed_at": now()})
        return save(folder, state)


def mark(folder: Path, key: str, **fields: Any) -> dict[str, Any]:
    with _LOCK:
        state = load(folder)
        steps = state.setdefault("steps", {})
        steps[key] = {**(steps.get(key) or {}), **fields}
        return save(folder, state)


def retry(folder: Path, key: str) -> dict[str, Any]:
    """Park 点了「重试」：清掉这一步的错误和次数。"""
    with _LOCK:
        state = load(folder)
        state.setdefault("steps", {}).pop(key, None)
        return save(folder, state)


def plan(state: dict[str, Any], approvals: dict[str, dict[str, Any]], running: set[str], *, title: str,
         xhs: bool) -> list[tuple[str, str]]:
    """下一步做什么：[(动作, 步骤)]。动作是 approve（做好了，自动定稿）、start（开始做）、
    interrupted（记着在跑但没有线程：重起）、give_up（断了太多次，停下报错）。

    approvals 是 approvals.status() 的结果；running 是现在真在跑的步骤。没 armed 什么都不做。"""
    if not state.get("armed"):
        return []
    steps = state.get("steps") or {}
    actions: list[tuple[str, str]] = []
    locked = {k for k, a in approvals.items() if a.get("approved") and a.get("valid")}
    for key in ORDER:
        if key == "xhs" and not xhs:
            continue
        dep = DEPENDS.get(key)
        if dep and dep not in locked:
            continue  # 上一步还没好，这一步等着
        if key in locked:
            continue
        if key in running:
            continue
        step = steps.get(key) or {}
        a = approvals.get(key) or {}
        if step.get("state") == "error":
            continue  # 失败了：等 Park 点重试，不自己反复跑
        if step.get("state") == "running":
            actions.append(("interrupted" if int(step.get("tries") or 0) < MAX_TRIES else "give_up", key))
            continue
        stale_cover = key == "cover" and step.get("title") not in (None, title)
        if a.get("made") and not stale_cover:
            actions.append(("approve", key))
            locked.add(key)  # 这一步定了，下一步这一轮就能开始
            continue
        actions.append(("start", key))
    return actions


def view(state: dict[str, Any], approvals: dict[str, dict[str, Any]], running: set[str], *, xhs: bool,
         detail: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """页面上那张进度清单：每一步 done / running / waiting / error / idle，加一句话。"""
    steps = state.get("steps") or {}
    rows = []
    for key in ORDER:
        if key == "xhs" and not xhs:
            continue
        a = approvals.get(key) or {}
        step = steps.get(key) or {}
        if a.get("approved") and a.get("valid"):
            st, note = "done", (detail or {}).get(key) or "好了"
        elif key in running or step.get("state") == "running":
            st, note = "running", (detail or {}).get(key) or "在做"
        elif step.get("state") == "error":
            st, note = "error", step.get("error") or "没做成"
        elif state.get("armed"):
            dep = DEPENDS.get(key)
            st, note = "waiting", f"等「{LABEL.get(dep, '标题')}」好了自动开始" if dep and dep != "copy" else "马上开始"
        else:
            st, note = "idle", "定了标题后自动做"
        rows.append({"key": key, "label": LABEL[key], "state": st, "note": note, "by": a.get("by")})
    return rows
