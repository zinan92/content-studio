from __future__ import annotations

import json
from pathlib import Path

import pytest

from content_studio import cover


def test_split_title_keeps_latin_words_whole() -> None:
    lines = cover.split_title("我终于理解了dontbesilent为什么开源dbskill！")
    assert "dontbesilent" in lines and "".join(lines) == "我终于理解了dontbesilent为什么开源dbskill！"
    assert all(cover.units(l) <= 8 for l in lines)


def test_line_breaks_may_not_change_the_words() -> None:
    cover.check_lines("自媒体的下半场", ["自媒体的", "下半场"], "下半场")
    with pytest.raises(cover.CoverError, match="一字不差"):
        cover.check_lines("自媒体的下半场", ["自媒体", "下半场！"], "下半场！")
    with pytest.raises(cover.CoverError, match="一整行"):
        cover.check_lines(None, ["自媒体的", "下半场"], "半场")
    with pytest.raises(cover.CoverError, match="空"):
        cover.check_lines(None, ["  "], "")


@pytest.mark.parametrize("fmt", ["横", "竖"])
def test_layout_emphasis_is_bigger_and_left_edge_lines_up(fmt: str) -> None:
    rows = cover.layout(["我终于理解了", "dontbesilent", "为什么开源", "dbskill！"], "dbskill！", fmt)
    f = cover.FORMATS[fmt]
    em = next(r for r in rows if r["emphasis"])
    assert all(em["size"] >= r["size"] for r in rows)
    # skewX 之后每行的左边落在同一条线上
    assert {round(r["x"] - cover.SKEW * r["y"]) for r in rows} == {f["x0"]}
    assert all(r["width"] <= f["maxw"] * 1.05 for r in rows)
    assert rows[0]["y"] - rows[0]["size"] >= f["top"] - 1 and rows[-1]["y"] <= f["bottom"] + 1


def test_svg_escapes_text_and_pins_person_to_the_bottom() -> None:
    doc = cover.svg(["A&B<", "强调"], "强调", "横", "p.png", 0.8)
    assert "A&amp;B&lt;" in doc and 'href="p.png"' in doc
    p = cover.FORMATS["横"]["person"]
    assert f'y="{1080 - p["h"]}"' in doc and f'height="{p["h"]}"' in doc


def test_face_rect_comes_from_the_edit_plan(tmp_path: Path) -> None:
    assert cover.face_rect(tmp_path) is None
    (tmp_path / "part-b-body").mkdir()
    (tmp_path / "part-b-body" / "edit.json").write_text(json.dumps({"measured_layout": {"face_rect": [10, 20, 30, 40]}}))
    assert cover.face_rect(tmp_path) == (10, 20, 30, 40)


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
