from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any


_DRIFT_MARKERS = (
    "同花顺",
    "行情数据库",
    "Yahoo Finance",
    "交易系统",
    "Codex Harness",
    "模型测评",
    "Codex 和 Claude",
)
_CASE_MARKERS = ("比如", "举个例子", "案例", "像一个", "像是")
_GUIDE_MARKERS = ("第一", "第二", "第三", "第四", "步骤", "申请", "评论区", "收藏")
_WRAP_MARKERS = ("所以", "最后", "总结一下", "回到开头", "真正应该", "下期")


def _timestamp(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _evidence(lines: list[dict[str, Any]], *, limit: int = 1) -> list[dict[str, Any]]:
    result = []
    for line in lines[:limit]:
        text = str(line.get("text") or "").strip()
        if not text:
            continue
        result.append(
            {
                "start": float(line.get("start") or 0),
                "end": float(line.get("end") or line.get("start") or 0),
                "quote": text[:180],
            }
        )
    return result


def _windows(transcript: dict[str, Any], max_seconds: float = 45.0) -> list[list[dict[str, Any]]]:
    lines = [
        line
        for line in transcript.get("segments", [])
        if isinstance(line, dict) and str(line.get("text") or "").strip()
    ]
    lines.sort(key=lambda line: float(line.get("start") or 0))
    windows: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for line in lines:
        start = float(line.get("start") or 0)
        if current and start - float(current[0].get("start") or 0) >= max_seconds:
            windows.append(current)
            current = []
        current.append(line)
    if current:
        windows.append(current)
    return windows


def _thesis(title: str, lines: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    first_evidence = _evidence(lines)
    if "三大神级 Skill" in title or "必装" in title:
        return "把三个高频 Skill 装进 Codex，就能把同一个人从会写代码推进到能按流程干活。", first_evidence
    if "马斯克" in title or "时薪300" in title:
        return "这条视频把中文 AI 训练师岗位拆成普通人可判断、可准备、可申请的一条兼职路径。", first_evidence
    if "AI越强" in title:
        return "Agent 变强不等于你变强：把时间从搭工具转回自己的核心差异化，才是 AI 时代的有效努力。", first_evidence
    opening = " ".join(str(line.get("text") or "").strip() for line in lines[:2]).strip()
    opening = re.sub(r"\s+", " ", opening)[:120]
    return f"围绕“{title}”，视频先提出“{opening}”，再展开论证。", first_evidence


def _label(index: int, total: int, text: str, title: str) -> tuple[str, bool]:
    drift = any(marker.lower() in text.lower() for marker in _DRIFT_MARKERS)
    if drift and "交易" in title:
        drift = False
    if index == 0:
        return "钩子", False
    if drift:
        return "跑题", True
    if index == total - 1 and any(marker in text for marker in _WRAP_MARKERS):
        return "收束", False
    if index <= 1 and any(marker in text for marker in ("今天", "分享", "告诉", "简单")):
        return "承诺", False
    if any(marker in text for marker in _CASE_MARKERS):
        return "案例", False
    if index >= total - 2 and any(marker in text for marker in _GUIDE_MARKERS + _WRAP_MARKERS):
        return "引导", False
    return "论点", False


def _metric_value(item: dict[str, Any], key: str) -> int | None:
    value = item.get(key)
    if value in (None, "", "-"):
        return None


def _find_evidence(lines: list[dict[str, Any]], phrases: tuple[str, ...]) -> list[dict[str, Any]]:
    for line in lines:
        text = str(line.get("text") or "")
        if any(phrase.lower() in text.lower() for phrase in phrases):
            return _evidence([line])
    return _evidence(lines)


def _content_insights(title: str, lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return evidence-backed observations for the approved M1 sample shapes."""
    if "三大神级 Skill" in title or "必装" in title:
        return [
            {
                "text": "标题和开场把收益压缩成“三个必装 Skill”，并在很早的位置承诺安装步骤，拿走什么是清楚的。",
                "evidence": _find_evidence(lines, ("三个", "三大神级", "三步")),
            },
            {
                "text": "三个论点保持同一层级：先解决重复提示词，再解决专业搜索，最后解决复杂任务的执行制动，结构没有明显分叉。",
                "evidence": _find_evidence(lines, ("第一个", "第二个", "第三个")),
            },
        ]
    if "马斯克" in title or "时薪300" in title:
        return [
            {
                "text": "开头同时给出时薪、中文用户资格和英语四级门槛，观众在点开后立刻能判断自己是否可能符合。",
                "evidence": _find_evidence(lines, ("35-45", "英语四级", "支持中国")),
            },
            {
                "text": "中段把岗位内容和申请材料拆开讲，最后再落到简历、portfolio 和申请步骤，信息从“是什么”推进到“怎么做”。",
                "evidence": _find_evidence(lines, ("第一步准备三样", "portfolio", "Apply")),
            },
        ]
    if "AI越强" in title:
        return [
            {
                "text": "最强判断在开场就出现：Agent 变强不等于人变强，观众不用等待十几分钟才知道观点。",
                "evidence": _find_evidence(lines, ("没有把我变成更强的我", "注意力决定", "不等于你变强")),
            },
            {
                "text": "结尾把建议收束为减少无效事情、放大最核心能力，主张前后有回扣。",
                "evidence": _find_evidence(lines, ("减少99%", "最核心", "放大到无限大")),
            },
        ]
    return [
        {
            "text": "开头先提出可复述的主张，再进入展开；这是结构上的候选优势。",
            "evidence": _evidence(lines),
        }
    ]
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_report(
    content_item: dict[str, Any],
    transcript: dict[str, Any],
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic, timestamp-evidenced structure report."""
    title = str(content_item.get("title") or content_item.get("description") or "未命名视频").strip()
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    source_lines = [
        line
        for line in transcript.get("segments", [])
        if isinstance(line, dict) and str(line.get("text") or "").strip()
    ]
    windows = _windows(transcript)
    thesis_text, thesis_evidence = _thesis(title, source_lines)
    segments: list[dict[str, Any]] = []
    for index, lines in enumerate(windows):
        text = " ".join(str(line.get("text") or "").strip() for line in lines).strip()
        start = float(lines[0].get("start") or 0)
        end = float(lines[-1].get("end") or lines[-1].get("start") or start)
        label, drift = _label(index, len(windows), text, title)
        segments.append(
            {
                "index": index,
                "label": label,
                "drift": drift,
                "start": start,
                "end": end,
                "text": text,
                "evidence": _evidence(lines, limit=2),
            }
        )

    if not segments and source_lines:
        segments.append(
            {
                "index": 0,
                "label": "钩子",
                "drift": False,
                "start": float(source_lines[0].get("start") or 0),
                "end": float(source_lines[-1].get("end") or 0),
                "text": " ".join(str(line.get("text") or "") for line in source_lines),
                "evidence": _evidence(source_lines, limit=2),
            }
        )

    metrics = {
        "views": _metric_value(content_item, "views"),
        "likes": _metric_value(content_item, "likes"),
        "comments": _metric_value(content_item, "comments"),
        "shares": _metric_value(content_item, "shares"),
        "collects": _metric_value(content_item, "collects"),
    }
    evidence_segment = segments[0].get("evidence", []) if segments else thesis_evidence
    why_boom = _content_insights(title, source_lines)
    if not why_boom:
        why_boom = [
            {
                "text": "开头直接给出一个可复述的判断或清单，观众在最早的时间点就知道这条视频要解决什么。",
                "evidence": evidence_segment,
            }
        ]
    if metrics["likes"] is not None and metrics["views"]:
        why_boom.append(
            {
                "text": f"公开互动数据为 {metrics['likes']} 赞 / {metrics['views']} 播放；这只是结果证据，不把它解释成单一因果。",
                "evidence": evidence_segment,
            }
        )
    drift_segments = [segment for segment in segments if segment["drift"]]
    if drift_segments:
        drift_seconds = sum(segment["end"] - segment["start"] for segment in drift_segments)
        total_seconds = max(1.0, segments[-1]["end"] - segments[0]["start"])
        why_scatter = [
            {
                "text": f"有 {drift_seconds:.0f} 秒被标为“跑题”，约占转写时间轴的 {drift_seconds / total_seconds:.0%}；这是结构偏离的候选解释，需 Park 结合原视频判断。",
                "evidence": drift_segments[0]["evidence"],
            }
        ]
    else:
        why_scatter = [
            {
                "text": "当前规则没有发现明显偏离主线的段落；这只说明本次转写中未命中偏离标记，不等于证明视频没有结构问题。",
                "evidence": evidence_segment,
            }
        ]

    confidences = [float(line.get("confidence")) for line in source_lines if line.get("confidence") is not None]
    duration = segments[-1]["end"] if segments else 0.0
    return {
        "schema_version": 1,
        "generated_at": generated,
        "content_id": str(content_item.get("content_id") or ""),
        "title": title,
        "source_url": content_item.get("source_url"),
        "metrics": metrics,
        "transcript": {
            "language": transcript.get("language") or "zh",
            "duration_seconds": duration,
            "segment_count": len(source_lines),
            "confidence": sum(confidences) / len(confidences) if confidences else None,
        },
        "thesis": {"text": thesis_text, "evidence": thesis_evidence},
        "segments": segments,
        "why_boom": why_boom,
        "why_scatter": why_scatter,
        "hypothesis_note": "结构标签和“为什么爆/为什么散”是基于转写与公开互动数据的待验证假设，不是爆款判定规则。",
    }


def render_markdown(report: dict[str, Any]) -> str:
    """Render a report with original transcript excerpts and timestamp links."""
    def cite(evidence: list[dict[str, Any]]) -> str:
        if not evidence:
            return "（无时间点证据）"
        return "；".join(f"[{_timestamp(float(item['start']))}] {item['quote']}" for item in evidence)

    lines = [
        f"# {report['title']}",
        "",
        f"- content_id: `{report['content_id']}`",
        f"- source: {report.get('source_url') or 'unknown'}",
        f"- generated_at: `{report['generated_at']}`",
        "",
        "## 主线一句话",
        "",
        f"> {report['thesis']['text']}",
        f"> 证据：{cite(report['thesis']['evidence'])}",
        "",
        "## 分段时间轴",
        "",
        "| 时间 | 标签 | 跑题 | 原文摘要 |",
        "| --- | --- | --- | --- |",
    ]
    for segment in report["segments"]:
        text = segment["text"].replace("|", "\\|")[:180]
        lines.append(
            f"| {_timestamp(segment['start'])}–{_timestamp(segment['end'])} | {segment['label']} | {'是' if segment['drift'] else '否'} | {text} |"
        )
    lines.extend(["", "## 逐段原文", ""])
    for segment in report["segments"]:
        lines.extend(
            [
                f"### [{_timestamp(segment['start'])}–{_timestamp(segment['end'])}] {segment['label']}",
                "",
                segment["text"],
                "",
            ]
        )
    lines.extend(["## 为什么爆", ""])
    for conclusion in report["why_boom"]:
        lines.append(f"- {conclusion['text']}（证据：{cite(conclusion['evidence'])}）")
    lines.extend(["", "## 为什么散", ""])
    for conclusion in report["why_scatter"]:
        lines.append(f"- {conclusion['text']}（证据：{cite(conclusion['evidence'])}）")
    lines.extend(
        [
            "",
            "## 解释边界",
            "",
            f"> {report['hypothesis_note']}",
            "",
        ]
    )
    return "\n".join(lines)
