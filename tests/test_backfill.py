from __future__ import annotations

from content_studio import backfill as b


def test_split_douyin_title_drops_activity_tags_and_finds_the_headline() -> None:
    s = b.split_douyin_title("某某问题的答案比你想的简单 第二句是描述。 #认知 #青年创作者成长计划 #某某新星计划")
    assert s["title"] == "某某问题的答案比你想的简单" and s["body"] == "第二句是描述。"
    assert s["tags"] == ["认知"]
    assert b.split_douyin_title("how to win #认知")["title"] == "how to win"
    assert b.split_douyin_title("测试哪个coding agent最听话！ 后面是描述")["title"] == "测试哪个coding agent最听话！"


def test_link_prefers_published_video_id_then_a_similar_titled_topic_with_a_douyin_record() -> None:
    videos = [{"video_id": "v1", "title": "我终于想明白了一件事 #话题"}, {"video_id": "v2", "title": "完全不相关的内容"}, {"video_id": "v3", "title": "直接连上的"}]
    topics = [{"id": 1, "title": "内部选题名", "published_video_id": None}, {"id": 2, "title": "没发过抖音", "published_video_id": None},
              {"id": 3, "title": "x", "published_video_id": "v3"}]
    records = {1: {"douyin": {}}, 2: {}}
    links = b.link_topics(videos, topics, records, {1: "我终于想明白了一件事！"})
    assert links == {"v1": 1, "v3": 3}


def test_queue_counts_gaps_on_video_platforms_only_and_puts_best_first() -> None:
    videos = [{"video_id": "a", "title": "a", "likes": 10}, {"video_id": "b", "title": "b", "likes": 500}, {"video_id": "c", "title": "c", "likes": 900}]
    records = {7: {"douyin": {}, "channels": {}, "xiaohongshu": {}, "bilibili": {}, "youtube": {}}}
    rows = b.queue(videos, links={"c": 7}, records=records, marks={"b": {"youtube", "x"}}, median=100)
    assert [r["video_id"] for r in rows] == ["b", "a", "c"]  # c is complete, so last
    b_row = rows[0]
    assert b_row["done"]["youtube"] == "mark" and b_row["done"]["x"] == "mark" and "youtube" not in b_row["missing"]
    assert b_row["missing"] == ["channels", "xiaohongshu", "bilibili"] and b_row["multiple"] == 5.0
    assert rows[-1]["missing"] == []
