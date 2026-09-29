from __future__ import annotations

from pathlib import Path

import pytest

from content_studio import cover


def test_split_title_keeps_latin_words_whole() -> None:
    lines = cover.split_title("我终于理解了dontbesilent为什么开源dbskill！")
    assert "dontbesilent" in lines and "".join(lines) == "我终于理解了dontbesilent为什么开源dbskill！"
    assert all(cover.units(l) <= 8 for l in lines)


def test_generate_hands_codex_the_frame_refs_and_title_and_files_the_two_covers(tmp_path: Path, monkeypatch) -> None:
    """9/29：封面改由 Codex image_gen 出。这里给它一帧、两张风格参考、逐字标题；它交回两张，放进 final/covers/。"""
    skill = tmp_path / "skill"
    for rel in cover.STYLE_REFS.values():
        (skill / rel).parent.mkdir(parents=True, exist_ok=True)
        (skill / rel).write_bytes(b"png")
    monkeypatch.setenv("CONTENT_STUDIO_KOUBO_SKILL", str(skill))
    base = tmp_path / "proj"
    (base / "final" / "covers").mkdir(parents=True)
    (base / "final" / "covers" / "旧-竖封面.jpg").write_bytes(b"old")
    calls = []
    monkeypatch.setattr(cover, "_run", lambda args, what, timeout=120: calls.append(what) or (Path(args[-1]).write_bytes(b"jpg") if what == "取帧" else ""))
    monkeypatch.setattr(cover, "_ratio_ok", lambda path, want: True)
    monkeypatch.setattr(cover, "word_breaks", lambda text: set(range(1, len(text))))
    seen = {}

    def runner(text: str, cwd: Path) -> None:
        seen["text"] = text
        seen["files"] = sorted(p.name for p in cwd.iterdir())
        (cwd / "out" / "cover-3x4.png").write_bytes(b"p")
        (cwd / "out" / "cover-4x3.png").write_bytes(b"l")

    made = cover.generate(base, tmp_path / "raw.mov", at=292.0, title="做自媒体没有大流量如何月入10个", runner=runner)
    assert made == {"竖": "final/covers/做自媒体没有大流量如何月入10个-竖封面.png", "横": "final/covers/做自媒体没有大流量如何月入10个-横封面.png"}
    assert seen["files"] == ["out", "person.jpg", "prompt.md", "style-3x4.png", "style-4x3.png"]
    assert "做自媒体没有大流量如何月入10个" in seen["text"] and "SOLE PERSON SOURCE" in seen["text"] and "STYLE REFERENCE ONLY" in seen["text"]
    assert (base / "final" / "covers" / "_old" / "旧-竖封面.jpg").is_file()


def test_generate_says_so_when_a_cover_is_missing(tmp_path: Path, monkeypatch) -> None:
    skill = tmp_path / "skill"
    for rel in cover.STYLE_REFS.values():
        (skill / rel).parent.mkdir(parents=True, exist_ok=True)
        (skill / rel).write_bytes(b"png")
    monkeypatch.setenv("CONTENT_STUDIO_KOUBO_SKILL", str(skill))
    monkeypatch.setattr(cover, "_run", lambda args, what, timeout=120: "")
    monkeypatch.setattr(cover, "word_breaks", lambda text: set(range(1, len(text))))
    with pytest.raises(cover.CoverError, match="没出来"):
        cover.generate(tmp_path / "p", tmp_path / "v.mp4", at=1, title="标题", runner=lambda text, cwd: None)
    with pytest.raises(cover.CoverError, match="先写标题"):
        cover.generate(tmp_path / "p", tmp_path / "v.mp4", at=1, title=" ", runner=lambda text, cwd: None)


def test_pick_frames_keeps_the_best_faces_in_time_order(tmp_path: Path, monkeypatch) -> None:
    """9/29：画面机器挑。多取几帧，留人脸质量最好的几张（按时间排），分最高的标 pick；没脸/多张脸不算。"""
    frames = [{"at": float(i * 10), "path": tmp_path / f"f{i}.jpg"} for i in range(12)]
    monkeypatch.setattr(cover, "candidate_frames", lambda video, out_dir, count: frames[:count])
    scores = {f["path"]: s for f, s in zip(frames, [0.1, 0.9, -1, 0.5, 0.2, 0.8, 0.3, -1, 0.7, 0.4, 0.6, 0.05])}
    monkeypatch.setattr(cover, "score_frames", lambda paths: scores)
    kept = cover.pick_frames(tmp_path / "v.mp4", tmp_path, keep=6, sample=12)
    assert [f["at"] for f in kept] == [10.0, 30.0, 50.0, 80.0, 90.0, 100.0]
    assert [f["at"] for f in kept if f["pick"]] == [10.0]


def test_pick_frames_falls_back_to_the_middle_when_nothing_scores(tmp_path: Path, monkeypatch) -> None:
    frames = [{"at": float(i), "path": tmp_path / f"f{i}.jpg"} for i in range(12)]
    monkeypatch.setattr(cover, "candidate_frames", lambda video, out_dir, count: frames[:count])
    monkeypatch.setattr(cover, "score_frames", lambda paths: {p: -1.0 for p in paths})
    kept = cover.pick_frames(tmp_path / "v.mp4", tmp_path, keep=6, sample=12)
    assert len(kept) == 6 and sum(f["pick"] for f in kept) == 1


def test_long_phrase_breaks_between_words_and_keeps_punctuation_on_the_line() -> None:
    """9/29 以前「99%的自媒体人都在追求流量，」被硬切成「99%的自媒体 / 人都在追求流 / 量，」。"""
    title = "99%的自媒体人都在追求流量，但是变现和流量关系并不大"
    words = ["99", "%", "的", "自媒体", "人", "都", "在", "追求", "流量", "，", "但是", "变现", "和", "流量", "关系", "并", "不", "大"]
    breaks, i = set(), 0
    for w in words:
        i += len(w)
        breaks.add(i)
    assert cover.split_title(title, breaks=breaks) == ["99%的自媒体人", "都在追求流量，", "但是变现和", "流量关系并不大"]
