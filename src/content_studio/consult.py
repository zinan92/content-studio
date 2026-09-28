"""客户咨询录音 → 转文字 + 分析 → Obsidian 里一篇左右对照的笔记。

Park 9/28：做完一单 1v1 咨询，把录音（语音备忘录的 m4a）丢进工作台，出一篇笔记放在
vault 的 010_咨询/：左边是转写原文，右边是逐段分析，最上面是整场的总结。

- 转写本机跑 mlx-whisper，原文不经模型改写：45 分钟的对话让模型整段抄一遍，
  会截断、会悄悄改字（口播那边就是这样才加了漂移守卫）。左栏永远是 whisper 的原话。
- 分析交给 claude -p：只拿编号的段落，回每段一句分析 + 整场总结，不重抄原文。
- 每一步的结果都落在工作目录里（~/.config/content-studio/consults/<名字>/），
  中途断了重跑会跳过已完成的转写。
- 笔记只写进空文件或工作台自己写的文件；Park 手写过内容的同名文件不覆盖，另存一份。
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any, Callable

from .writer import cli_write

ROOT_ENV = "CONTENT_STUDIO_CONSULTS"
DEFAULT_ROOT = Path("~/.config/content-studio/consults")
FOLDER = "010_咨询"
MARKER = "generated_by: 内容工作台"
AUDIO_SUFFIXES = (".m4a", ".mp3", ".wav", ".aac", ".mp4", ".mov", ".caf")
CHUNK_SECONDS = 150
WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"
POSITIONING = Path("~/.claude/skills/park-content-qa/positioning.md")
ANALYZE_COMMAND = (
    "claude -p --model opus --output-format text "
    "--disallowedTools Bash,Edit,Write,Read,Glob,Grep,WebFetch,WebSearch,NotebookEdit,Skill,Task"
)

Transcriber = Callable[[Path], list[dict[str, Any]]]
Analyzer = Callable[[str], str]


class ConsultError(RuntimeError):
    """Shown to Park as-is."""


# -- 工作目录与状态 --------------------------------------------------------------

def root() -> Path:
    return Path(os.environ.get(ROOT_ENV) or DEFAULT_ROOT).expanduser()


def slug(name: str, day: date) -> str:
    clean = re.sub(r"[\\/:*?\"<>|\n\r\t]+", " ", name or "").strip() or "客户"
    return f"{day:%m%d}-{clean[:40]}"


def load_state(folder: Path) -> dict[str, Any]:
    try:
        return json.loads((folder / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(folder: Path, **changes: Any) -> dict[str, Any]:
    state = {**load_state(folder), **changes, "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (folder / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    return state


def audio_of(folder: Path) -> Path | None:
    for path in sorted(folder.glob("audio.*")):
        if path.suffix.lower() in AUDIO_SUFFIXES:
            return path
    return None


# -- 转写 -------------------------------------------------------------------------

def whisper_transcriber(audio: Path) -> list[dict[str, Any]]:
    try:
        import mlx_whisper
    except ImportError as exc:
        raise ConsultError("这台机器上没有 mlx-whisper，转不了文字") from exc
    # initial_prompt 让 whisper 带标点、出简体；关掉 condition_on_previous_text，
    # 长录音才不会卡在一句话上反复输出。
    result = mlx_whisper.transcribe(
        str(audio), path_or_hf_repo=WHISPER_MODEL, language="zh", verbose=None,
        initial_prompt="以下是普通话的对话，请加上标点符号。", condition_on_previous_text=False,
    )
    return [
        {"start": round(float(s["start"]), 2), "end": round(float(s["end"]), 2), "text": (s.get("text") or "").strip()}
        for s in result.get("segments") or []
    ]


def transcribe(folder: Path, *, transcriber: Transcriber | None = None) -> list[dict[str, Any]]:
    """转过就直接读 transcript.json，不重跑。"""
    cached = folder / "transcript.json"
    if cached.is_file():
        try:
            segments = clean(json.loads(cached.read_text(encoding="utf-8")).get("segments") or [])
        except ValueError:
            segments = []
        if segments:
            return segments
    audio = audio_of(folder)
    if not audio:
        raise ConsultError("找不到录音文件")
    segments = clean((transcriber or whisper_transcriber)(audio))
    if not segments:
        raise ConsultError("录音里没转出文字：确认一下是不是空录音")
    cached.write_text(json.dumps({"segments": segments}, ensure_ascii=False), encoding="utf-8")
    return segments


def clean(segments: list[dict[str, Any]], *, max_repeat: int = 3) -> list[dict[str, Any]]:
    """去掉 whisper 在长录音上的两种幻觉循环（9/28 那场都出现过）：
    时间往回跳、两句来回刷（「where is my phone / Holy shit」×7）；同一句连刷几十遍（「嗯」×22）。"""
    out: list[dict[str, Any]] = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text or seg["end"] < seg["start"] or (out and seg["start"] < out[-1]["end"] - 0.5):
            continue
        tail = out[-max_repeat:]
        if len(tail) == max_repeat and all(t["text"] == text for t in tail):
            continue
        out.append({**seg, "text": text})
    return out


def chunks(segments: list[dict[str, Any]], seconds: int = CHUNK_SECONDS) -> list[dict[str, Any]]:
    """按 whisper 的句子边界切成两三分钟一段，一段是对照表的一行。"""
    out: list[dict[str, Any]] = []
    for seg in segments:
        if not out or seg["start"] - out[-1]["start"] >= seconds:
            out.append({"i": len(out) + 1, "start": seg["start"], "end": seg["end"], "parts": []})
        out[-1]["end"] = seg["end"]
        out[-1]["parts"].append(seg["text"])
    return [{"i": c["i"], "start": c["start"], "end": c["end"], "text": _join(c["parts"])} for c in out]


def _join(parts: list[str]) -> str:
    text = ""
    for part in (re.sub(r"\s+", "，", p.strip()) for p in parts):
        if text and not re.search(r"[。！？，、；：…,.!?]$", text):
            text += "，"
        text += part
    return text


def clock(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


# -- 分析 -------------------------------------------------------------------------

def _positioning() -> str:
    try:
        text = POSITIONING.expanduser().read_text(encoding="utf-8")
    except OSError:
        return ""
    return text.split("## 飞轮")[0].strip()[:4000]


def prompt(name: str, parts: list[dict[str, Any]], *, positioning: str | None = None) -> str:
    body = "\n\n".join(f"[{c['i']}] {clock(c['start'])}–{clock(c['end'])}\n{c['text']}" for c in parts)
    context = positioning if positioning is not None else _positioning()
    return f"""你在帮 Park 复盘一场刚做完的 1v1 付费咨询。客户：{name}。

下面是 Park 自己的定位，用来理解他卖什么、想从咨询里得到什么（不要照抄进输出）：
<定位>
{context}
</定位>

下面是整场录音的机器转写，已经切成 {len(parts)} 段，每段前面有编号和时间。
转写没有区分说话人，有错别字和同音字；请根据上下文判断哪句是 Park、哪句是客户。

<转写>
{body}
</转写>

请严格按下面的格式输出，不要输出别的：

=== 总结 ===
（Markdown，用下面这些二级标题，顺序不变。每个判断后面用（mm:ss）标出依据在录音里的时间。
只写录音里真的说过的；客户没提的数字、价格、承诺一律不写，拿不准就写「录音里没提」。）

## 一句话
## 客户是谁
（做什么生意、做到什么程度、现在卡在哪。）
## 客户真正的问题
（他嘴上问的 vs 真正要解决的。）
## Park 给的诊断
（Park 在对话里给出的判断和建议，按原意提炼。）
## 成交信号与下一步
（客户的需求、顾虑、预算线索、他说接下来要做什么；Park 该怎么跟进。）
## 给客户的纪要
（可以直接发给客户的 3–6 条，第二人称，不带时间标记。）
## 素材候选
（1–3 个可以拍成视频的选题：隐去客户名字、公司和可识别的细节。每个写一个标题 + 为什么值得拍。）
## 复盘提纲
（Park 录复盘视频时照着讲的 3–5 点。）
## 下次可以做得更好
（问法、节奏、漏问的地方，具体到哪一段。）

=== 逐段 ===
[1] 这一段在聊什么，以及值得注意的：客户信号、Park 的关键判断、能当素材的原话。一到三句，不超过 80 字。
[2] ……
（每一段都要有，从 [1] 写到 [{len(parts)}]，不要合并。）
"""


def cli_analyzer(text: str) -> str:
    return cli_write(text, command=os.environ.get("CONTENT_STUDIO_CONSULT_CMD") or ANALYZE_COMMAND, timeout=1800)


def parse(output: str, count: int) -> dict[str, Any]:
    match = re.search(r"===\s*总结\s*===\s*(.*?)\s*===\s*逐段\s*===\s*(.*)$", output or "", re.S)
    if not match:
        raise ConsultError("分析没有按格式返回，可以点重试")
    summary, rest = match.group(1).strip(), match.group(2)
    notes: dict[int, str] = {}
    for m in re.finditer(r"^\s*\[(\d+)\]\s*(.*?)(?=^\s*\[\d+\]|\Z)", rest, re.S | re.M):
        i = int(m.group(1))
        if 1 <= i <= count and m.group(2).strip():
            notes[i] = m.group(2).strip()
    if len(summary) < 80:
        raise ConsultError("分析的总结太短，可以点重试")
    return {"summary": summary, "notes": notes, "missing": [i for i in range(1, count + 1) if i not in notes]}


# -- 笔记 -------------------------------------------------------------------------

def _cell(text: str) -> str:
    return re.sub(r"\s*\n\s*", "<br>", (text or "").strip()).replace("|", "\\|") or "—"


def render(*, name: str, day: date, audio: Path, parts: list[dict[str, Any]], analysis: dict[str, Any]) -> str:
    duration = clock(parts[-1]["end"]) if parts else "00:00"
    rows = "\n".join(
        f"| {clock(c['start'])} | {_cell(c['text'])} | {_cell(analysis['notes'].get(c['i'], ''))} |" for c in parts
    )
    return f"""---
type: consult
date: {day.isoformat()}
client: "{name}"
duration: "{duration}"
audio: "{audio}"
cssclasses: [consult]
{MARKER}
---

# {day:%m%d} · {name} · 咨询记录

> 录音 {duration}。下面先是整场总结；「逐段对照」左边是机器转写的原话（有错字、没分说话人），右边是这一段的分析。

{analysis['summary']}

## 逐段对照

| 时间 | 原话 | 分析 |
|:--|:--|:--|
{rows}
"""


def note_path(vault: Path, name: str) -> Path:
    """空文件或工作台写过的同名文件直接写；Park 手写过的不碰，另存「… 转写」。"""
    folder = vault / FOLDER
    target = folder / f"{name}.md"
    if target.exists():
        text = target.read_text(encoding="utf-8")
        if text.strip() and MARKER not in text:
            target = folder / f"{name} 转写.md"
    return target


# -- 一整趟 ---------------------------------------------------------------------

def run(folder: Path, vault: Path, *, transcriber: Transcriber | None = None, analyzer: Analyzer | None = None) -> Path:
    state = load_state(folder)
    name, day = state.get("name") or folder.name, date.fromisoformat(state.get("day") or date.today().isoformat())
    save_state(folder, stage="transcribing", error=None, pid=os.getpid())
    parts = chunks(transcribe(folder, transcriber=transcriber))
    save_state(folder, stage="analyzing", minutes=round(parts[-1]["end"] / 60))
    analysis = parse((analyzer or cli_analyzer)(prompt(name, parts)), len(parts))
    markdown = render(name=name, day=day, audio=audio_of(folder) or folder, parts=parts, analysis=analysis)
    target = note_path(vault, folder.name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(markdown, encoding="utf-8")
    save_state(folder, stage="done", note=str(target), missing=analysis["missing"], pid=None)
    return target


def jobs() -> list[dict[str, Any]]:
    base = root()
    if not base.is_dir():
        return []
    rows = [{"slug": d.name, **load_state(d)} for d in base.iterdir() if d.is_dir() and (d / "state.json").is_file()]
    return sorted(rows, key=lambda r: r.get("created_at") or "", reverse=True)
