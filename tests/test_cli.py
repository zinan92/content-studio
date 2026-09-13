from __future__ import annotations

import json
from pathlib import Path

from content_studio.cli import main


def test_creator_sync_rejects_cookie_file_inside_repository(tmp_path: Path, monkeypatch) -> None:
    cookies = tmp_path / "cookies.json"
    cookies.write_text(json.dumps({"sessionid": "redacted"}), encoding="utf-8")
    cookies.chmod(0o600)
    monkeypatch.chdir(tmp_path)

    assert main(["creator-sync", "--cookies", "cookies.json", "--db", "db.sqlite3"]) == 1


def test_help_exposes_manual_creator_sync_command() -> None:
    try:
        main(["--help"])
    except SystemExit as exc:
        assert exc.code == 0
