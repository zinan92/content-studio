"""Daily briefing: what Park should read today and which pieces can become today's video.

Inputs come only from the read-only vault and the local store. The model must cite
sources that were actually in the input; anything else fails validation and retries.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import os
import re
from typing import Any, Callable

from . import vault
from .judge import JudgeError, JudgeLoginError, cli_judge

BRIEF_COMMAND_ENV = "CONTENT_STUDIO_BRIEF_CMD"
DEFAULT_BRIEF_COMMAND = (
    "claude -p --model opus --output-format text "
    "--disallowedTools Bash,Edit,Write,Read,Glob,Grep,WebFetch,WebSearch,NotebookEdit,Skill"
)
MAX_DAILY_CHARS = 14000
EFFORTS = ("低", "中", "高")

BriefFn = Callable[[str], dict]


class BriefingError(RuntimeError):
    """The briefing could not be produced; the message is shown to Park."""


def _strip_html(html: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def gather_inputs(vault_raw: str, day: date, *, own_videos: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    root = vault.vault_root(vault_raw)
    dailies = []
    for item in vault.dailies(vault_raw, day):
        if not item["path"]:
            continue
        raw = (root / item["path"]).read_text(encoding="utf-8", errors="replace")
        text = _strip_html(raw) if item["kind"] == "html" else raw
        dailies.append({"label": item["label"], "path": item["path"], "text": text[:MAX_DAILY_CHARS]})
    now = datetime.combine(day, datetime.max.time())
    recent = vault.inbox(vault_raw, since=datetime.combine(day - timedelta(days=2), datetime.min.time()), sources=("clipping", "saved"))
    raw_outputs = vault.inbox(vault_raw, since=datetime.combine(day - timedelta(days=7), datetime.min.time()), sources=("raw",))
    notes = [
        {"kind": i["source_label"], "path": i["path"], "title": i["title"], "url": i["url"], "summary": i["summary"]}
        for i in (recent[:25] + raw_outputs[:15])
        if max(i["created_at"], i["modified_at"]) <= now.isoformat()
    ]
    urls = set()
    for d in dailies:
        urls.update(re.findall(r"\((https?://[^)\s]+)\)", d["text"]))
    urls.update(n["url"] for n in notes if n["url"])
    return {
        "day": day.isoformat(),
        "dailies": dailies,
        "notes": notes,
        "own_videos": own_videos or [],
        "allowed_paths": sorted({d["path"] for d in dailies} | {n["path"] for n in notes}),
        "allowed_urls": sorted(urls),
    }


def build_prompt(inputs: dict[str, Any], error: str | None = None) -> str:
    dailies = "\n\n".join(f"### {d['label']}（path: {d['path']}）\n{d['text']}" for d in inputs["dailies"]) or "（今天的日报还没出）"
    notes = "\n".join(
        f"- [{n['kind']}] {n['title']}（path: {n['path']}{'；url: ' + n['url'] if n['url'] else ''}）：{n['summary']}" for n in inputs["notes"]
    ) or "（没有新笔记）"
    videos = "\n".join(
        f"- {v['title'][:40]} · {v.get('published_at', '')[:10]} · 点赞 {v.get('likes')} · 倍数 {v.get('multiple')}" for v in inputs["own_videos"]
    ) or "（没有数据）"
    retry = f"\n\n上一次输出没有通过校验：{error}\n请修正后重新输出完整 JSON。" if error else ""
    return f"""你是 Park 的内容统筹。Park 的抖音号是「Park 的 AI 世界」，方向是 AI + 金融，形式是口播视频；他也会把观点写成文章发到会员产品。
今天是 {inputs['day']}。请只根据下面的材料，帮他统筹今天：先读什么，今天可以拍什么。

## 今天的日报
{dailies}

## 近 2 天的剪藏 / 收藏，近 7 天 Park 自己的原始输出
{notes}

## Park 最近的视频表现（倍数 = 点赞 ÷ 账号点赞中位数）
{videos}

## 要求
- 只输出一个 JSON 对象，不要任何其他文字。字符串里需要引号时用「」。
- known：从材料里能确定的事实，2–4 条；unknown：做判断还缺的信息，1–3 条。不要编造 Park 的数据、经历或态度。
- reads：今天最值得 Park 读的 3–6 条。每条 title、why（为什么值得他读，一句话，结合他的方向）、source（只能是上面出现过的 path 或 url，写成 {{"path": "..."}} 或 {{"url": "..."}}）。
- videos：今天可以拍的 2–4 条，恰好 1 条 primary 为 true（首选）。每条：
  title（视频标题，说人话），hook（前 15 秒要说的一句话），claim（核心主张一句话），
  outline（口播骨架 3–5 条，每条一句），sources（1–3 个，只能是上面出现过的 path 或 url，每个 {{"path"或"url": "...", "title": "..."}}），
  why_today（为什么是今天拍），effort（拍摄负担：低/中/高），caution（不能讲过头的地方，没有就写空字符串）。
  优先用 Park 自己的原始输出做主线、用日报和剪藏做由头；不要只是复述新闻。
- prep：今日最小准备，一两句话。

## 输出格式
{{"known": [...], "unknown": [...], "reads": [{{"title": "", "why": "", "source": {{"path": ""}}}}], "videos": [{{"title": "", "hook": "", "claim": "", "outline": [], "sources": [], "why_today": "", "effort": "中", "caution": "", "primary": true}}], "prep": ""}}{retry}"""


def _source_ok(source: Any, inputs: dict[str, Any]) -> bool:
    if not isinstance(source, dict):
        return False
    if source.get("path"):
        return source["path"] in inputs["allowed_paths"]
    if source.get("url"):
        return source["url"] in inputs["allowed_urls"]
    return False


def validate(raw: dict[str, Any], inputs: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for key in ("known", "unknown"):
        if not isinstance(raw.get(key), list):
            problems.append(f"{key} 必须是列表")
    reads = raw.get("reads")
    if not isinstance(reads, list) or not 1 <= len(reads) <= 6:
        problems.append("reads 需要 1–6 条")
    else:
        for i, item in enumerate(reads):
            if not isinstance(item, dict) or not str(item.get("title") or "").strip() or not str(item.get("why") or "").strip():
                problems.append(f"reads[{i}] 缺少 title 或 why")
            elif not _source_ok(item.get("source"), inputs):
                problems.append(f"reads[{i}].source 不是材料里出现过的 path 或 url")
    videos = raw.get("videos")
    if not isinstance(videos, list) or not 1 <= len(videos) <= 4:
        problems.append("videos 需要 1–4 条")
    else:
        if sum(1 for v in videos if isinstance(v, dict) and v.get("primary") is True) != 1:
            problems.append("videos 必须恰好 1 条 primary 为 true")
        for i, video in enumerate(videos):
            if not isinstance(video, dict):
                problems.append(f"videos[{i}] 不是对象")
                continue
            for field in ("title", "hook", "claim", "why_today"):
                if not str(video.get(field) or "").strip():
                    problems.append(f"videos[{i}].{field} 缺失")
            outline = video.get("outline")
            if not isinstance(outline, list) or not 3 <= len(outline) <= 5:
                problems.append(f"videos[{i}].outline 需要 3–5 条")
            if video.get("effort") not in EFFORTS:
                problems.append(f"videos[{i}].effort 只能是 低/中/高")
            sources = video.get("sources")
            if not isinstance(sources, list) or not sources:
                problems.append(f"videos[{i}].sources 为空")
            elif not all(_source_ok(s, inputs) for s in sources):
                problems.append(f"videos[{i}].sources 含有材料里没有的来源")
    return problems


def generate_briefing(
    inputs: dict[str, Any],
    *,
    brief_fn: BriefFn | None = None,
    attempts: int = 3,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not inputs["dailies"] and not inputs["notes"]:
        raise BriefingError("今天的日报还没出，近几天也没有新笔记，没有可统筹的材料")
    fn = brief_fn or (lambda prompt: cli_judge(prompt, command=os.environ.get(BRIEF_COMMAND_ENV) or DEFAULT_BRIEF_COMMAND, timeout=900))
    error: str | None = None
    for _ in range(attempts):
        try:
            raw = fn(build_prompt(inputs, error))
        except JudgeLoginError:
            raise
        except JudgeError as exc:
            error = str(exc)
            continue
        problems = validate(raw, inputs)
        if not problems:
            titles = {p: n["title"] for n in inputs["notes"] for p in [n["path"]]}
            titles.update({d["path"]: d["label"] for d in inputs["dailies"]})
            for video in raw["videos"]:
                for source in video["sources"]:
                    if source.get("path") and not source.get("title"):
                        source["title"] = titles.get(source["path"], source["path"])
            return {
                **raw,
                "day": inputs["day"],
                "generated_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
                "input_counts": {"dailies": len(inputs["dailies"]), "notes": len(inputs["notes"])},
            }
        error = "；".join(problems[:6])
    raise BriefingError(f"统筹连续 {attempts} 次没通过校验，可点重新生成：{error}")
