"""Anna: the resident content editor in the workbench's right column.

Everything Park says inside the workbench goes to Anna. Her role, principles and
knowledge live in Park's Obsidian vault as plain Markdown (the "soul"); the
workbench reads them on every turn so editing the file edits the person. Each
turn also carries a fresh snapshot of what Park is looking at (the "context"),
assembled by the web layer.

Anna only talks. The model runs with every tool disabled; when she wants
something done she writes a `[动作]` line, the page turns it into a button and
Park clicks it. The workbench is reachable through a password proxy, so a chat
box that could run commands would be a shell for anyone holding that password.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
from typing import Any, Callable

ANNA_COMMAND_ENV = "CONTENT_STUDIO_ANNA_CMD"
ANNA_ROLE_ENV = "CONTENT_STUDIO_ANNA_ROLE"
ANNA_SKILL_ENV = "CONTENT_STUDIO_QA_GUIDE"
DEFAULT_ROLE = Path("~/park-hands/001_role/content_editor Anna.md")
DEFAULT_SKILL = Path("~/.claude/skills/park-content-qa/SKILL.md")
# Claude Code, logged in on this Mac: fast enough for a chat turn, resumable, no API key.
# Every tool is disabled; Anna reads the prompt and answers.
DEFAULT_ANNA_COMMAND = (
    "claude -p --model sonnet --output-format json "
    "--disallowedTools Bash,Edit,Write,Read,Glob,Grep,WebFetch,WebSearch,NotebookEdit,Skill,Task"
)
KNOWLEDGE_SUFFIXES = (".md", ".txt")
MAX_KNOWLEDGE_FILE_CHARS = 12000
MAX_CONTEXT_CHARS = 24000
TURN_TIMEOUT_SECONDS = 180

SCOPE_LABELS = {"input": "进项", "board": "加工中", "work": "这条视频", "output": "已发出", "settings": "设置"}
# What each [动作] line may ask for; anything else is shown as text.
ACTION_KINDS = {"存进备注": "memo", "重写提纲": "outline", "拿来做": "take", "按三点评分": "qa"}

TurnFn = Callable[[str, str, str | None], dict]


class AnnaError(RuntimeError):
    """A turn could not be completed; the message is shown in the panel."""


class AnnaLoginError(AnnaError):
    """The local CLI is logged out or out of quota; retrying will not help."""


# -- soul ---------------------------------------------------------------------

def _strip_frontmatter(text: str) -> str:
    return re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S).strip()


def load_soul(role_path: Path | None = None, skill_path: Path | None = None) -> dict[str, Any]:
    """Role file + its knowledge folder + the three-point QA skill, as one system prompt."""
    role = (role_path or Path(os.environ.get(ANNA_ROLE_ENV) or DEFAULT_ROLE)).expanduser()
    skill = (skill_path or Path(os.environ.get(ANNA_SKILL_ENV) or DEFAULT_SKILL)).expanduser()
    parts: list[str] = []
    sources: list[str] = []
    try:
        parts.append(_strip_frontmatter(role.read_text(encoding="utf-8")))
        sources.append(str(role))
    except OSError:
        parts.append("# Anna｜内容主编\n\n第一目标：让对的人看得更久。Park 的抖音号是「Park 的 AI 世界」（AI + 金融），口播视频。")
    knowledge_dir = role.with_suffix("") / "knowledge"
    if knowledge_dir.is_dir():
        for path in sorted(knowledge_dir.iterdir()):
            if path.suffix.lower() not in KNOWLEDGE_SUFFIXES or path.name.startswith("."):
                continue
            try:
                body = _strip_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            if body:
                parts.append(f"## 知识：{path.stem}\n\n{body[:MAX_KNOWLEDGE_FILE_CHARS]}")
                sources.append(str(path))
    try:
        parts.append("## 三点评分标准\n\n" + _strip_frontmatter(skill.read_text(encoding="utf-8")))
        sources.append(str(skill))
    except OSError:
        pass
    return {"text": "\n\n---\n\n".join(parts), "sources": sources}


WORKBENCH_RULES = """## 你在内容工作台里

你是 Anna，常驻在 Park 的内容工作台右侧。Park 在工作台里说的每一句话都是对你说的。每一轮消息里的 <工作台> 块是他此刻正在看的页面的实时资料；以它为准，不要凭记忆编造工作台里没有的数据。

回答规则：
- 全中文，简单直接。先给一句话结论，再给依据（引用资料里的原话或数字），最后落到一个动作上。不写长篇。
- 不讨好。题不行就说不行，素材太薄就说太薄。
- 每次最多追问一个问题。
- 你只动嘴不动手。需要工作台做事时，在回答最后单独成行写「[动作]」，Park 会看到按钮，点了才执行。只能用下面几种，每种最多一行：
  [动作] 存进备注：<要存进这条视频备注的一句话>
  [动作] 重写提纲
  [动作] 按三点评分
  [动作] 拿来做：<新选题的标题>
  「重写提纲」「按三点评分」只在看着某一条视频时用；「拿来做」只在进项或加工中用。没有动作就不写。
- 不给投资建议，不承诺收益，不编 Park 的经历和数据。"""


def system_prompt(soul_text: str) -> str:
    return f"{soul_text}\n\n---\n\n{WORKBENCH_RULES}"


# -- turns ---------------------------------------------------------------------

def compose_user_message(context: str, message: str, *, scope_label: str) -> str:
    context = context.strip()
    if len(context) > MAX_CONTEXT_CHARS:
        context = context[:MAX_CONTEXT_CHARS] + "\n（资料过长，已截断）"
    return f"<工作台 页面=\"{scope_label}\">\n{context or '（这一页没有资料）'}\n</工作台>\n\nPark：{message.strip()}"


def parse_reply(text: str) -> dict[str, Any]:
    """Split Anna's answer into prose and the [动作] buttons she asked for."""
    actions: list[dict[str, str]] = []
    kept: list[str] = []
    for line in text.strip().splitlines():
        m = re.match(r"^\s*\[动作\]\s*(存进备注|重写提纲|按三点评分|拿来做)\s*[:：]?\s*(.*)$", line)
        if not m:
            kept.append(line)
            continue
        kind, arg = ACTION_KINDS[m.group(1)], m.group(2).strip()
        if kind in ("memo", "take") and not arg:
            continue
        if not any(a["kind"] == kind and a.get("arg") == arg for a in actions):
            actions.append({"kind": kind, "label": m.group(1), "arg": arg})
    return {"text": "\n".join(kept).strip(), "actions": actions[:4]}


def _detail(stderr: str, stdout: str) -> str:
    return (stderr.strip() or stdout.strip())[-300:] or "没有输出"


def cli_turn(system: str, user: str, session_id: str | None, *, command: str | None = None, timeout: float = TURN_TIMEOUT_SECONDS) -> dict[str, Any]:
    """One turn through the local Claude Code CLI; returns {"text", "session_id"}."""
    argv = shlex.split(command or os.environ.get(ANNA_COMMAND_ENV) or DEFAULT_ANNA_COMMAND)
    argv += ["--system-prompt", system]
    if session_id:
        argv += ["--resume", session_id]
    try:
        completed = subprocess.run(argv, input=user, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise AnnaError(f"Anna 想了 {int(timeout)} 秒还没答完，再问一次试试") from exc
    except OSError as exc:
        raise AnnaError(f"找不到本机的 Claude 命令：{exc}") from exc
    if completed.returncode != 0:
        detail = f"{completed.stderr}\n{completed.stdout}"
        if re.search(r"authenticat|log ?in|oauth", detail, re.IGNORECASE):
            raise AnnaLoginError("本机 Claude 命令行登录已过期：在终端运行 claude 重新登录，再回来问")
        if re.search(r"usage limit|rate limit|limit reached|quota", detail, re.IGNORECASE):
            raise AnnaLoginError(f"本机 Claude 额度用完或被限流，稍后再问：{_detail(completed.stderr, completed.stdout)[:120]}")
        if session_id and re.search(r"session|resume|not found", detail, re.IGNORECASE):
            # The CLI forgot the session (restart, cleanup): start over rather than fail the panel.
            return cli_turn(system, user, None, command=command, timeout=timeout)
        raise AnnaError(f"Anna 没答上来（退出码 {completed.returncode}）：{_detail(completed.stderr, completed.stdout)}")
    try:
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        payload = {"result": completed.stdout.strip(), "session_id": session_id}
    if payload.get("is_error"):
        raise AnnaError(f"Anna 没答上来：{str(payload.get('result') or '')[:300]}")
    text = str(payload.get("result") or "").strip()
    if not text:
        raise AnnaError("Anna 没有回话，再问一次试试")
    return {"text": text, "session_id": payload.get("session_id") or session_id}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run_turn(
    *,
    scope: str,
    scope_label: str,
    context: str,
    message: str,
    session_id: str | None,
    turn_fn: TurnFn | None = None,
    soul: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compose one turn and return the assistant message ready to store."""
    soul = soul or load_soul()
    system = system_prompt(soul["text"])
    user = compose_user_message(context, message, scope_label=scope_label)
    fn = turn_fn or cli_turn
    result = fn(system, user, session_id)
    parsed = parse_reply(result["text"])
    return {
        "role": "anna",
        "text": parsed["text"],
        "actions": parsed["actions"],
        "at": now_iso(),
        "session_id": result.get("session_id"),
        "scope": scope,
    }
