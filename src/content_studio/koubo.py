"""口播 Step 3–4：把成片变成一张能标 Hook 的工作台。

这两步以前要开终端：跑 whisper 出字幕，跑 build_worktable.py 出 HTML，在浏览器里标完
导出 JSON 落进下载文件夹，再手动拷回项目的 analysis/worktable.json。

这里把这三段接起来。工作台不重做那张 HTML——`ask-park-video` 的模板已经在用了，
重做一张只会和后面 14 步的格式对不上。它只负责：找到成片、跑转写、生成那张表、
把表开在页面里、把结果直接写回项目目录。
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

SKILL_ENV = "CONTENT_STUDIO_KOUBO_SKILL"
DEFAULT_SKILL = Path("~/.agents/skills/ask-park-video")
WHISPER_MODEL_ENV = "CONTENT_STUDIO_WHISPER_MODEL"
DEFAULT_WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"
VIDEO_SUFFIXES = (".mp4", ".mov", ".m4v")
# 成片和它的只读备份放一起时，优先挑大的：粗剪通常比备份长、比备份大。
SKIP_DIRS = {"part-a-hook", "part-b-body", "final", "renders", "tmp", "node_modules", "subtitles"}


class KouboError(RuntimeError):
    """说给 Park 看的一句话，不是堆栈。"""


def skill_dir() -> Path:
    return Path(os.environ.get(SKILL_ENV) or DEFAULT_SKILL).expanduser()


def find_video(base: Path) -> Path | None:
    """项目根目录下最大的那个视频文件。中间产物目录不看。"""
    found = [p for p in base.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_SUFFIXES]
    for sub in base.iterdir():
        if sub.is_dir() and sub.name not in SKIP_DIRS and not sub.name.startswith("."):
            found += [p for p in sub.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_SUFFIXES]
    return max(found, key=lambda p: p.stat().st_size) if found else None


def find_srt(base: Path) -> Path | None:
    """先看约定位置，再看根目录——剪映导出的 SRT 通常和视频并排放着。"""
    fixed = base / "subtitles" / "source.srt"
    if fixed.is_file():
        return fixed
    loose = sorted(p for p in base.iterdir() if p.is_file() and p.suffix.lower() == ".srt")
    return loose[0] if loose else None


def state(base: Path) -> dict[str, Any]:
    """这个项目现在有什么、缺什么。前端拿它决定显示哪颗按钮。"""
    video = find_video(base)
    srt = find_srt(base)
    sentences = base / "subtitles" / "transcript.sentences.json"
    worktable = base / "analysis" / "worktable.html"
    exported = base / "analysis" / "worktable.json"
    return {
        "video": {"name": video.name, "mb": round(video.stat().st_size / 1_048_576, 1)} if video else None,
        "srt": {"name": srt.name, "at_fixed_path": srt == base / "subtitles" / "source.srt"} if srt else None,
        "sentences": sentences.is_file(),
        "worktable": worktable.is_file(),
        "exported": exported.is_file(),
    }


def transcribe(video: Path, base: Path, *, model: str | None = None) -> Path:
    """本机跑一遍，出 subtitles/source.srt。

    没有字幕时才跑，而且要 Park 先点确认——15 分钟的片子要跑两三分钟，
    不该在他不知情的时候占住机器。
    """
    try:
        import mlx_whisper
        from mlx_whisper.writers import get_writer
    except ImportError as exc:
        raise KouboError("这台机器上没有 mlx-whisper，装一下或者自己导一份 SRT 放进项目目录") from exc
    out = base / "subtitles"
    out.mkdir(parents=True, exist_ok=True)
    result = mlx_whisper.transcribe(
        str(video), path_or_hf_repo=model or os.environ.get(WHISPER_MODEL_ENV) or DEFAULT_WHISPER_MODEL, language="zh", verbose=None
    )
    get_writer("srt", str(out))(result, str(video), {"max_line_width": None, "max_line_count": None, "highlight_words": False})
    written = out / f"{video.stem}.srt"
    target = out / "source.srt"
    if written != target:
        written.replace(target)
    return target


def build_worktable(base: Path, *, srt: Path, skill: Path | None = None, python: str | None = None) -> Path:
    """跑 ask-park-video 自己的脚本。工作台不重写这张表——重写就和 14 步对不上了。"""
    script = (skill or skill_dir()) / "scripts" / "build_worktable.py"
    if not script.is_file():
        raise KouboError(f"找不到 ask-park-video 的 build_worktable.py：{script}")
    exe = python or shutil.which("python3") or "python3"
    sentences = base / "subtitles" / "transcript.sentences.json"
    out = base / "analysis" / "worktable.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    for args in (
        [exe, str(script), "map", "--srt", str(srt), "-o", str(sentences)],
        [exe, str(script), "html", str(sentences), "-o", str(out)],
    ):
        done = subprocess.run(args, capture_output=True, text=True, timeout=300)
        if done.returncode != 0:
            raise KouboError(f"生成工作台失败：{(done.stderr or done.stdout).strip()[:300]}")
    return out


# 把「保存到项目」挂到那张表上。只依赖模板里的全局 payload()——它变了就退回原来的
# 导出按钮，不会把整张表搞坏。
SAVE_SCRIPT = """
<script>
(function () {
  if (typeof payload !== 'function') return;
  var bar = document.getElementById('btnExport');
  if (!bar || !bar.parentNode) return;
  var b = document.createElement('button');
  b.textContent = '保存到项目';
  b.id = 'btnSaveToProject';
  b.style.cssText = 'margin-left:8px';
  b.onclick = async function () {
    b.disabled = true;
    b.textContent = '保存中…';
    try {
      var r = await fetch(%(url)s, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Content-Studio': '1' },
        body: JSON.stringify({ text: JSON.stringify(payload(), null, 2), filename: 'worktable.json', overwrite: true }),
      });
      if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
      b.textContent = '已存进 analysis/worktable.json';
    } catch (e) {
      b.textContent = '保存失败：' + e.message;
      b.disabled = false;
    }
  };
  bar.parentNode.insertBefore(b, bar.nextSibling);
})();
</script>
"""


def worktable_html(base: Path, *, save_url: str) -> str:
    path = base / "analysis" / "worktable.html"
    if not path.is_file():
        raise KouboError("还没有生成工作台")
    import json

    return path.read_text(encoding="utf-8") + SAVE_SCRIPT % {"url": json.dumps(save_url)}
