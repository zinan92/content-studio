from __future__ import annotations

from pathlib import Path

from content_studio import archive


def _fake_download(fail_on: str | None = None):
    calls: list[str] = []

    def fn(url: str, cookies: Path, out: Path) -> Path:
        vid = url.rsplit("/", 1)[-1]
        calls.append(vid)
        if vid == fail_on:
            raise RuntimeError("风控")
        media = out / "douyin" / "me" / vid / "media"
        media.mkdir(parents=True)
        (media / "video.mp4").write_bytes(b"x" * 10)
        (media / "cover.jpg").write_bytes(b"y")
        return media.parent

    return fn, calls


def test_usable_root_needs_the_disk_to_be_there(tmp_path: Path) -> None:
    assert archive.usable_root("") is None
    assert archive.usable_root(str(tmp_path / "a" / "b")) is None  # parent missing
    made = archive.usable_root(str(tmp_path / "archive"))
    assert made is not None and made.is_dir()
    assert archive.usable_root("/Volumes/没有这块盘-xyz/视频/存档") is None


def test_archive_pending_is_serial_newest_first_and_stops_on_failure(tmp_path: Path) -> None:
    videos = [{"video_id": "old", "published_at": "2026-01-01"}, {"video_id": "new", "published_at": "2026-09-01"},
              {"video_id": "img", "published_at": "2026-09-02", "is_image_post": 1}, {"video_id": "mid", "published_at": "2026-05-01"}]
    fn, calls = _fake_download(fail_on="mid")
    slept: list[float] = []
    seen: list[dict] = []
    r = archive.archive_pending(videos, root=tmp_path, cookie_path=tmp_path / "c.json", download_fn=fn, delay=7, sleep=slept.append, on_progress=seen.append)
    assert calls == ["new", "mid"] and r["done"] == ["new"] and r["failed"]["video_id"] == "mid"
    assert slept == [7] and seen[-1]["state"] == "failed"
    assert archive.video_file(tmp_path, "new").name == "video.mp4"
    assert [v["video_id"] for v in archive.pending(videos, tmp_path)] == ["mid", "old"]
    fn2, calls2 = _fake_download()
    archive.archive_pending(videos, root=tmp_path, cookie_path=tmp_path / "c.json", download_fn=fn2, limit=1, sleep=lambda _s: None)
    assert calls2 == ["mid"]


def test_no_root_means_nothing_is_downloaded(tmp_path: Path) -> None:
    fn, calls = _fake_download()
    r = archive.archive_pending([{"video_id": "a"}], root=None, cookie_path=tmp_path, download_fn=fn)
    assert calls == [] and r["skipped"]
