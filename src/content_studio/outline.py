"""Shooting outline for a talking-head video topic.

Not a word-for-word script: Park speaks from an outline. The first 15 seconds must
state the thesis, because his recent videos are watched for only 14–26 seconds on
average, and every section must serve the thesis (the teardown's drift test).
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any

from .judge import JudgeLoginError
from .writer import ARTICLE_BLOCK, DEFAULT_DRAFTS_DIR, WriteFn, WriterError, cli_write, gather_sources

OUTLINE_COMMAND_ENV = "CONTENT_STUDIO_OUTLINE_CMD"
DEFAULT_OUTLINE_COMMAND = (
    "claude -p --model opus --output-format text "
    '--disallowedTools "Bash Edit Write Read Glob Grep WebFetch WebSearch NotebookEdit Skill"'
)


def build_prompt(topic: dict[str, Any], sources: list[dict[str, Any]], error: str | None = None, adjustments: list[str] | None = None) -> str:
    material = "\n\n".join(
        f"### 素材 {i + 1}：{s['title']}\n来源：{s['url'] or s['path']}\n\n{s['body']}" for i, s in enumerate(sources)
    ) or "（没有附带素材，只根据选题和备注写。）"
    retry = f"\n\n上一次输出有问题：{error}。请修正后重新输出。" if error else ""
    adjust = "\n".join(f"- {a}" for a in (adjustments or [])[:3])
    adjust_block = f"\n\n最近一次每周复盘定下的调整，这份提纲要照着做：\n{adjust}" if adjust else ""
    return f"""你在帮 Park 准备一条抖音口播视频的拍摄提纲。Park 的号是「Park 的 AI 世界」（AI + 金融），他对着提纲即兴讲，不念逐字稿。

两条硬约束来自他账号的真实数据和拆解：
1. 他近期视频平均只被看 14–26 秒，所以「前 15 秒」必须直接说出这条视频的主线和观众为什么要听下去，不寒暄、不铺垫。
2. 每一段都要为主线服务：假设删掉这一段主线会不会明显变弱？不会就不要这一段。{adjust_block}

## 选题
{topic['title']}

## Park 的备注（可能包含每日统筹给的 Hook 和骨架）
{topic.get('memo') or '（无）'}

## 素材
{material}

## 输出要求
Markdown，严格按下面的结构，放在单独一行的 <<<ARTICLE>>> 和单独一行的 <<<END>>> 之间：

# 视频标题
预计时长：N 分钟

## 前 15 秒
- 第一句：……（直接说主线）
- 为什么要听下去：……

## 主线
一句话。

## 第 1 段：小标题
- 论点：……
- 例子 / 素材：……（素材里别人的观点注明是谁说的）
- 画面提示：……（可选，没有就写「人脸」）

（3–5 段，每段同样结构）

## 结尾
- 收束一句：……
- 引导：……（关注、评论问题，一句）

## 不要讲过头
- ……（素材缺证据、不能说成事实、不能给投资建议的地方）

不要编造 Park 的经历、数据和收入；不写逐字稿。{retry}"""


def extract_outline(output: str) -> str:
    match = ARTICLE_BLOCK.search(output)
    if not match:
        raise WriterError("模型没有按格式返回提纲")
    text = match.group(1).strip()
    if not text.startswith("#"):
        raise WriterError("提纲缺少标题")
    for heading in ("## 前 15 秒", "## 主线", "## 结尾"):
        if heading not in text:
            raise WriterError(f"提纲缺少「{heading[3:]}」一节")
    sections = len(re.findall(r"^## 第\s*\d+\s*段", text, flags=re.MULTILINE))
    if not 3 <= sections <= 5:
        raise WriterError(f"正文需要 3–5 段，现在是 {sections} 段")
    return text + "\n"


def write_outline(
    topic: dict[str, Any],
    *,
    vault_raw: str,
    drafts_dir: Path = DEFAULT_DRAFTS_DIR,
    write_fn: WriteFn | None = None,
    attempts: int = 2,
    now: datetime | None = None,
    adjustments: list[str] | None = None,
) -> dict[str, Any]:
    fn = write_fn or (lambda prompt: cli_write(prompt, command=os.environ.get(OUTLINE_COMMAND_ENV) or DEFAULT_OUTLINE_COMMAND, timeout=900))
    sources = gather_sources(vault_raw, topic.get("note_paths") or [])
    error: str | None = None
    for _ in range(attempts):
        try:
            outline = extract_outline(fn(build_prompt(topic, sources, error, adjustments)))
            break
        except JudgeLoginError:
            raise
        except WriterError as exc:
            error = str(exc)
    else:
        raise WriterError(f"连续 {attempts} 次没写成提纲：{error}")
    folder = drafts_dir.expanduser() / f"topic-{topic['id']}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "outline.md"
    path.write_text(outline, encoding="utf-8")
    meta = {
        "topic_id": topic["id"],
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "sources": [{k: s[k] for k in ("path", "title", "url")} for s in sources],
    }
    (folder / "outline.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"outline_path": str(path), **meta}


def read_outline(topic: dict[str, Any]) -> dict[str, Any] | None:
    if not topic.get("outline_path"):
        return None
    path = Path(topic["outline_path"])
    if not path.is_file():
        return None
    meta_path = path.with_name("outline.meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    return {"markdown": path.read_text(encoding="utf-8"), "updated_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds"), **meta}
