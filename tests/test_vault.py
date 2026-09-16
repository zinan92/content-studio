from __future__ import annotations

from datetime import date, datetime
import os
from pathlib import Path

import pytest

from content_studio import vault


def _write(path: Path, text: str, when: datetime | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if when:
        ts = when.timestamp()
        os.utime(path, (ts, ts))
    return path


@pytest.fixture
def root(tmp_path: Path) -> Path:
    old = datetime(2026, 8, 1)
    _write(tmp_path / "006_ai daily newsletter" / "26-09-14.md", "# AI Daily\n")
    _write(tmp_path / "007_finance daily newsletter" / "2026-09-13-finance-daily-newsletter.md", "x")
    _write(tmp_path / "009_morning brief" / "2026-09-14.html", "<h1>brief</h1>")
    _write(
        tmp_path / "Clippings" / "new.md",
        '---\ntitle: "起号逻辑"\nsource: "https://x.com/a/status/1"\ncreated: 2026-09-14\n---\n![Image](https://x/y.jpg)\n**正文**第一段 [链接](https://z)',
        datetime(2026, 9, 14, 9),
    )
    _write(tmp_path / "Clippings" / "old.md", "---\ncreated: 2026-08-01\n---\nold", old)
    _write(tmp_path / "003_park原始输出" / "ai与人" / "灵感.md", "# 不是我用AI\n今天想到", datetime(2026, 9, 13, 22))
    _write(tmp_path / "_secrets" / "token.md", "secret")
    return tmp_path


def test_dailies_match_both_date_formats(root: Path) -> None:
    items = {item["key"]: item for item in vault.dailies(str(root), date(2026, 9, 14))}
    assert items["ai_daily"]["path"] == "006_ai daily newsletter/26-09-14.md"
    # 财经日报和晨报属于交易线，工作台不再读它们
    assert set(items) == {"ai_daily"}
    with pytest.raises(vault.VaultError):
        vault.read_note(str(root), "009_morning brief/2026-09-14.html")


def test_inbox_lists_recent_notes_with_titles_and_summaries(root: Path) -> None:
    items = vault.inbox(str(root), since=datetime(2026, 9, 13))
    assert [i["title"] for i in items] == ["起号逻辑", "不是我用AI"]
    clip = items[0]
    assert clip["source_label"] == "Clippings" and clip["url"] == "https://x.com/a/status/1"
    assert clip["summary"] == "正文第一段 链接"
    assert vault.inbox(str(root), since=datetime(2026, 9, 13), sources=("raw",))[0]["source"] == "raw"


@pytest.mark.parametrize("relative", ["_secrets/token.md", "../etc/passwd", "Clippings/../_secrets/token.md", "/etc/hosts", "Clippings"])
def test_paths_outside_allowed_folders_are_refused(root: Path, relative: str) -> None:
    with pytest.raises(vault.VaultError):
        vault.read_note(str(root), relative)


def test_symlink_escape_is_refused(root: Path) -> None:
    (root / "Clippings" / "link.md").symlink_to(root / "_secrets" / "token.md")
    with pytest.raises(vault.VaultError):
        vault.read_note(str(root), "Clippings/link.md")


def test_read_note_and_missing_vault(root: Path) -> None:
    note = vault.read_note(str(root), "Clippings/new.md")
    assert note["title"] == "起号逻辑" and "正文" in note["body"] and note["meta"]["source"].startswith("https://")
    with pytest.raises(vault.VaultError, match="找不到"):
        vault.inbox(str(root / "nope"), since=datetime(2026, 9, 1))


def test_window_start_is_midnight() -> None:
    assert vault.window_start(1, datetime(2026, 9, 14, 15)) == datetime(2026, 9, 13)
