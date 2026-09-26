"""抖音成片存档：自己发过的每条抖音视频，本机留一份。

Park：视频本身应该存在本地，不该用的时候再去下。所以第一次把已发的全部补下来，
之后每次同步发现新视频，就顺手把新的下一份。补发队列、发布台都直接用这里的文件。

存档目录是一个设置项（profile 的 douyin_archive）。它通常在外接硬盘上：内部硬盘放不下
几个小时的视频。硬盘没插的时候整件事跳过——不往别处写，也不报错打断同步。

下载一次一条、中间停一会儿；哪条失败就停，不连着撞风控。
"""
from __future__ import annotations

from pathlib import Path
import time
from typing import Any, Callable

DownloadFn = Callable[[str, Path, Path], Path]
DEFAULT_DELAY_SECONDS = 20


def usable_root(raw: str | None) -> Path | None:
    """The archive folder, or None when it is not configured or its disk is not there."""
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


def video_file(root: Path | None, video_id: str) -> Path | None:
    if root is None:
        return None
    folder = root / video_id
    if not folder.is_dir():
        return None
    found = sorted(folder.rglob("*.mp4"), key=lambda p: p.stat().st_size, reverse=True)
    return found[0] if found else None


def pending(videos: list[dict[str, Any]], root: Path | None) -> list[dict[str, Any]]:
    """Own videos (not image posts) that have no archived file yet, newest first."""
    if root is None:
        return []
    own = [v for v in videos if not v.get("is_image_post")]
    own.sort(key=lambda v: v.get("published_at") or "", reverse=True)
    return [v for v in own if video_file(root, v["video_id"]) is None]


def download(video_id: str, *, root: Path, cookie_path: Path, download_fn: DownloadFn | None = None) -> Path:
    if download_fn is None:
        from .pipeline import _download_one as download_fn
    target = root / video_id
    target.mkdir(parents=True, exist_ok=True)
    download_fn(f"https://www.douyin.com/video/{video_id}", cookie_path, target)
    found = video_file(root, video_id)
    if found is None:
        raise RuntimeError("下载完了，但没找到视频文件")
    return found


def archive_pending(videos: list[dict[str, Any]], *, root: Path | None, cookie_path: Path, limit: int | None = None,
                    delay: float = DEFAULT_DELAY_SECONDS, download_fn: DownloadFn | None = None,
                    on_progress: Callable[[dict[str, Any]], None] | None = None, sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Download what is missing, one at a time. Stops at the first failure."""
    todo = pending(videos, root)
    if limit is not None:
        todo = todo[:limit]
    result: dict[str, Any] = {"root": str(root) if root else None, "todo": len(todo), "done": [], "failed": None}
    if root is None:
        result["skipped"] = "存档目录没配置，或者那块硬盘没插"
        return result
    for i, v in enumerate(todo):
        if on_progress:
            on_progress({"state": "downloading", "video_id": v["video_id"], "index": i + 1, "total": len(todo), "done": len(result["done"])})
        try:
            download(v["video_id"], root=root, cookie_path=cookie_path, download_fn=download_fn)
        except Exception as exc:  # noqa: BLE001 - stop the batch, surface the reason
            result["failed"] = {"video_id": v["video_id"], "error": str(exc)[:200] or type(exc).__name__}
            break
        result["done"].append(v["video_id"])
        if i + 1 < len(todo):
            sleep(delay)
    if on_progress:
        on_progress({"state": "failed" if result["failed"] else "done", "done": len(result["done"]), "total": len(todo), "failed": result["failed"]})
    return result
