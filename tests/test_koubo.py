from __future__ import annotations

import json
from pathlib import Path

import pytest

from content_studio import koubo


def _project(tmp_path: Path) -> Path:
    base = tmp_path / "2026-09-22_测试"
    (base / "subtitles").mkdir(parents=True)
    return base


def test_finds_the_biggest_video_and_ignores_intermediates(tmp_path: Path) -> None:
    """成片和只读备份常常并排放着；中间产物目录里也全是 mp4，不能当成片。"""
    base = _project(tmp_path)
    (base / "备份.mov").write_bytes(b"x" * 500)
    (base / "粗剪.mp4").write_bytes(b"x" * 9000)
    for skipped in ("part-a-hook", "final", "renders"):
        (base / skipped).mkdir()
        (base / skipped / "video.mp4").write_bytes(b"x" * 99999)
    assert koubo.find_video(base).name == "粗剪.mp4"
    (base / "说明.txt").write_bytes(b"x" * 99999)  # 不是视频，再大也不算
    assert koubo.find_video(base).name == "粗剪.mp4"
    empty = tmp_path / "空项目"
    empty.mkdir()
    assert koubo.find_video(empty) is None


def test_srt_at_the_fixed_path_wins_over_a_loose_one(tmp_path: Path) -> None:
    """剪映导出的 SRT 通常和视频并排；约定位置有了就用约定位置。"""
    base = _project(tmp_path)
    assert koubo.find_srt(base) is None
    (base / "剪映导出.srt").write_text("1\n", encoding="utf-8")
    loose = koubo.find_srt(base)
    assert loose.name == "剪映导出.srt"
    (base / "subtitles" / "source.srt").write_text("1\n", encoding="utf-8")
    assert koubo.find_srt(base) == base / "subtitles" / "source.srt"


def test_state_tells_the_frontend_which_button_to_show(tmp_path: Path) -> None:
    base = _project(tmp_path)
    assert koubo.state(base) == {"video": None, "srt": None, "sentences": False, "worktable": False, "exported": False}
    (base / "粗剪.mp4").write_bytes(b"x" * 2_097_152)
    s = koubo.state(base)
    assert s["video"] == {"name": "粗剪.mp4", "mb": 2.0} and s["srt"] is None
    (base / "subtitles" / "source.srt").write_text("1\n", encoding="utf-8")
    assert koubo.state(base)["srt"]["at_fixed_path"] is True
    (base / "analysis").mkdir()
    (base / "analysis" / "worktable.html").write_text("<html></html>", encoding="utf-8")
    assert koubo.state(base)["worktable"] is True and koubo.state(base)["exported"] is False


def test_build_worktable_says_which_script_is_missing(tmp_path: Path) -> None:
    base = _project(tmp_path)
    srt = base / "subtitles" / "source.srt"
    srt.write_text("1\n", encoding="utf-8")
    with pytest.raises(koubo.KouboError, match="找不到 ask-park-video"):
        koubo.build_worktable(base, srt=srt, skill=tmp_path / "没装")


def test_build_worktable_runs_the_skills_own_script(tmp_path: Path) -> None:
    """工作台不重写那张表——重写就和后面 14 步的格式对不上了。"""
    base = _project(tmp_path)
    srt = base / "subtitles" / "source.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:02,000\n你好世界。\n", encoding="utf-8")
    skill = tmp_path / "skill" / "scripts"
    skill.mkdir(parents=True)
    fake_rows = json.dumps({"transcript": [
        {"id": f"s{i:03d}", "text": "一句话。", "start_hint": i * 4.0, "end_hint": i * 4.0 + 3.5} for i in range(1, 20)
    ]}, ensure_ascii=False)
    (skill / "build_worktable.py").write_text(
        "import sys, pathlib\n"
        "out = sys.argv[sys.argv.index('-o') + 1]\n"
        "pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)\n"
        f"pathlib.Path(out).write_text({fake_rows!r} if out.endswith('.json') else '<html>x</html>', encoding='utf-8')\n",
        encoding="utf-8",
    )
    out = koubo.build_worktable(base, srt=srt, skill=tmp_path / "skill")
    assert out == base / "analysis" / "worktable.html" and out.is_file()
    rows = json.loads((base / "subtitles" / "transcript.sentences.json").read_text(encoding="utf-8"))["transcript"]
    assert len(rows) == 19


def test_the_save_button_is_appended_not_woven_in(tmp_path: Path) -> None:
    """只依赖模板里的全局 payload()。它没了就退回原来的导出按钮，不把表搞坏。"""
    base = _project(tmp_path)
    (base / "analysis").mkdir()
    (base / "analysis" / "worktable.html").write_text("<html><body>原表</body></html>", encoding="utf-8")
    html = koubo.worktable_html(base, save_url="/api/topics/7/video-project/worktable")
    assert html.startswith("<html><body>原表</body></html>")
    assert "typeof payload !== 'function'" in html
    assert '"/api/topics/7/video-project/worktable"' in html
    assert "X-Content-Studio" in html
    with pytest.raises(koubo.KouboError, match="还没有生成工作台"):
        koubo.worktable_html(tmp_path / "别的", save_url="/x")


def test_latest_export_is_the_newest_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """剪映不往项目目录里导，文件名还全是日期。Park：「就拿最新的就好了，命名用来校对。」"""
    import os

    root = tmp_path / "剪映导出"
    root.mkdir()
    for name, age in (("9月7日.mp4", 300), ("9月22日.mp4", 10), ("9月17日(2).mp4", 100)):
        f = root / name
        f.write_bytes(b"x" * 1_048_576)
        os.utime(f, (0, 1_700_000_000 - age))
    # 带字幕导出时剪映建一个同名文件夹，mp4 和 srt 放在里面。
    folder = root / "8月19日"
    folder.mkdir()
    (folder / "8月19日.mp4").write_bytes(b"x" * 2_097_152)
    (folder / "8月19日.srt").write_text("1\n", encoding="utf-8")
    os.utime(folder / "8月19日.mp4", (0, 1_700_000_000 - 500))

    latest = koubo.latest_export(root)
    assert latest["name"] == "9月22日.mp4" and latest["mb"] == 1.0 and latest["srt"] is None
    assert koubo.latest_export(tmp_path / "没有这个目录") is None

    rows = koubo.recent_exports(root, durations=False)
    assert [r["name"] for r in rows] == ["9月22日.mp4", "9月17日(2).mp4", "9月7日.mp4", "8月19日.mp4"]
    assert rows[-1]["srt"] == "8月19日.srt" and rows[-1]["folder"] == "8月19日"


def test_adopting_keeps_the_date_so_it_stays_traceable(tmp_path: Path) -> None:
    """项目里躺一个叫「粗剪.mp4」的东西，回头对不上是哪一次导的。"""
    root = tmp_path / "剪映导出"
    folder = root / "9月22日"
    folder.mkdir(parents=True)
    video = folder / "9月22日.mp4"
    video.write_bytes(b"x" * 1024)
    srt = folder / "9月22日.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好。\n", encoding="utf-8")

    base = tmp_path / "项目"
    out = koubo.adopt(video, base, srt=srt)
    assert out == {"video": "粗剪-9月22日.mp4", "srt": "subtitles/source.srt"}
    assert (base / "粗剪-9月22日.mp4").read_bytes() == b"x" * 1024
    assert (base / "subtitles" / "source.srt").is_file()
    assert koubo.find_video(base).name == "粗剪-9月22日.mp4"
    assert koubo.find_srt(base) == base / "subtitles" / "source.srt"

    with pytest.raises(koubo.KouboError, match="找不到这个文件"):
        koubo.adopt(root / "不存在.mp4", base)


def _sentences(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"transcript": rows}, ensure_ascii=False), encoding="utf-8")


def test_a_transcript_with_no_punctuation_is_caught_not_shipped(tmp_path: Path) -> None:
    """真发生过：whisper 转中文不给标点，12 分钟被切成 1 句。

    build_worktable 靠标点断句，所以那张表看起来生成成功了，打开才发现是一整坨，
    没法标 Hook 也没法挂视觉标注。宁可当场报错。
    """
    bad = tmp_path / "bad.json"
    _sentences(bad, [{"id": "s001", "text": "有幸有一些博主朋友" * 60, "start_hint": 0.7, "end_hint": 713.0}])
    with pytest.raises(koubo.KouboError, match="断句失败"):
        koubo._guard_sentences(bad)

    good = tmp_path / "good.json"
    _sentences(good, [{"id": f"s{i:03d}", "text": "一句话。", "start_hint": i * 4.0, "end_hint": i * 4.0 + 3.5} for i in range(1, 180)])
    koubo._guard_sentences(good)  # 不该抛

    empty = tmp_path / "empty.json"
    _sentences(empty, [])
    with pytest.raises(koubo.KouboError, match="断句结果是空的"):
        koubo._guard_sentences(empty)

    missing = tmp_path / "没有这个.json"
    koubo._guard_sentences(missing)  # 读不到就别拦，真正的错误在别处报


def test_the_punctuation_prompt_is_actually_punctuated() -> None:
    """prompt 本身没有标点的话，模型照着学的就是没标点。"""
    assert sum(koubo.PUNCTUATION_PROMPT.count(c) for c in "。，！？：") >= 4
