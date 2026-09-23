from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from content_studio import publisher, x_article
from content_studio.x_post import XError

CREDS = {"api_key": "k", "api_secret": "s", "access_token": "t", "access_secret": "a"}
ARTICLE = """# 我终于理解了dontbesilent为什么开源dbskill

开头一段，**产品变便宜了**，信任变贵了。
接着同一段。

## 一、用便宜的东西换贵的东西

- 内容便宜
1. 先做产品

> 信任是最贵的产品

![截图](shot.png)
"""


class Fake:
    """记下每个请求，按网址回话。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, bytes, dict]] = []

    def __call__(self, request):
        self.calls.append((request.full_url, request.data, dict(request.headers)))
        url = request.full_url
        if url.endswith("/media/upload"):
            reply = {"data": {"id": f"m{len(self.calls)}"}}
        elif url.endswith("/articles/draft"):
            reply = {"data": {"id": "a1"}}
        else:
            reply = {"data": {"post_id": "99"}}
        return io.BytesIO(json.dumps(reply).encode())


def test_markdown_becomes_draftjs_blocks() -> None:
    title, items = x_article.parse_markdown(ARTICLE)
    assert title == "我终于理解了dontbesilent为什么开源dbskill"
    kinds = [i["type"] for i in items]
    assert kinds == ["unstyled", "header-one", "unordered-list-item", "ordered-list-item", "blockquote", "image"]
    assert items[0]["text"] == "开头一段，产品变便宜了，信任变贵了。 接着同一段。"
    assert items[0]["styles"] == [{"offset": 5, "length": 6, "style": "bold"}]
    state = x_article.content_state(items, {"shot.png": "m9"})
    atomic = state["blocks"][-1]
    assert atomic["type"] == "atomic" and atomic["entity_ranges"][0]["key"] == 0
    assert state["entities"][0]["value"]["data"]["media_items"][0] == {"media_category": "tweet_image", "media_id": "m9"}


def test_offsets_count_utf16() -> None:
    _, styles = x_article._inline("👍好**棒**")
    assert styles == [{"offset": 3, "length": 1, "style": "bold"}]


def test_uploads_cover_first_then_drafts_and_only_publishes_when_asked(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text(ARTICLE, encoding="utf-8")
    (tmp_path / "shot.png").write_bytes(b"\x89PNG....")
    cover = tmp_path / "横封面.jpg"
    cover.write_bytes(b"\xff\xd8....")
    fake = Fake()
    result = x_article.publish_article(tmp_path / "a.md", cover=cover, creds=CREDS, send=fake)
    urls = [c[0] for c in fake.calls]
    assert urls == [x_article.UPLOAD, x_article.UPLOAD, f"{x_article.API}/articles/draft"]
    assert b'filename="\xe6\xa8\xaa\xe5\xb0\x81\xe9\x9d\xa2.jpg"' in fake.calls[0][1] and b"tweet_image" in fake.calls[0][1]
    draft = json.loads(fake.calls[2][1])
    assert draft["title"].startswith("我终于理解了") and draft["content_state"]["blocks"][0]["type"] == "atomic"
    assert result == {"id": "a1", "title": draft["title"], "images": 2, "published": False, "url": "https://x.com/compose/articles"}
    assert all("OAuth " in c[2]["Authorization"] for c in fake.calls)

    fake = Fake()
    done = x_article.publish_article(tmp_path / "a.md", cover=cover, publish=True, creds=CREDS, send=fake)
    assert fake.calls[-1][0] == f"{x_article.API}/articles/a1/publish" and done["url"].endswith("/99")


def test_refuses_before_uploading_anything(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("# 只有字\n\n正文", encoding="utf-8")
    fake = Fake()
    with pytest.raises(XError, match="至少要一张图"):
        x_article.publish_article(tmp_path / "a.md", creds=CREDS, send=fake)
    (tmp_path / "b.md").write_text("# 标题\n\n![](missing.png)", encoding="utf-8")
    with pytest.raises(XError, match="找不到图片"):
        x_article.publish_article(tmp_path / "b.md", creds=CREDS, send=fake)
    assert fake.calls == []


def test_x_publishes_the_article_not_the_copy(tmp_path: Path) -> None:
    with pytest.raises(publisher.PublishError, match="研习室文章"):
        publisher.build_payload("x", "article_draft", video=None, copy={"x": {"body": "一句话"}})
    article = tmp_path / "article.md"
    article.write_text("# 标题在这\n\n正文", encoding="utf-8")
    cover = tmp_path / "c.jpg"
    cover.write_bytes(b"1")
    payload = publisher.build_payload("x", "article_publish", video=None, copy=None, article=article, cover=cover)
    assert payload["title"] == "标题在这" and payload["cover"] == str(cover)
    argv = publisher.command_for(payload)
    assert argv[-5:] == ["--article", str(article), "--cover", str(cover), "--publish"]
