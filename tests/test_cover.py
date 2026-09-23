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
