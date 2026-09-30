"""各平台主页：工作台里写名字、简介、链接；X 能直接改上去，别的平台贴完记一笔（9/30 Park）。"""
from __future__ import annotations

import io
import json

import pytest
from fastapi.testclient import TestClient

from content_studio import profiles, web, x_profile
from tests.test_web import client  # noqa: F401 - fixture


def _x(client: TestClient) -> dict:
    return next(p for p in client.get("/api/profiles").json()["platforms"] if p["key"] == "x")


def test_write_save_and_mark_applied(client: TestClient) -> None:
    client.put("/api/settings", json={"platform_accounts": {"x": {"on": True, "handle": "Park"}, "bilibili": {"on": True, "handle": ""}}})
    ps = client.get("/api/profiles").json()["platforms"]
    assert [p["key"] for p in ps][:2] == ["douyin", "x"]  # 主攻的排前面
    assert _x(client)["state"] == "empty" and _x(client)["can_push"] is True
    client.put("/api/profiles/x", json={"name": "Park｜帕克动手", "bio": "企业家的 AI 产品经理。"})
    assert _x(client)["state"] == "draft" and _x(client)["bio"] == "企业家的 AI 产品经理。"
    # 只改一个字段，别的留着
    client.put("/api/profiles/x", json={"link": "https://example.com"})
    assert _x(client)["name"] == "Park｜帕克动手" and _x(client)["link"] == "https://example.com"
    # X 的上限是知道的：超了就拦
    assert client.put("/api/profiles/x", json={"bio": "字" * 161}).status_code == 400
    assert client.put("/api/profiles/nope", json={"bio": "x"}).status_code == 400

    client.put("/api/profiles/bilibili", json={"bio": "签名"})
    client.post("/api/profiles/bilibili/applied")
    b = next(p for p in client.get("/api/profiles").json()["platforms"] if p["key"] == "bilibili")
    assert b["state"] == "applied" and b["applied_at"] and b["can_push"] is False
    client.put("/api/profiles/bilibili", json={"bio": "新签名"})  # 贴完又改了：回到「还没改到平台」
    assert next(p for p in client.get("/api/profiles").json()["platforms"] if p["key"] == "bilibili")["state"] == "draft"


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
    assert "name=" in seen["body"] and "description=" in seen["body"] and "url=" not in seen["body"]  # 链接没填就不动它
    assert "oauth_signature=" in seen["auth"] and live["location"] == "Singapore"
    with pytest.raises(Exception, match="没有要改的"):
        x_profile.update(name="", bio="", creds=creds, opener=opener)
