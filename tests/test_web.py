from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from content_studio import web
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
        items = [
            {"aweme_id": str(i), "desc": f"作品{i}", "create_time": 1780000000 + i, "duration": 90000,
             "statistics": {"digg_count": likes, "collect_count": 10, "share_count": 5, "comment_count": 1}}
            for i, likes in enumerate([100, 120, 90, 110, 5000], start=1)
        ]
        return {"items": items, "has_more": False}


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(web, "LEGACY_REPORT_DIRS", ())
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
    )
    app.state.worker.process_fn = process
    with TestClient(app) as test_client:
        test_client.processed = processed
        yield test_client
    app.state.store.close()


ARTICLE = "# 为什么用了 AI 反而更累\n\n" + "我发现一件事。" * 60


def _fake_writer(prompt: str) -> str:
    assert "作者是 Park" in prompt
    if "炸掉" in prompt:
        raise RuntimeError("boom")
    return f"好的\n<<<ARTICLE>>>\n{ARTICLE}\n<<<END>>>\n"


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
                    "effort": "低", "caution": "", "primary": True}],
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
        "generated_at": "2026-09-14T00:00:00+00:00",
        "content_id": video_id,
        "title": "报告标题",
        "author": "对标号",
        "source_url": f"https://www.douyin.com/video/{video_id}",
        "facts": {"likes": 5000, "multiple_of_median": 45.5},
        "transcript": {"duration_seconds": 60, "line_count": 2, "language": "zh"},
        "thesis": {"text": "主线", "evidence": []},
        "opening": None,
        "segments": [{"index": 0, "label": "钩子", "drift": False, "start": 0, "end": 60, "summary": "s", "reason": "r", "text": "t", "evidence": []}],
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
    assert client.processed == ["https://www.douyin.com/video/5"]
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

    assert state["vault"]["path"] == "~/park-hands"
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
    (root / "Clippings").mkdir(parents=True)
    (root / "Clippings" / "a.md").write_text("---\ntitle: 剪藏A\n---\n正文", encoding="utf-8")
    (root / "009_morning brief").mkdir()
    today = _date.today().isoformat()
    (root / "009_morning brief" / f"{today}.html").write_text("<script>alert(1)</script>", encoding="utf-8")
    (root / "_secrets").mkdir()
    (root / "_secrets" / "k.md").write_text("secret", encoding="utf-8")
    client.put("/api/settings", json={"obsidian_vault": str(root)})

    inbox = client.get("/api/vault/inbox").json()["items"]
    assert [i["title"] for i in inbox] == ["剪藏A"] and inbox[0]["triage"] is None
    assert client.put("/api/vault/triage", json={"path": "Clippings/a.md", "status": "ignored"}).status_code == 200
    assert client.get("/api/vault/inbox").json()["items"][0]["triage"] == "ignored"
    assert client.put("/api/vault/triage", json={"path": "_secrets/k.md", "status": "topic"}).status_code == 404
    assert client.put("/api/vault/triage", json={"path": "Clippings/a.md", "status": "bogus"}).status_code == 400

    assert client.get("/api/vault/note", params={"path": "Clippings/a.md"}).json()["body"] == "正文"
    assert client.get("/api/vault/note", params={"path": "_secrets/k.md"}).status_code == 404
    raw = client.get("/api/vault/raw", params={"path": f"009_morning brief/{today}.html"})
    assert raw.status_code == 200 and "sandbox" in raw.headers["content-security-policy"]

    dailies = client.get("/api/today/dailies").json()["items"]
    brief = [d for d in dailies if d["key"] == "morning_brief"][0]
    assert brief["path"] and brief["checked_at"] is None
    client.put("/api/today/checks", json={"day": today, "key": "morning_brief", "checked": True})
    assert [d for d in client.get("/api/today/dailies").json()["items"] if d["key"] == "morning_brief"][0]["checked_at"]
    assert client.put("/api/today/checks", json={"day": today, "key": "nope", "checked": True}).status_code == 400
    assert (root / "Clippings" / "a.md").read_text(encoding="utf-8").endswith("正文")


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

    plan = client.get("/api/today/plan").json()
    steps = {s["key"]: s for s in plan["steps"]}
    assert steps["triage"]["done"] is True and steps["pick"]["done"] is True
    client.put("/api/today/checks", json={"day": plan["day"], "key": "video_shot", "checked": True})
    assert {s["key"]: s for s in client.get("/api/today/plan").json()["steps"]}["video"]["done"] is True


def test_skills_endpoint_lists_registry(client: TestClient) -> None:
    data = client.get("/api/skills").json()
    assert [s["key"] for s in data["stages"]] == ["collect", "plan", "make", "ship", "review"]
    assert any(s["name"] == "khazix-writer" and s["author"] == "数字生命卡兹克" for s in data["skills"])


def test_hot_endpoint_without_vault_explains(client: TestClient, tmp_path: Path) -> None:
    client.put("/api/settings", json={"obsidian_vault": str(tmp_path / "missing")})
    data = client.get("/api/hot").json()
    assert data["douyin_search"]["available"] is False
    assert "找不到" in data["vault_error"] and data["benchmarks"]["items"] == []


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

    video_only = client.post("/api/topics", json={"title": "只拍视频", "formats": "video"}).json()
    assert client.post(f"/api/topics/{video_only['id']}/write").status_code == 400
    broken = client.post("/api/topics", json={"title": "炸掉", "formats": "article"}).json()
    client.post(f"/api/topics/{broken['id']}/write")
    failed = _wait_topic(client, broken["id"])
    assert failed["write_state"] == "failed" and "boom" in failed["write_error"]


def test_daily_briefing_generate_and_make_topic(client: TestClient, tmp_path: Path) -> None:
    import time
    from datetime import date as _date

    root = tmp_path / "vault4"
    today = _date.today()
    (root / "006_ai daily newsletter").mkdir(parents=True)
    (root / "006_ai daily newsletter" / f"{today.strftime('%y-%m-%d')}.md").write_text("- **A** | [Codex 新功能](https://x.com/1)", encoding="utf-8")
    (root / "003_park原始输出").mkdir()
    (root / "003_park原始输出" / "累.md").write_text("# 用了 AI 更累\n落差", encoding="utf-8")
    client.put("/api/settings", json={"obsidian_vault": str(root)})

    assert client.get("/api/briefing").json()["state"] == "missing"
    assert client.post("/api/briefing/generate", json={}).json()["started"] is True
    for _ in range(200):
        record = client.get("/api/briefing").json()
        if record["state"] != "running":
            break
        time.sleep(0.02)
    assert record["state"] == "done", record
    assert record["data"]["videos"][0]["primary"] is True and record["data"]["input_counts"]["notes"] == 1
    topic = client.post("/api/briefing/topic", json={"day": record["day"], "index": 0}).json()["topic"]
    assert topic["formats"] == "video" and topic["note_paths"] == ["003_park原始输出/累.md"] and "Hook：累的不是活" in topic["memo"]
    assert client.post("/api/briefing/topic", json={"day": record["day"], "index": 5}).status_code == 400
