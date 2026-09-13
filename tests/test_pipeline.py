from __future__ import annotations

import json
from pathlib import Path

from content_studio.pipeline import run_pipeline


def _judge(_prompt: str) -> dict:
    return {
        "thesis": {"text": "主线", "evidence_start": 0},
        "segments": [
            {"start": 0, "end": 4, "label": "钩子", "summary": "主张", "serves_thesis": True, "reason": "开门见山"}
        ],
        "why_boom": [{"text": "收藏/赞 50.0%", "evidence_start": 0}],
        "why_scatter": [{"text": "只有 4 秒，无法判断", "evidence_start": 0}],
        "opening": None,
    }


STUB = {"judge_fn": _judge, "baseline_fn": lambda *_args: None, "creator_db": None}


def _write_content_item(root: Path, content_id: str = "v1") -> Path:
    content_dir = root / "douyin" / "author" / content_id
    (content_dir / "media").mkdir(parents=True)
    (content_dir / "content_item.json").write_text(
        json.dumps(
            {
                "platform": "douyin",
                "content_id": content_id,
                "content_type": "video",
                "title": "AI越强，你越是在瞎努力",
                "description": "",
                "author_id": "author",
                "author_name": "Park",
                "publish_time": "2026-09-13T00:00:00+00:00",
                "source_url": "https://www.douyin.com/video/" + content_id,
                "media_files": ["media/video.mp4"],
            }
        ),
        encoding="utf-8",
    )
    (content_dir / "transcript.json").write_text(
        json.dumps(
            {
                "language": "zh",
                "segments": [
                    {"text": "Agent 变强，不等于你变强。", "start": 0, "end": 4, "confidence": 0.9}
                ],
                "full_text": "Agent 变强，不等于你变强。",
            }
        ),
        encoding="utf-8",
    )
    return content_dir


def test_pipeline_reuses_downloaded_content_and_writes_two_report_formats(tmp_path: Path) -> None:
    downloads = tmp_path / "downloads"
    content_dir = _write_content_item(downloads, content_id="123")
    calls: list[str] = []

    result = run_pipeline(
        ["https://www.douyin.com/video/123"],
        cookie_path=tmp_path / "cookies.json",
        data_dir=tmp_path / "data",
        downloads_dir=downloads,
        download_fn=lambda *_args, **_kwargs: calls.append("download") or content_dir,
        extract_fn=lambda path, _model: calls.append("extract") or path,
        generated_at="2026-09-13T00:00:00+00:00",
        **STUB,
    )

    assert calls == []
    assert result["status"] == "ok"
    report_dir = tmp_path / "data" / "reports" / "123"
    assert (report_dir / "report.json").is_file()
    assert (report_dir / "report.md").is_file()


def test_pipeline_runs_download_and_extract_for_a_new_link(tmp_path: Path) -> None:
    downloads = tmp_path / "downloads"
    calls: list[str] = []

    def download(_url: str, _cookies: Path, output_dir: Path) -> Path:
        calls.append("download")
        content_dir = _write_content_item(output_dir)
        (content_dir / "transcript.json").unlink()
        return content_dir

    def extract(path: Path, _model: str) -> Path:
        calls.append("extract")
        (path / "transcript.json").write_text(
            json.dumps(
                {
                    "language": "zh",
                    "segments": [
                        {"text": "Agent 变强，不等于你变强。", "start": 0, "end": 4, "confidence": 0.9}
                    ],
                    "full_text": "Agent 变强，不等于你变强。",
                }
            ),
            encoding="utf-8",
        )
        return path

    result = run_pipeline(
        ["https://www.douyin.com/video/v1"],
        cookie_path=tmp_path / "cookies.json",
        data_dir=tmp_path / "data",
        downloads_dir=downloads,
        download_fn=download,
        extract_fn=extract,
        generated_at="2026-09-13T00:00:00+00:00",
        **STUB,
    )

    assert calls == ["download", "extract"]
    assert result["reports"][0]["content_id"] == "v1"


def test_pipeline_does_not_reuse_arbitrary_content_for_short_link(tmp_path: Path) -> None:
    downloads = tmp_path / "downloads"
    existing = _write_content_item(downloads)
    calls: list[str] = []

    def download(_url: str, _cookies: Path, _output_dir: Path) -> Path:
        calls.append("download")
        return existing

    result = run_pipeline(
        ["https://v.douyin.com/example"],
        cookie_path=tmp_path / "cookies.json",
        data_dir=tmp_path / "data",
        downloads_dir=downloads,
        download_fn=download,
        generated_at="2026-09-13T00:00:00+00:00",
        **STUB,
    )

    assert calls == ["download"]
    assert result["reports"][0]["content_id"] == "v1"
