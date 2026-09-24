from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import time

import pytest
from fastapi.testclient import TestClient

from content_studio import outline, web
from content_studio.store import StudioStore
from content_studio.worker import TeardownWorker, WorkerConfig


SEC = "MS4wLjABAAAAweb_test"


class FakeClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def resolve_profile(self, url):
        return None

    async def profile(self, sec_uid):
        return {"nickname": "对标号", "follower_count": 12345}

    async def posts(self, sec_uid, cursor):
        # 发布时间相对「现在」：写死的时间戳会随真实时间推移掉出 7 天 / 30 天 / 90 天各种窗口，
        # 到某一天整批测试就会无缘无故失败。作品 1 最旧、作品 5 最新，顺序和原来一致。
        base = datetime.now(timezone.utc) - timedelta(days=6)
        items = [
            {"aweme_id": str(i), "desc": f"作品{i}", "create_time": int((base + timedelta(hours=i)).timestamp()), "duration": 90000,
             "statistics": {"digg_count": likes, "collect_count": 10, "share_count": 5, "comment_count": 1}}
            for i, likes in enumerate([100, 120, 90, 110, 5000], start=1)
        ]
        return {"items": items, "has_more": False}


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(web, "LEGACY_REPORT_DIRS", ())
    # 框架是 Obsidian 里的文件，Park 随时会改。测试用自己的副本，不读他的。
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    (workflows / outline.FRAMEWORK_FILE).write_text(
        f"# {outline.LABEL}\n\n前三句里必须有一个真实数字。结尾禁止稀缺性和催单。\n", encoding="utf-8")
    monkeypatch.setenv(outline.WORKFLOWS_ENV, str(workflows))
    cookie = tmp_path / "cookies.json"
    cookie.write_text(json.dumps({"sessionid": "x"}))
    cookie.chmod(0o600)
    store_path = tmp_path / "studio.sqlite3"
    processed: list[str] = []

    def process(url, **kwargs):
        processed.append(url)
        video_id = url.rsplit("/", 1)[-1]
        report_dir = tmp_path / "data" / "reports" / video_id
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "report.json").write_text(json.dumps(_report(video_id)), encoding="utf-8")
        return {"content_id": video_id, "report_json": str(report_dir / "report.json")}

    app = web.create_app(
        store_path=store_path,
        cookie_path=cookie,
        creator_db=None,
        data_dir=tmp_path / "data",
        downloads_dir=tmp_path / "downloads",
        client_factory=FakeClient,
        start_worker=False,
        drafts_dir=tmp_path / "drafts",
        write_fn=_fake_writer,
        brief_fn=_fake_brief,
        opening_fn=lambda prompt: {"stated_at": 0.5, "quote": "开门见山说主线", "before": "", "fixes": ["保持"]},
        anna_fn=_fake_anna,
        qa_fn=lambda prompt: {k: {"score": 4, "reason": "r", "evidence": "大多数人以为是能力问题"} for k in ("pain", "contrast", "delivery")} | {"thin": False, "fix": "补一张截图", "caution": ""},
        outline_fn=lambda prompt: "<<<ARTICLE>>>\n# 标题\n\n## 主线\n大多数人以为是能力问题，其实是位置问题。\n\n## 开头候选\n"
        + "\n".join(f"{i}. 「大多数人以为是能力问题，其实是位置问题。」（绝对否定 · 靠素材）" for i in range(1, 7))
        + "\n\n## 中间骨架\n### 论点 A：他上周还在用它改错别字\n证据：素材里有。\n\n### 论点 B：别人已经用它改了收入结构\n证据：要补 —— 去截一张后台收入图。\n"
        + "\n## 结尾\n你手里有人，来找我聊聊。\n<<<END>>>",
    )
    app.state.worker.process_fn = process
    # Never let a test reach Park's real vault: the setting used to default to Park's vault, and the
    # transcript hook writes there on every successful teardown.
    app.state.store.update_settings({"obsidian_vault": str(tmp_path / "vault-default")})
    (tmp_path / "vault-default").mkdir(exist_ok=True)
    with TestClient(app, headers={"X-Content-Studio": "1"}) as test_client:
        test_client.processed = processed
        yield test_client
    app.state.store.close()


ARTICLE = "# 为什么用了 AI 反而更累\n\n" + "我发现一件事。" * 60


def _fake_writer(prompt: str) -> str:
    assert "作者是 Park" in prompt
    if "炸掉" in prompt:
        raise RuntimeError("boom")
    return f"好的\n<<<ARTICLE>>>\n{ARTICLE}\n<<<END>>>\n"


def _fake_anna(system: str, user: str, session_id: str | None) -> dict:
    _fake_anna.last_user = user
    assert "让对的人看得更久" in system or "Anna" in system
    if "炸掉" in user:
        raise RuntimeError("boom")
    seen = "看到报告" if "Park 正在看的拆解报告" in user else "看到提纲" if "## 拍摄提纲" in user else "没有提纲"
    return {"text": f"{seen}｜上一轮 {session_id}\n[动作] 按三点评分", "session_id": "sess-1"}


def _fake_brief(prompt: str) -> dict:
    import re as _re

    paths = _re.findall(r"path: ([^；）]+)", prompt)
    note = [p for p in paths if p.startswith("003_")][0]
    daily = [p for p in paths if p.startswith("006_")][0]
    return {
        "known": ["今天 AI 日报在讲 Codex"], "unknown": ["Park 今天能拍多久"],
        "reads": [{"title": "Codex 新功能", "why": "和你的方向相关", "source": {"path": daily}}],
        "videos": [{"title": "为什么用了 AI 反而更累", "hook": "累的不是活，是落差", "claim": "预期落差让人累",
                    "outline": ["一", "二", "三"], "sources": [{"path": note}, {"path": daily}], "why_today": "日报在讲",
                    "effort": "低", "caution": "", "qa": {"pain": 4, "contrast": 3, "delivery": 3, "note": "n"}, "primary": True}],
        "prep": "打开录制窗口",
    }


def _wait_topic(client: TestClient, topic_id: int) -> dict:
    import time

    for _ in range(200):
        topic = [t for t in client.get("/api/topics").json() if t["id"] == topic_id][0]
        if topic["write_state"] != "running":
            return topic
        time.sleep(0.02)
    raise AssertionError("writing did not finish")


def _report(video_id: str) -> dict:
    return {
        "schema_version": 2,
        # Relative to now: reports untouched for REPORT_STALE_DAYS are auto-archived on read,
        # so a hard-coded date turns every test that reads this fixture into a time bomb.
        # Spread by video id so /api/reports (newest first) has a deterministic order.
        "generated_at": (datetime.now(timezone.utc) - timedelta(days=1) + timedelta(seconds=int(video_id) if video_id.isdigit() else 0)).isoformat(),
        "content_id": video_id,
        "title": "报告标题",
        "author": "对标号",
        "source_url": f"https://www.douyin.com/video/{video_id}",
        "facts": {"likes": 5000, "multiple_of_median": 45.5},
        "transcript": {"duration_seconds": 60, "line_count": 2, "language": "zh"},
        "thesis": {"text": "主线", "evidence": []},
        "opening": None,
        "segments": [{"index": 0, "label": "钩子", "drift": False, "start": 0, "end": 60, "summary": "s", "reason": "r", "text": "正文" * 200, "evidence": []}],
        "drift": {"seconds": 0, "share": 0},
        "why_boom": [{"text": "收藏/赞 1%", "evidence": []}],
        "why_scatter": [{"text": "评论/赞 1%", "evidence": []}],
        "hypothesis_note": "待验证",
    }


def _wait_sync(client: TestClient) -> None:
    import time

    for _ in range(100):
        if not client.app.state.ops.syncing and not client.app.state.ops.full_sync_running:
            return
        time.sleep(0.02)
    raise AssertionError("sync did not finish")


def test_index_and_state_load_on_an_empty_library(client: TestClient) -> None:
    assert "内容工作台" in client.get("/").text
    state = client.get("/api/state").json()
    assert state["cookies"]["ok"] is True
    assert state["self_account"] is None
    assert client.get("/api/mine").json() == {"account": None, "videos": []}
    assert client.get("/api/reports").json() == []


def test_add_benchmark_syncs_and_breakout_is_auto_queued_then_reported(client: TestClient) -> None:
    res = client.post("/api/accounts", json={"url": f"https://www.douyin.com/user/{SEC}?from_tab_name=main"})
    assert res.status_code == 200
    _wait_sync(client)
    accounts = client.get("/api/accounts").json()
    assert accounts[0]["nickname"] == "对标号"
    assert accounts[0]["median_likes"] == 110.0
    assert accounts[0]["breakout_count"] == 1
    outliers = client.get("/api/outliers").json()
    assert [o["video_id"] for o in outliers] == ["5"]
    assert outliers[0]["job"]["stage"] == "queued"

    client.app.state.worker.drain()
    # Every recent post is queued now, not just the breakout; the 5× one is among them.
    assert "https://www.douyin.com/video/5" in client.processed
    assert client.get("/api/outliers").json()[0]["has_report"] is True
    report = client.get("/api/reports/5").json()
    assert report["facts"]["multiple_of_median"] == 45.5
    assert client.get("/api/reports").json()[0]["video_id"] == "5"


def test_other_platforms_are_stored_pending_and_errors_are_chinese(client: TestClient) -> None:
    res = client.post("/api/accounts", json={"url": "https://x.com/karpathy"})
    assert res.json()["account"]["status"] == "pending_platform"
    dup = client.post("/api/accounts", json={"url": "https://x.com/karpathy"})
    assert dup.status_code == 400 and "已经在库里" in dup.json()["error"]
    bad = client.post("/api/accounts", json={"url": "https://example.com"})
    assert bad.status_code == 400 and "没认出平台" in bad.json()["error"]
    sync = client.post(f"/api/accounts/{res.json()['account']['id']}/sync")
    assert sync.status_code == 400 and "待接入" in sync.json()["error"]


def test_manual_job_validation_dedup_and_retry(client: TestClient) -> None:
    bad = client.post("/api/jobs", json={"url": "https://www.douyin.com/user/abc"})
    assert bad.status_code == 400 and "账号主页" in bad.json()["error"]
    first = client.post("/api/jobs", json={"url": "分享 https://www.douyin.com/video/42 看看"}).json()
    assert first["created"] is True
    again = client.post("/api/jobs", json={"url": "https://www.douyin.com/video/42"}).json()
    assert again["created"] is False

    def boom(url, **kwargs):
        raise RuntimeError("下载失败：网络超时")

    client.app.state.worker.process_fn = boom
    client.app.state.worker.drain()
    job = client.get("/api/jobs").json()[0]
    assert job["stage"] == "failed" and "网络超时" in job["error"]
    assert client.post(f"/api/jobs/{job['id']}/retry").json()["job"]["stage"] == "queued"


def test_self_account_shows_in_mine_and_cannot_be_deleted(client: TestClient) -> None:
    res = client.post("/api/accounts", json={"url": f"https://www.douyin.com/user/{SEC}", "is_self": True}).json()
    _wait_sync(client)
    mine = client.get("/api/mine").json()
    assert mine["account"]["nickname"] == "对标号"
    assert len(mine["videos"]) == 5
    assert client.get("/api/outliers").json() == []
    assert client.delete(f"/api/accounts/{res['account']['id']}").status_code == 400


def test_settings_validation(client: TestClient) -> None:
    assert client.put("/api/settings", json={"threshold": 8}).json()["threshold"] == 8.0
    assert client.put("/api/settings", json={"sync_delay_seconds": 0.2}).status_code == 400


def test_report_404_for_missing_and_legacy_reports(client: TestClient, tmp_path: Path) -> None:
    assert client.get("/api/reports/999").status_code == 404
    legacy = tmp_path / "data" / "reports" / "777"
    legacy.mkdir(parents=True)
    (legacy / "report.json").write_text(json.dumps({"schema_version": 1}))
    assert client.get("/api/reports/777").status_code == 404
    assert client.get("/api/reports/../../etc").status_code == 404


def test_reports_can_be_archived_and_restored(client: TestClient, tmp_path: Path) -> None:
    report_dir = tmp_path / "data" / "reports" / "321"
    report_dir.mkdir(parents=True)
    (report_dir / "report.json").write_text(json.dumps(_report("321")), encoding="utf-8")
    assert client.get("/api/reports").json()[0]["archived_at"] is None
    assert client.post("/api/reports/321/archive").json()["archived_at"]
    assert client.post("/api/reports/321/archive").status_code == 200
    assert client.get("/api/reports").json()[0]["archived_at"]
    assert client.get("/api/reports/321").status_code == 200
    assert client.delete("/api/reports/321/archive").json()["archived_at"] is None
    assert client.get("/api/reports").json()[0]["archived_at"] is None
    assert client.post("/api/reports/999/archive").status_code == 404


def test_multiple_own_accounts_and_vault_setting(client: TestClient, tmp_path: Path) -> None:
    first = client.post("/api/accounts", json={"url": f"https://www.douyin.com/user/{SEC}", "is_self": True}).json()
    _wait_sync(client)
    second = client.post("/api/accounts", json={"url": "https://www.douyin.com/user/MS4wLjABAAAAsecond", "is_self": True}).json()
    _wait_sync(client)
    state = client.get("/api/state").json()
    assert [a["id"] for a in state["my_accounts"]] == [first["account"]["id"], second["account"]["id"]]
    assert client.get(f"/api/mine?account_id={second['account']['id']}").json()["account"]["id"] == second["account"]["id"]
    assert client.get("/api/mine?account_id=99999").json()["account"]["id"] == first["account"]["id"]
    assert client.get("/api/accounts").json() == []

    # The fixture points the vault at tmp_path so no test can write into Park's real vault.
    assert state["vault"]["path"].endswith("vault-default")
    assert client.put("/api/settings", json={"obsidian_vault": "  "}).status_code == 400
    vault = tmp_path / "vault"
    vault.mkdir()
    client.put("/api/settings", json={"obsidian_vault": str(vault)})
    assert client.get("/api/state").json()["vault"]["ok"] is True
    client.put("/api/settings", json={"obsidian_vault": str(tmp_path / "missing")})
    assert "找不到 Obsidian 库" in client.get("/api/state").json()["vault"]["message"]


def test_vault_endpoints_are_read_only_and_sandboxed(client: TestClient, tmp_path: Path) -> None:
    from datetime import date as _date

    root = tmp_path / "vault"
    (root / "002_clippings").mkdir(parents=True)
    (root / "002_clippings" / "a.md").write_text("---\ntitle: 剪藏A\n---\n正文", encoding="utf-8")
    (root / "009_morning brief").mkdir()
    today = _date.today().isoformat()
    (root / "009_morning brief" / f"{today}.html").write_text("<script>alert(1)</script>", encoding="utf-8")
    (root / "_secrets").mkdir()
    (root / "_secrets" / "k.md").write_text("secret", encoding="utf-8")
    client.put("/api/settings", json={"obsidian_vault": str(root)})

    inbox = client.get("/api/vault/inbox").json()["items"]
    assert [i["title"] for i in inbox] == ["剪藏A"] and inbox[0]["triage"] is None
    assert client.put("/api/vault/triage", json={"path": "002_clippings/a.md", "status": "ignored"}).status_code == 200
    assert client.get("/api/vault/inbox").json()["items"][0]["triage"] == "ignored"
    assert client.put("/api/vault/triage", json={"path": "_secrets/k.md", "status": "topic"}).status_code == 404
    assert client.put("/api/vault/triage", json={"path": "002_clippings/a.md", "status": "bogus"}).status_code == 400

    assert client.get("/api/vault/note", params={"path": "002_clippings/a.md"}).json()["body"] == "正文"
    assert client.get("/api/vault/note", params={"path": "_secrets/k.md"}).status_code == 404
    assert client.get("/api/vault/raw", params={"path": f"009_morning brief/{today}.html"}).status_code == 404

    dailies = client.get("/api/today/dailies").json()["items"]
    ai = [d for d in dailies if d["key"] == "ai_daily"][0]
    assert [d["key"] for d in dailies] == ["ai_daily", "finance_daily", "kline_daily"] and ai["checked_at"] is None
    client.put("/api/today/checks", json={"day": today, "key": "ai_daily", "checked": True})
    assert [d for d in client.get("/api/today/dailies").json()["items"] if d["key"] == "ai_daily"][0]["checked_at"]
    assert client.put("/api/today/checks", json={"day": today, "key": "nope", "checked": True}).status_code == 400
    assert (root / "002_clippings" / "a.md").read_text(encoding="utf-8").endswith("正文")


def test_topics_from_triage_and_today_plan(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "vault2"
    (root / "003_park原始输出").mkdir(parents=True)
    (root / "003_park原始输出" / "灵感.md").write_text("# 不是我用AI\n想法", encoding="utf-8")
    client.put("/api/settings", json={"obsidian_vault": str(root)})

    res = client.put("/api/vault/triage", json={"path": "003_park原始输出/灵感.md", "status": "topic"}).json()
    topic = res["topic"]
    assert topic["title"] == "不是我用AI" and topic["note_paths"] == ["003_park原始输出/灵感.md"]
    again = client.put("/api/vault/triage", json={"path": "003_park原始输出/灵感.md", "status": "topic"}).json()
    assert again["topic"]["id"] == topic["id"] and len(client.get("/api/topics").json()) == 1

    manual = client.post("/api/topics", json={"title": "手动选题", "formats": "video"}).json()
    assert client.post("/api/topics", json={"title": " "}).status_code == 400
    assert client.patch(f"/api/topics/{manual['id']}", json={"status": "nope"}).status_code == 400
    published = client.patch(f"/api/topics/{manual['id']}", json={"status": "published", "published_url": "https://v.douyin.com/x"}).json()
    assert published["published_at"]
    client.patch(f"/api/topics/{manual['id']}", json={"archived": True})
    assert [t["id"] for t in client.get("/api/topics").json()] == [topic["id"]]

    client.put("/api/today/checks", json={"day": __import__("datetime").date.today().isoformat(), "key": "video_shot", "checked": True})
    assert client.get("/api/board").json()["streak"]["today_done"] is True


def test_skills_endpoint_lists_registry(client: TestClient) -> None:
    data = client.get("/api/skills").json()
    assert [s["key"] for s in data["stages"]] == ["collect", "plan", "make", "ship", "review"]
    assert any(s["name"] == "khazix-writer" and s["author"] == "数字生命卡兹克" for s in data["skills"])


def test_article_line_write_edit_download_handoff(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "vault3"
    (root / "003_park原始输出").mkdir(parents=True)
    (root / "003_park原始输出" / "a.md").write_text("# 预期落差\n人对 AI 预期太高", encoding="utf-8")
    client.put("/api/settings", json={"obsidian_vault": str(root)})
    topic = client.post("/api/topics", json={"title": "用了 AI 更累", "note_paths": ["003_park原始输出/a.md"], "formats": "article"}).json()

    assert client.get(f"/api/topics/{topic['id']}/article").status_code == 404
    assert client.post(f"/api/topics/{topic['id']}/handoff").status_code == 400
    assert client.post(f"/api/topics/{topic['id']}/write").json()["started"] is True
    done = _wait_topic(client, topic["id"])
    assert done["write_state"] is None and done["status"] == "drafting" and done["article_path"]
    draft = client.get(f"/api/topics/{topic['id']}/article").json()
    assert draft["markdown"].startswith("# 为什么") and draft["sources"][0]["path"] == "003_park原始输出/a.md"
    assert str(tmp_path / "drafts") in done["article_path"]
    assert (root / "003_park原始输出" / "a.md").read_text(encoding="utf-8").endswith("太高")

    edited = client.put(f"/api/topics/{topic['id']}/article", json={"markdown": "# 改过的标题\n正文"}).json()
    assert edited["markdown"] == "# 改过的标题\n正文\n"
    download = client.get(f"/api/topics/{topic['id']}/article.md")
    assert download.status_code == 200 and "attachment" in download.headers["content-disposition"]

    assert client.put("/api/settings", json={"yanxishi_admin_url": "http://insecure"}).status_code == 400
    client.put("/api/settings", json={"yanxishi_admin_url": "https://admin.example.com"})
    handed = client.post(f"/api/topics/{topic['id']}/handoff").json()
    assert handed["topic"]["status"] == "ready" and handed["admin_url"] == "https://admin.example.com"

    # 只做视频的选题点「写文章」：不再挡，改成文章 + 视频接着写。
    video_only = client.post("/api/topics", json={"title": "只拍视频", "formats": "video"}).json()
    assert client.post(f"/api/topics/{video_only['id']}/write").json()["started"] is True
    assert _wait_topic(client, video_only["id"])["formats"] == "both"
    broken = client.post("/api/topics", json={"title": "炸掉", "formats": "article"}).json()
    client.post(f"/api/topics/{broken['id']}/write")
    failed = _wait_topic(client, broken["id"])
    assert failed["write_state"] == "failed" and "boom" in failed["write_error"]


def test_outline_generate_edit_and_format_rules(client: TestClient) -> None:
    import time

    video = client.post("/api/topics", json={"title": "拍一条", "formats": "video"}).json()
    article_only = client.post("/api/topics", json={"title": "只写", "formats": "article"}).json()
    assert client.post(f"/api/topics/{article_only['id']}/outline").status_code == 400
    assert client.get(f"/api/topics/{video['id']}/outline").status_code == 404
    assert client.post(f"/api/topics/{video['id']}/outline").json()["started"] is True
    for _ in range(200):
        topic = [t for t in client.get("/api/topics").json() if t["id"] == video["id"]][0]
        if topic["outline_state"] != "running":
            break
        time.sleep(0.02)
    assert topic["outline_state"] is None and topic["outline_path"]
    assert client.get(f"/api/topics/{video['id']}/outline").json()["markdown"].startswith("# 标题")
    saved = client.put(f"/api/topics/{video['id']}/outline", json={"markdown": "# 改了"}).json()
    assert saved["markdown"] == "# 改了\n"
    # The three-point QA runs right after the outline is written and shows on the board card.
    for _ in range(200):
        qa = client.get(f"/api/topics/{video['id']}/qa").json()
        if qa["result"]:
            break
        time.sleep(0.02)
    assert qa["result"]["total"] == 12 and qa["result"]["verdict"] == "go" and qa["result"]["fix"] == "补一张截图"
    card = [c for c in client.get("/api/board").json()["cards"] if c["id"] == video["id"]][0]
    assert card["qa"] == {"total": 12, "verdict": "go"}
    assert client.post(f"/api/topics/{article_only['id']}/qa").status_code == 400
    assert client.post(f"/api/topics/{video['id']}/qa").json()["started"] in (True, False)


def test_video_project_link_create_inspect_and_files(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "videos"
    (root / "2026-01-01_old" / "delivery").mkdir(parents=True)
    (root / "2026-01-01_old" / "delivery" / "final-video.mp4").write_bytes(b"0")
    (root / "2026-01-01_old" / "page.html").write_text("<script>1</script>", encoding="utf-8")
    client.put("/api/settings", json={"video_projects_root": str(tmp_path / "missing")})
    assert "找不到" in client.get("/api/video-projects").json()["error"]
    client.put("/api/settings", json={"video_projects_root": str(root)})
    assert [p["name"] for p in client.get("/api/video-projects").json()["projects"]] == ["2026-01-01_old"]

    topic = client.post("/api/topics", json={"title": "拍这条", "formats": "video"}).json()
    assert client.get(f"/api/topics/{topic['id']}/video-project").status_code == 404
    assert client.put(f"/api/topics/{topic['id']}/video-project", json={"name": "nope"}).status_code == 404
    client.put(f"/api/topics/{topic['id']}/video-project", json={"name": "2026-01-01_old"})
    info = client.get(f"/api/topics/{topic['id']}/video-project").json()
    assert info["delivered"] is True and info["continue_command"].startswith("用 ask-park-video")
    listed = client.get("/api/video-projects").json()["projects"][0]
    assert listed["topic_id"] == topic["id"]

    page = client.get("/api/video-projects/2026-01-01_old/file", params={"path": "page.html"})
    assert "allow-scripts" in page.headers["content-security-policy"] and "allow-same-origin" not in page.headers["content-security-policy"]
    assert client.get("/api/video-projects/2026-01-01_old/file", params={"path": "../2026-01-01_old/../../x"}).status_code == 404

    other = client.post("/api/topics", json={"title": "新的一条", "formats": "video"}).json()
    created = client.post(f"/api/topics/{other['id']}/video-project").json()
    assert created["layout"] == "fresh" and (root / created["name"] / "README.md").is_file()
    assert client.post(f"/api/topics/{other['id']}/video-project").status_code == 400


def test_publish_link_performance_and_snapshots(client: TestClient) -> None:
    me = client.post("/api/accounts", json={"url": f"https://www.douyin.com/user/{SEC}", "is_self": True}).json()["account"]
    _wait_sync(client)
    topic = client.post("/api/topics", json={"title": "作品5", "formats": "video", "account_id": me["id"]}).json()
    data = client.get(f"/api/topics/{topic['id']}/publish").json()
    assert data["account"]["id"] == me["id"] and len(data["recent"]) == 5
    assert client.put(f"/api/topics/{topic['id']}/publish", json={"video_id": "nope"}).status_code == 400
    linked = client.put(f"/api/topics/{topic['id']}/publish", json={"video_id": "5"}).json()
    assert linked["status"] == "published" and linked["published_url"].endswith("/video/5")
    perf = client.get(f"/api/topics/{topic['id']}/publish").json()["video"]
    assert perf["likes"] == 5000 and perf["multiple"] and len(perf["series"]) == 1
    other = client.post("/api/topics", json={"title": "别的", "formats": "video"}).json()
    assert "5" not in [v["video_id"] for v in client.get(f"/api/topics/{other['id']}/publish").json()["recent"]]
    assert client.put(f"/api/topics/{topic['id']}/publish", json={"video_id": None}).json()["published_video_id"] is None


def test_copy_pack_and_platform_records(client: TestClient) -> None:
    topic = client.post("/api/topics", json={"title": "文案", "formats": "video"}).json()
    assert client.post(f"/api/topics/{topic['id']}/copy").status_code == 405  # no more AI copy generation
    assert client.get(f"/api/topics/{topic['id']}/copy").json()["copy"] is None
    shared = {"title": "一个标题", "body": "简介", "tags": ["#AI"]}
    edited = client.put(f"/api/topics/{topic['id']}/copy", json={"platforms": {k: shared for k in ("douyin", "channels", "bilibili", "youtube")}}).json()
    assert edited["platforms"]["douyin"]["tags"] == ["AI"] and edited["platforms"]["channels"]["title"] == "一个标题" and edited["checks"]["channels"] == []
    assert client.put(f"/api/topics/{topic['id']}/copy", json={"platforms": {"tiktok": {}}}).status_code == 400
    records = client.put(f"/api/topics/{topic['id']}/platforms", json={"platform": "xiaohongshu", "published": True, "url": "https://www.xiaohongshu.com/x"}).json()
    assert records["xiaohongshu"]["url"].startswith("https://")
    assert client.put(f"/api/topics/{topic['id']}/platforms", json={"platform": "x", "published": True, "url": "ftp://x"}).status_code == 400
    assert client.put(f"/api/topics/{topic['id']}/platforms", json={"platform": "xiaohongshu", "published": False}).json() == {}


def test_workflow_run_gate_and_approve(tmp_path: Path) -> None:
    import time
    from content_studio import web as web_module

    root = tmp_path / "videos"
    project = root / "p"
    (project / "subtitles").mkdir(parents=True)
    (project / "analysis").mkdir()
    presets = {"media": "m", "audio": "a", "caption_style": "c", "caption_layout": "l"}
    (project / "project.json").write_text(json.dumps({"presets": presets, "step_status": {"2": "pass", "3": "pass"}, "approvals": {}}), encoding="utf-8")
    cookie = tmp_path / "cookies.json"
    cookie.write_text(json.dumps({"sessionid": "x"}))
    cookie.chmod(0o600)
    app = web_module.create_app(store_path=tmp_path / "s.sqlite3", cookie_path=cookie, creator_db=None, data_dir=tmp_path / "d",
                                downloads_dir=tmp_path / "dl", client_factory=FakeClient, start_worker=False,
                                runs_dir=tmp_path / "runs", runner_command="sh -c 'sleep 0.3; cat' _")
    with TestClient(app, headers={"X-Content-Studio": "1"}) as c:
        c.put("/api/settings", json={"video_projects_root": str(root)})
        topic = c.post("/api/topics", json={"title": "t", "formats": "video"}).json()
        c.put(f"/api/topics/{topic['id']}/video-project", json={"name": "p"})
        started = c.post(f"/api/topics/{topic['id']}/video-project/run").json()
        assert started["run"]["state"] == "running"
        other = c.post("/api/topics", json={"title": "t2", "formats": "video"}).json()
        c.put(f"/api/topics/{other['id']}/video-project", json={"name": "p"})
        assert c.post(f"/api/topics/{other['id']}/video-project/run").status_code == 400
        for _ in range(100):
            run = c.get(f"/api/topics/{topic['id']}/video-project/run").json()["run"]
            if run["state"] != "running":
                break
            time.sleep(0.05)
        assert run["state"] == "done" and "ask-park-video" in run["log_tail"]

        for rel in ("subtitles/source.srt", "subtitles/transcript.sentences.json", "analysis/worktable.html"):
            (project / rel).write_text("x", encoding="utf-8")
        assert "H1" in c.post(f"/api/topics/{topic['id']}/video-project/run").json()["error"]
        assert c.post(f"/api/topics/{topic['id']}/video-project/approve", json={"gate": "H1"}).status_code == 400
        (project / "analysis" / "worktable.json").write_text(json.dumps({"hooks": [{"order": 1, "text": "h"}]}), encoding="utf-8")
        assert c.get(f"/api/topics/{topic['id']}/video-project/gate").json()["review"]["hooks"][0]["text"] == "h"
        assert c.post(f"/api/topics/{topic['id']}/video-project/approve", json={"gate": "H2"}).status_code == 400
        approved = c.post(f"/api/topics/{topic['id']}/video-project/approve", json={"gate": "H1"}).json()
        assert approved["project"]["current_step"] == 6 and approved["project"]["gate"] is None
    app.state.store.close()


def test_publish_requires_confirmation(tmp_path: Path) -> None:
    import sys
    import time
    from content_studio import web as web_module

    root = tmp_path / "videos"
    (root / "p" / "final").mkdir(parents=True)
    (root / "p" / "final" / "video.mp4").write_bytes(b"0" * 1024)
    marker = tmp_path / "published.txt"
    cred = tmp_path / "cookie.json"
    cred.write_text("{}")
    script = f"import json,pathlib,sys; pathlib.Path({str(marker)!r}).write_text(sys.argv[1]); print(json.dumps({{'ok': True, 'url': 'https://x/1'}}))"
    specs = {"channels": {"label": "视频号", "copy_key": "channels", "credential": cred, "login_hint": "",
                          "modes": {"draft": {"label": "草稿", "argv": [sys.executable, "-c", script, "{title}"]}}}}
    cookie = tmp_path / "cookies.json"
    cookie.write_text(json.dumps({"sessionid": "x"}))
    cookie.chmod(0o600)
    app = web_module.create_app(store_path=tmp_path / "s.sqlite3", cookie_path=cookie, creator_db=None, data_dir=tmp_path / "d",
                                downloads_dir=tmp_path / "dl", client_factory=FakeClient, start_worker=False, drafts_dir=tmp_path / "drafts",
                                publishers=specs)
    with TestClient(app, headers={"X-Content-Studio": "1"}) as c:
        c.put("/api/settings", json={"video_projects_root": str(root)})
        topic = c.post("/api/topics", json={"title": "t", "formats": "video"}).json()
        assert c.post(f"/api/topics/{topic['id']}/publish-jobs", json={"platform": "channels", "mode": "draft"}).status_code == 400
        c.put(f"/api/topics/{topic['id']}/video-project", json={"name": "p"})
        info = c.get(f"/api/topics/{topic['id']}/publish-jobs").json()
        assert info["video"]["mb"] >= 0 and info["platforms"]["channels"]["credential"]
        assert "标题" in c.post(f"/api/topics/{topic['id']}/publish-jobs", json={"platform": "channels", "mode": "draft"}).json()["error"]
        c.put(f"/api/topics/{topic['id']}/copy", json={"platforms": {"channels": {"title": "发布标题", "body": "b", "tags": []}}})
        job = c.post(f"/api/topics/{topic['id']}/publish-jobs", json={"platform": "channels", "mode": "draft"}).json()["job"]
        assert job["state"] == "awaiting_confirm" and job["payload"]["title"] == "发布标题"
        time.sleep(0.3)
        assert not marker.exists()
        c.post(f"/api/publish-jobs/{job['id']}/confirm")
        assert c.post(f"/api/publish-jobs/{job['id']}/confirm").status_code == 400
        for _ in range(100):
            current = c.get(f"/api/topics/{topic['id']}/publish-jobs").json()["jobs"][0]
            if current["state"] not in ("running",):
                break
            time.sleep(0.05)
        assert current["state"] == "done" and marker.read_text() == "发布标题"
        records = c.get(f"/api/topics/{topic['id']}/copy").json()["records"]
        assert records["channels"]["url"] == "https://x/1"
        again = c.post(f"/api/topics/{topic['id']}/publish-jobs", json={"platform": "channels", "mode": "draft"}).json()["job"]
        assert c.delete(f"/api/publish-jobs/{again['id']}").json()["job"]["state"] == "cancelled"
        assert c.post(f"/api/publish-jobs/{again['id']}/confirm").status_code == 400
    app.state.store.close()


def test_cross_site_writes_are_blocked(client: TestClient) -> None:
    from fastapi.testclient import TestClient as _TC

    bare = _TC(client.app)
    assert bare.post("/api/topics", json={"title": "x"}).status_code == 403
    assert bare.get("/api/topics").status_code == 200
    evil = client.post("/api/topics", json={"title": "x"}, headers={"Origin": "https://evil.example"})
    assert evil.status_code == 403
    assert client.post("/api/topics", json={"title": "ok"}, headers={"Origin": "http://testserver"}).status_code == 200


def test_unread_benchmark_reports_auto_archive_after_seven_days(client, tmp_path) -> None:
    import json as _json
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz

    base = tmp_path / "data" / "reports"
    for vid, age, is_self in (("old", 8, False), ("fresh", 2, False), ("mine", 30, True)):
        folder = base / vid
        folder.mkdir(parents=True)
        facts = {"creator_avg_view_second": 20} if is_self else {}
        folder.joinpath("report.json").write_text(_json.dumps({"schema_version": 2, "title": vid, "facts": facts,
                                                               "generated_at": (_dt.now(_tz.utc) - _td(days=age)).isoformat()}), encoding="utf-8")
    listed = {r["video_id"]: r for r in client.get("/api/reports").json()}
    assert listed["old"]["archived_at"] and listed["old"].get("auto_archived")
    assert listed["fresh"]["archived_at"] is None and listed["mine"]["archived_at"] is None


def test_opening_check_reads_project_subtitles(client: TestClient, tmp_path: Path) -> None:
    import time

    root = tmp_path / "videos"
    (root / "rec" / "subtitles").mkdir(parents=True)
    client.put("/api/settings", json={"video_projects_root": str(root)})
    topic = client.post("/api/topics", json={"title": "开头", "formats": "video"}).json()
    client.put(f"/api/topics/{topic['id']}/video-project", json={"name": "rec"})
    assert client.get(f"/api/topics/{topic['id']}/opening").json()["subtitles"] is None
    assert client.post(f"/api/topics/{topic['id']}/opening").status_code == 400
    (root / "rec" / "subtitles" / "source.srt").write_text("1\n00:00:00,500 --> 00:00:02,000\n开门见山说主线\n", encoding="utf-8")
    assert client.post(f"/api/topics/{topic['id']}/opening").json()["started"] is True
    for _ in range(200):
        data = client.get(f"/api/topics/{topic['id']}/opening").json()
        if data["state"] != "running":
            break
        time.sleep(0.02)
    assert data["result"]["passed"] is True and data["subtitles"]["label"] == "原始录音" and data["result"]["thesis"] == "开头"


def test_a_note_taken_into_the_pool_links_back_to_it_and_can_become_the_focus(client: TestClient, tmp_path: Path) -> None:
    """The pool is manual only now: nothing lands in it unless Park takes it from 进项."""
    root = tmp_path / "vault5"
    (root / "003_park原始输出").mkdir(parents=True)
    (root / "003_park原始输出" / "累.md").write_text("# 用了 AI 更累\n落差", encoding="utf-8")
    (root / "003_park原始输出" / "问卷.md").write_text("# 问卷\nFDE", encoding="utf-8")
    client.put("/api/settings", json={"obsidian_vault": str(root)})

    board = client.get("/api/board").json()
    assert [s["label"] for s in board["stages"]] == ["提纲", "录制", "剪辑", "待发"]
    assert board["pool"] == [] and board["focus"] is None and "recommend" not in board

    topic = client.put("/api/vault/triage", json={"path": "003_park原始输出/累.md", "status": "topic"}).json()["topic"]
    board = client.get("/api/board").json()
    assert [c["id"] for c in board["pool"]] == [topic["id"]]
    assert board["cards"][0]["stage"] == "outline" and board["cards"][0]["next"]["text"] == "写拍摄提纲"

    client.post(f"/api/topics/{topic['id']}/focus")
    board = client.get("/api/board").json()
    assert board["focus"]["id"] == topic["id"] and board["pool"] == []

    client.put("/api/vault/triage", json={"path": "003_park原始输出/问卷.md", "status": "shot"})
    inbox = {i["path"]: i for i in client.get("/api/vault/inbox?days=1").json()["items"]}
    assert inbox["003_park原始输出/累.md"]["used_by"]["topic_id"] == topic["id"]
    assert inbox["003_park原始输出/问卷.md"]["triage"] == "shot" and inbox["003_park原始输出/问卷.md"]["used_by"] is None

def test_anna_chat_per_scope_with_context_and_actions(client: TestClient) -> None:
    import time

    assert client.get("/api/anna", params={"scope": "nope"}).status_code == 400
    topic = client.post("/api/topics", json={"title": "问 Anna", "formats": "video"}).json()
    client.put(f"/api/topics/{topic['id']}/outline", json={"markdown": "# 提纲\n## 主线\nx\n## 前一分钟\n- 第一句：a\n- b\n- c\n## 后面讲什么\n- d\n- e\n- 结尾：f"})
    scope = f"work:{topic['id']}"
    empty = client.get("/api/anna", params={"scope": scope}).json()
    assert empty["messages"] == [] and empty["title"] == "问 Anna" and empty["label"] == "这条视频"
    assert client.post("/api/anna", json={"scope": scope, "message": "  "}).status_code == 400
    assert client.post("/api/anna", json={"scope": scope, "message": "能拍吗"}).json()["started"] is True
    for _ in range(200):
        chat = client.get("/api/anna", params={"scope": scope}).json()
        if not chat["busy"]:
            break
        time.sleep(0.02)
    assert [m["role"] for m in chat["messages"]] == ["park", "anna"]
    assert chat["messages"][1]["text"] == "看到提纲｜上一轮 None" and chat["messages"][1]["actions"] == [{"kind": "qa", "label": "按三点评分", "arg": ""}]
    client.post("/api/anna", json={"scope": scope, "message": "再问"})
    for _ in range(200):
        chat = client.get("/api/anna", params={"scope": scope}).json()
        if not chat["busy"]:
            break
        time.sleep(0.02)
    assert chat["messages"][-1]["text"] == "看到提纲｜上一轮 sess-1"  # the second turn resumes the session
    # One conversation across pages: the board sees the same four messages, each tagged with where it was said.
    board_view = client.get("/api/anna", params={"scope": "board"}).json()
    assert [m["role"] for m in board_view["messages"]] == ["park", "anna", "park", "anna"]
    assert board_view["label"] == "加工中" and board_view["messages"][0]["page"] == "《问 Anna》" and board_view["messages"][0]["scope"] == scope
    client.post("/api/anna", json={"scope": "board", "message": "炸掉"})
    for _ in range(200):
        board = client.get("/api/anna", params={"scope": "board"}).json()
        if not board["busy"]:
            break
        time.sleep(0.02)
    assert "boom" in board["error"] and [m["role"] for m in board["messages"]][-1] == "park"
    assert board["messages"][-1]["page"] == "加工中"
    assert client.delete("/api/anna", params={"scope": "board"}).json()["ok"] is True
    assert client.get("/api/anna", params={"scope": scope}).json()["messages"] == []


def test_anna_input_scope_reads_real_inbox_without_naive_aware_crash(client: TestClient, tmp_path: Path) -> None:
    # Regression: vault.inbox() compares file mtimes (naive) against `since`; the input-scope
    # context builder must pass a naive `since` too, or this raises "can't compare offset-naive
    # and offset-aware datetimes" the moment there is anything in the Clippings folder.
    import time

    vault = tmp_path / "vault"
    (vault / "002_clippings").mkdir(parents=True)
    (vault / "002_clippings" / "note.md").write_text("正文", encoding="utf-8")
    client.put("/api/settings", json={"obsidian_vault": str(vault)})
    assert client.post("/api/anna", json={"scope": "input", "message": "今天有什么"}).json()["started"] is True
    for _ in range(200):
        chat = client.get("/api/anna", params={"scope": "input"}).json()
        if not chat["busy"]:
            break
        time.sleep(0.02)
    assert chat["error"] is None
    assert chat["messages"][-1]["role"] == "anna"


def test_board_is_a_single_focus_pipeline(client: TestClient) -> None:
    a = client.post("/api/topics", json={"title": "A", "formats": "video"}).json()
    b = client.post("/api/topics", json={"title": "B", "formats": "video"}).json()
    c = client.post("/api/topics", json={"title": "C", "formats": "video"}).json()
    board = client.get("/api/board").json()
    assert board["focus"] is None and sorted(p["id"] for p in board["pool"]) == sorted([a["id"], b["id"], c["id"]])
    assert [m["key"] for m in board["milestones"]] == ["topic", "outline", "record", "edit", "ready", "shipped"]

    assert client.post(f"/api/topics/{a['id']}/focus").json()["previous"] is None
    swapped = client.post(f"/api/topics/{b['id']}/focus").json()
    assert swapped["previous"] == "A"  # only one video in production at a time
    board = client.get("/api/board").json()
    assert board["focus"]["id"] == b["id"] and sorted(p["id"] for p in board["pool"]) == sorted([a["id"], c["id"]])

    client.post(f"/api/topics/{c['id']}/snooze", json={"days": 14})
    board = client.get("/api/board").json()
    assert [p["id"] for p in board["pool"]] == [a["id"]] and [p["id"] for p in board["snoozed"]] == [c["id"]]
    client.delete(f"/api/topics/{c['id']}/snooze")
    assert sorted(p["id"] for p in client.get("/api/board").json()["pool"]) == sorted([a["id"], c["id"]])

    client.put(f"/api/topics/{b['id']}/outline", json={"markdown": "# 提纲\n- a\n- b\n- c\n- d"})
    assert client.get("/api/board").json()["focus"]["milestone"] == 2
    client.post(f"/api/topics/{b['id']}/stage", json={"stage": "outline"})
    focus = client.get("/api/board").json()["focus"]
    assert focus["milestone"] == 1 and focus["manual_stage"] == "outline"
    assert client.post(f"/api/topics/{b['id']}/stage", json={"stage": "record"}).status_code == 400
    client.post(f"/api/topics/{b['id']}/stage", json={"stage": None})
    assert client.get("/api/board").json()["focus"]["milestone"] == 2

    client.delete(f"/api/topics/{b['id']}/focus")
    board = client.get("/api/board").json()
    # 「对标这周爆了」不在看板上了——爆款属于进项，和别的进项一起按优先级排。
    assert board["focus"] is None and len(board["pool"]) == 3 and "attention" not in board


def test_reach_combines_douyin_snapshots_with_hand_typed_platforms(client: TestClient) -> None:
    from datetime import date

    today = date.today().isoformat()
    r = client.get("/api/reach").json()
    assert [p["key"] for p in r["platforms"]][:2] == ["douyin", "channels"] and len(r["days"]) == 14 and r["today"] == 0
    assert client.put("/api/reach", json={"day": today, "platform": "douyin", "views": 5}).status_code == 400
    assert client.put("/api/reach", json={"day": today, "platform": "x", "views": -1}).status_code == 400
    r = client.put("/api/reach", json={"day": today, "platform": "x", "views": 120}).json()
    assert r["today"] == 120 and r["days"][-1]["by_platform"] == {"x": 120}
    client.put("/api/reach", json={"day": today, "platform": "youtube", "views": 30})
    r = client.put("/api/reach", json={"day": today, "platform": "x", "views": None}).json()
    assert r["today"] == 30 and [p["today"] for p in r["platforms"] if p["key"] == "youtube"] == [30]
    client.put("/api/settings", json={"platform_accounts": {"x": {"on": True, "handle": "@park"}}})
    r = client.get("/api/reach").json()
    x = [p for p in r["platforms"] if p["key"] == "x"][0]
    assert x["on"] is True and x["handle"] == "@park"


def test_a_followed_accounts_new_posts_reach_the_input_page(client: TestClient) -> None:
    res = client.post("/api/accounts", json={"url": f"https://www.douyin.com/user/{SEC}"})
    assert res.status_code == 200
    _wait_sync(client)

    assert [a["nickname"] for a in client.get("/api/accounts").json()] == ["对标号"]
    feed = client.get("/api/followed/posts").json()
    assert [p["video_id"] for p in feed["posts"]] == ["5", "4", "3", "2", "1"]
    assert feed["account_count"] == 1
    # Windowed on publish date: nothing this account posted is older than a day.
    assert client.get("/api/followed/posts?days=0").json()["posts"] == []

    client.post("/api/jobs", json={"video_id": "5", "source": "对标"})
    client.app.state.worker.drain()
    assert client.get("/api/reports").json()[0]["video_id"] == "5"


def test_anna_can_propose_a_rule_and_park_writing_it_reaches_the_scorer(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from content_studio import qa, standard

    guide = tmp_path / "SKILL.md"
    guide.write_text("---\nname: park-content-qa\n---\n\n# 标准\n\n## 参考与致谢\n\n- 甲\n", encoding="utf-8")
    monkeypatch.setenv(qa.QA_GUIDE_ENV, str(guide))

    assert client.get("/api/standard").json()["rules"] == []
    posted = client.post("/api/standard", json={"text": "高客单要靠认知型深度内容", "source": "一勾工作号"})
    assert posted.status_code == 200
    rule = posted.json()["rule"]

    # The rule must land in what the scorer actually reads, not just in a list.
    assert "高客单要靠认知型深度内容" in qa.load_guide()
    assert guide.read_text(encoding="utf-8").rstrip().endswith("- 甲")

    assert client.post("/api/standard", json={"text": "高客单要靠认知型深度内容"}).status_code == 400
    assert client.delete(f"/api/standard/{rule['id']}").json()["rules"] == []
    assert client.delete(f"/api/standard/{rule['id']}").status_code == 400
    assert standard.BLOCK_START not in guide.read_text(encoding="utf-8")


def test_anna_on_the_report_page_is_given_the_open_teardown(client: TestClient) -> None:
    """Without the report in her context she would invent the lesson Park then writes into his standard."""
    client.post("/api/accounts", json={"url": f"https://www.douyin.com/user/{SEC}", "kind": "teacher"})
    _wait_sync(client)
    client.post("/api/jobs", json={"video_id": "5", "source": "老师"})
    client.app.state.worker.drain()

    import time

    assert client.post("/api/anna", json={"scope": "output", "message": "这条教了什么方法", "report_id": "5"}).json()["started"] is True
    for _ in range(200):
        chat = client.get("/api/anna", params={"scope": "output"}).json()
        if not chat["busy"]:
            break
        time.sleep(0.02)
    assert "看到报告" in chat["messages"][-1]["text"]


def test_a_followed_posts_transcript_becomes_a_note_park_can_read_and_take(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point: the text has to land in the vault, or 进项 can only show a title."""
    from content_studio import transcripts

    monkeypatch.setattr(transcripts, "FRESH_DAYS", 3650)  # the fixture's posts are from May
    root = tmp_path / "vault-bench"
    (root / "002_对标内容").mkdir(parents=True)
    client.put("/api/settings", json={"obsidian_vault": str(root)})
    client.post("/api/accounts", json={"url": f"https://www.douyin.com/user/{SEC}"})
    _wait_sync(client)

    client.post("/api/jobs", json={"video_id": "5", "source": "对标"})
    client.app.state.worker.drain()

    # With the window opened up the sync queues the whole catalogue, so every post lands.
    notes = {p.name: p.read_text(encoding="utf-8") for p in (root / "002_对标内容").glob("*.md")}
    assert len(notes) == 5
    body = next(b for b in notes.values() if "video/5" in b)
    assert "source: https://www.douyin.com/video/5" in body and "## 全文" in body and "author: 对标号" in body

    # 对标 notes are windowed on the author's publish date (the fixture posts are ~6 days old).
    item = next(i for i in client.get("/api/vault/inbox?days=7").json()["items"] if i["source"] == "benchmark")
    assert item["author"] == "对标号"  # 进项 shows the blogger, not the folder
    assert client.get("/api/vault/note", params={"path": item["path"]}).json()["body"]
    topic = client.put("/api/vault/triage", json={"path": item["path"], "status": "topic"}).json()["topic"]
    assert topic["note_paths"] == [item["path"]]


def test_a_video_older_than_the_fresh_window_never_becomes_a_note(client: TestClient, tmp_path: Path) -> None:
    """Park: 半年前的内容跟我现在的选题已经没有关系了。A first sync pulls the whole back
    catalogue, so an old video arriving today would sit in 进项 looking as new as today's."""
    root = tmp_path / "vault-stale"
    (root / "002_对标内容").mkdir(parents=True)
    client.put("/api/settings", json={"obsidian_vault": str(root)})
    client.post("/api/accounts", json={"url": f"https://www.douyin.com/user/{SEC}"})
    _wait_sync(client)

    # Age one video past the window on purpose, rather than relying on the fixture's dates.
    store = client.app.state.store
    old_day = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
    with store.tx() as conn:
        conn.execute("UPDATE videos SET published_at = ? WHERE video_id = '5'", (old_day,))
    for path in (tmp_path / "data" / "reports").glob("*/report.json"):
        path.unlink()
    (root / "002_对标内容").mkdir(exist_ok=True)
    for note in (root / "002_对标内容").glob("*.md"):
        note.unlink()

    client.post("/api/jobs", json={"video_id": "5", "source": "对标"})
    client.app.state.worker.drain()
    # The report is still there to read in 拆解报告; it just does not clutter 进项. Its recent
    # siblings do become notes, which is what makes the absence of this one meaningful.
    assert "5" in [r["video_id"] for r in client.get("/api/reports").json()]
    notes = [p.read_text(encoding="utf-8") for p in (root / "002_对标内容").glob("*.md")]
    assert notes and not any("douyin.com/video/5" in n for n in notes)


def test_announcements_are_dropped_after_transcription_not_before(tmp_path: Path) -> None:
    """Park's rule: filter on the content, not on likes — and the content only exists once
    the video has been transcribed."""
    from datetime import datetime, timezone

    from content_studio import transcripts

    assert transcripts.is_thin(title="凡尔赛一下，今晚8点见", text="正文" * 400, duration_seconds=300)
    assert transcripts.is_thin(title="正常选题", text="太短", duration_seconds=300)
    assert transcripts.is_thin(title="正常选题", text="正文" * 400, duration_seconds=12)
    assert transcripts.is_thin(title="高客单获客，必须做认知型深度内容", text="正文" * 400, duration_seconds=300) is None
    assert transcripts.is_stale("2026-06-27T10:00:00", now=datetime(2026, 9, 20, tzinfo=timezone.utc)) is True
    assert transcripts.is_stale("2026-09-18T10:00:00", now=datetime(2026, 9, 20, tzinfo=timezone.utc)) is False


def test_anna_is_given_the_backend_index_and_recent_events_not_just_one_page(client: TestClient, tmp_path: Path) -> None:
    """Park: 前端只是后端打包出来的。She must know a topic just moved and what else exists,
    without being handed all 83 teardown reports every turn."""
    root = tmp_path / "vault-ctx"
    (root / "003_park原始输出").mkdir(parents=True)
    (root / "003_park原始输出" / "n.md").write_text("# 一条笔记\n正文", encoding="utf-8")
    client.put("/api/settings", json={"obsidian_vault": str(root)})

    topic = client.put("/api/vault/triage", json={"path": "003_park原始输出/n.md", "status": "topic"}).json()["topic"]
    client.post(f"/api/topics/{topic['id']}/focus")

    client.post("/api/anna", json={"scope": "output", "message": "现在什么情况"})
    for _ in range(200):
        chat = client.get("/api/anna", params={"scope": "output"}).json()
        if not chat["busy"]:
            break
        time.sleep(0.02)
    seen = _fake_anna.last_user  # the fake records the prompt it was handed
    assert "工作台全局" in seen and "最近发生了什么" in seen
    assert "从进项进了选题池" in seen and "开始做《一条笔记》" in seen
    assert "进项近 7 天还没处理" in seen and "触达" in seen

    # index, not contents: once a report exists the block names it, never carries its body
    report_dir = tmp_path / "data" / "reports" / "555"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "report.json").write_text(json.dumps(_report("555")), encoding="utf-8")
    client.post("/api/anna", json={"scope": "board", "message": "再看一眼"})
    for _ in range(200):
        if not client.get("/api/anna", params={"scope": "board"}).json()["busy"]:
            break
        time.sleep(0.02)
    again = _fake_anna.last_user
    assert "拆解报告共 1 份" in again and "正文" not in again.split("## 最近发生了什么")[0]


def test_my_own_videos_get_their_own_library_with_no_thin_filter(client: TestClient, tmp_path: Path) -> None:
    """Park 的内容库：每一条都要在，包括短的和没爆的——分析自己的风格时，
    失败的那几条同样是证据。对标那边的「太薄就丢」不适用。"""
    from content_studio import transcripts

    root = tmp_path / "vault-mine"
    (root / transcripts.MINE_FOLDER).mkdir(parents=True)
    client.put("/api/settings", json={"obsidian_vault": str(root)})
    me = client.post("/api/accounts", json={"url": f"https://www.douyin.com/user/{SEC}", "is_self": True}).json()["account"]
    _wait_sync(client)

    # 把它做成「又老又短」——对标会被丢掉，自己的不该丢
    store = client.app.state.store
    old_day = (datetime.now(timezone.utc) - timedelta(days=300)).isoformat()
    with store.tx() as conn:
        conn.execute("UPDATE videos SET published_at = ?, title = '今晚8点见' WHERE video_id = '5'", (old_day,))

    client.post("/api/jobs", json={"video_id": "5", "source": "我的视频"})
    client.app.state.worker.drain()

    notes = list((root / transcripts.MINE_FOLDER).glob("*.md"))
    assert len(notes) == 1, "自己的视频必须落盘，不受时效和标题筛选影响"
    assert "douyin.com/video/5" in notes[0].read_text(encoding="utf-8")
    # 没有混进对标那个文件夹
    assert not (root / transcripts.FOLDER).exists() or not list((root / transcripts.FOLDER).glob("*.md"))


def test_an_image_post_still_gets_a_note_saying_it_is_one(tmp_path: Path) -> None:
    from content_studio import transcripts

    got = transcripts.render_image_post(
        video={"video_id": "9", "title": "重新思考公司架构。1. Company 不是先按人定义", "published_at": "2026-03-11T10:00:00", "likes": 88},
        account="Park的AI世界",
    )
    assert "format: 图文" in got and "没有口播内容" in got
    assert "重新思考公司架构" in got  # 文案全文保留，它就是这条的全部内容


def test_state_tells_a_fresh_install_that_there_is_no_profile_yet(client: TestClient) -> None:
    """页面顶部那条横幅读的就是这个：没 profile 时说「还没有」，不是报 5 个必填错吓人。"""
    setup = client.get("/api/state").json()["setup"]
    assert setup["present"] is False and setup["ok"] is False
    assert "profile.example.yaml" in setup["hint"]
    assert setup["missing_required"] == []


def test_profile_seeds_settings_and_accounts_without_overwriting_hand_edits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """profile 只填空不覆盖：设置页里手改过的值优先；账号只登记不同步。"""
    monkeypatch.setattr(web, "LEGACY_REPORT_DIRS", ())
    root = tmp_path / "vault"
    (root / "mine").mkdir(parents=True)
    profile = {
        "me": {"name": "某人", "douyin": f"https://www.douyin.com/user/{SEC}", "platforms": {"x": "someone", "bilibili": ""}},
        "ai": {"backend": "claude-cli"},
        "benchmarks": ["https://www.douyin.com/user/MS4wLjABAAAAbench1"],
        "vault": {"path": str(root), "folders": {"my_writing": "mine"}},
        "video_projects_root": str(tmp_path),
    }
    cookie = tmp_path / "c.json"; cookie.write_text("{}", encoding="utf-8")
    app = web.create_app(store_path=tmp_path / "s.sqlite3", cookie_path=cookie, creator_db=None,
                         data_dir=tmp_path / "d", downloads_dir=tmp_path / "dl",
                         client_factory=FakeClient, start_worker=False, profile=profile)
    store = app.state.store
    try:
        s = store.settings()
        assert s["obsidian_vault"] == str(root)
        assert s["video_projects_root"] == str(tmp_path)
        assert s["platform_accounts"] == {"x": {"on": True, "handle": "someone"}}   # 空的 bilibili 没登记
        assert store.self_account()["profile_url"].endswith(SEC)
        assert [a["profile_url"] for a in store.followed_accounts()] == ["https://www.douyin.com/user/MS4wLjABAAAAbench1"]
        assert all(a["last_synced_at"] is None for a in store.accounts())               # 只登记，没去抓
        # 手改过的值不被 profile 覆盖
        store.update_settings({"obsidian_vault": "/somewhere/else"})
        web._apply_profile(store, profile)
        assert store.settings()["obsidian_vault"] == "/somewhere/else"
        assert len(store.followed_accounts()) == 1                                    # 再跑一次不重复登记
    finally:
        store.close()


def test_a_dropped_topic_can_be_picked_up_again_from_the_inbox(client: TestClient, tmp_path: Path) -> None:
    """Park 标了「不做了」，又改主意。进项必须说实话，而且要能真的拿回来。

    之前这条路是断的：「入选题池」找到那个已归档的选题就不动了，接口返回成功，
    看板上却永远不出现——进项显示「已入选题池」，点进去是死路。
    """
    root = tmp_path / "vault"
    (root / "003_park原始输出").mkdir(parents=True)
    note = "003_park原始输出/想清楚了再拍.md"
    (root / note).write_text("---\ntitle: 想清楚了再拍\n---\n\n正文。\n", encoding="utf-8")
    client.app.state.store.update_settings({"obsidian_vault": str(root)})

    created = client.put("/api/vault/triage", json={"path": note, "status": "topic"}).json()
    topic_id = created["topic"]["id"]
    assert any(t["id"] == topic_id for t in client.get("/api/topics").json())

    # 不做了：笔记要重新变成可选的，不能留一个指向归档选题的死标记。
    client.patch(f"/api/topics/{topic_id}", json={"archived": True})
    row = next(i for i in client.get("/api/vault/inbox?days=30").json()["items"] if i["path"] == note)
    assert row["triage"] is None and row["used_by"]["dropped"] is True
    assert not any(t["id"] == topic_id for t in client.get("/api/topics").json())

    # 改主意：捡回来的是原来那条，不是新建一条——提纲、备注、拆解都还在上面。
    again = client.put("/api/vault/triage", json={"path": note, "status": "topic"}).json()
    assert again["topic"]["id"] == topic_id and again["topic"]["archived_at"] is None
    assert any(t["id"] == topic_id for t in client.get("/api/topics").json())
    back = next(i for i in client.get("/api/vault/inbox?days=30").json()["items"] if i["path"] == note)
    assert back["used_by"]["dropped"] is False



def test_the_h2_page_is_served_with_its_assets(client: TestClient, tmp_path: Path) -> None:
    """审批页和它引用的样片都要能按路径加载；视频要能拖进度。"""
    from urllib.parse import quote

    root = tmp_path / "videos"
    base = root / "2026-09-22_9月22日"
    (base / "analysis" / "h2.assets").mkdir(parents=True)
    (base / "analysis" / "h2.assets" / "V01.mp4").write_bytes(bytes(range(256)) * 40)
    (base / "analysis" / "h2-visual-review-final.html").write_text(
        f'<video src="file://{quote(str(base))}/analysis/h2.assets/V01.mp4"></video>', encoding="utf-8")
    client.put("/api/settings", json={"video_projects_root": str(root)})
    prefix = f"/api/video-projects/{quote(base.name)}/raw/"

    page = client.get(prefix + "analysis/h2-visual-review-final.html")
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    assert f'src="{prefix}analysis/h2.assets/V01.mp4"' in page.text
    assert page.headers["content-security-policy"].startswith("sandbox")
    assert page.headers["x-content-type-options"] == "nosniff"

    clip = client.get(prefix + "analysis/h2.assets/V01.mp4", headers={"Range": "bytes=0-99"})
    assert clip.status_code == 206 and len(clip.content) == 100

    assert client.get(prefix + "analysis/../../x.mp4").status_code == 404


def test_cover_dialog_defaults_and_make(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """封面弹窗：默认用发布文案的标题，给候选帧；出图写进 final/covers/。"""
    from content_studio import cover

    root = tmp_path / "videos"
    base = root / "2026-09-22_9月22日"
    (base / "final").mkdir(parents=True)
    client.put("/api/settings", json={"video_projects_root": str(root)})
    topic = client.post("/api/topics", json={"title": "选题名", "formats": "video"}).json()
    client.put(f"/api/topics/{topic['id']}/video-project", json={"name": base.name})
    assert client.get(f"/api/topics/{topic['id']}/cover").status_code == 400  # 没有成片

    (base / "final" / "9月22日-上传版.mp4").write_bytes(b"0" * 64)
    (base / "final" / "发布文案.md").write_text("## 推荐标题\n我终于理解了dbskill！\n", encoding="utf-8")

    def frames(video: Path, out: Path, count: int = 6) -> list[dict]:
        out.mkdir(parents=True, exist_ok=True)
        (out / "frame-0012.jpg").write_bytes(b"\xff\xd8")
        return [{"at": 12.0, "path": out / "frame-0012.jpg"}]

    seen = {}

    def make(b: Path, video: Path, **kw) -> dict:
        seen.update(kw, base=b, video=video.name)
        return {"横": "final/covers/9月22日-横封面.jpg", "竖": "final/covers/9月22日-竖封面.jpg"}

    monkeypatch.setattr(cover, "candidate_frames", frames)
    monkeypatch.setattr(cover, "make_covers", make)
    opts = client.get(f"/api/topics/{topic['id']}/cover").json()
    assert opts["title"] == "我终于理解了dbskill！" and "".join(opts["lines"]) == opts["title"]
    assert opts["emphasis"] == opts["lines"][-1]
    assert client.get(opts["frames"][0]["url"]).status_code == 200

    made = client.post(f"/api/topics/{topic['id']}/cover", json={"lines": ["我终于理解了", "dbskill！"], "emphasis": "dbskill！", "at": 12})
    assert made.json() == {"project": base.name, "covers": {"横": "final/covers/9月22日-横封面.jpg", "竖": "final/covers/9月22日-竖封面.jpg"}}
    assert seen["base"] == base and seen["video"] == "9月22日-上传版.mp4" and seen["at"] == 12.0

    monkeypatch.setattr(cover, "make_covers", lambda *a, **k: (_ for _ in ()).throw(cover.CoverError("强调短语必须是其中一整行")))
    bad = client.post(f"/api/topics/{topic['id']}/cover", json={"lines": ["a"], "emphasis": "b", "at": 1})
    assert bad.status_code == 400 and "一整行" in bad.json()["detail"]


def test_titles_endpoint_runs_in_background_and_reads_the_srt(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from content_studio import titles

    (tmp_path / "workflows" / titles.FRAMEWORK_FILE).write_text("# 标题\n暴论。", encoding="utf-8")
    root = tmp_path / "videos"
    base = root / "2026-09-22_9月22日"
    (base / "subtitles").mkdir(parents=True)
    (base / "subtitles" / "source.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\n我看了dontbesilent开源dbskill\n", encoding="utf-8")
    client.put("/api/settings", json={"video_projects_root": str(root)})
    topic = client.post("/api/topics", json={"title": "dbskill", "formats": "video"}).json()
    client.put(f"/api/topics/{topic['id']}/video-project", json={"name": base.name})
    assert client.get(f"/api/topics/{topic['id']}/titles").json() == {"running": False, "error": None, "result": None}

    seen: list[str] = []
    rows = ["我终于理解了dontbesilent为什么开源dbskill！｜借力点名｜依据：「开源dbskill」"] + [f"标题{'一二三四五六'[i]}｜悖论｜依据：「……」" for i in range(5)]
    reply = "<<<ARTICLE>>>\n## 点名的人\ndontbesilent\n\n## 候选\n" + "\n".join(f"{i}. {r}" for i, r in enumerate(rows, 1)) + "\n<<<END>>>"
    monkeypatch.setattr(titles, "cli_write", lambda prompt, **kw: seen.append(prompt) or reply)
    assert client.post(f"/api/topics/{topic['id']}/titles").json()["started"] is True
    for _ in range(50):
        state = client.get(f"/api/topics/{topic['id']}/titles").json()
        if not state["running"]:
            break
        time.sleep(0.05)
    assert state["error"] is None and len(state["result"]["candidates"]) == 6
    assert "我看了dontbesilent开源dbskill" in seen[0] and state["result"]["had_transcript"] is True


def test_phone_preview_endpoint(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """手机预览在后台压，结果从 final/手机预览/ 读出来，地址能直接播。"""
    from content_studio import phone

    root = tmp_path / "videos"
    base = root / "2026-09-22_9月22日"
    (base / "final").mkdir(parents=True)
    client.put("/api/settings", json={"video_projects_root": str(root)})
    topic = client.post("/api/topics", json={"title": "预览", "formats": "video"}).json()
    client.put(f"/api/topics/{topic['id']}/video-project", json={"name": base.name})
    assert client.post(f"/api/topics/{topic['id']}/phone-preview").status_code == 400  # 没有成片

    (base / "final" / "9月22日-抖音上传版.mp4").write_bytes(b"0" * 64)

    def fake(b: Path, video: Path, **kw) -> list:
        folder = b / "final" / phone.FOLDER
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "01_00-00至12-06.mp4").write_bytes(b"1" * 2048)
        return phone.existing(b)

    monkeypatch.setattr(phone, "make_preview", fake)
    assert client.post(f"/api/topics/{topic['id']}/phone-preview").json()["started"] is True
    for _ in range(50):
        state = client.get(f"/api/topics/{topic['id']}/phone-preview").json()
        if not state["running"]:
            break
        time.sleep(0.05)
    assert state["error"] is None and [p["name"] for p in state["parts"]] == ["01_00-00至12-06.mp4"]
    clip = client.get(state["parts"][0]["url"], headers={"Range": "bytes=0-99"})
    assert clip.status_code == 206 and len(clip.content) == 100


def test_radar_lists_every_video_of_one_account(client: TestClient) -> None:
    """对标雷达「全部作品」：不只爆款，每条带中位倍数和拆解状态。"""
    acct = client.post("/api/accounts", json={"url": f"https://www.douyin.com/user/{SEC}"}).json()["account"]
    _wait_sync(client)
    data = client.get(f"/api/accounts/{acct['id']}/videos").json()
    assert data["nickname"] == "对标号" and len(data["videos"]) == 5
    likes_to_multiple = {v["likes"]: v["multiple"] for v in data["videos"]}
    assert likes_to_multiple[110] == 1.0 and likes_to_multiple[5000] > 40  # 中位 110
    assert all("has_report" in v and "job" in v for v in data["videos"])
    started = client.post(f"/api/accounts/{acct['id']}/sync?deep=true").json()
    assert started["started"] is True and "往回翻" in started["message"]
    _wait_sync(client)
