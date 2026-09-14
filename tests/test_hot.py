from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from content_studio import hot
from content_studio.store import StudioStore


AI_DAILY = """# AI Daily Newsletter — 2026-09-14
## 快讯
### 底层工具
- **Orange AI** | [免费、优雅的 Markdown 编辑器 ColaMD](https://x.com/oran_ge/status/1)  
  摘要
- **Nate Herk** | [Codex 新功能：goal 命令](https://www.youtube.com/watch?v=2)  
## 深读
### [深度复盘：用 Codex 一个月做到 2 万粉](https://x.com/ai/status/3)
"""

FINANCE = """## 过去24小时发生了什么
1. **所供报道援引 Sam Altman：OpenAI 今年不上市** | 中 确信度
2. **TRM 研究指出，x402 结算多数并非来自 AI Agents** | 中 确信度
"""


def _vault(tmp_path: Path) -> Path:
    (tmp_path / "006_ai daily newsletter").mkdir(parents=True)
    (tmp_path / "006_ai daily newsletter" / "26-09-14.md").write_text(AI_DAILY, encoding="utf-8")
    (tmp_path / "007_finance daily newsletter").mkdir()
    (tmp_path / "007_finance daily newsletter" / "2026-09-14-finance-daily-newsletter.md").write_text(FINANCE, encoding="utf-8")
    (tmp_path / "Clippings").mkdir()
    (tmp_path / "Clippings" / "a.md").write_text("---\ntitle: 99% 的人用错了 Codex 的「goal 命令」\ncreated: 2026-09-13\n---\n正文", encoding="utf-8")
    (tmp_path / "Clippings" / "b.md").write_text("---\ntitle: OpenAI 发布会速看\ncreated: 2026-09-13\n---\n正文", encoding="utf-8")
    return tmp_path


def test_headlines_parse_ai_and_finance_dailies(tmp_path: Path) -> None:
    items = hot.daily_headlines(str(_vault(tmp_path)), date(2026, 9, 14))
    titles = [i["title"] for i in items]
    assert len(titles) == len(set(titles))
    assert titles[:3] == ["免费、优雅的 Markdown 编辑器 ColaMD", "Codex 新功能：goal 命令", "深度复盘：用 Codex 一个月做到 2 万粉"]
    assert items[0]["source"] == "Orange AI" and items[0]["url"].startswith("https://x.com/")
    assert "所供报道援引 Sam Altman：OpenAI 今年不上市" in titles
    assert all(i["daily"] in ("AI 日报", "财经日报") for i in items)


def test_frequent_topics_count_distinct_documents(tmp_path: Path) -> None:
    topics = {t["term"]: t for t in hot.frequent_topics(str(_vault(tmp_path)), today=date(2026, 9, 14))}
    assert topics["Codex"]["count"] == 3
    assert topics["OpenAI"]["count"] == 2
    assert "AI" not in topics and "com" not in topics


def test_benchmark_breakouts_split_recent_and_week(tmp_path: Path) -> None:
    store = StudioStore(tmp_path / "s.sqlite3")
    account = store.add_account(platform="抖音", profile_url="https://www.douyin.com/user/x", external_id="x", status="ok")
    now = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)
    def iso(delta):
        return (now - delta).isoformat()
    base = dict(platform="抖音", duration_seconds=60, is_top=0, is_image_post=0, comments=0, shares=0, collects=0, views=None)
    videos = [dict(base, video_id=str(i), title=f"v{i}", published_at=iso(timedelta(days=20 + i)), likes=100) for i in range(5)]
    videos.append(dict(base, video_id="hot1", title="hot", published_at=iso(timedelta(hours=10)), likes=5000))
    videos.append(dict(base, video_id="hot2", title="old", published_at=iso(timedelta(days=4)), likes=3000))
    store.upsert_videos(account["id"], videos)
    result = hot.benchmark_breakouts(store, threshold=5, now=now)
    assert [v["video_id"] for v in result["items"]] == ["hot1"]
    assert result["fallback"] == []
    assert [v["video_id"] for v in hot.benchmark_breakouts(store, threshold=5, now=now + timedelta(days=2))["fallback"]] == ["hot1", "hot2"]
    store.close()
