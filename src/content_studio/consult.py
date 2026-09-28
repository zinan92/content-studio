"""客户咨询录音/录像 → 转文字 + 分析 → 两份成品：给 Park 的、给客户的。

Park 9/28：做完一单 1v1 咨询，把录音（语音备忘录的 m4a）或录像丢进工作台：
- 本机留两样：原件（原件.m4a / 原件.mp4）和文字（转写.txt），都在工作目录里。
- 给 Park 的：vault 010_咨询/ 一篇笔记，最上面整场总结（含成交信号、素材、复盘），
  下面左边转写原文、右边逐段分析。
- 给客户的：同目录一份「· 客户版.html」，只有会议纪要和 takeaway，不附转写，
  也不带任何只给 Park 看的东西（成交判断、报价策略、素材、复盘）。Park 直接发给客户。

- 转写本机跑 mlx-whisper，原文不经模型改写：45 分钟的对话让模型整段抄一遍，
  会截断、会悄悄改字（口播那边就是这样才加了漂移守卫）。左栏永远是 whisper 的原话。
- 分析交给 claude -p：只拿编号的段落，回每段一句分析 + 整场总结，不重抄原文。
  客户版是第二次调用，拿总结和原文写给客户看的纪要。
- 每一步的结果都落在工作目录里（~/.config/content-studio/consults/<名字>/），
  中途断了重跑会跳过已完成的步骤（转写、分析、客户版各自缓存）。
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
MEDIA_SUFFIXES = (".m4a", ".mp3", ".wav", ".aac", ".caf", ".mp4", ".mov", ".m4v", ".webm", ".mkv")
ORIGINAL = "原件"
TEXT_FILE = "转写.txt"
CLIENT_SUFFIX = " · 客户版.html"
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
    for path in sorted(folder.glob(f"{ORIGINAL}.*")) + sorted(folder.glob("audio.*")):
        if path.suffix.lower() in MEDIA_SUFFIXES:
            return path
    return None


def write_text(folder: Path, segments: list[dict[str, Any]]) -> Path:
    """本机留一份能直接看的文字：一行一句，前面是录音里的时间。"""
    path = folder / TEXT_FILE
    path.write_text("\n".join(f"[{clock(s['start'])}] {s['text']}" for s in segments) + "\n", encoding="utf-8")
    return path


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
            if not (folder / TEXT_FILE).is_file():
                write_text(folder, segments)
            return segments
    audio = audio_of(folder)
    if not audio:
        raise ConsultError("找不到录音文件")
    segments = clean((transcriber or whisper_transcriber)(audio))
    if not segments:
        raise ConsultError("录音里没转出文字：确认一下是不是空录音")
    cached.write_text(json.dumps({"segments": segments}, ensure_ascii=False), encoding="utf-8")
    write_text(folder, segments)
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


# -- 客户版 -----------------------------------------------------------------------

CLIENT_HEADINGS = ("你现在的情况", "这次聊的核心问题", "我的判断", "建议你做的", "下一步")


def client_prompt(name: str, parts: list[dict[str, Any]], summary: str) -> str:
    body = "\n\n".join(f"[{clock(c['start'])}] {c['text']}" for c in parts)
    headings = "\n".join(f"## {h}" for h in CLIENT_HEADINGS)
    return f"""Park 刚做完一场 1v1 付费咨询，现在要发给客户一份会后纪要。请你以 Park 的口吻（第一人称「我」，称客户为「你」）写。

客户：{name}（这是 Park 自己写的，客户的名字以这里为准；转写里的同音字、别字不算）

下面是 Park 自己的复盘总结（内部用，里面有很多**不能给客户看**的东西）和整场录音的机器转写（有错别字、没分说话人）。

<内部总结>
{summary}
</内部总结>

<转写>
{body}
</转写>

写作要求：
- 这是会议纪要 + takeaway，给客户看的。简洁、具体、能执行，读完两三分钟。
- 只写录音里真的聊过的内容。数字只用客户自己说过的，口径要准（比如客户说的是销售额，就写销售额，不要写成利润）；录音里没谈的价格、报价、承诺一律不写。
- **绝对不能出现**：对这单生意的成交判断、报价策略、「素材」「选题」「复盘」「下次改进」、对客户的内部评价、Park 自己的定位宣传、任何平台引流字样。
- 不附转写原文，不写时间戳。
- Park 答应客户要做的事，放进「下一步」的「我这边」；客户自己说要做的，放进「你那边」。

严格按下面格式输出，不要输出别的：

称呼：（客户的称呼，以上面「客户」一栏里的名字为准，例如「阿皮」；看不出名字就写「你好」）
标题：（一句话概括这次咨询，15 字以内）

{headings}

每个二级标题下用 2–5 条「- 」开头的要点，可以用 **加粗** 标出关键词。「下一步」下面分两组：「**我这边**」和「**你那边**」，各自再列要点。
"""


def parse_client(output: str) -> dict[str, str]:
    text = (output or "").strip()
    call = re.search(r"^称呼[:：]\s*(.+)$", text, re.M)
    title = re.search(r"^标题[:：]\s*(.+)$", text, re.M)
    body = text[text.find("## "):] if "## " in text else ""
    missing = [h for h in CLIENT_HEADINGS if f"## {h}" not in body]
    if not body or missing:
        raise ConsultError(f"客户版没有按格式返回（缺：{'、'.join(missing) or '正文'}），可以点重试")
    return {"call": (call.group(1).strip() if call else "你好"), "title": (title.group(1).strip() if title else "咨询纪要"), "body": body}


LOGO = ('<svg viewBox="0 0 120 120" width="40" height="40" aria-hidden="true">'
        '<path d="M14 66 Q30 28 48 86" fill="none" stroke="#B7B0A3" stroke-width="9" stroke-linecap="round" stroke-linejoin="round"/>'
        '<path d="M48 86 Q76 88 106 22" fill="none" stroke="#15171C" stroke-width="11" stroke-linecap="round" stroke-linejoin="round"/>'
        '<circle cx="48" cy="86" r="9" fill="#E2461F"/></svg>')


def render_client(client: dict[str, str], *, day: date) -> str:
    import html

    import markdown as md

    body = md.markdown(client["body"], extensions=["sane_lists"])
    esc = html.escape
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(client['title'])} · 帕克动手</title>
<style>
:root{{--ink:#15171C;--ink-2:#5F5A51;--stone:#B7B0A3;--red:#E2461F;--paper:#F4F1EA;--card:#FFFFFF;--line:#E4DFD4}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.75 "PingFang SC","Noto Sans SC","Hiragino Sans GB",system-ui,sans-serif;-webkit-font-smoothing:antialiased}}
.page{{max-width:720px;margin:0 auto;padding:40px 20px 56px}}
header{{display:flex;align-items:center;gap:12px;padding-bottom:18px;border-bottom:1px solid var(--line)}}
.brand b{{display:block;font-family:"Songti SC","Noto Serif SC",serif;font-weight:900;font-size:20px;letter-spacing:.06em;line-height:1.2}}
.brand span{{font-size:12px;color:var(--ink-2);letter-spacing:.04em}}
.meta{{margin:28px 0 6px;font-size:13px;color:var(--ink-2);letter-spacing:.04em}}
h1{{font-family:"Songti SC","Noto Serif SC",serif;font-weight:900;font-size:28px;line-height:1.35;margin:0 0 18px}}
.hello{{margin:0 0 8px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:6px 24px 18px;margin-top:18px}}
h2{{font-family:"Songti SC","Noto Serif SC",serif;font-size:19px;margin:22px 0 8px;padding-left:12px;border-left:4px solid var(--red);line-height:1.3}}
ul,ol{{margin:0;padding-left:1.25em}}
li{{margin:6px 0}}
li::marker{{color:var(--stone)}}
strong{{font-weight:700}}
p{{margin:10px 0}}
footer{{margin-top:36px;padding-top:16px;border-top:1px solid var(--line);font-size:13px;color:var(--ink-2);display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}}
footer b{{color:var(--ink)}}
@media print{{body{{background:#fff}}.card{{border:0;padding:0}}}}
</style>
</head>
<body>
<div class="page">
<header>{LOGO}<div class="brand"><b>帕克动手</b><span>企业家的 AI 产品经理</span></div></header>
<div class="meta">咨询纪要 · {day.year} 年 {day.month} 月 {day.day} 日</div>
<h1>{esc(client['title'])}</h1>
<p class="hello">{esc(client['call'])}，这是我们这次聊的要点和接下来要做的事。</p>
<div class="card">
{body}
</div>
<footer><span><b>帕克动手</b> · PARK &amp; CO.</span><span>不交报告，交结果。</span></footer>
</div>
</body>
</html>
"""


# -- 笔记 -------------------------------------------------------------------------

def _cell(text: str) -> str:
    return re.sub(r"\s*\n\s*", "<br>", (text or "").strip()).replace("|", "\\|") or "—"


def render(*, name: str, day: date, audio: Path, parts: list[dict[str, Any]], analysis: dict[str, Any], client_file: str | None = None) -> str:
    duration = clock(parts[-1]["end"]) if parts else "00:00"
    client_line = f"\n> 发给客户的版本：[[{client_file}]]（只有纪要和 takeaway，不带转写）" if client_file else ""
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

> 录音 {duration}。这是给我自己看的版本：先是整场总结，「逐段对照」左边是机器转写的原话（有错字、没分说话人），右边是这一段的分析。{client_line}

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

def _cached(folder: Path, name: str, make: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    path = folder / name
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    value = make()
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return value


def run(folder: Path, vault: Path, *, transcriber: Transcriber | None = None, analyzer: Analyzer | None = None) -> Path:
    state = load_state(folder)
    name, day = state.get("name") or folder.name, date.fromisoformat(state.get("day") or date.today().isoformat())
    ask = analyzer or cli_analyzer
    save_state(folder, stage="transcribing", error=None, pid=os.getpid())
    parts = chunks(transcribe(folder, transcriber=transcriber))
    save_state(folder, stage="analyzing", minutes=round(parts[-1]["end"] / 60))
    analysis = _cached(folder, "analysis.json", lambda: parse(ask(prompt(name, parts)), len(parts)))
    analysis["notes"] = {int(k): v for k, v in analysis["notes"].items()}
    save_state(folder, stage="client")
    client = _cached(folder, "client.json", lambda: parse_client(ask(client_prompt(name, parts, analysis["summary"]))))

    target = note_path(vault, folder.name)
    target.parent.mkdir(parents=True, exist_ok=True)
    page = render_client(client, day=day)
    (folder / "客户版.html").write_text(page, encoding="utf-8")
    client_path = target.parent / f"{folder.name}{CLIENT_SUFFIX}"
    client_path.write_text(page, encoding="utf-8")
    target.write_text(render(name=name, day=day, audio=audio_of(folder) or folder, parts=parts,
                             analysis=analysis, client_file=client_path.name), encoding="utf-8")
    save_state(folder, stage="done", note=str(target), client=str(client_path), missing=analysis["missing"], pid=None)
    return target


def jobs() -> list[dict[str, Any]]:
    base = root()
    if not base.is_dir():
        return []
    rows = [{"slug": d.name, **load_state(d)} for d in base.iterdir() if d.is_dir() and (d / "state.json").is_file()]
    return sorted(rows, key=lambda r: r.get("created_at") or "", reverse=True)
