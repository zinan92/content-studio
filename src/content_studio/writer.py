"""Write an article draft for a topic with the local Claude CLI and the khazix-writer skill.

The skill supplies the writing method; the author is always Park. Drafts live under
the app data directory and are never written back into the Obsidian vault.
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

from . import vault
from .paths import config_dir
from .judge import JudgeLoginError

DEFAULT_WRITER_COMMAND = (
    "claude -p --model opus --output-format text "
    '--allowedTools "Skill Read Glob Grep" '
    '--disallowedTools "Bash Edit Write WebFetch WebSearch NotebookEdit"'
)
WRITER_COMMAND_ENV = "CONTENT_STUDIO_WRITER_CMD"
DEFAULT_DRAFTS_DIR = config_dir() / "drafts"
MAX_NOTE_CHARS = 12000
MAX_SOURCE_CHARS = 30000
ARTICLE_BLOCK = re.compile(r"<<<ARTICLE>>>\s*\n(.*?)\n\s*<<<END>>>", re.DOTALL)
FOREIGN_SIGNATURE = re.compile(r"(作者[:：]\s*卡兹克|数字生命卡兹克|wzglyay@|投稿或爆料)")

WriteFn = Callable[[str], str]


class WriterError(RuntimeError):
    """The article could not be produced; the message is shown to Park."""


def gather_sources(vault_raw: str, note_paths: list[str]) -> list[dict[str, Any]]:
    sources, used = [], 0
    for path in note_paths:
        try:
            note = vault.read_note(vault_raw, path)
        except vault.VaultError:
            continue
        body = (note.get("body") or "").strip()[:MAX_NOTE_CHARS]
        if not body or used >= MAX_SOURCE_CHARS:
            continue
        body = body[: MAX_SOURCE_CHARS - used]
        used += len(body)
        sources.append({"path": path, "title": note["title"], "url": note["meta"].get("source") or note["meta"].get("url"), "body": body})
    return sources


def topic_sources(vault_raw: str, topic: dict[str, Any], drafts_dir: Path) -> list[dict[str, Any]]:
    """Everything a topic was built from: snapshots stored with it (a 快讯 picked from the
    daily), then its vault notes, under one character budget."""
    from .newsletter import attached_sources

    out, used = [], 0
    for src in [*attached_sources(drafts_dir, topic["id"]), *gather_sources(vault_raw, topic.get("note_paths") or [])]:
        if used >= MAX_SOURCE_CHARS:
            break
        body = src["body"][: min(MAX_NOTE_CHARS, MAX_SOURCE_CHARS - used)]
        used += len(body)
        out.append({**src, "body": body})
    return out


TRANSCRIPT_TITLE = "视频原话（转写）"
VIDEO_RULE = """
- 这篇的内容来自 Park 那条视频的原话（文章里不要提视频）。**观点、例子和先后顺序以「视频原话」为准**：把口语整理成书面语，
  删掉口头禅和重复，但不要加视频里没说的观点、经历和数字；笔记只用来核对和补细节。"""


def _memo_for_writer(memo: str | None) -> str:
    """备注里工作台自己记的流程话（比如补发时的「补发：抖音发过的旧视频」）不是写作要求，不给写作看：
    9/27 它让文章开头写成了「这是我之前在抖音发过的视频，整理成了文字版」。"""
    return "\n".join(l for l in (memo or "").splitlines() if not l.strip().startswith("补发")).strip()


def _rewrite_part(instruction: str, previous: str) -> str:
    """9/29 Park：「重写就完全不一样了，我要知道它怎么会不一样。」重写一定带一句要求和上一版，只改他说的。"""
    if not instruction.strip():
        return ""
    return f"""

## 这次是重写
Park 看了上一版，要这样改：{instruction.strip()}
只按这句话改；他没提到的地方（观点、例子、结构、措辞）保持上一版不动。素材规则照旧。

### 上一版全文
{previous.strip()}"""


def build_prompt(topic: dict[str, Any], sources: list[dict[str, Any]], error: str | None = None,
                 instruction: str = "", previous: str = "") -> str:
    from_video = any(s["title"] == TRANSCRIPT_TITLE for s in sources)
    material = "\n\n".join(
        f"### 素材 {i + 1}：{s['title']}\n来源：{s['url'] or s['path']}\n\n{s['body']}" for i, s in enumerate(sources)
    ) or "（没有附带素材，只根据选题和备注写。）"
    retry = f"\n\n上一次输出有问题：{error}。请修正后重新输出。" if error else ""
    return f"""你在帮 Park 写一篇公众号文章，文章会发到他的会员内容产品「Park 研习室」。

请使用 khazix-writer skill 的写作方法、风格规则和自检流程来写。
重要：khazix-writer 只提供写法。文章作者是 Park，不是卡兹克。
- 不要出现卡兹克的署名、邮箱、投稿方式、「以上，既然看到这里了……三连」这类他的固定结尾。
- 用第一人称「我」写 Park 的观点；素材里别人的观点要说明是谁说的，不要据为己有。
- 素材里没有的事实、数字、人名不要编。
- 文章要像专门为这个平台写的：不要提它来自哪个平台或哪条视频，不要写「之前在抖音发过」「整理成文字版」「补发」
  「视频里」「关注我」这类话，也不要出现抖音、视频号、小红书、B 站等平台名（Park 9/27：其他平台会当成引流）。{VIDEO_RULE if from_video else ""}

## 选题
{topic['title']}

## Park 的备注
{_memo_for_writer(topic.get('memo')) or '（无）'}

## 素材
{material}

{_rewrite_part(instruction, previous)}

## 输出
只输出文章本身，Markdown 格式，第一行是「# 标题」。把整篇文章放在单独一行的 <<<ARTICLE>>> 和单独一行的 <<<END>>> 之间，前后不要有其他说明。{retry}"""


def cli_write(prompt: str, *, command: str | None = None, timeout: float = 1200.0) -> str:
    argv = shlex.split(command or os.environ.get(WRITER_COMMAND_ENV) or DEFAULT_WRITER_COMMAND)
    try:
        completed = subprocess.run(argv, input=prompt, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise WriterError("写作超时（20 分钟），可以点重试") from exc
    except OSError as exc:
        raise WriterError(f"找不到写作命令：{exc}") from exc
    if completed.returncode != 0:
        detail = f"{completed.stderr}\n{completed.stdout}"
        if re.search(r"authenticat|log ?in|oauth", detail, re.IGNORECASE):
            raise JudgeLoginError("本机 Claude 命令行登录已过期：在终端运行 claude 并按提示重新登录，然后点重试")
        raise WriterError(f"写作命令失败（退出码 {completed.returncode}）：{completed.stderr.strip()[:200]}")
    return completed.stdout


def extract_article(output: str) -> str:
    match = ARTICLE_BLOCK.search(output)
    if not match:
        raise WriterError("模型没有按格式返回文章")
    article = match.group(1).strip()
    if not article.startswith("#") or len(article) < 200:
        raise WriterError("返回的文章太短或缺少标题")
    if FOREIGN_SIGNATURE.search(article):
        raise WriterError("文章里带了卡兹克的署名或联系方式")
    return article + "\n"


def write_article(
    topic: dict[str, Any],
    *,
    vault_raw: str,
    drafts_dir: Path = DEFAULT_DRAFTS_DIR,
    write_fn: WriteFn = cli_write,
    attempts: int = 2,
    now: datetime | None = None,
    transcript: str = "",
    instruction: str = "",
) -> dict[str, Any]:
    sources = topic_sources(vault_raw, topic, drafts_dir)
    folder = drafts_dir.expanduser() / f"topic-{topic['id']}"
    old = folder / "article.md"
    previous = old.read_text(encoding="utf-8") if old.is_file() else ""
    if transcript.strip():
        # 视频拍完了：原话排第一，不占笔记的字数额度。
        sources = [{"path": "视频项目", "title": TRANSCRIPT_TITLE, "url": None, "body": transcript.strip()[:MAX_SOURCE_CHARS]}, *sources]
    error: str | None = None
    for _ in range(attempts):
        try:
            article = extract_article(write_fn(build_prompt(topic, sources, error, instruction, previous)))
            break
        except JudgeLoginError:
            raise
        except WriterError as exc:
            error = str(exc)
    else:
        raise WriterError(f"连续 {attempts} 次没写成：{error}")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "article.md"
    if previous:
        (folder / "article.prev.md").write_text(previous, encoding="utf-8")  # 上一版留一份，重写不满意还能找回
    path.write_text(article, encoding="utf-8")
    meta = {
        "topic_id": topic["id"],
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "skill": "khazix-writer",
        "sources": [{k: s[k] for k in ("path", "title", "url")} for s in sources],
        **({"instruction": instruction.strip()} if instruction.strip() else {}),
    }
    (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"article_path": str(path), **meta}


def read_draft(topic: dict[str, Any]) -> dict[str, Any] | None:
    if not topic.get("article_path"):
        return None
    path = Path(topic["article_path"])
    if not path.is_file():
        return None
    meta_path = path.with_name("meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    return {"markdown": path.read_text(encoding="utf-8"), "updated_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds"), **meta}
