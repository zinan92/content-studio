from __future__ import annotations

import io
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from content_studio import publisher, wechat_publish as wx

CREDS = {"appid": "wx1", "secret": "s"}
ARTICLE = "# 标题在这\n\n第一段，**关键一句**，后面还有。\n\n## 从卖课到卖产品\n\n- 甲\n- 乙\n\n1. 一\n2. 二\n\n> 信任是最贵的产品\n"


class Fake:
    def __init__(self, *, publish_status: int = 0, submit_error: int | None = None) -> None:
        self.calls: list[tuple[str, bytes | None]] = []
        self.publish_status, self.submit_error = publish_status, submit_error

    def __call__(self, request):
        url = request.full_url
        self.calls.append((url.split("?")[0], request.data))
        if "/token" in url:
            reply = {"access_token": "T"}
        elif "add_material" in url:
            reply = {"media_id": "THUMB"}
        elif "draft/add" in url:
            reply = {"media_id": "DRAFT"}
        elif "draft/get" in url:
            reply = {"news_item": [{"title": "标题在这"}]}
        elif "freepublish/submit" in url:
            reply = {"errcode": self.submit_error, "errmsg": "x"} if self.submit_error else {"publish_id": "P1"}
        else:
            reply = {"publish_status": self.publish_status, "article_detail": {"item": [{"article_url": "https://mp.weixin.qq.com/s/abc"}]}}
        return io.BytesIO(json.dumps(reply).encode())


def test_markdown_becomes_olive_inline_html() -> None:
    title, digest, body = wx.render_html(ARTICLE)
    assert title == "标题在这" and digest.startswith("第一段，关键一句")
    assert "class=" not in body and "<style" not in body
    assert 'border-bottom:2px solid #ed7b2f' in body and ">关键一句<" in body
    assert "<ul" in body and "<ol" in body and ">01<" in body and "信任是最贵的产品" in body
    assert body.count("<li") == 4


@pytest.mark.skipif(not Path.home().joinpath(".claude/skills/gzh-design/scripts/validate_gzh_html.py").is_file(), reason="gzh-design not installed")
def test_output_passes_the_gzh_design_validator(tmp_path: Path) -> None:
    page = tmp_path / "a.html"
    page.write_text(wx.render_html(ARTICLE)[2], encoding="utf-8")
    done = subprocess.run([sys.executable, str(Path.home() / ".claude/skills/gzh-design/scripts/validate_gzh_html.py"), str(page)],
                          capture_output=True, text=True, check=False)
    assert "完全合规" in done.stdout, done.stdout


@pytest.mark.skipif(not shutil.which("magick"), reason="imagemagick missing")
def test_draft_then_readback_and_publish_only_when_asked(tmp_path: Path) -> None:
    article = tmp_path / "article.md"
    article.write_text(ARTICLE, encoding="utf-8")
    cover = tmp_path / "c.jpg"
    subprocess.run(["magick", "-size", "1440x1080", "xc:white", str(cover)], check=True)
    fake = Fake()
    r = wx.publish_article(article, cover=cover, creds=CREDS, send=fake, wait=lambda s: None)
    assert [c[0].rsplit("/", 1)[-1] for c in fake.calls] == ["token", "add_material", "add", "get"]
    draft = json.loads(fake.calls[2][1].decode("utf-8"))["articles"][0]
    assert draft["thumb_media_id"] == "THUMB" and draft["title"] == "标题在这"
    assert "标题在这".encode() in fake.calls[2][1]  # 原样 UTF-8，不是 \\u 转义
    assert r["published"] is False and "草稿箱" in r["message"]
    assert (tmp_path / "公众号封面.jpg").is_file()  # 4:3 垫成了 2.35:1

    fake = Fake()
    r = wx.publish_article(article, cover=cover, publish=True, creds=CREDS, send=fake, wait=lambda s: None)
    assert r["published"] is True and r["url"] == "https://mp.weixin.qq.com/s/abc"

    r = wx.publish_article(article, cover=cover, publish=True, creds=CREDS, send=Fake(submit_error=48001), wait=lambda s: None)
    assert r["published"] is False and "没有这个接口的权限" in r["message"]


def test_errors_are_explained() -> None:
    fake = lambda request: io.BytesIO(json.dumps({"errcode": 40164, "errmsg": "invalid ip"}).encode())  # noqa: E731
    with pytest.raises(wx.WechatError, match="白名单"):
        wx.get_token(CREDS, send=fake)
    with pytest.raises(wx.WechatError, match="# 标题"):
        wx.render_html("没有标题")


def test_desk_sends_the_article_and_cover(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(publisher, "python_with", lambda mods, candidates=None: "/py")
    with pytest.raises(publisher.PublishError, match="研习室文章"):
        publisher.build_payload("wechat_mp", "draft", video=None, copy=None)
    article = tmp_path / "article.md"
    article.write_text(ARTICLE, encoding="utf-8")
    cover = tmp_path / "w.jpg"
    cover.write_bytes(b"1")
    argv = publisher.command_for(publisher.build_payload("wechat_mp", "publish", video=None, copy=None, article=article, cover=cover))
    assert argv[1:3] == ["-m", "content_studio.wechat_publish"] and argv[-1] == "--publish" and str(cover) in argv
