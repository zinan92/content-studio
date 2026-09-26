"""作品库：自己发过的每条抖音视频一个文件夹，成片、中间产物、原始录像都在里面。

Park：视频本身应该存在本地；大部分原片本机本来就有，按时长和大致日期就能认出哪条是哪条。
作品库的结构（Park 定的）：

    作品库/
      00 总表.md
      originals.json              每条抖音视频 → 它的文件夹和成片（工作台读这个）
      2026-09-24 某某标题/
        info.md                   抖音链接、时长、每个文件从哪来
        1 成片/                    发出去的那一版；抖音下载版.mp4 是从抖音下的备份
        2 中间产物/
        3 原始录像/
      _未发布/  _待确认/

同步发现新视频时：
1. 先在本机按时长找原片（差 1.5 秒以内、文件日期在发布前后 30 天内），找到就硬链接进
   「1 成片」——同一块盘上不占双倍空间，原位置照样能用；
2. 找不到才从抖音下，存成「1 成片/抖音下载版.mp4」。一次一条、有超时；时长对不上就删掉报错
   （下载器有时只拿到三十秒的片段）。

作品库通常在外接硬盘上。硬盘没插的时候整件事跳过，不往内部硬盘写。
"""
from __future__ import annotations

from datetime import date, datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Callable

DownloadFn = Callable[[str, Path, Path], Any]
ProbeFn = Callable[[Path], "float | None"]
DEFAULT_DELAY_SECONDS = 20
DOWNLOAD_TIMEOUT_SECONDS = 900
MATCH_SECONDS = 1.5
DOWNLOAD_TOLERANCE_SECONDS = 3.0
DATE_WINDOW_DAYS = 30
INDEX_FILE = "originals.json"
SCAN_CACHE = ".local-scan.json"
FINAL_DIR = "1 成片"
DOWNLOAD_NAME = "抖音下载版.mp4"
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".mkv"}
FINAL_HINTS = re.compile(r"上传版|剪映导出|抖音视频|final|成片|导出", re.IGNORECASE)
MIN_BYTES = 3 * 1024 * 1024


def usable_root(raw: str | None) -> Path | None:
    """The library folder, or None when it is not configured or its disk is not there."""
    if not raw:
        return None
    root = Path(raw).expanduser()
    if root.is_dir():
        return root
    parts = root.parts
    if len(parts) > 2 and parts[1] == "Volumes":
        # 外接盘：盘挂着才建目录。没插的时候 /Volumes/<盘名> 不在，别在那儿凭空建一个。
        if not Path(*parts[:3]).is_dir():
            return None
    elif not root.parent.is_dir():
        return None
    root.mkdir(parents=True, exist_ok=True)
    return root


# -- index -------------------------------------------------------------------------

def read_index(root: Path | None) -> dict[str, dict[str, Any]]:
    if root is None:
        return {}
    try:
        return json.loads((root / INDEX_FILE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_index(root: Path, index: dict[str, dict[str, Any]]) -> None:
    tmp = root / (INDEX_FILE + ".tmp")
    tmp.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(root / INDEX_FILE)


def video_file(root: Path | None, video_id: str) -> Path | None:
    """This video's final: what the index points at, else anything in its 「1 成片」 folder."""
    entry = read_index(root).get(video_id) if root is not None else None
    if not entry:
        return None
    if entry.get("path") and Path(entry["path"]).is_file():
        return Path(entry["path"])
    folder = Path(entry.get("folder") or "") / FINAL_DIR
    if folder.is_dir():
        files = sorted((p for p in folder.iterdir() if p.suffix.lower() in VIDEO_SUFFIXES),
                       key=lambda p: (p.name == DOWNLOAD_NAME, -p.stat().st_size))
        return files[0] if files else None
    return None


def source_of(root: Path | None, video_id: str) -> str | None:
    f = video_file(root, video_id)
    if f is None:
        return None
    return "douyin" if f.name == DOWNLOAD_NAME else "local"


def pending(videos: list[dict[str, Any]], root: Path | None) -> list[dict[str, Any]]:
    """Own videos (not image posts) with no final yet, newest first."""
    if root is None:
        return []
    own = [v for v in videos if not v.get("is_image_post")]
    own.sort(key=lambda v: v.get("published_at") or "", reverse=True)
    return [v for v in own if video_file(root, v["video_id"]) is None]


def folder_name(video: dict[str, Any]) -> str:
    from .backfill import split_douyin_title

    title = split_douyin_title(video.get("title") or "")["title"] or video["video_id"]
    title = "".join(c for c in title if c not in '/:\\?*"<>|').strip()[:40]
    return f"{str(video.get('published_at') or '')[:10]} {title}".strip()


def video_folder(root: Path, video: dict[str, Any], index: dict[str, dict[str, Any]]) -> Path:
    entry = index.get(video["video_id"])
    if entry and entry.get("folder"):
        return Path(entry["folder"])
    return root / folder_name(video)


def write_info(folder: Path, video: dict[str, Any], note: str) -> None:
    info = folder / "info.md"
    if info.exists():
        with info.open("a", encoding="utf-8") as fh:
            fh.write(f"\n- {datetime.now().date()}：{note}\n")
        return
    info.write_text(
        f"# {folder.name[11:] or video['video_id']}\n\n- 抖音发布：{str(video.get('published_at') or '')[:10]}\n"
        f"- 抖音时长：{video.get('duration_seconds') or 0:.1f} 秒\n- 抖音链接：https://www.douyin.com/video/{video['video_id']}\n\n"
        f"## 这里的文件从哪来\n\n- {datetime.now().date()}：{note}\n", encoding="utf-8")


# -- step 1: the original on this machine ---------------------------------------------

def ffprobe_duration(path: Path) -> float | None:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True, timeout=60)
        return float(r.stdout.strip()) if r.stdout.strip() else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def scan_local(dirs: list[Path], *, root: Path, probe: ProbeFn = ffprobe_duration) -> list[dict[str, Any]]:
    """Every video under the search folders (outside the library) with its duration, cached."""
    cache_path = root / SCAN_CACHE
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        cache = {}
    out, fresh = [], {}
    root_r = root.resolve()
    for base in dirs:
        base = base.expanduser()
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            try:
                if p.suffix.lower() not in VIDEO_SUFFIXES or any(part.startswith(".") for part in p.parts):
                    continue
                if root_r in p.resolve().parents:
                    continue
                st = p.stat()
            except OSError:
                continue
            if st.st_size < MIN_BYTES:
                continue
            key = f"{p}|{st.st_size}|{int(st.st_mtime)}"
            dur = cache[key] if key in cache else probe(p)
            fresh[key] = dur
            if dur:
                out.append({"path": str(p), "dur": dur, "size": st.st_size, "mtime": st.st_mtime})
    try:
        cache_path.write_text(json.dumps(fresh, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return out


def match_local(video: dict[str, Any], files: list[dict[str, Any]]) -> dict[str, Any] | None:
    dur = video.get("duration_seconds")
    if not dur:
        return None
    try:
        published = date.fromisoformat(str(video.get("published_at") or "")[:10])
    except ValueError:
        published = None
    hits = []
    for f in files:
        diff = abs(f["dur"] - dur)
        if diff > MATCH_SECONDS:
            continue
        if published is not None and abs((datetime.fromtimestamp(f["mtime"]).date() - published).days) > DATE_WINDOW_DAYS:
            continue
        hits.append((0 if FINAL_HINTS.search(f["path"]) else 1, -(f["size"] / max(f["dur"], 1)), diff, f))
    if not hits:
        return None
    hits.sort(key=lambda h: h[:3])
    best = hits[0][3]
    return {"path": best["path"], "diff": round(abs(best["dur"] - dur), 2), "candidates": len(hits)}


def link_or_copy(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return
    try:
        os.link(src, dest)  # same disk: one file, two names
    except OSError:
        shutil.copy2(src, dest)


# -- step 2: download from Douyin ------------------------------------------------------

def douyin_download(url: str, cookies: Path, out: Path, timeout: int = DOWNLOAD_TIMEOUT_SECONDS) -> None:
    from .deps import subprocess_env

    try:
        done = subprocess.run([sys.executable, "-m", "content_downloader", "download", url, "--cookies", str(cookies), "--output-dir", str(out)],
                              capture_output=True, text=True, env=subprocess_env(), timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"下载超过 {timeout // 60} 分钟没完成，停了") from exc
    if done.returncode != 0:
        tail = (done.stderr or done.stdout or "").strip().splitlines()
        raise RuntimeError(f"下载失败（退出码 {done.returncode}）{('：' + tail[-1][:160]) if tail else ''}")


def download(video: dict[str, Any], *, root: Path, cookie_path: Path, index: dict[str, dict[str, Any]],
             download_fn: DownloadFn | None = None, probe: ProbeFn = ffprobe_duration) -> Path:
    vid = video["video_id"]
    tmp = root / ".downloading" / vid
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        (download_fn or douyin_download)(f"https://www.douyin.com/video/{vid}", cookie_path, tmp)
        found = sorted(tmp.rglob("*.mp4"), key=lambda p: p.stat().st_size, reverse=True)
        if not found:
            raise RuntimeError("下载完了，但没找到视频文件")
        want = video.get("duration_seconds")
        got = probe(found[0])
        if want and (got is None or abs(got - want) > DOWNLOAD_TOLERANCE_SECONDS):
            raise RuntimeError(f"下回来的只有 {round(got or 0)} 秒，抖音上是 {round(want)} 秒，不是完整视频")
        folder = video_folder(root, video, index)
        dest = folder / FINAL_DIR / DOWNLOAD_NAME
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(found[0]), dest)
        return dest
    finally:
        shutil.rmtree(tmp, ignore_errors=True)  # a half file must never count as archived


def archive_pending(videos: list[dict[str, Any]], *, root: Path | None, cookie_path: Path, search: list[Path] | None = None,
                    limit: int | None = None, delay: float = DEFAULT_DELAY_SECONDS, download_fn: DownloadFn | None = None,
                    probe: ProbeFn = ffprobe_duration, on_progress: Callable[[dict[str, Any]], None] | None = None,
                    sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Local originals first; download only the rest, one at a time. A failed download is
    recorded and skipped; two failures in a row stop the run (it looks like risk control)."""
    result: dict[str, Any] = {"root": str(root) if root else None, "local": [], "done": [], "failed": []}
    if root is None:
        result["skipped"] = "作品库没配置，或者那块硬盘没插"
        return result
    todo = pending(videos, root)
    index = read_index(root)
    if search and todo:
        if on_progress:
            on_progress({"state": "scanning", "total": len(todo)})
        files = scan_local(search, root=root, probe=probe)
        for v in list(todo):
            hit = match_local(v, files)
            if not hit:
                continue
            folder = video_folder(root, v, index)
            dest = folder / FINAL_DIR / Path(hit["path"]).name
            link_or_copy(Path(hit["path"]), dest)
            index[v["video_id"]] = {"folder": str(folder), "path": str(dest), "source": "local"}
            write_info(folder, v, f"成片：本机原片 {hit['path']}（时长差 {hit['diff']} 秒，{hit['candidates']} 个候选里挑的）")
            result["local"].append(v["video_id"])
        write_index(root, index)
        todo = [v for v in todo if v["video_id"] not in result["local"]]
    if limit is not None:
        todo = todo[:limit]
    result["todo"] = len(todo)
    streak = 0
    for i, v in enumerate(todo):
        if on_progress:
            on_progress({"state": "downloading", "video_id": v["video_id"], "index": i + 1, "total": len(todo),
                         "done": len(result["done"]), "local": len(result["local"])})
        try:
            dest = download(v, root=root, cookie_path=cookie_path, index=index, download_fn=download_fn, probe=probe)
            index[v["video_id"]] = {"folder": str(dest.parent.parent), "path": str(dest), "source": "douyin"}
            write_index(root, index)
            write_info(dest.parent.parent, v, "成片：从抖音下的备份（码率低于原片）")
            result["done"].append(v["video_id"])
            streak = 0
        except Exception as exc:  # noqa: BLE001 - recorded, shown on the queue
            result["failed"].append({"video_id": v["video_id"], "error": str(exc)[:200] or type(exc).__name__})
            streak += 1
            if streak >= 2:
                result["stopped"] = "连着两条下载失败，可能是抖音风控，先停"
                break
        if i + 1 < len(todo):
            sleep(delay)
    if on_progress:
        on_progress({"state": "stopped" if result.get("stopped") else "done", "done": len(result["done"]), "local": len(result["local"]),
                     "failed": result["failed"], "total": len(todo), "stopped": result.get("stopped")})
    return result
