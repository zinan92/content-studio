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


def _proposed(folder: Path) -> Path:
    """一篇文章 + 一份提案：两张图，一张顶掉 AI 图。"""
    from PIL import Image

    article = folder / "article.md"
    folder.mkdir(parents=True, exist_ok=True)
    article.write_text("# 标题\n\n先给你看一个东西。\n\n世界发展有一个规律。\n\n![AI 画的](illustrations/01-a.png)\n\n结尾。\n", encoding="utf-8")
    out = folder / evidence.OUT
    out.mkdir()
    for f in ("01-f0001.jpg", "tweet-01-naval.png"):
        Image.new("RGB", (400, 300), "white").save(out / f)
    items = [{"kind": "frame", "file": "01-f0001.jpg", "after": "先给你看一个东西", "caption": "我的简报", "replaces": "", "placed": True},
             {"kind": "tweet", "file": "tweet-01-naval.png", "after": "世界发展有一个规律", "caption": "Naval", "replaces": "01-a.png",
              "url": "https://x.com/naval/status/9", "placed": True}]
    (out / evidence.PROPOSAL).write_text(json.dumps({"items": items, "rejected": [{"why": "糊"}]}, ensure_ascii=False), encoding="utf-8")
    return article


def test_picking_evidence_puts_only_the_chosen_ones_in_and_can_be_taken_back(tmp_path: Path) -> None:
    """10/2 Park：找了图没人看等于白找。找完他一张张挑；没挑之前算「等你挑」，文字平台先不发。"""
    article = _proposed(tmp_path / "topic-1")
    original = article.read_text(encoding="utf-8")
    st = evidence.status(article)
    assert st["state"] == "pending" and evidence.pending(article) and len(st["items"]) == 2 and st["rejected"] == 1
    st = evidence.apply(article, ["tweet-01-naval.png"], now="2026-10-02T12:00:00+00:00")
    text = article.read_text(encoding="utf-8")
    assert st["state"] == "applied" and st["used"] == ["tweet-01-naval.png"] and not evidence.pending(article)
    assert "evidence/tweet-01-naval.png" in text and "01-f0001" not in text and "01-a.png" not in text  # 没勾的不放；顶掉的 AI 图拿掉
    from content_studio.illustrate import strip_images
    assert strip_images(evidence.strip(text)) == strip_images(original)  # 定稿看的字没变：文章那一步不用重新定稿
    with pytest.raises(evidence.EvidenceError):
        evidence.apply(article, ["01-f0001.jpg"], now="x")  # 已经放过：先撤回再挑
    st = evidence.undo(article)
    assert article.read_text(encoding="utf-8") == original and st["state"] == "pending"  # AI 图回来了，回到等他挑
    assert evidence.apply(article, [], now="x")["state"] == "skipped" and article.read_text(encoding="utf-8") == original
    assert not evidence.pending(article)  # 说了不要，也不拦
    assert evidence.undo(article)["state"] == "pending"


def test_undo_will_not_throw_away_words_he_changed_after_the_images_went_in(tmp_path: Path) -> None:
    article = _proposed(tmp_path / "topic-1")
    evidence.apply(article, ["01-f0001.jpg"], now="x")
    article.write_text(article.read_text(encoding="utf-8").replace("结尾。", "结尾改过了。"), encoding="utf-8")
    with pytest.raises(evidence.EvidenceError, match="改过字"):
        evidence.undo(article)
    assert "结尾改过了" in article.read_text(encoding="utf-8")


def test_an_article_with_no_proposal_or_nothing_usable_is_not_held(tmp_path: Path) -> None:
    article = tmp_path / "topic-2" / "article.md"
    article.parent.mkdir()
    article.write_text("# 标题\n\n一段。\n", encoding="utf-8")
    assert evidence.status(article)["state"] == "none" and not evidence.pending(article)
    (article.parent / evidence.OUT).mkdir()
    (article.parent / evidence.OUT / evidence.PROPOSAL).write_text(json.dumps({"items": [], "rejected": [{"why": "糊"}]}), encoding="utf-8")
    assert evidence.status(article)["state"] == "empty" and not evidence.pending(article)


def test_the_pack_page_finds_picks_and_undoes_evidence_through_the_api(client, tmp_path: Path) -> None:
    topic = client.post("/api/topics", json={"title": "旧视频"}).json()
    article = _proposed(tmp_path / "drafts" / f"topic-{topic['id']}")
    client.app.state.store.update_topic(topic["id"], article_path=str(article))
    st = client.get(f"/api/topics/{topic['id']}/evidence").json()
    assert st["state"] == "pending" and not st["running"] and st["skip"]  # 测试里没有视频：找不了，但能挑已有的提案
    assert st["items"][0]["src"] == f"/api/topics/{topic['id']}/article-file/evidence/01-f0001.jpg"
    assert client.get(st["items"][0]["src"]).status_code == 200
    assert client.post(f"/api/topics/{topic['id']}/evidence").status_code == 400  # 没视频
    st = client.post(f"/api/topics/{topic['id']}/evidence/apply", json={"files": ["01-f0001.jpg"]}).json()
    assert st["state"] == "applied" and st["can_undo"]
    assert client.post(f"/api/topics/{topic['id']}/evidence/apply", json={"files": ["01-f0001.jpg"]}).status_code == 400
    assert client.post(f"/api/topics/{topic['id']}/evidence/undo").json()["state"] == "pending"
    assert client.post(f"/api/topics/{topic['id']}/evidence/apply", json={"files": []}).json()["state"] == "skipped"
