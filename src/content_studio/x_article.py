"""把研习室文章（Markdown）发成 X 的图文文章（X Articles），用 Park 自己的开发者密钥。

9/23 Park：「X 的形式一定要是图文文章。」纯文字推文不够。X 在 2026 年开放了文章接口：
先上传图片拿 media_id，再 POST /2/articles/draft 建草稿（DraftJS 的 content_state），
需要时 POST /2/articles/{id}/publish 发布。发文章的账号要有 X Premium。

图：横版封面放在最前面；文章里用 `![说明](相对路径)` 插的本地图片一起上传。
默认只存草稿——Park 在 X 上看一眼再点发布；直接发布要他在发布台再确认一次。

    python3 -m content_studio.x_article --article 文章.md --cover 横封面.jpg [--publish]
"""
from __future__ import annotations

import argparse
import json
import mimetypes
from pathlib import Path
import re
import secrets
from typing import Any, Callable
import urllib.error
import urllib.request

from .x_post import XError, authorization_header, load_credentials

API = "https://api.x.com/2"
UPLOAD = f"{API}/media/upload"
IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024
IMAGE_LINE = re.compile(r"^!\[(?P<alt>[^\]]*)\]\((?P<src>[^)\s]+)\)\s*$")
BOLD = re.compile(r"\*\*(.+?)\*\*")
LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")


def _u16(text: str) -> int:
    """DraftJS 的偏移按 UTF-16 算：emoji 占两个。"""
    return len(text.encode("utf-16-le")) // 2


def _inline(text: str) -> tuple[str, list[dict[str, Any]]]:
    """去掉 Markdown 记号，返回纯文字和加粗范围。链接写成「文字（网址）」。"""
    text = LINK.sub(lambda m: f"{m.group(1)}（{m.group(2)}）", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", text)  # 斜体不保留
    text = re.sub(r"`([^`]+)`", r"\1", text)
    plain, ranges, last = "", [], 0
    for m in BOLD.finditer(text):
        plain += text[last:m.start()]
        ranges.append({"offset": _u16(plain), "length": _u16(m.group(1)), "style": "bold"})
        plain += m.group(1)
        last = m.end()
    plain += text[last:]
    return plain, ranges


def parse_markdown(markdown: str) -> tuple[str, list[dict[str, Any]]]:
    """标题 + 块列表。图片块是 {"type": "image", "src": ..., "alt": ...}，上传后才变成 atomic。"""
    title = ""
    items: list[dict[str, Any]] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            text, styles = _inline(" ".join(p.strip() for p in paragraph))
            if text.strip():
                items.append({"type": "unstyled", "text": text, "styles": styles})
            paragraph.clear()

    for raw in markdown.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or re.fullmatch(r"[-*_]{3,}", stripped):
            flush()
            continue
        if stripped.startswith("# ") and not title:
            flush()
            title = _inline(stripped[2:].strip())[0]
            continue
        image = IMAGE_LINE.match(stripped)
        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        bullet = re.match(r"^[-*+]\s+(.*)$", stripped)
        number = re.match(r"^\d+[.)、]\s+(.*)$", stripped)
        quote = re.match(r"^>\s?(.*)$", stripped)
        if image:
            flush()
            items.append({"type": "image", "src": image["src"], "alt": image["alt"]})
        elif heading:
            flush()
            text, styles = _inline(heading.group(2))
            items.append({"type": "header-one" if len(heading.group(1)) <= 2 else "header-two", "text": text, "styles": styles})
        elif bullet or number or quote:
            flush()
            kind = "unordered-list-item" if bullet else "ordered-list-item" if number else "blockquote"
            text, styles = _inline((bullet or number or quote).group(1))
            items.append({"type": kind, "text": text, "styles": styles})
        else:
            paragraph.append(stripped)
    flush()
    if not title:
        raise XError("文章第一行要是「# 标题」")
    return title, items


def content_state(items: list[dict[str, Any]], media: dict[str, str]) -> dict[str, Any]:
    """块列表 → DraftJS content_state。media 把图片 src 映射到上传后的 media_id。"""
    blocks, entities = [], []
    for item in items:
        if item["type"] == "image":
            key = str(len(entities))
            entities.append({"key": key, "value": {"type": "image", "mutability": "immutable", "data": {
                "media_items": [{"media_category": "tweet_image", "media_id": media[item["src"]]}],
                **({"caption": item["alt"]} if item.get("alt") else {})}}})
            blocks.append({"text": " ", "type": "atomic", "entity_ranges": [{"key": int(key), "offset": 0, "length": 1}]})
            continue
        block: dict[str, Any] = {"text": item["text"], "type": item["type"]}
        if item.get("styles"):
            block["inline_style_ranges"] = item["styles"]
        blocks.append(block)
    return {"blocks": blocks, "entities": entities}


def _check_image(path: Path) -> None:
    if not path.is_file():
        raise XError(f"找不到图片：{path}")
    if path.suffix.lower() not in IMAGE_TYPES:
        raise XError(f"X 文章只收 jpg/png/webp 图片：{path.name}")
    if path.stat().st_size > MAX_IMAGE_BYTES:
        raise XError(f"图片超过 5 MB：{path.name}")


Send = Callable[[urllib.request.Request], Any]


def _call(request: urllib.request.Request, send: Send | None) -> dict[str, Any]:
    opener = send or (lambda r: urllib.request.urlopen(r, timeout=60))
    try:
        with opener(request) as response:
            return json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        if exc.code == 401:
            raise XError(f"X 拒绝了这次调用（401）：密钥不对，或者应用权限不是 Read and Write。{detail}") from exc
        if exc.code == 403:
            raise XError(f"X 不让发（403）：发图文文章需要账号开通 X Premium，应用也要有写权限。{detail}") from exc
        if exc.code == 429:
            raise XError("X 说超额了（429），等额度恢复再发") from exc
        raise XError(f"X 返回 {exc.code}：{detail}") from exc
    except OSError as exc:
        raise XError(f"连不上 X：{exc}") from exc


def upload_image(path: Path, creds: dict[str, str], *, send: Send | None = None) -> str:
    _check_image(path)
    boundary = secrets.token_hex(12)
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    body = b"".join([
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"media_category\"\r\n\r\ntweet_image\r\n".encode(),
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"media\"; filename=\"{path.name}\"\r\nContent-Type: {mime}\r\n\r\n".encode(),
        path.read_bytes(), f"\r\n--{boundary}--\r\n".encode(),
    ])
    request = urllib.request.Request(UPLOAD, data=body, method="POST")
    # multipart 的内容不进签名，只签 oauth_* 参数。
    request.add_header("Authorization", authorization_header("POST", UPLOAD, creds))
    request.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    data = _call(request, send).get("data") or {}
    media_id = data.get("id") or data.get("media_id_string")
    if not media_id:
        raise XError("图片传上去了，但 X 没给 media_id")
    return str(media_id)


def _post_json(url: str, payload: dict[str, Any] | None, creds: dict[str, str], send: Send | None) -> dict[str, Any]:
    request = urllib.request.Request(url, data=json.dumps(payload or {}, ensure_ascii=False).encode(), method="POST")
    request.add_header("Authorization", authorization_header("POST", url, creds))
    request.add_header("Content-Type", "application/json")
    return _call(request, send)


def publish_article(article: Path, *, cover: Path | None = None, publish: bool = False,
                    creds: dict[str, str] | None = None, send: Send | None = None) -> dict[str, Any]:
    title, items = parse_markdown(article.read_text(encoding="utf-8"))
    if cover is not None:
        items = [{"type": "image", "src": str(cover), "alt": ""}, *items]
    images = {item["src"]: (Path(item["src"]) if Path(item["src"]).is_absolute() else article.parent / item["src"])
              for item in items if item["type"] == "image"}
    for path in images.values():
        _check_image(path)  # 先全部查一遍，别传了一半才发现有张图不行
    if not images:
        raise XError("图文文章至少要一张图：先做封面，或者在文章里插图")
    creds = creds or load_credentials()
    media = {src: upload_image(path, creds, send=send) for src, path in images.items()}
    draft = _post_json(f"{API}/articles/draft", {"title": title, "content_state": content_state(items, media)}, creds, send)
    article_id = (draft.get("data") or {}).get("id")
    if not article_id:
        raise XError("X 没返回草稿 id")
    result: dict[str, Any] = {"id": str(article_id), "title": title, "images": len(media), "published": False,
                              "url": "https://x.com/compose/articles"}
    if publish:
        done = _post_json(f"{API}/articles/{article_id}/publish", None, creds, send).get("data") or {}
        result["published"] = True
        post_id = done.get("post_id") or done.get("id")
        result["url"] = f"https://x.com/i/web/status/{post_id}" if post_id else None
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="把 Markdown 文章发成 X 图文文章")
    parser.add_argument("--article", required=True, type=Path)
    parser.add_argument("--cover", default="")
    parser.add_argument("--publish", action="store_true", help="建完草稿直接发布（默认只存草稿）")
    args = parser.parse_args()
    try:
        cover = Path(args.cover) if args.cover else None
        print(json.dumps({"ok": True, **publish_article(args.article, cover=cover, publish=args.publish)}, ensure_ascii=False))
    except XError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
