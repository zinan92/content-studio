"""Shooting outline for a talking-head video topic.

Bullet points only: one thesis line and 4–8 short points Park speaks from. The first
point must state the thesis, because his recent videos are watched for only 14–26
seconds on average, and every point must serve the thesis (the teardown's drift test).
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

硬约束来自 Park 自己定的原则：他要优化的不是完播率，是**前 1 分钟的留存**，以及收藏、评论、推荐。
三点是整条内容的骨架，顺序固定——认知反差 → 痛点具象 → 交付可行性，不要打乱：

1. **第一分钟要紧凑，唯一任务是把人留下。** 开场第一句是一句泛话题的反常识暴论，让所有人都觉得跟自己搭点边；不寒暄、不铺垫、不自我介绍，也不要在这里摆结果。写成「大多数人以为……，其实……」这类冲突，后半句要有素材支撑。然后很快落到痛点具象——具体的人、场景和损失，让想跟 Park 学的人觉得「这说的就是我」。交付不要放进第一分钟。
2. **第一分钟之后按 Park 自己的顺序讲。** 他已经在情绪上认可你了，这一段要有认知、有深度，不用再考核节奏。
3. **交付可行性放在后半段，通常在结尾。** 真实结果，或者观众能迈出的第一步。素材里没有结果，就在这一条写「需要补素材：……」，不要编。
4. **不说教。** 没有人想在自媒体上听课，他要的是共鸣和被理解。能用他的话说的，不要用讲课的话说。
5. 每一条都要为主线服务：删掉这一条主线会不会明显变弱？不会就不要这一条。{adjust_block}

## 选题
{topic['title']}

## Park 的备注（可能包含每日统筹给的 Hook 和骨架）
{topic.get('memo') or '（无）'}

## 素材
{material}

## 输出要求
Markdown，严格按下面的结构，放在单独一行的 <<<ARTICLE>>> 和单独一行的 <<<END>>> 之间。只写要点，每条一句话，不展开解释，不写逐字稿：

# 视频标题

## 主线
一句话。

## 前一分钟
- 第一句：……（泛话题的认知冲突 / 反常识暴论，不是主线摘要，不摆结果）
- ……
- ……

（3–6 条。这是全片最紧的一段，每条对应 5–10 秒，每一条都要是一个论点，不能只是过渡。
中间要落到痛点具象，写出具体的人、场景和损失，让他觉得「这说的就是我」。这一段不放交付。）

## 后面讲什么
- ……
- ……
- 结尾：……（交付可行性：真实结果或观众能迈出的第一步；素材里没有结果就写「需要补素材：……」）

（3–8 条。这一段是认知和深度，节奏按 Park 自己的来，但大约每条要能抓一下——
强调一遍主线，或者给一个能被记住的爆点。素材里别人的观点注明是谁说的。）

## 不要讲过头
- ……（可选，最多 3 条：素材缺证据、不能说成事实、不能给投资建议的地方；没有就删掉这一节）

不要编造 Park 的经历、数据和收入。{retry}"""


def extract_outline(output: str) -> str:
    match = ARTICLE_BLOCK.search(output)
    if not match:
        raise WriterError("模型没有按格式返回提纲")
    text = match.group(1).strip()
    if not text.startswith("#"):
        raise WriterError("提纲缺少标题")
    for heading in ("## 主线", "## 前一分钟", "## 后面讲什么"):
        if not re.search(rf"^{heading}\s*$", text, flags=re.MULTILINE):
            raise WriterError(f"提纲缺少「{heading[3:]}」一节")
    # The two halves run at different speeds, so they are counted separately: a hook that sprawls
    # is the exact failure Park named (前 30 秒抓不住), and it hides inside a single total.
    for heading, low, high in (("前一分钟", 3, 6), ("后面讲什么", 3, 8)):
        body = re.search(rf"^## {heading}\s*\n(.*?)(?=^## |\Z)", text, flags=re.MULTILINE | re.DOTALL).group(1)
        n = len(re.findall(r"^\s*[-*] +\S", body, flags=re.MULTILINE))
        if not low <= n <= high:
            raise WriterError(f"「{heading}」需要 {low}–{high} 条要点，现在是 {n} 条")
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
