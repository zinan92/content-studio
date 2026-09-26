"""补发队列：抖音发过、别的平台还没发的旧视频，排队拿去全量分发。

Park 一开始只发抖音，现在要全量分发；抖音风控、没拍新视频的日子，就从这里挑一条旧的，
走现有的发布台发到别的平台。这里只算「哪条在哪个平台缺」，发布本身仍然是发布台那一套，
每个平台照旧要 Park 点确认。

一条抖音视频和一个选题怎么对上：选题的 published_video_id 等于它；否则看这个选题有没有
抖音的发布记录、标题（选题名或发布文案的标题）和抖音标题够不够像。Park 在工作台之外
发过的平台，用「已经发过」标一下，记在这张表里，不为了打标去建选题。
"""
from __future__ import annotations

from difflib import SequenceMatcher
import re
from typing import Any

# 全量分发：抖音以外的每个平台都算缺口（Park 9/26：只算四个视频平台不对）。
# 视频平台直接发这条视频；文字平台发它的文章版（写文章用这条视频的逐字稿）；小宇宙发音频。
PLATFORMS = ("channels", "xiaohongshu", "bilibili", "youtube", "wechat_mp", "miniprogram", "x", "xiaoyuzhou")
KIND = {"channels": "视频", "xiaohongshu": "视频", "bilibili": "视频", "youtube": "视频",
        "wechat_mp": "文字", "miniprogram": "文字", "x": "文字", "xiaoyuzhou": "音频"}
# 抖音的活动话题，搬到别的平台没有意义。
ACTIVITY_WORDS = ("计划", "大赏", "征稿", "大会", "挑战赛", "活动", "新星")
TAG = re.compile(r"#\s*([^\s#]+)")
MATCH_RATIO = 0.6


def normalize(text: str) -> str:
    text = TAG.sub("", text or "")
    return re.sub(r"[\s\W_]+", "", text).lower()


def split_douyin_title(raw: str) -> dict[str, Any]:
    """抖音的「标题」其实是整段描述：一句标题 + 一段话 + 一串话题。拆成发布台要的三样。"""
    raw = (raw or "").strip()
    tags = [t for t in TAG.findall(raw) if len(t) >= 2 and not any(w in t for w in ACTIVITY_WORDS)]
    text = TAG.sub("", raw).strip()
    head = headline(text)
    body = text[len(head):].strip()
    return {"title": head.strip(), "body": body, "tags": list(dict.fromkeys(tags))}


CJK = re.compile(r"[\u3000-\u9fff\uff00-\uffef]")


def headline(text: str) -> str:
    """一句标题：第一个中文后面的空格处断开（抖音习惯「标题 描述」）；没有就到第一个句末标点；再没有取前 30 字。"""
    first = text.split("\n", 1)[0]
    for m in re.finditer(r"\s", first):
        if 8 <= m.start() <= 40 and CJK.match(first[m.start() - 1]):
            return first[: m.start()]
    m = re.search(r"[！？。!?]", first)
    if m and m.end() <= 40:
        return first[: m.end()]
    return first[:30]


def similarity(a: str, b: str) -> float:
    a, b = normalize(a), normalize(b)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def link_topics(videos: list[dict[str, Any]], topics: list[dict[str, Any]],
                records: dict[int, dict[str, Any]], copy_titles: dict[int, str]) -> dict[str, int]:
    """video_id → topic_id。先认 published_video_id，再在有抖音发布记录的选题里按标题找最像的。"""
    linked: dict[str, int] = {}
    taken: set[int] = set()
    for t in topics:
        vid = t.get("published_video_id")
        if vid:
            linked[str(vid)] = t["id"]
            taken.add(t["id"])
    candidates = [t for t in topics if t["id"] not in taken and "douyin" in (records.get(t["id"]) or {})]
    for v in videos:
        if v["video_id"] in linked:
            continue
        best, score = None, 0.0
        for t in candidates:
            if t["id"] in taken:
                continue
            s = max(similarity(v.get("title") or "", t.get("title") or ""), similarity(v.get("title") or "", copy_titles.get(t["id"], "")))
            if s > score:
                best, score = t, s
        if best is not None and score >= MATCH_RATIO:
            linked[v["video_id"]] = best["id"]
            taken.add(best["id"])
    return linked


def queue(videos: list[dict[str, Any]], *, links: dict[str, int], records: dict[int, dict[str, Any]],
          marks: dict[str, set[str]], median: float | None, platforms: tuple[str, ...] = PLATFORMS) -> list[dict[str, Any]]:
    """每条视频在每个平台的状态。排序：还有缺口的在前，缺口里点赞高的在前——同样一条旧视频，
    在抖音上验证过的先拿去别的平台。"""
    rows = []
    for v in videos:
        tid = links.get(v["video_id"])
        rec = records.get(tid) or {} if tid else {}
        done = {}
        for p in platforms:
            done[p] = "record" if p in rec else "mark" if p in marks.get(v["video_id"], set()) else None
        missing = [p for p in platforms if not done[p]]
        likes = v.get("likes")
        rows.append({
            "video_id": v["video_id"], "title": v.get("title") or "", "headline": split_douyin_title(v.get("title") or "")["title"],
            "published_at": v.get("published_at"), "likes": likes,
            "multiple": round(likes / median, 1) if median and likes is not None else None,
            "topic_id": tid, "done": done, "missing": missing,
        })
    rows.sort(key=lambda r: (0 if r["missing"] else 1, -(r["likes"] or 0)))
    return rows
