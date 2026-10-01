"""证据图（10/1 Park）：视频里的笔记截图 + 名人原推，夜里跑，只出提案。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from content_studio import evidence
from tests.test_web import client  # noqa: F401 - fixture


def test_propose_puts_images_after_their_paragraph_and_can_replace_an_ai_illustration() -> None:
    md = "# 标题\n\n先给你看一个东西。\n\n世界发展有一个规律，创业者最大的技能是加杠杆。\n\n![AI 画的杠杆](illustrations/01-leverage.png)\n\n结尾。\n"
    items = [{"file": "01-f0008.jpg", "after": "先给你看一个东西", "caption": "我的 AI 简报（真实截图）", "replaces": ""},
             {"file": "02-f0051.jpg", "after": "世界发展有一个规律，创业者", "caption": "我的备忘录", "replaces": "01-leverage.png"},
             {"file": "03-x.jpg", "after": "文章里没有这一句", "caption": "x", "replaces": ""}]
    text, placed = evidence.propose(md, items)
    assert "![我的 AI 简报（真实截图）](evidence/01-f0008.jpg)" in text and text.index("先给你看") < text.index("01-f0008")
    assert "01-leverage.png" not in text and text.index("加杠杆") < text.index("02-f0051")  # AI 那张被真图顶掉
    assert [p["placed"] for p in placed] == [True, True, False]


def test_private_text_in_a_screenshot_is_caught() -> None:
    assert evidence.private_hit("AppID\nwxef32b0b407bf9978")
    assert evidence.private_hit("ef32b0b407bf9978")  # OCR 常把前面的 wx 截掉
    assert evidence.private_hit("电话 13812345678") and evidence.private_hit("park@example.com")
    assert evidence.private_hit("api_key: abc") and evidence.private_hit("密码：123")
    assert evidence.private_hit("Y = ax1 + bx2 + cx3\n人力杠杆：人越多公司越值钱") is None


def test_a_tweet_only_counts_if_that_person_really_said_that() -> None:
    real = {"text": "Code and media are permissionless leverage. They're the leverage behind the newly rich.",
            "user": {"screen_name": "naval"}, "created_at": "2018-05-31T08:37:56.000Z"}
    look = lambda tid: real if tid == "1002106893265920000" else None  # noqa: E731
    item = {"url": "https://x.com/naval/status/1002106893265920000", "screen_name": "naval", "quote": "code and media are permissionless leverage"}
    assert evidence.verify_tweet(item, look)["url"] == "https://x.com/naval/status/1002106893265920000"
    assert evidence.verify_tweet({**item, "screen_name": "elonmusk"}, look) is None  # 不是这个人
    assert evidence.verify_tweet({**item, "quote": "AI will replace all jobs tomorrow"}, look) is None  # 原话对不上
    assert evidence.verify_tweet({**item, "url": "https://x.com/naval/status/1"}, look) is None  # 查不到
    assert evidence.verify_tweet({**item, "url": "https://example.com/naval"}, look) is None


def test_crop_boxes_are_clamped_and_tiny_ones_dropped() -> None:
    assert evidence.clamp([-20, -5, 2000, 900], (1920, 1080)) == (0, 0, 1920, 900)
    assert evidence.clamp([100, 100, 200, 150], (1920, 1080)) is None
    assert evidence.clamp(["a", 0, 1, 2], (1920, 1080)) is None


def test_run_topic_only_writes_a_proposal_and_throws_out_what_does_not_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from PIL import Image, ImageDraw

    article = tmp_path / "topic-1" / "article.md"
    article.parent.mkdir()
    original = "# 明牌机会\n\n先给你看一个东西。\n\n它回我，每天大概600到900篇。\n\n![AI 图](illustrations/02-x.png)\n\n结尾。\n"
    article.write_text(original, encoding="utf-8")
    frames = article.parent / evidence.WORK / "frames"
    frames.mkdir(parents=True)
    for i, shade in enumerate((30, 120, 220), 1):  # 三个不一样的画面
        im = Image.new("RGB", (1920, 1080), (shade, shade, shade))
        ImageDraw.Draw(im).rectangle((400, 100, 1500 - i * 100, 600), fill=(255 - shade, 0, 0))
        im.save(frames / f"f{i:04d}.jpg")
    answer = {"frames": [{"id": "f0001", "crop": [400, 0, 1920, 800], "after": "先给你看一个东西", "caption": "我的 AI 简报（真实截图）", "replaces": ""},
                         {"id": "f0002", "crop": [0, 0, 1920, 800], "after": "它回我，每天大概", "caption": "带着 AppID 的那张", "replaces": ""},
                         {"id": "f0003", "crop": [0, 0, 100, 100], "after": "结尾", "caption": "太小", "replaces": ""}],
              "tweets": [{"url": "https://x.com/naval/status/9", "screen_name": "naval", "quote": "code and media are leverage", "after": "它回我", "caption": "Naval"},
                         {"url": "https://x.com/someone/status/8", "screen_name": "someone", "quote": "made up words here", "after": "结尾", "caption": "编的"}]}
    seen = {}

    def run(args: list[str], what: str, timeout: int = 600) -> str:
        if args[0] == "swift":  # 读字：第一张干净，第二张带 AppID
            return "".join(f"### {p}\n" + ("这是我每天早上收到的 AI 简报，三条主线：能源、黄金、中美\n" if "f0001" in p else "AppID wxef32b0b407bf9978 新的 repo 放到 git\n") for p in args[2:])
        raise AssertionError(args)

    monkeypatch.setattr(evidence.shutil, "which", lambda name: "/usr/bin/" + name)
    tweet = {"text": "Code and media are leverage behind the newly rich.", "user": {"screen_name": "naval"}, "created_at": "2018"}
    res = evidence.run_topic(article, tmp_path / "v.mp4", segments=[{"start": 0, "text": "先给你看一个东西"}],
                             llm=lambda prompt: seen.setdefault("prompt", prompt) and f"```json\n{json.dumps(answer, ensure_ascii=False)}\n```",
                             run=run, lookup=lambda tid: tweet if tid == "9" else None,
                             shot=lambda tid, out: Image.new("RGB", (550, 300), "white").save(out))
    assert article.read_text(encoding="utf-8") == original  # 正式稿不动
    proposed = (article.parent / evidence.PROPOSED).read_text(encoding="utf-8")
    assert "evidence/01-f0001.jpg" in proposed and "evidence/tweet-01-naval.png" in proposed and "illustrations/02-x.png" in proposed
    assert [(i["kind"], i["file"]) for i in res["items"]] == [("frame", "01-f0001.jpg"), ("tweet", "tweet-01-naval.png")]
    whys = " ".join(r["why"] for r in res["rejected"])
    assert "隐私" in whys and "太小" in whys and "对不上" in whys and len(res["rejected"]) == 3
    assert not (article.parent / evidence.OUT / "02-f0002.jpg").exists()  # 有隐私的那张删掉了
    assert json.loads((article.parent / evidence.OUT / evidence.PROPOSAL).read_text(encoding="utf-8"))["items"]
    assert "先给你看一个东西" in seen["prompt"] and "f0001" in seen["prompt"] and "绝不编" in seen["prompt"]


def test_the_night_queue_lists_unfinished_content_and_says_why_it_skips(client) -> None:
    from tests.test_web import SEC, _wait_sync

    assert client.get("/api/evidence/queue").json() == {"topics": []}
    client.post("/api/accounts", json={"url": f"https://www.douyin.com/user/{SEC}", "is_self": True})
    _wait_sync(client)
    vid = client.get("/api/backfill").json()["videos"][0]["video_id"]
    tid = client.post(f"/api/backfill/{vid}/take").json()["topic_id"]
    row = next(t for t in client.get("/api/evidence/queue").json()["topics"] if t["topic_id"] == tid)
    assert row["skip"] == "还没有文章" and row["done"] is False
