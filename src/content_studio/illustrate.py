"""正文配图：文章写好后，用 ian-xiaohei-illustrations 配 4–8 张 16:9 白底手绘图，插到对应段落后面。

Park 9/27：公众号、研习室、X、小红书的文字版都要过一遍插图。这个 skill 靠 Codex 自带的
image_gen 出图（Claude 不出图），所以这里起一个 `codex exec`：它读文章、选几个认知锚点、
一张一张画，存进文章目录的 illustrations/，再写一份 plan.json 说每张放在哪一段后面。
插图本身由这里插回文章（`![说明](illustrations/01-xxx.png)`），codex 不碰文章。
各平台发的时候把这些本地图各自传上去（X 本来就会；公众号、研习室、小红书各自处理）。
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Callable

FOLDER = "illustrations"
PLAN = "plan.json"
SKILL = "ian-xiaohei-illustrations"
IMAGE_LINE = re.compile(r"^!\[[^\]]*\]\(" + FOLDER + r"/[^)\s]+\)\s*$")
TIMEOUT_SECONDS = 45 * 60

Runner = Callable[[str, Path], None]


class IllustrateError(RuntimeError):
    """Shown to Park as-is."""


def codex_bin() -> str:
    for cand in ("/opt/homebrew/bin/codex", shutil.which("codex") or ""):
        if cand and Path(cand).is_file():
            return cand
    raise IllustrateError("这台机器上找不到 codex，配不了图")


def prompt(article: Path) -> str:
    return f"""用 ${SKILL} 给这篇中文文章配图，并直接生成（不用等我确认）。

文章：{article.name}（就在当前目录）

要求：
- 按 skill 的方法选认知锚点，文章长就 5–8 张，短就 3–4 张；每张用 image_gen 单独生成，16:9。
- 图里的中文标注要少、要对，不要出现抖音、视频号、小红书、B 站等平台名，也不要「关注」「点赞」之类引流字样。
- 生成的图保存到当前目录的 {FOLDER}/ 下，按顺序命名 01-英文短名.png、02-英文短名.png ……
- 最后写 {FOLDER}/{PLAN}：JSON 数组，每张一项
  {{"file": "01-xxx.png", "after": "这张图放在哪一段后面：那一段开头的原文，一字不差抄 12–20 个字", "caption": "一句话说这张图讲什么"}}
- 不要改 {article.name}，不要改别的文件。
"""


def codex_runner(text: str, cwd: Path) -> None:
    try:
        done = subprocess.run([codex_bin(), "exec", "--skip-git-repo-check", "-s", "workspace-write", text],
                              cwd=str(cwd), capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        raise IllustrateError(f"配图超过 {TIMEOUT_SECONDS // 60} 分钟还没画完，停了") from exc
    if done.returncode != 0:
        tail = (done.stderr or done.stdout or "").strip().splitlines()[-3:]
        raise IllustrateError("配图失败：" + " / ".join(tail)[:240])


def _norm(text: str) -> str:
    return re.sub(r"[\s*_`>#\-]+", "", text or "")


def strip_images(markdown: str) -> str:
    """去掉上一轮插进去的配图行（重新配图时先清掉）。"""
    lines = [l for l in markdown.splitlines() if not IMAGE_LINE.match(l.strip())]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).rstrip() + "\n"


def insert(markdown: str, plan: list[dict[str, Any]], folder: Path) -> tuple[str, list[dict[str, Any]]]:
    """按 plan 把图插到对应段落后面；对不上的段落不插，报出来。返回新文章和每张的结果。"""
    paras = re.split(r"\n\s*\n", strip_images(markdown).strip())
    after: dict[int, list[str]] = {}
    placed = []
    for item in plan:
        name = Path(str(item.get("file") or "")).name
        if not name or not (folder / name).is_file():
            placed.append({**item, "placed": False, "why": "图没画出来"})
            continue
        anchor = _norm(str(item.get("after") or ""))[:16]
        hit = next((i for i, p in enumerate(paras) if anchor and _norm(p).startswith(anchor)), None)
        if hit is None:
            hit = next((i for i, p in enumerate(paras) if anchor and anchor in _norm(p)), None)
        if hit is None:
            placed.append({**item, "file": name, "placed": False, "why": "找不到它该放的那一段"})
            continue
        caption = str(item.get("caption") or "").replace("]", "）").replace("[", "（").strip()
        after.setdefault(hit, []).append(f"![{caption}]({FOLDER}/{name})")
        placed.append({**item, "file": name, "placed": True})
    out = []
    for i, p in enumerate(paras):
        out.append(p)
        out.extend(after.get(i, []))
    return "\n\n".join(out).rstrip() + "\n", placed


def illustrate(article: Path, *, runner: Runner = codex_runner) -> dict[str, Any]:
    if not article.is_file():
        raise IllustrateError("还没有文章")
    folder = article.parent / FOLDER
    if folder.exists():
        old = folder.parent / f"{FOLDER}.old"
        shutil.rmtree(old, ignore_errors=True)
        folder.rename(old)  # 上一轮的图挪开，不和这一轮混
    folder.mkdir(parents=True)
    runner(prompt(article), article.parent)
    try:
        plan = json.loads((folder / PLAN).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise IllustrateError("图画了，但没写清楚每张放哪（plan.json 缺失或坏了）") from exc
    if not isinstance(plan, list) or not plan:
        raise IllustrateError("一张图都没配出来")
    text, placed = insert(article.read_text(encoding="utf-8"), plan, folder)
    article.write_text(text, encoding="utf-8")
    shutil.rmtree(folder.parent / f"{FOLDER}.old", ignore_errors=True)
    return {"images": [p for p in placed if p.get("placed")], "skipped": [p for p in placed if not p.get("placed")]}


def state(article: Path | None) -> dict[str, Any]:
    if article is None or not article.is_file():
        return {"images": [], "count": 0}
    folder = article.parent / FOLDER
    text = article.read_text(encoding="utf-8")
    used = re.findall(r"!\[([^\]]*)\]\(" + FOLDER + r"/([^)\s]+)\)", text)
    return {"images": [{"file": f, "caption": c} for c, f in used if (folder / f).is_file()], "count": len(used)}
