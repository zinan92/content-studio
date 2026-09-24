"""公众号一键发：研习室那篇 Markdown → 橄榄手记排版 → 封面 → 草稿箱（读回核对）→ 可选发布。

7/13、7/14 两篇是 Codex 一步步手工做进草稿箱的（每篇现写排版脚本），那套流程 9/21 停了，
之后「送去公众号」的文章就停在「等配图和排版」。9/24 Park：公众号要一键发，插图不要。

- 排版：gzh-design 的「橄榄手记」主题，全部内联样式（公众号不认 class / <style>）。
- 封面：公众号封面 2.35:1。有封面弹窗出的「公众号封面」就用它；没有就把横版封面垫进 2.35:1。
- 发布：freepublish 是「发布」——出现在公众号主页，但**不推送给粉丝**；推送是群发，这里不做。
  账号没有发布接口权限时（未认证的号常见），停在草稿箱，说清楚去手机上点。

    python3 -m content_studio.wechat_publish --article 文章.md --cover 封面.jpg [--publish]
"""
from __future__ import annotations

import argparse
import html
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import subprocess
import time
from typing import Any, Callable
import urllib.parse
import urllib.request

from .wechat import ERRORS, SECRETS_PATH, TOKEN_URL, load_credentials

API = "https://api.weixin.qq.com/cgi-bin"
TITLE_MAX = 64
DIGEST_MAX = 120
WIDE = (2.35, 1)
PAPER = "#fdfdf8"
FONT = "'IBM Plex Sans',-apple-system,system-ui,'PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif"
MORE_ERRORS = {
    48001: "这个公众号没有这个接口的权限（未认证的号不能用接口发布）：已经在草稿箱里了，去手机上点发布",
    40007: "封面素材无效：重新传一次",
    45002: "正文太长了",
    53503: "草稿没法发布：可能有违规或格式问题，去后台打开草稿看看",
}


class WechatError(RuntimeError):
    """说给人听的一句话。"""


# -- 排版 ---------------------------------------------------------------------

def _inline(text: str) -> str:
    """转义，再把 **加粗** 换成主题的橙色下划线，链接写成「文字（网址）」。"""
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r"\1（\2）", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    out, last = [], 0
    for m in re.finditer(r"\*\*(.+?)\*\*", text):
        out.append(html.escape(text[last:m.start()]))
        out.append(f'<span style="border-bottom:2px solid #ed7b2f;font-weight:600;color:#23251d;"><span leaf="">{html.escape(m.group(1))}</span></span>')
        last = m.end()
    out.append(html.escape(text[last:]))
    joined = "".join(out)
    # 普通文字也要包 <span leaf>，公众号编辑器才不会重排；加粗段已经包过
    return re.sub(r"(^|</span></span>)([^<]+)", lambda m: m.group(1) + (f'<span leaf="">{m.group(2)}</span>' if m.group(2).strip() else m.group(2)), joined)


def _block(inner: str) -> str:
    return f'<section style="margin-top:24px;"><section style="font-family:{FONT};">{inner}</section></section>'


def render_html(markdown: str) -> tuple[str, str, str]:
    """(标题, 摘要, 正文 HTML)。标题取第一行「# 」，摘要取第一段。"""
    title, digest, parts, para, items, kind = "", "", [], [], [], ""
    part_no = 0

    def flush_para() -> None:
        nonlocal digest
        if para:
            text = " ".join(para).strip()
            if text:
                digest = digest or re.sub(r"\*\*|`", "", text)
                parts.append(_block(f'<p style="margin:0;font-size:14px;line-height:1.9;text-align:justify;color:#4d4f46;">{_inline(text)}</p>'))
            para.clear()

    def flush_list() -> None:
        nonlocal kind
        if items:
            tag, marker = ("ol", "decimal") if kind == "ol" else ("ul", "disc")
            lis = "".join(f'<li style="margin-bottom:8px;font-size:15px;color:#4d4f46;list-style-type:{marker};"><section>{_inline(i)}</section></li>' for i in items)
            parts.append(_block(f'<{tag} style="margin:0;padding-left:22px;line-height:1.8;list-style-position:outside;">{lis}</{tag}>'))
            items.clear()
        kind = ""

    for raw in markdown.splitlines():
        line = raw.strip()
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        bullet = re.match(r"^[-*+]\s+(.*)$", line)
        number = re.match(r"^\d+[.)、]\s+(.*)$", line)
        quote = re.match(r"^>\s?(.*)$", line)
        if not line or re.fullmatch(r"[-*_]{3,}", line) or re.match(r"^!\[", line):
            flush_para(); flush_list()
            continue
        if heading and heading.group(1) == "#" and not title:
            flush_para(); flush_list()
            title = re.sub(r"\*\*", "", heading.group(2)).strip()
            continue
        if bullet or number:
            flush_para()
            want = "ol" if number else "ul"
            if kind and kind != want:
                flush_list()
            kind = want
            items.append((bullet or number).group(1))
            continue
        flush_list()
        if heading:
            flush_para()
            text = re.sub(r"\*\*", "", heading.group(2)).strip()
            if len(heading.group(1)) <= 2:
                part_no += 1
                parts.append(f'<section style="margin-top:32px;"><section style="font-family:{FONT};display:flex;align-items:center;gap:14px;">'
                             f'<section style="text-align:center;flex-shrink:0;"><p style="margin:0;font-size:24px;font-weight:800;color:#23251d;line-height:1;letter-spacing:-2px;"><span leaf="">{part_no:02d}</span></p>'
                             f'<p style="margin:0;font-size:8px;font-weight:700;color:#9ea096;letter-spacing:2px;"><span leaf="">PART</span></p></section>'
                             f'<span style="width:1px;height:36px;background:#bfc1b7;flex-shrink:0;display:inline-block;overflow:hidden;vertical-align:middle;font-size:0;line-height:0;"><span leaf="">&nbsp;</span></span>'
                             f'<p style="margin:0;font-size:17px;font-weight:800;color:#23251d;letter-spacing:0.2px;"><span leaf="">{html.escape(text)}</span></p></section></section>')
            else:
                parts.append(_block(f'<p style="margin:0;font-size:15px;font-weight:800;color:#23251d;"><span leaf="">{html.escape(text)}</span></p>'))
        elif quote:
            flush_para()
            parts.append(_block(f'<section style="background:#fdfdf8;border-radius:6px;padding:16px 18px;border:1px solid #bfc1b7;">'
                                f'<p style="font-size:14px;color:#23251d;margin:0;line-height:1.8;text-align:justify;font-weight:600;">{_inline(quote.group(1))}</p></section>'))
        else:
            para.append(line)
    flush_para(); flush_list()
    if not title:
        raise WechatError("文章第一行要是「# 标题」")
    body = f'<section style="max-width:677px;margin:0 auto;padding:8px;box-sizing:border-box;background:{PAPER};color:#4d4f46;font-family:{FONT};line-height:1.75;">{"".join(parts)}</section>'
    return title, digest[:DIGEST_MAX], body


def wide_cover(cover: Path, out: Path) -> Path:
    """封面变成公众号的 2.35:1。已经够宽就原样用；不够宽就居中放在纸色底上，字和人都不裁。"""
    size = subprocess.run(["magick", "identify", "-format", "%w %h", str(cover)], capture_output=True, text=True, check=False).stdout.split()
    if len(size) != 2:
        raise WechatError(f"读不了封面：{cover.name}")
    w, h = int(size[0]), int(size[1])
    if w / h >= 2.2:
        return cover
    height = h
    width = round(height * WIDE[0] / WIDE[1])
    done = subprocess.run(["magick", str(cover), "-background", PAPER, "-gravity", "center", "-extent", f"{width}x{height}",
                           "-resize", "1880x800>", "-quality", "90", str(out)], capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise WechatError(f"封面转换失败：{done.stderr.strip()[:120]}")
    return out


# -- 接口 ---------------------------------------------------------------------

Send = Callable[[urllib.request.Request], Any]


def _explain(payload: dict[str, Any]) -> str:
    code = payload.get("errcode")
    if code in ERRORS:
        return ERRORS[code][1]
    return MORE_ERRORS.get(code, f"微信返回 {code} {payload.get('errmsg', '')}")


def _call(request: urllib.request.Request, send: Send | None) -> dict[str, Any]:
    opener = send or (lambda r: urllib.request.urlopen(r, timeout=60))
    try:
        with opener(request) as response:
            payload = json.loads(response.read().decode() or "{}")
    except OSError as exc:
        raise WechatError(f"连不上微信：{exc}") from exc
    if payload.get("errcode"):
        raise WechatError(_explain(payload))
    return payload


def get_token(creds: dict[str, str], send: Send | None = None) -> str:
    if not creds.get("appid") or not creds.get("secret"):
        raise WechatError(f"{SECRETS_PATH} 的 wechat: 段里还缺 appid / secret")
    query = urllib.parse.urlencode({"grant_type": "client_credential", "appid": creds["appid"], "secret": creds["secret"]})
    token = _call(urllib.request.Request(f"{TOKEN_URL}?{query}"), send).get("access_token")
    if not token:
        raise WechatError("微信没给令牌")
    return str(token)


def _post(path: str, token: str, payload: dict[str, Any], send: Send | None) -> dict[str, Any]:
    # 必须原样发 UTF-8：用 \\u 转义的话，草稿里的中文会显示成一串 \\u 码
    request = urllib.request.Request(f"{API}/{path}?access_token={token}", data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), method="POST")
    request.add_header("Content-Type", "application/json; charset=utf-8")
    return _call(request, send)


def upload_cover(path: Path, token: str, send: Send | None = None) -> str:
    boundary = secrets.token_hex(12)
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    body = b"".join([
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"media\"; filename=\"cover{path.suffix.lower()}\"\r\nContent-Type: {mime}\r\n\r\n".encode(),
        path.read_bytes(), f"\r\n--{boundary}--\r\n".encode(),
    ])
    request = urllib.request.Request(f"{API}/material/add_material?access_token={token}&type=image", data=body, method="POST")
    request.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    media_id = _call(request, send).get("media_id")
    if not media_id:
        raise WechatError("封面传上去了，但微信没给 media_id")
    return str(media_id)


def publish_article(article: Path, *, cover: Path, publish: bool = False, author: str | None = None,
                    creds: dict[str, str] | None = None, send: Send | None = None,
                    wait: Callable[[float], None] = time.sleep, polls: int = 10) -> dict[str, Any]:
    title, digest, body = render_html(article.read_text(encoding="utf-8"))
    from . import gzh_layout

    styled = gzh_layout.current(article)
    if styled is not None:
        body = styled.read_text(encoding="utf-8")  # gzh skill 排的版优先；文章改过就作废，用上面的机械排版
    if len(title) > TITLE_MAX:
        raise WechatError(f"公众号标题最多 {TITLE_MAX} 字，这篇 {len(title)} 字")
    if not cover.is_file():
        raise WechatError("还没有封面：先在发布台做封面")
    wide = wide_cover(cover, article.parent / "公众号封面.jpg")
    token = get_token(creds or load_credentials(), send)
    thumb = upload_cover(wide, token, send)
    draft = _post("draft/add", token, {"articles": [{
        "title": title, "author": author or "", "digest": digest, "content": body,
        "thumb_media_id": thumb, "need_open_comment": 1, "only_fans_can_comment": 0,
    }]}, send)
    media_id = str(draft.get("media_id") or "")
    if not media_id:
        raise WechatError("微信没返回草稿 id")
    got = _post("draft/get", token, {"media_id": media_id}, send).get("news_item") or [{}]
    if (got[0] or {}).get("title") != title:
        raise WechatError("草稿建了，但读回来标题对不上：去草稿箱看一眼")
    result: dict[str, Any] = {"media_id": media_id, "title": title, "published": False, "layout": "gzh" if styled else "basic",
                              "url": "https://mp.weixin.qq.com/", "message": "已存进公众号草稿箱" + ("（gzh 排版）" if styled else "（基础排版：还没用 gzh 排，或文章改过）")}
    if not publish:
        return result
    try:
        publish_id = str(_post("freepublish/submit", token, {"media_id": media_id}, send).get("publish_id") or "")
    except WechatError as exc:
        return {**result, "message": f"已存进草稿箱，但没能发布：{exc}"}
    for _ in range(polls):
        wait(3)
        status = _post("freepublish/get", token, {"publish_id": publish_id}, send)
        code = status.get("publish_status")
        if code == 0:
            items = ((status.get("article_detail") or {}).get("item")) or [{}]
            return {**result, "published": True, "publish_id": publish_id, "url": items[0].get("article_url") or result["url"],
                    "message": "已发布（在公众号主页能看到，不推送粉丝）"}
        if code not in (1, None):
            return {**result, "publish_id": publish_id, "message": f"已存进草稿箱，发布没成功（状态 {code}）：去后台看看"}
    return {**result, "publish_id": publish_id, "message": "已提交发布，微信还在处理：过几分钟去公众号主页看"}


def main() -> int:
    parser = argparse.ArgumentParser(description="把 Markdown 文章排好版，存进公众号草稿箱（可选直接发布）")
    parser.add_argument("--article", required=True, type=Path)
    parser.add_argument("--cover", required=True)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    try:
        import yaml

        author = ((yaml.safe_load(SECRETS_PATH.read_text(encoding="utf-8")) or {}).get("wechat") or {}).get("author")
    except Exception:  # noqa: BLE001 - 作者名可以空着
        author = None
    try:
        if not args.cover:
            raise WechatError("还没有封面：先在发布台做封面")
        result = publish_article(args.article, cover=Path(args.cover), publish=args.publish, author=author)
        print(json.dumps({"ok": True, **result}, ensure_ascii=False))
    except WechatError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
