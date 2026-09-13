from __future__ import annotations

from content_studio.structure import build_report, render_markdown


def _item(title: str = "AI越强，你越是在瞎努力") -> dict:
    return {
        "content_id": "v1",
        "title": title,
        "source_url": "https://www.douyin.com/video/v1",
        "likes": 1647,
        "comments": 42,
        "shares": 257,
        "collects": 1431,
        "views": 81856,
    }


def test_report_keeps_timestamped_transcript_and_evidence_for_conclusions() -> None:
    transcript = {
        "language": "zh",
        "segments": [
            {"text": "Agent 变强，不等于你变强。", "start": 0.0, "end": 4.0, "confidence": 0.92},
            {"text": "真正重要的是把注意力留给自己的核心差异化。", "start": 4.0, "end": 12.0, "confidence": 0.91},
            {"text": "所以回到开头，减少无效努力。", "start": 12.0, "end": 20.0, "confidence": 0.9},
        ],
        "full_text": "Agent 变强，不等于你变强。真正重要的是把注意力留给自己的核心差异化。所以回到开头，减少无效努力。",
    }

    report = build_report(_item(), transcript, generated_at="2026-09-13T00:00:00+00:00")

    assert report["thesis"]["text"]
    assert report["thesis"]["evidence"][0]["start"] == 0.0
    assert report["segments"]
    assert all(segment["evidence"] for segment in report["segments"])
    conclusions = report["why_boom"] + report["why_scatter"]
    assert conclusions
    assert all(conclusion["evidence"] for conclusion in conclusions)
    markdown = render_markdown(report)
    assert "为什么爆" in markdown
    assert "[00:00]" in markdown
    assert "Agent 变强，不等于你变强。" in markdown


def test_report_marks_known_off_topic_material_without_making_it_a_rule() -> None:
    transcript = {
        "language": "zh",
        "segments": [
            {"text": "Agent 变强不等于你变强。", "start": 0.0, "end": 5.0, "confidence": 0.9},
            {"text": "我把同花顺和行情数据库都下载到了本地。", "start": 50.0, "end": 70.0, "confidence": 0.88},
            {"text": "最后还是要找到自己的核心差异化。", "start": 90.0, "end": 100.0, "confidence": 0.9},
        ],
        "full_text": "Agent 变强不等于你变强。我把同花顺和行情数据库都下载到了本地。最后还是要找到自己的核心差异化。",
    }

    report = build_report(_item(), transcript, generated_at="2026-09-13T00:00:00+00:00")

    assert any(segment["label"] == "跑题" for segment in report["segments"])
    assert "待验证" in render_markdown(report)
