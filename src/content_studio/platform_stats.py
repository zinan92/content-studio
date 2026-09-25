"""B站 / X / 研习室：每天读一次自己每条内容的累计播放（阅读、曝光），算进「触达」。

9/25 Park：「现在只有抖音的数据是自动的。」逐个试过，这三个能读，而且都用现成的登录或钥匙：
- B站：投稿时存下的登录（content-toolkit 的 bilibili_creator.json），读创作中心的稿件列表；
- X：发文章那套开发者密钥，读自己最近的推文的 impression_count；
- 研习室：工作台钥匙调 admin-api 的 content.list（只有标题和阅读数，不带正文）。
视频号、小红书没有开放接口，公众号没认证（datacube 48001），这三个继续手填。

只存每条内容每次读到的累计数；每天的触达 = 当天最后一次减前一天最后一次（reach.daily_views）。
第一次读到的老内容只当基线，不算成当天的触达。一个平台读失败不影响别的平台。
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable
import urllib.error
import urllib.parse
import urllib.request

from .store import StudioStore, now_iso

BILI_COOKIES = Path("~/content-toolkit/capabilities/publish/cookies/bilibili_creator.json").expanduser()
BILI_ARCHIVES = "https://member.bilibili.com/x/web/archives"
X_API = "https://api.x.com/2"
XINGQIU = Path("~/work/wechat-xingqiu-shell").expanduser()
# launchd 的日常同步没有 Homebrew 的 PATH，node 和 tcb 都在那儿。
TOOL_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
LABELS = {"bilibili": "B站", "x": "X", "miniprogram": "研习室", "youtube": "YouTube"}
CONTENT_OPS = Path("~/work/content-ops").expanduser()

Post = dict[str, Any]  # {post_id, title, published_at, views}


class StatsError(RuntimeError):
    """说给人听的一句话。"""


class NotConnected(StatsError):
    """还没接上（比如 YouTube 还没授权「查看」）：安静跳过，不记成失败。"""


def _get_json(request: urllib.request.Request) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        raise StatsError(f"返回 {exc.code}：{exc.read().decode(errors='replace')[:200]}") from exc
    except (OSError, ValueError) as exc:
        raise StatsError(f"连不上：{exc}") from exc


def bilibili_posts(cookie_file: Path = BILI_COOKIES, *, max_pages: int = 10) -> list[Post]:
    try:
        raw = json.loads(cookie_file.read_text(encoding="utf-8"))
        cookies = (raw.get("cookie_info") or {}).get("cookies") or []
    except (OSError, ValueError) as exc:
        raise StatsError("没有 B站 登录（先在发布台登录一次 B站）") from exc
    cookie = "; ".join(f"{c['name']}={c['value']}" for c in cookies if c.get("name"))
    posts: list[Post] = []
    for page in range(1, max_pages + 1):
        query = urllib.parse.urlencode({"status": "is_pubing,pubed,not_pubed", "pn": page, "ps": 50})
        request = urllib.request.Request(f"{BILI_ARCHIVES}?{query}", headers={"Cookie": cookie, "User-Agent": UA, "Referer": "https://member.bilibili.com/"})
        data = _get_json(request)
        if data.get("code") == -101:
            raise StatsError("B站 登录过期了，在发布台重新登录一次 B站")
        if data.get("code") != 0:
            raise StatsError(f"B站 返回 {data.get('code')}：{data.get('message')}")
        items = (data.get("data") or {}).get("arc_audits") or []
        for item in items:
            archive = item.get("Archive") or {}
            if not archive.get("bvid"):
                continue
            ptime = archive.get("ptime")
            posts.append({"post_id": archive["bvid"], "title": archive.get("title") or "",
                          "published_at": datetime.fromtimestamp(ptime, timezone.utc).isoformat(timespec="seconds") if ptime else None,
                          "views": int((item.get("stat") or {}).get("view") or 0)})
        if len(items) < 50:
            break
    return posts


def x_posts(creds: dict[str, str] | None = None) -> list[Post]:
    from .x_post import XError, authorization_header, load_credentials

    try:
        creds = creds or load_credentials()
    except XError as exc:
        raise StatsError(str(exc)) from exc

    def get(url: str, query: dict[str, str]) -> dict[str, Any]:
        full = f"{url}?{urllib.parse.urlencode(query)}" if query else url
        return _get_json(urllib.request.Request(full, headers={"Authorization": authorization_header("GET", url, creds, query=query)}))

    me = (get(f"{X_API}/users/me", {}).get("data") or {}).get("id")
    if not me:
        raise StatsError("X 没告诉我这个账号的 id")
    # 最近 100 条（不含转推）；再老的每天也涨不了几个曝光。
    data = get(f"{X_API}/users/{me}/tweets", {"max_results": "100", "exclude": "retweets", "tweet.fields": "public_metrics,created_at"})
    return [{"post_id": t["id"], "title": (t.get("text") or "")[:60], "published_at": t.get("created_at"),
             "views": int((t.get("public_metrics") or {}).get("impression_count") or 0)} for t in data.get("data") or []]


def yanxishi_posts(*, runner: Callable[..., Any] = subprocess.run) -> list[Post]:
    from .publisher import _secret

    key, env_id = _secret("yanxishi", "workbench_key"), _secret("yanxishi", "env_id")
    if not key or not env_id:
        raise StatsError("secrets.yaml 里没有研习室工作台钥匙（yanxishi: workbench_key、env_id）")
    env = {**os.environ, "WORKBENCH_KEY": key, "PATH": f"{TOOL_PATH}:{os.environ.get('PATH', '')}"}
    try:
        done = runner(["node", str(XINGQIU / "scripts/workbench-stats.mjs"), "--env", env_id], capture_output=True, text=True, timeout=180, env=env, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise StatsError(f"跑不起来研习室脚本：{exc}") from exc
    lines = [line for line in (done.stdout or "").splitlines() if line.startswith("{")]
    try:
        result = json.loads(lines[-1])
    except (IndexError, ValueError):
        raise StatsError(f"研习室脚本没有返回结果：{(done.stderr or '').strip()[-200:]}") from None
    if not result.get("ok"):
        raise StatsError(str(result.get("error") or "研习室拒绝了"))
    return [{"post_id": a["id"], "title": a.get("title") or "", "published_at": a.get("publishedAt"), "views": int(a.get("reads") or 0)}
            for a in result.get("items") or [] if a.get("id")]


def youtube_posts(*, runner: Callable[..., Any] = subprocess.run) -> list[Post]:
    """content-ops 的 youtube_channel.py stats（它自己切到带 Google 库的 venv）。
    授权里没有只读权限时算「还没接上」，等 Park 点一次授权。"""
    try:
        done = runner([sys.executable, str(CONTENT_OPS / "scripts/youtube_channel.py"), "stats"], capture_output=True, text=True, timeout=180, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise StatsError(f"跑不起来 YouTube 脚本：{exc}") from exc
    try:
        result = json.loads(done.stdout or "")
    except ValueError:
        raise StatsError(f"YouTube 脚本没有返回结果：{(done.stderr or '').strip()[-200:]}") from None
    if result.get("status") in ("needs_reauth", "token_missing"):
        raise NotConnected(str(result.get("message") or "YouTube 还没授权"))
    if not result.get("ok"):
        raise StatsError(str(result.get("message") or result.get("status") or "YouTube 读失败"))
    return [{"post_id": v["id"], "title": v.get("title") or "", "published_at": v.get("publishedAt"), "views": int(v.get("views") or 0)}
            for v in result.get("items") or [] if v.get("id")]


FETCHERS: dict[str, Callable[[], list[Post]]] = {"bilibili": bilibili_posts, "x": x_posts, "miniprogram": yanxishi_posts, "youtube": youtube_posts}


def sync(store: StudioStore, fetchers: dict[str, Callable[[], list[Post]]] | None = None) -> dict[str, Any]:
    """每个平台读一次；读到的记一笔快照。返回每个平台 ok / 条数 / 出错原因。"""
    out: dict[str, Any] = {}
    fetched_at = now_iso()
    for platform, fetch in (fetchers or FETCHERS).items():
        error = None
        for _ in range(2):  # 这台机器连腾讯云、X 偶尔超时，再试一次
            try:
                posts = fetch()
                error = None
                break
            except NotConnected as exc:
                error = exc
                break
            except StatsError as exc:
                error = exc
        if isinstance(error, NotConnected):
            out[platform] = {"ok": False, "not_connected": True, "error": str(error)}
            continue
        if error is not None:
            out[platform] = {"ok": False, "error": str(error)}
            store.log_event("reach", f"{LABELS.get(platform, platform)} 数据没读到：{error}")
            continue
        store.add_post_snapshots(platform, posts, fetched_at)
        out[platform] = {"ok": True, "posts": len(posts)}
    return out
