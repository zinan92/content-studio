from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys

import pytest

from content_studio import publisher as pub


def _specs(tmp_path: Path, script: str) -> dict:
    cred = tmp_path / "cookie.json"
    cred.write_text("{}")
    old = (datetime.now() - timedelta(days=90)).timestamp()
    os.utime(cred, (old, old))
    return {"channels": {"label": "视频号", "copy_key": "channels", "credential": cred, "login_hint": "扫码",
                         "modes": {"draft": {"label": "草稿", "argv": [sys.executable, "-c", script, "{video}", "{title}", "{body}", "{tags}"]}}},
            "youtube": {"label": "YouTube", "copy_key": "youtube", "credential": tmp_path / "missing.json", "login_hint": "auth", "modes": {"private": {"label": "私享", "argv": ["true"]}}}}


def test_readiness_flags_old_and_missing_credentials(tmp_path: Path) -> None:
    ready = pub.readiness(_specs(tmp_path, ""))
    assert ready["channels"]["credential"] and ready["channels"]["likely_expired"] and "重新登录" in ready["channels"]["note"]
    assert ready["youtube"]["credential"] is False


def test_payload_requires_video_copy_and_known_mode(tmp_path: Path) -> None:
    specs = _specs(tmp_path, "")
    video = tmp_path / "final.mp4"
    with pytest.raises(pub.PublishError, match="成片"):
        pub.build_payload("channels", "draft", video=video, copy={}, publishers=specs)
    video.write_bytes(b"0" * 2048)
    with pytest.raises(pub.PublishError, match="标题"):
        pub.build_payload("channels", "draft", video=video, copy={}, publishers=specs)
    with pytest.raises(pub.PublishError, match="方式"):
        pub.build_payload("channels", "publish", video=video, copy={}, publishers=specs)
    payload = pub.build_payload("channels", "draft", video=video, copy={"channels": {"title": "标题", "body": "正文", "tags": ["AI"]}}, publishers=specs)
    assert payload["title"] == "标题" and payload["tags"] == ["AI"] and pub.command_for(payload, specs)[-4:] == [str(video), "标题", "正文", "AI"]


def test_confirm_window_and_state() -> None:
    now = datetime.now(timezone.utc)
    pub.confirmable({"state": "awaiting_confirm", "created_at": now.isoformat()}, now=now)
    with pytest.raises(pub.PublishError, match="30 分钟"):
        pub.confirmable({"state": "awaiting_confirm", "created_at": (now - timedelta(minutes=31)).isoformat()}, now=now)
    with pytest.raises(pub.PublishError, match="不在等待确认"):
        pub.confirmable({"state": "done", "created_at": now.isoformat()}, now=now)


def test_run_parses_json_and_explains_login(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"0")
    ok_script = "import json,sys; print('log line'); print(json.dumps({'ok': True, 'status': 'draft_saved_in_platform', 'url': 'https://channels.weixin.qq.com/x', 'title': sys.argv[2]}))"
    specs = _specs(tmp_path, ok_script)
    payload = pub.build_payload("channels", "draft", video=video, copy={"channels": {"title": "T", "body": "", "tags": []}}, publishers=specs)
    result = pub.run(payload, publishers=specs)
    assert result["ok"] and result["title"] == "T" and pub.result_url(result).startswith("https://")
    bad = _specs(tmp_path, "import json; print(json.dumps({'ok': False, 'status': 'cookie_invalid'})); raise SystemExit(2)")
    failed = pub.run(payload, publishers=bad)
    assert failed["ok"] is False and "重新扫码" in pub.explain(failed)
