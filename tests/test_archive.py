from __future__ import annotations

import json
import os
from pathlib import Path

from content_studio import archive


def _fake_download(fail_on: set[str] | None = None, seconds: float = 100.0):
    calls: list[str] = []

    def fn(url: str, cookies: Path, out: Path) -> None:
        vid = url.rsplit("/", 1)[-1]
        calls.append(vid)
        if fail_on and vid in fail_on:
            raise RuntimeError("风控")
        media = out / "douyin" / "me" / vid / "media"
        media.mkdir(parents=True)
        (media / "video.mp4").write_bytes(b"x" * 10)

    return fn, calls


def probe_const(value: float):
    return lambda _p: value


def test_usable_root_needs_the_disk_to_be_there(tmp_path: Path) -> None:
    assert archive.usable_root("") is None
    assert archive.usable_root(str(tmp_path / "a" / "b")) is None
    assert archive.usable_root(str(tmp_path / "lib")).is_dir()
    assert archive.usable_root("/Volumes/没有这块盘-xyz/视频/作品库") is None


def test_local_original_is_linked_into_its_folder_and_nothing_is_downloaded(tmp_path: Path) -> None:
    lib, src = tmp_path / "lib", tmp_path / "videos"
    lib.mkdir()
    (src / "剪映导出").mkdir(parents=True)
    original = src / "剪映导出" / "9月17日.mp4"
    original.write_bytes(b"v" * (4 * 1024 * 1024))
    os.utime(original, (1789000000, 1789000000))  # 2026-09-10-ish
    video = {"video_id": "v1", "title": "看懂一件事 #标签", "published_at": "2026-09-12T10:00:00", "duration_seconds": 1278.7}
    fn, calls = _fake_download()
    r = archive.archive_pending([video], root=lib, cookie_path=tmp_path / "c", search=[src], download_fn=fn, probe=probe_const(1278.72))
    assert r["local"] == ["v1"] and calls == []
    final = archive.video_file(lib, "v1")
    assert final is not None and final.parent.name == archive.FINAL_DIR and os.path.samefile(final, original)
    assert archive.source_of(lib, "v1") == "local"
    assert "本机原片" in (final.parent.parent / "info.md").read_text(encoding="utf-8")


def test_downloads_are_checked_serial_and_two_failures_stop(tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    lib.mkdir()
    vids = [{"video_id": f"v{i}", "title": f"第{i}条标题足够长的 描述", "published_at": f"2026-09-0{i}", "duration_seconds": 100.0} for i in range(1, 5)]
    fn, calls = _fake_download(fail_on={"v3", "v2"})
    r = archive.archive_pending(vids, root=lib, cookie_path=tmp_path / "c", download_fn=fn, probe=probe_const(100.0), sleep=lambda _s: None)
    assert calls == ["v4", "v3", "v2"] and r["done"] == ["v4"] and r["stopped"]
    assert archive.video_file(lib, "v4").name == archive.DOWNLOAD_NAME
    assert json.loads((lib / archive.INDEX_FILE).read_text(encoding="utf-8"))["v4"]["source"] == "douyin"
    assert not (lib / ".downloading" / "v3").exists()


def test_a_short_download_is_thrown_away(tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    lib.mkdir()
    fn, _ = _fake_download()
    v = {"video_id": "long", "title": "很长的一条视频标题 x", "published_at": "2026-09-12", "duration_seconds": 758.7}
    r = archive.archive_pending([v], root=lib, cookie_path=tmp_path / "c", download_fn=fn, probe=probe_const(30.0))
    assert r["done"] == [] and "只有 30 秒" in r["failed"][0]["error"]
    assert archive.video_file(lib, "long") is None


def test_no_root_means_nothing_happens(tmp_path: Path) -> None:
    fn, calls = _fake_download()
    r = archive.archive_pending([{"video_id": "a"}], root=None, cookie_path=tmp_path, download_fn=fn)
    assert calls == [] and r["skipped"]
