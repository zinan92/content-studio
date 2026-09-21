"""开头和结尾：把 Park 的原始内容包装成能开口的两头，中间留给他自己。

Park 的原话：「我自己本身的内容就是 don't be silent 的内容，我的思考足够深度。」
所以这里不重构、不写大纲，只写两样最难的——把人留在前一分钟的开头，和让人觉得
「这件事我够得着」的结尾。

规则不在代码里。它在 Anna 的工作流文件里（Obsidian，Park 随时能改），而那份文件的
每一条都来自一勾工作号真实逐字稿加点赞倍数。文件找不到就直接报错，不偷偷退回旧提示词：
Park 会以为他的修改生效了，其实没有。
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
WORKFLOWS_ENV = "CONTENT_STUDIO_WORKFLOWS"
DEFAULT_WORKFLOWS = Path("~/park-hands/001_role/content_editor Anna/workflows")
FRAMEWORK_FILE = "一勾式开头结尾.md"
LABEL = "一勾式开头和结尾"
FILENAME = "bookend.md"
DEFAULT_OUTLINE_COMMAND = (
    "claude -p --model opus --output-format text "
    '--disallowedTools "Bash Edit Write Read Glob Grep WebFetch WebSearch NotebookEdit Skill"'
)
# 下游真正会读的三节：opening.thesis_for() 解析「主线」，三点评分把开头当痛点和反差、
# 把结尾当交付。少一节，后面两个功能就静默降级成拿标题当主线。
SECTIONS = ("主线", "开头", "结尾")


def workflows_dir() -> Path:
    return Path(os.environ.get(WORKFLOWS_ENV) or DEFAULT_WORKFLOWS).expanduser()


def load_framework(root: Path | None = None) -> str:
    path = (root or workflows_dir()) / FRAMEWORK_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        raise WriterError(f"找不到框架文件：{path}") from None
    body = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S).strip()
    if not body:
        raise WriterError(f"框架文件是空的：{path}")
    return body


def build_prompt(
    topic: dict[str, Any],
    sources: list[dict[str, Any]],
    *,
    framework: str,
    error: str | None = None,
    adjustments: list[str] | None = None,
) -> str:
    material = "\n\n".join(
        f"### 素材 {i + 1}：{s['title']}\n来源：{s['url'] or s['path']}\n\n{s['body']}" for i, s in enumerate(sources)
    ) or "（没有附带素材，只根据选题和备注写。）"
    retry = f"\n\n上一次输出有问题：{error}。请修正后重新输出。" if error else ""
    adjust = "\n".join(f"- {a}" for a in (adjustments or [])[:3])
    adjust_block = f"\n\n## 最近一次每周复盘定下的调整\n这一稿要照着做：\n{adjust}" if adjust else ""
    return f"""你在帮 Park 准备一条抖音口播视频的**开头和结尾**。他的号是「Park 的 AI 世界」，对着稿子即兴讲。

**中间不要写。** 中间是 Park 自己的思考，他自己讲。你只写两头。

下面是他和 Anna 定的加工框架，每一条规则都来自一勾工作号真实视频的逐字稿和点赞倍数。
**严格照着做**，它比你的写作习惯优先：

---

{framework}

---

## 选题
{topic['title']}

## Park 的备注（可能写了这条要砸哪个数字、给谁看、结尾承接什么）
{topic.get('memo') or '（无）'}

## 素材（Park 的原始内容）
{material}{adjust_block}

## 输出
按框架的「输出」一节写，放在单独一行的 <<<ARTICLE>>> 和单独一行的 <<<END>>> 之间。
只要 {'、'.join(SECTIONS)} 三节，不写中间正文，不写编辑说明、评分或占位符。
不要编造 Park 的经历、数据和收入。{retry}"""


def extract_outline(output: str) -> str:
    match = ARTICLE_BLOCK.search(output)
    if not match:
        raise WriterError("模型没有按格式返回")
    text = match.group(1).strip()
    if not text.startswith("#"):
        raise WriterError("缺少标题")
    for name in SECTIONS:
        body = re.search(rf"^##\s*{name}\s*\n+(.+?)(?=^##\s|\Z)", text, flags=re.MULTILINE | re.DOTALL)
        if not body or not body.group(1).strip():
            raise WriterError(f"缺少「{name}」一节")
    # 开头一分钟大约 250–350 字；太短说明它只给了个提纲，没给能直接念的稿子。
    opening = re.search(r"^##\s*开头\s*\n+(.+?)(?=^##\s|\Z)", text, flags=re.MULTILINE | re.DOTALL).group(1)
    if len(re.sub(r"[#\s>*\-|]", "", opening)) < 120:
        raise WriterError("开头太短，要能直接念的一分钟，不是要点")
    return text + "\n"


def write_outline(
    topic: dict[str, Any],
    *,
    vault_raw: str,
    drafts_dir: Path = DEFAULT_DRAFTS_DIR,
    write_fn: WriteFn | None = None,
    workflows: Path | None = None,
    attempts: int = 2,
    now: datetime | None = None,
    adjustments: list[str] | None = None,
) -> dict[str, Any]:
    framework = load_framework(workflows)
    fn = write_fn or (lambda prompt: cli_write(prompt, command=os.environ.get(OUTLINE_COMMAND_ENV) or DEFAULT_OUTLINE_COMMAND, timeout=900))
    sources = gather_sources(vault_raw, topic.get("note_paths") or [])
    error: str | None = None
    for _ in range(attempts):
        try:
            outline = extract_outline(fn(build_prompt(topic, sources, framework=framework, error=error, adjustments=adjustments)))
            break
        except JudgeLoginError:
            raise
        except WriterError as exc:
            error = str(exc)
    else:
        raise WriterError(f"连续 {attempts} 次没写成：{error}")
    folder = drafts_dir.expanduser() / f"topic-{topic['id']}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / FILENAME
    path.write_text(outline, encoding="utf-8")
    meta = {
        "topic_id": topic["id"],
        "mode_label": LABEL,
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "sources": [{k: s[k] for k in ("path", "title", "url")} for s in sources],
    }
    (folder / "bookend.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"outline_path": str(path), **meta}


def read_outline(topic: dict[str, Any]) -> dict[str, Any] | None:
    """老选题的 outline.md / outline-*.md 照样读得出来——换写法不该让以前写的消失。"""
    if not topic.get("outline_path"):
        return None
    path = Path(topic["outline_path"])
    if not path.is_file():
        return None
    meta_path = path.with_name(path.stem + ".meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    return {
        "markdown": path.read_text(encoding="utf-8"),
        "updated_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds"),
        "path": str(path),
        **meta,
    }
