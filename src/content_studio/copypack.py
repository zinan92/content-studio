"""Per-platform publishing copy for one topic, plus where it has been published.

Nothing here publishes. Limits are the workbench's conservative caps for each
platform's fields; X counts CJK characters as two.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any, Callable

from .judge import JudgeError, JudgeLoginError, cli_judge

COPY_COMMAND_ENV = "CONTENT_STUDIO_COPY_CMD"
DEFAULT_COPY_COMMAND = (
    "claude -p --model sonnet --output-format text "
    "--disallowedTools Bash,Edit,Write,Read,Glob,Grep,WebFetch,WebSearch,NotebookEdit,Skill"
)

PLATFORMS: dict[str, dict[str, Any]] = {
    "douyin": {"label": "抖音", "title": 30, "body": 1000, "tags": 5, "admin": "https://creator.douyin.com/creator-micro/content/upload"},
    "channels": {"label": "视频号", "title": 16, "body": 1000, "tags": 5, "admin": "https://channels.weixin.qq.com/platform/post/create"},
    "xiaohongshu": {"label": "小红书", "title": 20, "body": 1000, "tags": 10, "admin": "https://creator.xiaohongshu.com/publish/publish"},
    "bilibili": {"label": "B 站", "title": 80, "body": 2000, "tags": 10, "admin": "https://member.bilibili.com/platform/upload/video/frame"},
    "youtube": {"label": "YouTube", "title": 100, "body": 5000, "tags": 15, "admin": "https://studio.youtube.com/"},
    "x": {"label": "X", "title": 0, "body": 280, "tags": 3, "admin": "https://x.com/compose/post", "weighted": True},
    "yanxishi": {"label": "研习室", "title": 64, "body": 200, "tags": 5, "admin": None},
}
# Park publishes to these three; the rest stay editable behind 「更多平台」 but are not generated.
CORE_PLATFORMS = ("douyin", "channels", "yanxishi")
CopyFn = Callable[[str], dict]


class CopyError(RuntimeError):
    """Copy could not be produced; the message is shown to Park."""


def x_length(text: str) -> int:
    return sum(2 if re.match(r"[⺀-鿿＀-￯　-〿]", ch) else 1 for ch in text)


def measure(platform: str, entry: dict[str, Any]) -> list[str]:
    spec = PLATFORMS[platform]
    problems = []
    title = str(entry.get("title") or "")
    body = str(entry.get("body") or "")
    tags = entry.get("tags") or []
    if spec["title"] and not title.strip():
        problems.append(f"{spec['label']}缺标题")
    if spec["title"] and len(title) > spec["title"]:
        problems.append(f"{spec['label']}标题 {len(title)} 字，超过 {spec['title']}")
    if not spec["title"] and title:
        problems.append(f"{spec['label']}不需要标题")
    length = x_length(body + " " + " ".join(f"#{t}" for t in tags)) if spec.get("weighted") else len(body)
    if not body.strip():
        problems.append(f"{spec['label']}缺正文")
    elif length > spec["body"]:
        problems.append(f"{spec['label']}正文长度 {length}，超过 {spec['body']}")
    if not isinstance(tags, list) or len(tags) > spec["tags"] or any(not str(t).strip() or "#" in str(t) for t in tags):
        problems.append(f"{spec['label']}话题最多 {spec['tags']} 个，不带 #")
    return problems


def build_prompt(topic: dict[str, Any], basis: str, error: str | None = None, platforms: tuple[str, ...] = CORE_PLATFORMS) -> str:
    limits = "\n".join(
        f"- {key}（{spec['label']}）：" + (f"标题 ≤{spec['title']} 字，" if spec["title"] else "不要标题（title 填空字符串），")
        + f"正文 ≤{spec['body']}{'（中文字按 2 计，含话题）' if spec.get('weighted') else ' 字'}，话题 ≤{spec['tags']} 个"
        for key, spec in PLATFORMS.items()
        if key in platforms
    )
    retry = f"\n\n上一次输出没有通过校验：{error}\n请修正后重新输出完整 JSON。" if error else ""
    return f"""你在帮 Park（抖音号「Park 的 AI 世界」，AI + 金融）为同一条内容写各平台的发布文案。内容以口播视频为主，研习室是他的会员文章产品。

## 选题
{topic['title']}

## 内容依据（提纲 / 文章 / 备注）
{basis[:12000]}

## 各平台上限
{limits}

## 要求
- 只输出一个 JSON 对象，键是上面的平台 key，每个值 {{"title": "", "body": "", "tags": []}}。字符串里需要引号时用「」。
- 按平台习惯写：抖音、视频号简短有钩子；小红书标题口语、正文分段带表情可少量；B 站、YouTube 简介写清这期讲了什么（可分点）；X 一条就能看懂的观点；研习室是一句话摘要。只写上面列出的平台。
- tags 不带 #。不要编造数据和经历；不写「保证赚钱」「必涨」这类承诺；不给投资建议。{retry}"""


def generate_copy(topic: dict[str, Any], basis: str, *, copy_fn: CopyFn | None = None, attempts: int = 3, platforms: tuple[str, ...] = CORE_PLATFORMS) -> dict[str, Any]:
    if not basis.strip():
        raise CopyError("先写拍摄提纲或文章，再生成文案")
    fn = copy_fn or (lambda prompt: cli_judge(prompt, command=os.environ.get(COPY_COMMAND_ENV) or DEFAULT_COPY_COMMAND, timeout=600))
    error: str | None = None
    for _ in range(attempts):
        try:
            raw = fn(build_prompt(topic, basis, error, platforms))
        except JudgeLoginError:
            raise
        except JudgeError as exc:
            error = str(exc)
            continue
        problems = [p for key in platforms for p in (measure(key, raw[key]) if isinstance(raw.get(key), dict) else [f"缺少 {key}"])]
        if not problems:
            return {key: {"title": raw[key].get("title") or "", "body": raw[key]["body"], "tags": [str(t).strip() for t in raw[key].get("tags") or []]} for key in platforms}
        error = "；".join(problems[:8])
    raise CopyError(f"文案连续 {attempts} 次没通过长度校验，可点重试：{error}")


def save_copy(drafts_dir: Path, topic_id: int, copy: dict[str, Any]) -> Path:
    folder = drafts_dir.expanduser() / f"topic-{topic_id}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "copy.json"
    payload = {"updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "platforms": copy}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_copy(drafts_dir: Path, topic_id: int) -> dict[str, Any] | None:
    path = drafts_dir.expanduser() / f"topic-{topic_id}" / "copy.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    data["checks"] = {key: measure(key, entry) for key, entry in data["platforms"].items() if key in PLATFORMS}
    return data
