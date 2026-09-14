"""Weekly review: what worked, what did not, and what to change next week.

Built from Park's own videos of the last 7 days (numbers computed in code), their
teardown reports, topics finished this week and benchmark breakouts. Every claim must
point at a video that was in the input.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from typing import Any, Callable

from .judge import JudgeError, JudgeLoginError, cli_judge

REVIEW_COMMAND_ENV = "CONTENT_STUDIO_REVIEW_CMD"
DEFAULT_REVIEW_COMMAND = (
    "claude -p --model opus --output-format text "
    "--disallowedTools Bash,Edit,Write,Read,Glob,Grep,WebFetch,WebSearch,NotebookEdit,Skill"
)
ReviewFn = Callable[[str], dict]


class ReviewError(RuntimeError):
    """The weekly review could not be produced; the message is shown to Park."""


def week_key(now: datetime) -> str:
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


def _published(video: dict[str, Any]) -> datetime | None:
    raw = video.get("published_at")
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def gather_inputs(
    *,
    own_videos: list[dict[str, Any]],
    median_likes: float | None,
    creator: dict[str, dict[str, Any]],
    reports: dict[str, dict[str, Any]],
    topics: list[dict[str, Any]],
    breakouts: list[dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    since = now - timedelta(days=7)
    videos = []
    for video in own_videos:
        published = _published(video)
        if video.get("is_image_post") or published is None or published < since:
            continue
        metrics = creator.get(video["video_id"]) or {}
        report = reports.get(video["video_id"])
        videos.append(
            {
                "video_id": video["video_id"],
                "title": (video.get("title") or "")[:60],
                "published_at": published.isoformat(timespec="minutes"),
                "likes": video.get("likes"),
                "multiple": round(video["likes"] / median_likes, 1) if median_likes and video.get("likes") is not None else None,
                "collect_per_like": round((video.get("collects") or 0) / video["likes"], 3) if video.get("likes") else None,
                "fans": metrics.get("fan_increment"),
                "avg_watch_seconds": round(metrics["avg_view_second"]) if metrics.get("avg_view_second") else None,
                "bounce_2s": metrics.get("bounce_rate_2s"),
                "report": {
                    "thesis": (report.get("thesis") or {}).get("text"),
                    "why_boom": [w.get("text") for w in report.get("why_boom", [])][:4],
                    "why_scatter": [w.get("text") for w in report.get("why_scatter", [])][:4],
                    "drift_share": (report.get("drift") or {}).get("share"),
                } if report else None,
            }
        )
    done_topics = [t["title"] for t in topics if t.get("published_at") and (_published({"published_at": t["published_at"]}) or since) >= since]
    week_breakouts = [
        {"video_id": b["video_id"], "title": (b.get("title") or "")[:60], "account": b.get("account_nickname"), "multiple": b.get("multiple"),
         "why_boom": [w.get("text") for w in (reports.get(b["video_id"]) or {}).get("why_boom", [])][:2]}
        for b in breakouts
        if (_published(b) or since - timedelta(days=1)) >= since
    ][:8]
    return {"week": week_key(now), "since": since.date().isoformat(), "until": now.date().isoformat(), "videos": videos,
            "median_likes": median_likes, "topics_done": done_topics, "breakouts": week_breakouts}


def build_prompt(inputs: dict[str, Any], error: str | None = None) -> str:
    def fmt_video(v: dict[str, Any]) -> str:
        lines = [f"- id {v['video_id']}｜{v['title']}｜{v['published_at'][:10]}｜点赞 {v['likes']}｜倍数 {v['multiple']}｜收藏/赞 {v['collect_per_like']}"
                 f"｜涨粉 {v['fans']}｜平均观看 {v['avg_watch_seconds']} 秒｜2 秒跳出 {v['bounce_2s']}"]
        if v["report"]:
            r = v["report"]
            lines.append(f"  拆解主线：{r['thesis']}；跑题占比 {r['drift_share']}")
            lines.append(f"  为什么爆：{'；'.join(r['why_boom'])}")
            lines.append(f"  为什么散：{'；'.join(r['why_scatter'])}")
        return "\n".join(lines)

    videos = "\n".join(fmt_video(v) for v in inputs["videos"]) or "（这周没有发视频）"
    breakouts = "\n".join(f"- id {b['video_id']}｜{b['account']}｜{b['title']}｜{b['multiple']}×｜{'；'.join(b['why_boom'])}" for b in inputs["breakouts"]) or "（没有）"
    retry = f"\n\n上一次输出没有通过校验：{error}\n请修正后重新输出完整 JSON。" if error else ""
    return f"""你是 Park 的内容复盘教练。Park 的抖音号「Park 的 AI 世界」，AI + 金融，口播长视频。账号点赞中位数 {inputs['median_likes']}。
复盘区间：{inputs['since']} 到 {inputs['until']}。

## 这周 Park 发的视频（数字由代码算好，引用时只能用这里的数）
{videos}

## 这周完成的选题
{chr(10).join('- ' + t for t in inputs['topics_done']) or '（没有）'}

## 同期对标账号的爆款
{breakouts}

## 要求
只输出一个 JSON 对象，不要其他文字；字符串里需要引号时用「」。
- summary：这一周一句话。
- wins：做对的 1–3 条，每条 {{"text": "", "video_ids": ["..."]}}，text 里要有数字。
- problems：问题 1–3 条，同样结构，落到具体做法（开头、跑题、选题、标题），不要空话。
- patterns：从这周数据看出的规律 0–3 条（字符串）；样本太少就明说「样本不足」，不要硬总结。
- next_week：下周最该调整的 2–3 件事（字符串），每条可执行。
- experiment：下周做一个小实验 {{"hypothesis": "", "how": "", "measure": ""}}。
video_ids 只能用上面出现过的 id。不要编造没有给出的数据。{retry}

## 输出格式
{{"summary": "", "wins": [], "problems": [], "patterns": [], "next_week": [], "experiment": {{"hypothesis": "", "how": "", "measure": ""}}}}"""


def validate(raw: dict[str, Any], inputs: dict[str, Any]) -> list[str]:
    ids = {v["video_id"] for v in inputs["videos"]} | {b["video_id"] for b in inputs["breakouts"]}
    problems: list[str] = []
    if not str(raw.get("summary") or "").strip():
        problems.append("summary 缺失")
    for key, low, high in (("wins", 0, 3), ("problems", 0, 3)):
        items = raw.get(key)
        if not isinstance(items, list) or not low <= len(items) <= high:
            problems.append(f"{key} 需要 {low}–{high} 条")
            continue
        for i, item in enumerate(items):
            if not isinstance(item, dict) or not str(item.get("text") or "").strip():
                problems.append(f"{key}[{i}].text 缺失")
            elif not item.get("video_ids") or any(vid not in ids for vid in item["video_ids"]):
                problems.append(f"{key}[{i}].video_ids 必须是输入里的视频 id")
    if not isinstance(raw.get("patterns"), list) or len(raw["patterns"]) > 3:
        problems.append("patterns 需要 0–3 条")
    if not isinstance(raw.get("next_week"), list) or not 2 <= len(raw["next_week"]) <= 3:
        problems.append("next_week 需要 2–3 条")
    experiment = raw.get("experiment")
    if not isinstance(experiment, dict) or not all(str(experiment.get(k) or "").strip() for k in ("hypothesis", "how", "measure")):
        problems.append("experiment 需要 hypothesis、how、measure")
    return problems


def generate_review(inputs: dict[str, Any], *, review_fn: ReviewFn | None = None, attempts: int = 3, now: datetime | None = None) -> dict[str, Any]:
    if not inputs["videos"]:
        raise ReviewError("这 7 天没有发视频，没有可复盘的数据；先同步我的数据再试")
    fn = review_fn or (lambda prompt: cli_judge(prompt, command=os.environ.get(REVIEW_COMMAND_ENV) or DEFAULT_REVIEW_COMMAND, timeout=900))
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
            titles = {v["video_id"]: v["title"] for v in inputs["videos"]} | {b["video_id"]: b["title"] for b in inputs["breakouts"]}
            for key in ("wins", "problems"):
                for item in raw[key]:
                    item["videos"] = [{"video_id": vid, "title": titles[vid]} for vid in item["video_ids"]]
            return {**raw, "week": inputs["week"], "since": inputs["since"], "until": inputs["until"],
                    "videos": inputs["videos"], "generated_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")}
        error = "；".join(problems[:6])
    raise ReviewError(f"复盘连续 {attempts} 次没通过校验，可点重新生成：{error}")
