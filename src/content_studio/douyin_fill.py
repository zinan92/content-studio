"""抖音半自动：开一个看得见的 Chrome，传视频、传封面、填好标题和描述，停在「发布」前。

Park 2026-09-29：以前让 Codex 开网页后台，上传视频、封面、填标题介绍全自动，只有最后点「发布」
那一下他自己来。这个脚本就做到那一步为止——**它从不点「发布」「定时发布」**，最后一下永远是 Park。

用 social-auto-upload 那套填表步骤（fill_title_and_description、set_thumbnail），不用它的
upload()：那个最后会自己点发布。Chrome 用独立的配置目录（不碰 Park 平时的 Chrome），第一次在
窗口里扫码登录，之后一直记着。

窗口一旦开了，脚本就不自己退出：退出会把 Chrome 连同传好的视频、填好的表一起关掉。哪一步没成
就说一声，留给 Park 在窗口里手动补。Park 点了发布（页面跳到作品管理）就报一次「已发出」；
窗口关了才退出。

用工具箱的 venv 跑（它装了 patchright）：
    <toolkit>/.venv/bin/python douyin_fill.py --toolkit <toolkit> --profile <dir> --video a.mp4 --title … --description … --tags a,b
每一步往 stdout 打一行 JSON：过程是 {"progress": "..."}，最后一行是结果（publisher.parse_result 读）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
import time
from typing import Any

UPLOAD_URL = "https://creator.douyin.com/creator-micro/content/upload"
PUBLISH_PAGES = ("/creator-micro/content/publish", "/creator-micro/content/post/video")
MANAGE_PAGE = "/creator-micro/content/manage"
COVER_SUFFIXES = (".jpg", ".jpeg", ".png")
UPLOAD_INPUT = "div[class^='container'] input"
DESCRIPTION_CAP = 1000  # 抖音作品描述上限，#话题 也算在里面

LOGIN_WAIT = 5 * 60
PUBLISH_PAGE_WAIT = 3 * 60
UPLOAD_WAIT = 30 * 60
COVER_WAIT = 2 * 60
PARK_WAIT = 3 * 3600 - 10 * 60  # 比工作台那边的 3 小时上限早一点收尾，结果才能正常回去

WAITING = "窗口已打开，等你在抖音点发布"
PUBLISHED = "已发出，窗口可以关了"


def emit(**event: Any) -> None:
    print(json.dumps(event, ensure_ascii=False), flush=True)


def is_published(url: str) -> bool:
    """点了「发布」，抖音会跳到作品管理页。"""
    return MANAGE_PAGE in (url or "")


def on_publish_page(url: str) -> bool:
    return any(p in (url or "") for p in PUBLISH_PAGES)


def tags_to_type(body: str, tags: list[str]) -> list[str]:
    """描述里已经写了 #话题 的，不再敲一遍。"""
    seen: set[str] = set()
    out = []
    for tag in tags:
        tag = tag.strip().lstrip("#").strip()
        if tag and tag not in seen and f"#{tag}" not in (body or ""):
            seen.add(tag)
            out.append(tag)
    return out


def fit_description(body: str, tags: list[str], cap: int = DESCRIPTION_CAP) -> str:
    """话题是接在描述后面敲的：描述太长，话题会被抖音截掉。先给话题留位置。"""
    room = cap - sum(len(t) + 3 for t in tags)  # 每个话题敲的是「 #话题」再加一个空格
    return (body or "")[: max(room, 0)]


def usable_cover(path: str) -> str | None:
    """抖音的封面框只收 jpg / png；svg 之类的跳过，别让弹窗卡住。"""
    if not path:
        return None
    p = Path(path)
    return str(p) if p.is_file() and p.suffix.lower() in COVER_SUFFIXES else None


class Closed(Exception):
    """Park 把窗口关了。"""


async def _login_visible(page: Any) -> bool:
    for text in ("扫码登录", "手机号登录", "验证码登录"):
        marker = page.get_by_text(text, exact=True).first
        try:
            if await marker.count() and await marker.is_visible():
                return True
        except Exception:  # noqa: BLE001 - page moving under us
            continue
    return False


async def _upload_ready(page: Any, wait: float) -> bool:
    """登录了才看得到上传框。以它为准，而不是「没看到登录字样」——跳登录页慢一点就会误判。"""
    try:
        await page.locator(UPLOAD_INPUT).first.wait_for(state="attached", timeout=wait * 1000)
        return True
    except Exception:  # noqa: BLE001 - not there (yet)
        return False


async def ensure_login(page: Any, state: dict[str, Any]) -> bool:
    await page.goto(UPLOAD_URL, wait_until="domcontentloaded")
    if await _upload_ready(page, 12):
        return True
    emit(progress="先在弹出的 Chrome 里扫码登录抖音（5 分钟内）")
    deadline = time.monotonic() + LOGIN_WAIT
    while time.monotonic() < deadline:
        if state["closed"]:
            raise Closed
        await asyncio.sleep(2)
        if "/creator-micro/" in page.url and not await _login_visible(page):
            if "/content/upload" not in page.url:
                await page.goto(UPLOAD_URL, wait_until="domcontentloaded")
            if await _upload_ready(page, 10):
                return True
    return False


async def upload_video(page: Any, video: str, state: dict[str, Any]) -> bool:
    emit(progress="正在上传视频")
    await page.locator(UPLOAD_INPUT).first.set_input_files(video)
    deadline = time.monotonic() + PUBLISH_PAGE_WAIT
    while time.monotonic() < deadline:
        if state["closed"]:
            raise Closed
        if on_publish_page(page.url):
            await asyncio.sleep(1)
            return True
        await asyncio.sleep(0.5)
    return False


async def wait_uploaded(page: Any, uploader: Any, state: dict[str, Any]) -> bool:
    emit(progress="等视频传完")
    retried = 0
    deadline = time.monotonic() + UPLOAD_WAIT
    while time.monotonic() < deadline:
        if state["closed"]:
            raise Closed
        try:
            if await page.locator('[class^="long-card"] div:has-text("重新上传")').count():
                return True
            if retried < 2 and await page.locator('div.progress-div > div:has-text("上传失败")').count():
                retried += 1
                await uploader.handle_upload_error(page)  # 只是重新选一次视频文件
        except Exception:  # noqa: BLE001 - keep waiting; the page re-renders while uploading
            pass
        await asyncio.sleep(2)
    return False


async def fill(args: argparse.Namespace) -> dict[str, Any]:
    start = time.monotonic()  # 总时长从这里算：登录、上传再慢，也要赶在工作台的 3 小时上限之前收尾
    # 这个文件所在的目录里有 content_studio 自己的 conf.py，会挡住工具箱的 conf：先拿掉
    here = Path(__file__).resolve().parent
    sys.path[:] = [args.toolkit, *(p for p in sys.path if Path(p or ".").resolve() != here)]
    from patchright.async_api import async_playwright
    from uploader.douyin_uploader.main import DouYinVideo

    tags = tags_to_type(args.description, [t for t in args.tags.split(",") if t.strip()])
    description = fit_description(args.description or args.title, tags)
    landscape, portrait = usable_cover(args.cover_landscape), usable_cover(args.cover_portrait)
    # 只拿它的填表方法用；它的 upload()（最后会点发布）不碰。
    uploader = DouYinVideo(title=args.title, file_path=args.video, tags=tags, publish_date=0, account_file="",
                           thumbnail_landscape_path=landscape, thumbnail_portrait_path=portrait, desc=description)
    state: dict[str, Any] = {"closed": False, "published": False}
    missed: list[str] = []

    Path(args.profile).mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(args.profile, channel="chrome", headless=False, no_viewport=True, locale="zh-CN")
        ctx.on("close", lambda *_: state.update(closed=True))
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        try:
            await page.bring_to_front()
        except Exception:  # noqa: BLE001
            pass

        async def step(label: str, coro: Any, *, timeout: float | None = None) -> bool:
            """一步失败不收摊：记下来，告诉 Park 在窗口里自己补。"""
            try:
                ok = await (asyncio.wait_for(coro, timeout) if timeout else coro)
            except Closed:
                raise
            except Exception:  # noqa: BLE001 - shown to Park as「没弄好」
                ok = False
            if state["closed"]:
                raise Closed
            if ok is False:
                missed.append(label)
            return ok is not False

        try:
            emit(progress="正在打开抖音创作者中心")
            if not await step("登录", ensure_login(page, state)):
                emit(progress="没等到扫码登录。窗口留着：登录后可以自己传，或者关掉窗口回工作台再点一次")
            elif await step("上传视频", upload_video(page, args.video, state)):
                emit(progress="正在填标题和描述")
                await step("标题和描述", uploader.fill_title_and_description(page, args.title, description, tags))
                uploaded = await step("等视频传完", wait_uploaded(page, uploader, state))
                if uploaded and (landscape or portrait):
                    emit(progress="正在传封面")
                    await step("封面", uploader.set_thumbnail(page), timeout=COVER_WAIT)
                elif not (landscape or portrait):
                    missed.append("封面（这条还没做）")
            note = f"（{'、'.join(missed)}没弄好，在窗口里自己补一下）" if missed else ""
            emit(progress=WAITING + note, missed=missed)
        except Closed:
            pass

        deadline = start + PARK_WAIT
        while not state["closed"] and time.monotonic() < deadline:
            pages = [p for p in ctx.pages if not p.is_closed()]
            if not pages:
                break
            if not state["published"] and any(is_published(p.url) for p in pages):
                state["published"] = True
                emit(progress=PUBLISHED, published=True)
            await asyncio.sleep(1)
        timed_out = not state["closed"] and time.monotonic() >= deadline
        if not state["closed"]:
            try:
                await ctx.close()
            except Exception:  # noqa: BLE001
                pass

    if state["published"]:
        return {"ok": True, "published": True, "platform": "douyin", "status": "published"}
    if timed_out:
        return {"ok": False, "status": "window_timeout", "message": "窗口开了快 3 小时没发，已经关掉"}
    return {"ok": False, "status": "window_closed", "message": "窗口关了，没发"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="抖音半自动：填好等 Park 点发布")
    parser.add_argument("--toolkit", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--video", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--description", default="")
    parser.add_argument("--tags", default="")
    parser.add_argument("--cover-landscape", default="")
    parser.add_argument("--cover-portrait", default="")
    args = parser.parse_args(argv)
    if not Path(args.video).is_file():
        emit(ok=False, status="video_missing", message="找不到成片文件")
        return 2
    try:
        result = asyncio.run(fill(args))
    except Exception as exc:  # noqa: BLE001 - reported to the job
        text = str(exc)
        if "ProcessSingleton" in text or "user data directory is already in use" in text:
            text = "抖音那个 Chrome 窗口已经开着了，先用那个，或者关掉再点"
        result = {"ok": False, "status": "error", "message": text[:300]}
    emit(**result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
