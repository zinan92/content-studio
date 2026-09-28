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
    home = consult.client_dir(tmp_path, "阿皮 抖音客户")
    assert home == tmp_path / consult.FOLDER / "阿皮 抖音客户"
    home.mkdir(parents=True)
    day = date(2026, 9, 28)
    assert consult.note_path(home, day) == home / "0928 咨询记录.md"
    (home / "0928 咨询记录.md").write_text("")
    assert consult.note_path(home, day) == home / "0928 咨询记录.md"
    (home / "0928 咨询记录.md").write_text("我自己记的")
    assert consult.note_path(home, day) == home / "0928 咨询记录 转写.md"


def test_list_after_a_bold_label_still_renders_as_a_list() -> None:
    page = consult.render_client({"call": "阿皮", "title": "t", "body": "## 下一步\n**我这边**\n- 发报告\n- 发链接"}, day=date(2026, 9, 28))
    assert "<li>发报告</li>" in page and "@page" in page


CLIENT = """称呼：阿平
标题：从零花钱生意到平台的第一步

## 你现在的情况
- 年销售额 150–200 万，三四个人

## 这次聊的核心问题
- 获客 ROI

## 我的判断
- **供应链**是你的牌

## 建议你做的
- 先做最小验证

## 下一步
**我这边**
- 发调研报告

**你那边**
- 定第一个场景
"""


def _fake(prompt: str) -> str:
    return CLIENT if "会后纪要" in prompt else _output(2)


def test_client_version_is_notes_only_and_branded() -> None:
    client = consult.parse_client(CLIENT)
    assert client["call"] == "阿平"
    page = consult.render_client(client, day=date(2026, 9, 28))
    assert "帕克动手" in page and "企业家的 AI 产品经理" in page and "2026 年 9 月 28 日" in page
    assert "<strong>供应链</strong>" in page and "阿平，这是我们这次聊的要点" in page
    with pytest.raises(consult.ConsultError, match="下一步"):
        consult.parse_client(CLIENT.split("## 下一步")[0])


def test_client_prompt_keeps_internal_sections_out() -> None:
    text = consult.client_prompt("阿皮", consult.chunks(SEGMENTS), "## 成交信号与下一步\n报价")
    assert "绝对不能出现" in text and "不附转写" in text and "客户：阿皮" in text


def test_run_transcribes_once_then_writes_the_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(consult, "to_pdf", lambda page, pdf: pdf.write_bytes(b"%PDF") or pdf)
    job = tmp_path / "jobs" / "0928-阿平"
    job.mkdir(parents=True)
    (job / "原件.m4a").write_bytes(b"x")
    consult.save_state(job, name="阿平", day="2026-09-28")
    vault = tmp_path / "vault"
    calls = []
    asked = []
    note = consult.run(job, vault, transcriber=lambda a: calls.append(a) or SEGMENTS, analyzer=lambda p: asked.append(p) or _fake(p))
    home = vault / consult.FOLDER / "阿平"
    assert note == home / "0928 咨询记录.md"
    assert "第 2 段的分析" in note.read_text()
    assert "[[0928 客户版.pdf]]" in note.read_text()
    assert (home / "0928 客户版.pdf").read_bytes() == b"%PDF"
    client = home / "0928 客户版.html"
    assert "从零花钱生意到平台的第一步" in client.read_text() and "我在宁波做小家电" not in client.read_text()
    assert (job / "转写.txt").read_text().startswith("[00:00] 你好 能听到吗")
    assert consult.load_state(job)["stage"] == "done"
    consult.run(job, vault, transcriber=lambda a: calls.append(a) or SEGMENTS, analyzer=lambda p: asked.append(p) or _fake(p))
    assert len(calls) == 1 and len(asked) == 2  # 第二次转写、分析、客户版都读缓存


def test_clean_drops_whisper_loops() -> None:
    loop = [{"start": 0.0, "end": 1.0, "text": "你好"}] + [{"start": 1.0 + i, "end": 2.0 + i, "text": "嗯"} for i in range(20)]
    loop += [{"start": 21.0, "end": 30.0, "text": "Holy shit"}, {"start": 30.0, "end": 31.0, "text": "where is my phone"}]
    loop += [{"start": 31.0, "end": 30.0, "text": "Holy shit"}, {"start": 30.0, "end": 31.0, "text": "where is my phone"}] * 5
    got = [s["text"] for s in consult.clean(loop)]
    assert got == ["你好", "嗯", "嗯", "嗯", "Holy shit", "where is my phone"]


def test_to_pdf_prints_a_real_pdf(tmp_path: Path) -> None:
    pytest.importorskip("playwright")
    page = tmp_path / "c.html"
    page.write_text(consult.render_client(consult.parse_client(CLIENT), day=date(2026, 9, 28)), encoding="utf-8")
    try:
        pdf = consult.to_pdf(page, tmp_path / "c.pdf")
    except Exception as exc:  # 没装浏览器内核的机器上跳过
        pytest.skip(f"chromium unavailable: {exc}")
    assert pdf.read_bytes()[:4] == b"%PDF"
