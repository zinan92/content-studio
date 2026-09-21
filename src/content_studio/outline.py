"""拍摄提纲：Park 的原始内容 → 能直接口播的稿子，两条轨道任选。

两份框架是 Anna 的工作流文件，人写的、放在 Obsidian 里，Park 随时能改：

- 保真版   不重排、不删减，只在原稿前后新增开场和结尾。他已经想清楚顺序时用。
- 重构版   允许重排、删减、合并，只留一条主线。003 里大多数是思考记录，所以这是默认。

提示词不写死在代码里——框架改了，下一次生成就跟着变。框架文件找不到就直接报错，
不偷偷退回旧提示词：Park 会以为他的修改生效了，其实没有。
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
DEFAULT_OUTLINE_COMMAND = (
    "claude -p --model opus --output-format text "
    '--disallowedTools "Bash Edit Write Read Glob Grep WebFetch WebSearch NotebookEdit Skill"'
)

# 顺序就是按钮顺序：重构版在前，因为它是默认。
MODES: dict[str, dict[str, str]] = {
    "restructured": {
        "label": "重构版",
        "file": "Park双轨编辑框架-重构版.md",
        "hint": "重排、删减、合并，只留一条主线",
    },
    "faithful": {
        "label": "保真版",
        "file": "Park双轨编辑框架-保真版.md",
        "hint": "不搬家，只在前后新增开场和结尾",
    },
}
DEFAULT_MODE = "restructured"


def workflows_dir() -> Path:
    return Path(os.environ.get(WORKFLOWS_ENV) or DEFAULT_WORKFLOWS).expanduser()


def load_framework(mode: str, root: Path | None = None) -> str:
    """读框架原文。缺文件是配置问题，说清楚缺哪个、该放哪里。"""
    if mode not in MODES:
        raise WriterError(f"没有「{mode}」这个版本，只有：{'、'.join(m['label'] for m in MODES.values())}")
    path = (root or workflows_dir()) / MODES[mode]["file"]
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        raise WriterError(f"找不到{MODES[mode]['label']}框架：{path}") from None
    body = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S).strip()
    if not body:
        raise WriterError(f"{MODES[mode]['label']}框架是空的：{path}")
    return body


def build_prompt(
    topic: dict[str, Any],
    sources: list[dict[str, Any]],
    *,
    mode: str = DEFAULT_MODE,
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
    return f"""你在帮 Park 把他自己写的东西，加工成一条抖音口播视频能直接照着讲的稿子。
他的号是「Park 的 AI 世界」（AI + 金融），对着稿子即兴讲，不念逐字稿。

下面是 Park 和 Anna 定的「{MODES[mode]['label']}」加工框架。**严格照着做**，它比你的习惯优先：

---

{framework}

---

## 选题
{topic['title']}

## Park 的备注
{topic.get('memo') or '（无）'}

## 素材（Park 的原始内容）
{material}{adjust_block}

## 输出
按框架的「输出」一节写，放在单独一行的 <<<ARTICLE>>> 和单独一行的 <<<END>>> 之间。
不要写编辑说明、评分、变更清单，也不要留任何占位符。不要编造 Park 的经历、数据和收入。{retry}"""


def extract_outline(output: str) -> str:
    """只校验下游真正依赖的两件事：有标题，有主线。

    正文长什么样由框架管——保真版和重构版的形状本来就不一样，在这里加结构检查等于
    把框架里的规则抄第二遍，改框架的时候会对不上。
    """
    match = ARTICLE_BLOCK.search(output)
    if not match:
        raise WriterError("模型没有按格式返回稿子")
    text = match.group(1).strip()
    if not text.startswith("#"):
        raise WriterError("稿子缺少标题")
    match = re.search(r"^##\s*主线\s*\n+(.+?)(?:\n\s*\n|\Z)", text, flags=re.MULTILINE | re.DOTALL)
    if not match or not match.group(1).strip():
        raise WriterError("稿子缺少「主线」一节，开头检查和三点评分要从这里读")
    # 主线之后还得有东西可讲。只数主线那一段之后的字，不然「一句话 + 标题」也能过。
    rest = text[match.end():]
    if len(re.sub(r"[#\s>*\-|]", "", rest)) < 150:
        raise WriterError("只有主线没有正文")
    return text + "\n"


def _paths(topic: dict[str, Any], mode: str, drafts_dir: Path) -> tuple[Path, Path]:
    folder = drafts_dir.expanduser() / f"topic-{topic['id']}"
    return folder / f"outline-{mode}.md", folder / f"outline-{mode}.meta.json"


def write_outline(
    topic: dict[str, Any],
    *,
    vault_raw: str,
    mode: str = DEFAULT_MODE,
    drafts_dir: Path = DEFAULT_DRAFTS_DIR,
    write_fn: WriteFn | None = None,
    workflows: Path | None = None,
    attempts: int = 2,
    now: datetime | None = None,
    adjustments: list[str] | None = None,
) -> dict[str, Any]:
    framework = load_framework(mode, workflows)
    fn = write_fn or (lambda prompt: cli_write(prompt, command=os.environ.get(OUTLINE_COMMAND_ENV) or DEFAULT_OUTLINE_COMMAND, timeout=900))
    sources = gather_sources(vault_raw, topic.get("note_paths") or [])
    error: str | None = None
    for _ in range(attempts):
        try:
            outline = extract_outline(fn(build_prompt(topic, sources, mode=mode, framework=framework, error=error, adjustments=adjustments)))
            break
        except JudgeLoginError:
            raise
        except WriterError as exc:
            error = str(exc)
    else:
        raise WriterError(f"连续 {attempts} 次没写成稿子：{error}")
    path, meta_path = _paths(topic, mode, drafts_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(outline, encoding="utf-8")
    meta = {
        "topic_id": topic["id"],
        "mode": mode,
        "mode_label": MODES[mode]["label"],
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "sources": [{k: s[k] for k in ("path", "title", "url")} for s in sources],
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"outline_path": str(path), **meta}


def _read(path: Path) -> dict[str, Any] | None:
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


def read_outline(topic: dict[str, Any], mode: str | None = None) -> dict[str, Any] | None:
    """mode 为 None 时读「当前这一版」，也就是 outline_path 指着的那个。

    老选题的 outline.md 没有 mode 字段，照样读得出来——换版本不该让以前写的提纲消失。
    """
    if mode is not None:
        current = Path(topic["outline_path"]).parent if topic.get("outline_path") else None
        if current is None:
            return None
        return _read(current / f"outline-{mode}.md")
    return _read(Path(topic["outline_path"])) if topic.get("outline_path") else None


def available(topic: dict[str, Any]) -> list[dict[str, Any]]:
    """哪些版本已经写过了——前端拿它画切换按钮。两版同时存在才谈得上比较。"""
    if not topic.get("outline_path"):
        return []
    folder = Path(topic["outline_path"]).parent
    out = []
    for key, spec in MODES.items():
        path = folder / f"outline-{key}.md"
        if path.is_file():
            out.append({"mode": key, "label": spec["label"], "updated_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")})
    return out
