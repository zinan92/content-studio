"""对外简介：一份 profile，正本在 Obsidian 的 park profile.md；各平台只记改没改（9/30 Park）。"""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from content_studio import profiles, x_profile
from tests.test_web import client  # noqa: F401 - fixture


def _file(tmp_path: Path) -> Path:
    return tmp_path / "vault-default" / profiles.FILE


def test_profile_is_the_obsidian_file_and_edits_write_back(client: TestClient, tmp_path: Path) -> None:
    f = _file(tmp_path)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("郑子男\n\n新加坡国立大学金融 × 计算机\n1v1 咨询\n![[头像.png]]\n", encoding="utf-8")
    d = client.get("/api/profile").json()
    p = d["profile"]
    assert p["name"] == "郑子男" and p["bio"] == "新加坡国立大学金融 × 计算机\n1v1 咨询" and p["embeds"] == 1
    assert p["obsidian"].startswith("obsidian://open?path=") and d["limits"] == {"name": 50, "bio": 160}

    res = client.put("/api/profile", json={"name": "Park｜帕克动手", "bio": "企业家的 AI 产品经理。", "mtime": p["mtime"]})
    assert res.status_code == 200
    text = f.read_text(encoding="utf-8")
    assert text.startswith("Park｜帕克动手\n\n企业家的 AI 产品经理。") and "![[头像.png]]" in text  # 图那一行原样留着

    # 在 Obsidian 里又改过：带着旧的修改时间来存，不能盖掉
    f.write_text("Park\n\n在 Obsidian 里改的\n", encoding="utf-8")
    import os
    os.utime(f, (p["mtime"] + 50, p["mtime"] + 50))
    stale = client.put("/api/profile", json={"name": "x", "bio": "y", "mtime": p["mtime"]})
    assert stale.status_code == 400 and "Obsidian" in stale.json()["error"]
    assert client.get("/api/profile").json()["profile"]["bio"] == "在 Obsidian 里改的"
    assert client.put("/api/profile", json={"name": "", "bio": "y"}).status_code == 400


def test_each_platform_only_tracks_which_version_it_has(client: TestClient, tmp_path: Path) -> None:
    client.put("/api/settings", json={"platform_accounts": {"x": {"on": True, "handle": ""}, "bilibili": {"on": True, "handle": ""}}})
    client.put("/api/profile", json={"name": "Park", "bio": "第一版"})
    state = lambda: {p["key"]: p["state"] for p in client.get("/api/profile").json()["platforms"]}  # noqa: E731
    assert state() == {"douyin": "never", "x": "never", "bilibili": "never"}
    client.post("/api/profile/applied/bilibili")
    assert state()["bilibili"] == "synced"
    p = client.get("/api/profile").json()["profile"]
    client.put("/api/profile", json={"name": "Park", "bio": "第二版", "mtime": p["mtime"]})
    assert state()["bilibili"] == "stale"  # 简介改了，B 站上还是旧的
    assert client.post("/api/profile/applied/nope").status_code == 400


def test_x_update_signs_the_form_and_only_sends_what_is_filled() -> None:
    seen = {}

    class Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def opener(request, timeout=30):
        seen["url"], seen["body"], seen["auth"] = request.full_url, request.data.decode(), request.headers["Authorization"]
        return Resp(json.dumps({"name": "Park｜帕克动手", "description": "企业家的 AI 产品经理。", "location": "Singapore"}).encode())

    creds = {"api_key": "k", "api_secret": "s", "access_token": "t", "access_secret": "a"}
    live = x_profile.update(name="Park｜帕克动手", bio="企业家的 AI 产品经理。", creds=creds, opener=opener)
    assert seen["url"].endswith("/1.1/account/update_profile.json")
    assert "name=" in seen["body"] and "description=" in seen["body"] and "url=" not in seen["body"]
    assert "oauth_signature=" in seen["auth"] and live["location"] == "Singapore"
    with pytest.raises(Exception, match="没有要改的"):
        x_profile.update(name="", bio="", creds=creds, opener=opener)
