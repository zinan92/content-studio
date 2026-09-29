"""链接：存成公开链接；存不成的标出来；「已发出 → 链接」一处看全。"""
from __future__ import annotations

from content_studio import links
from test_web import client  # noqa: F401 - fixture


def test_backend_pages_become_public_links() -> None:
    assert links.public_url("youtube", "https://studio.youtube.com/video/X1y5HoaVV74/edit") == "https://www.youtube.com/watch?v=X1y5HoaVV74"
    assert links.public_url("douyin", "https://creator.douyin.com/creator-micro/work-management/work-detail/7690817035621666111?enter_from=content") \
        == "https://www.douyin.com/video/7690817035621666111"
    assert links.public_url("x", "https://x.com/xparkzz/status/1") == "https://x.com/xparkzz/status/1"
    assert "群发后" in links.issue("wechat_mp", "https://mp.weixin.qq.com/s?__biz=1&tempkey=abc")
    assert links.issue("wechat_mp", None) == "还没贴链接" and links.issue("miniprogram", None) is None


def test_link_book_lists_every_platform_link_once(client) -> None:  # noqa: F811
    topic = client.post("/api/topics", json={"title": "流量", "formats": "video"}).json()
    client.put(f"/api/topics/{topic['id']}/platforms", json={"platform": "youtube", "published": True, "url": "https://studio.youtube.com/video/abcdefg/edit"})
    client.put(f"/api/topics/{topic['id']}/platforms", json={"platform": "wechat_mp", "published": True, "url": None})
    book = client.get("/api/links").json()
    row = next(r for r in book["rows"] if r["id"] == topic["id"])
    assert row["links"]["youtube"]["url"] == "https://www.youtube.com/watch?v=abcdefg" and row["links"]["youtube"]["issue"] is None
    assert row["links"]["wechat_mp"]["issue"] == "还没贴链接"
    assert [p["key"] for p in book["platforms"]][:2] == ["douyin", "channels"]
