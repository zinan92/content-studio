from datetime import date
from pathlib import Path

import pytest

from content_studio import consult


SEGMENTS = [
    {"start": 0.0, "end": 3.0, "text": "你好 能听到吗"},
    {"start": 3.0, "end": 80.0, "text": "我在宁波做小家电"},
    {"start": 160.0, "end": 170.0, "text": "现在订单掉得厉害"},
    {"start": 170.0, "end": 200.0, "text": "你先别急着投流"},
]


def _output(count: int, *, skip: int | None = None) -> str:
    notes = "\n".join(f"[{i}] 第 {i} 段的分析\n第二行" for i in range(1, count + 1) if i != skip)
    return "=== 总结 ===\n## 一句话\n" + "客户卡在订单下滑，Park 建议先别投流。（02:40）" * 3 + "\n\n=== 逐段 ===\n" + notes


def test_chunks_follow_segment_boundaries_and_keep_every_word() -> None:
    parts = consult.chunks(SEGMENTS, seconds=150)
    assert [(c["i"], c["start"], c["end"]) for c in parts] == [(1, 0.0, 80.0), (2, 160.0, 200.0)]
    assert parts[0]["text"] == "你好，能听到吗，我在宁波做小家电"
    assert parts[1]["text"] == "现在订单掉得厉害，你先别急着投流"


def test_parse_reads_summary_and_every_note_and_reports_missing() -> None:
    got = consult.parse(_output(3, skip=2), 3)
    assert got["summary"].startswith("## 一句话")
    assert got["notes"][1] == "第 1 段的分析\n第二行"
    assert got["missing"] == [2]
    with pytest.raises(consult.ConsultError):
        consult.parse("随便说了几句", 3)


def test_render_puts_raw_text_and_analysis_side_by_side() -> None:
    parts = consult.chunks(SEGMENTS)
    md = consult.render(name="阿平", day=date(2026, 9, 28), audio=Path("/a.m4a"),
                        parts=parts, analysis={"summary": "## 一句话\n好", "notes": {1: "a|b\nc"}})
    assert "cssclasses: [consult]" in md and consult.MARKER in md
    assert "| 00:00 | 你好，能听到吗，我在宁波做小家电 | a\\|b<br>c |" in md
    assert "| 02:40 | 现在订单掉得厉害，你先别急着投流 | — |" in md


def test_note_path_never_overwrites_what_park_wrote(tmp_path: Path) -> None:
    folder = tmp_path / consult.FOLDER
    folder.mkdir()
    assert consult.note_path(tmp_path, "0928-阿平") == folder / "0928-阿平.md"
    (folder / "0928-阿平.md").write_text("")
    assert consult.note_path(tmp_path, "0928-阿平") == folder / "0928-阿平.md"
    (folder / "0928-阿平.md").write_text("我自己记的")
    assert consult.note_path(tmp_path, "0928-阿平") == folder / "0928-阿平 转写.md"


def test_run_transcribes_once_then_writes_the_note(tmp_path: Path) -> None:
    job = tmp_path / "jobs" / "0928-阿平"
    job.mkdir(parents=True)
    (job / "audio.m4a").write_bytes(b"x")
    consult.save_state(job, name="阿平", day="2026-09-28")
    vault = tmp_path / "vault"
    calls = []
    note = consult.run(job, vault, transcriber=lambda a: calls.append(a) or SEGMENTS, analyzer=lambda p: _output(2))
    assert note == vault / consult.FOLDER / "0928-阿平.md"
    assert "第 2 段的分析" in note.read_text()
    assert consult.load_state(job)["stage"] == "done"
    consult.run(job, vault, transcriber=lambda a: calls.append(a) or SEGMENTS, analyzer=lambda p: _output(2))
    assert len(calls) == 1  # 第二次直接读 transcript.json


def test_clean_drops_whisper_loops() -> None:
    loop = [{"start": 0.0, "end": 1.0, "text": "你好"}] + [{"start": 1.0 + i, "end": 2.0 + i, "text": "嗯"} for i in range(20)]
    loop += [{"start": 21.0, "end": 30.0, "text": "Holy shit"}, {"start": 30.0, "end": 31.0, "text": "where is my phone"}]
    loop += [{"start": 31.0, "end": 30.0, "text": "Holy shit"}, {"start": 30.0, "end": 31.0, "text": "where is my phone"}] * 5
    got = [s["text"] for s in consult.clean(loop)]
    assert got == ["你好", "嗯", "嗯", "嗯", "Holy shit", "where is my phone"]
