"""封面：按 ask-park-video 的 bold-orange 预设出横版 4:3 和竖版 3:4。

预设在 skill 的 presets/covers/park-douyin-bold-orange-v1.json，一直在那里，但没人用——
9/23 Codex 去翻了旧项目找格式，Park 自己也找了一遍。这里把预设的 visual_rules 落成一个
生成器：暖象牙底、左上橙色斜切、黑色特粗斜体大标题、一句橙红强调加干笔下划线、
当前视频里抠出来的人（横版在右、竖版在下）。

预设的 variables 只有四样，也只接这四样：标题原字、换行、一个强调短语、当前视频的一帧。
avoid 里的东西（圆角照片卡、「AI时代」小徽章、英文副标题）生成器里根本没有。
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

SEGMENT = Path(__file__).parent / "native" / "segment_person.swift"
SKEW_DEG = 8
SKEW = math.tan(math.radians(SKEW_DEG))
CJK_FONT = "Hiragino Sans GB,Heiti SC,PingFang SC,sans-serif"
LATIN_FONT = "Arial Black,Hiragino Sans GB,sans-serif"
ORANGE = "#ef3711"
# 每种画幅：文字栏的左边、最大宽度、上下边界、字号范围；人像的高度和水平中心（底边贴住画布底）。
# 人像高度按 9/22 那张对过：头大约 500 像素，整张脸露全，不压标题。
FORMATS = {
    "横": {"w": 1440, "h": 1080, "x0": 78, "maxw": 720, "top": 150, "bottom": 830, "fs": (72, 124),
           "person": {"h": 820, "cx": 1130}},
    "竖": {"w": 1080, "h": 1440, "x0": 71, "maxw": 900, "top": 120, "bottom": 690, "fs": (64, 104),
           "person": {"h": 700, "cx": 560}},
}


class CoverError(RuntimeError):
    """说给人听的一句话。"""


# -- 排字 ---------------------------------------------------------------------

def units(text: str) -> float:
    """一行字的宽度，以字号为 1。汉字和全角标点 1，Arial Black 的拉丁字母约 0.62。"""
    total = 0.0
    for ch in text:
        if ch.isspace():
            total += 0.3
        elif ord(ch) < 0x2E80:
            total += 0.62
        else:
            total += 1.0
    return total


def split_title(title: str, *, per_line: float = 6.2) -> list[str]:
    """没给换行时自动断：一行不超过约 6 个汉字宽；拉丁单词不拆开。"""
    tokens = re.findall(r"[A-Za-z0-9]+|\s+|.", title.strip())
    lines, cur = [], ""
    for tok in tokens:
        if cur and units(cur + tok) > per_line and not tok.isspace():
            lines.append(cur.strip())
            cur = tok.lstrip()
        else:
            cur += tok
    if cur.strip():
        lines.append(cur.strip())
    return lines


def _clean(s: str) -> str:
    return re.sub(r"\s+", "", s)


def check_lines(title: str | None, lines: list[str], emphasis: str) -> None:
    """换行只能换行：拼回去必须一字不差；强调短语必须是其中一整行。"""
    lines = [l for l in lines if l.strip()]
    if not lines:
        raise CoverError("标题是空的")
    if title and _clean("".join(lines)) != _clean(title):
        raise CoverError("换行改了字：封面上的字拼回去要和标题一字不差")
    if emphasis not in lines:
        raise CoverError("强调短语必须是其中一整行")


def layout(lines: list[str], emphasis: str, fmt: str) -> list[dict[str, Any]]:
    """每行的字号、位置、宽度。普通行同一字号；强调行放大一档。"""
    f = FORMATS[fmt]
    lo, hi = f["fs"]
    normal = [l for l in lines if l != emphasis]
    fs = min([hi] + [f["maxw"] / units(l) for l in normal]) if normal else hi
    fs = max(lo, min(hi, fs))
    fs_e = max(lo, min(fs * 1.28, f["maxw"] / units(emphasis)))
    sizes = [fs_e if l == emphasis else fs for l in lines]
    gaps = [s * 1.3 for s in sizes]
    block = sum(gaps) - gaps[0] * 0.3
    y = f["top"] + max(0, (f["bottom"] - f["top"] - block) / 2) + sizes[0]
    rows = []
    for line, size, gap in zip(lines, sizes, gaps):
        latin = units(line) < len(line) * 0.8  # 以拉丁字母为主的行用 Arial Black
        width = min(units(line) * size, f["maxw"] * 1.05)
        # skewX 会把越往下的字往左推 y·tan8°，x 里补回来，左边才齐。
        rows.append({"text": line, "y": round(y), "x": round(f["x0"] + SKEW * y), "size": round(size),
                     "width": round(width), "emphasis": line == emphasis, "latin": latin})
        y += gap
    return rows


# -- SVG ----------------------------------------------------------------------

def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def svg(lines: list[str], emphasis: str, fmt: str, cutout_href: str, cutout_ratio: float) -> str:
    f = FORMATS[fmt]
    W, H, p = f["w"], f["h"], f["person"]
    rows = layout(lines, emphasis, fmt)
    pw = round(p["h"] * cutout_ratio)
    # 抠像底边是画面的裁切线，贴住封面底边；高度决定头有多大。
    px, py = round(p["cx"] - pw / 2), H - p["h"]
    text = []
    for r in rows:
        family = LATIN_FONT if r["latin"] or r["emphasis"] else CJK_FONT
        color, stroke = (ORANGE, ORANGE) if r["emphasis"] else ("#050505", "#080808")
        text.append(
            f'<text x="{r["x"]}" y="{r["y"]}" font-family="{family}" font-size="{r["size"]}" '
            f'textLength="{r["width"]}" lengthAdjust="spacingAndGlyphs" fill="{color}" stroke="{stroke}">{_esc(r["text"])}</text>'
        )
    em = next(r for r in rows if r["emphasis"])
    ux, uy, uw = f["x0"] - 48, em["y"] + round(em["size"] * 0.26), em["width"] + 60
    k = W / 1440
    return f'''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
<defs>
  <linearGradient id="paper" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#fffef9"/><stop offset=".58" stop-color="#fbf8ed"/><stop offset="1" stop-color="#efe8d8"/></linearGradient>
  <pattern id="orangePattern" width="58" height="58" patternUnits="userSpaceOnUse"><path d="M29 7c4 9 7 15 16 22-9 4-15 7-16 22-4-9-7-15-22-22 9-4 15-7 22-22z" fill="none" stroke="#ffd0b8" stroke-width="1.2" opacity=".16"/></pattern>
  <filter id="grain"><feTurbulence type="fractalNoise" baseFrequency=".72" numOctaves="2" seed="12"/><feColorMatrix values="0 0 0 0 .78 0 0 0 0 .74 0 0 0 0 .64 0 0 0 .045 0"/></filter>
  <linearGradient id="orange" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#f64216"/><stop offset="1" stop-color="#ec300b"/></linearGradient>
</defs>
<rect width="{W}" height="{H}" fill="url(#paper)"/>
<rect width="{W}" height="{H}" filter="url(#grain)" opacity=".16"/>
<g transform="scale({k})">
  <path d="M0 0H315L0 250Z" fill="url(#orange)"/><path d="M0 0H279L0 218Z" fill="url(#orangePattern)"/>
  <path d="M0 226L286 0H309L0 249Z" fill="#fffdf6"/><path d="M0 240L304 0H318L0 253Z" fill="#f14418"/>
</g>
<image xlink:href="{_esc(cutout_href)}" href="{_esc(cutout_href)}" x="{px}" y="{py}" width="{pw}" height="{p["h"]}" preserveAspectRatio="none"/>
<g transform="translate({W - 218 * k} {H - 234 * k}) scale({k})">
  <path d="M0 234L218 0V234Z" fill="url(#orange)"/><path d="M-32 234L218 -35V-17L-13 234Z" fill="#fffdf6"/><path d="M-48 234L218 -52V-39L-33 234Z" fill="#f14418"/>
</g>
<g transform="skewX(-{SKEW_DEG})" font-weight="900" paint-order="stroke fill" stroke-width="2.2" stroke-linejoin="round">
  {chr(10).join("  " + t for t in text)}
</g>
<g fill="none" stroke="{ORANGE}" stroke-linecap="round">
  <path d="M{ux} {uy}C{ux + uw * .2} {uy - 9} {ux + uw * .42} {uy + 1} {ux + uw * .67} {uy - 8}S{ux + uw * .92} {uy - 6} {ux + uw} {uy - 14}" stroke-width="8"/>
  <path d="M{ux + 8} {uy + 12}C{ux + uw * .22} {uy + 5} {ux + uw * .45} {uy + 14} {ux + uw * .68} {uy + 5}S{ux + uw * .9} {uy + 7} {ux + uw - 8} {uy}" stroke-width="2.8" opacity=".8"/>
  <path d="M{ux + 38} {uy + 20}C{ux + uw * .28} {uy + 15} {ux + uw * .48} {uy + 21} {ux + uw * .62} {uy + 15}" stroke-width="1.5" stroke-dasharray="13 8" opacity=".75"/>
</g>
</svg>
'''


# -- 取帧、抠像、出图 -----------------------------------------------------------

def _run(args: list[str], what: str, timeout: int = 120) -> str:
    done = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if done.returncode != 0:
        raise CoverError(f"{what}失败：{(done.stderr or done.stdout).strip()[:200]}")
    return done.stdout


def face_rect(base: Path) -> tuple[int, int, int, int] | None:
    """剪辑时量过的人像框（part-b-body/edit.json 的 measured_layout.face_rect）。"""
    edit = base / "part-b-body" / "edit.json"
    try:
        rect = json.loads(edit.read_text(encoding="utf-8"))["measured_layout"]["face_rect"]
        return tuple(int(v) for v in rect)  # type: ignore[return-value]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def candidate_frames(video: Path, out_dir: Path, *, count: int = 6) -> list[dict[str, Any]]:
    """从成片里等距取几帧给人挑。跳过开头 hook 的前 10% 和结尾。"""
    duration = float(_run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)], "读时长").strip())
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for i in range(count):
        at = round(duration * (0.12 + 0.76 * i / max(1, count - 1)), 1)
        path = out_dir / f"frame-{int(at):04d}.jpg"
        if not path.is_file():
            _run(["ffmpeg", "-v", "error", "-y", "-ss", str(at), "-i", str(video), "-frames:v", "1", "-q:v", "3", str(path)], "取帧")
        frames.append({"at": at, "path": path})
    return frames


def cutout(frame: Path, out: Path, *, rect: tuple[int, int, int, int] | None, scale: float = 2.2) -> float:
    """裁人像框 → 放大 → 抠人。返回抠像的宽高比。"""
    for tool in ("magick", "swift"):
        if not shutil.which(tool):
            raise CoverError(f"这台机器上没有 {tool}")
    work = out.with_suffix(".src.png")
    crop = ["-crop", f"{rect[2] - rect[0]}x{rect[3] - rect[1]}+{rect[0]}+{rect[1]}", "+repage"] if rect else []
    # 人像框只有三四百像素宽，封面上要一千多像素高：先用 Lanczos 放大再抠，边缘比让 rsvg 拉伸干净。
    _run(["magick", str(frame), *crop, "-filter", "Lanczos", "-resize", f"{int(scale * 100)}%", "-unsharp", "0x0.8+0.6+0.02", str(work)], "裁剪放大")
    try:
        _run(["swift", str(SEGMENT), str(work), str(out)], "抠人像", timeout=180)
    finally:
        work.unlink(missing_ok=True)
    # 裁到人的边界：人像框里头顶上面还有一截背景，不裁的话按头顶位置摆，人会沉下去。
    _run(["magick", str(out), "-trim", "+repage", str(out)], "裁边")
    w, h = (int(v) for v in _run(["magick", "identify", "-format", "%w %h", str(out)], "读尺寸").split())
    return w / h


def render(svg_path: Path) -> Path:
    if not shutil.which("rsvg-convert"):
        raise CoverError("这台机器上没有 rsvg-convert（brew install librsvg）")
    png = svg_path.with_suffix(".png")
    _run(["rsvg-convert", str(svg_path), "-o", str(png)], "渲染封面")
    _run(["magick", str(png), "-quality", "92", str(svg_path.with_suffix(".jpg"))], "转 JPG")
    return png


def make_covers(base: Path, video: Path, *, lines: list[str], emphasis: str, at: float,
                title: str | None = None, name: str | None = None) -> dict[str, str]:
    """出横竖两张封面到 final/covers/，返回相对项目目录的路径。"""
    lines = [l.strip() for l in lines if l.strip()]
    check_lines(title, lines, emphasis)
    out = base / "final" / "covers"
    out.mkdir(parents=True, exist_ok=True)
    stem = name or base.name.split("_", 1)[-1]
    frame = out / f"{stem}-取帧.png"
    _run(["ffmpeg", "-v", "error", "-y", "-ss", str(at), "-i", str(video), "-frames:v", "1", str(frame)], "取帧")
    person = out / f"{stem}-cutout.png"
    ratio = cutout(frame, person, rect=face_rect(base))
    result = {}
    for fmt, label in (("横", "横封面"), ("竖", "竖封面")):
        path = out / f"{stem}-{label}.svg"
        path.write_text(svg(lines, emphasis, fmt, person.name, ratio), encoding="utf-8")
        render(path)
        result[fmt] = str(path.with_suffix(".jpg").relative_to(base))
    return result
