from __future__ import annotations

from content_studio import board


def _topic(**kw):
    base = {"id": 1, "title": "t", "created_at": "2026-09-15", "outline_path": None, "status": "todo"}
    base.update(kw)
    return base


def test_stages_follow_the_shoot() -> None:
    assert board.stage_for(_topic(), None) == "outline"
    assert board.stage_for(_topic(outline_path="o.md"), None) == "record"
    assert board.stage_for(_topic(outline_path="o.md"), {"layout": "fresh", "current_step": None, "delivered": False}) == "record"
    assert board.stage_for(_topic(), {"layout": "v2.6", "current_step": 2, "delivered": False}) == "record"
    assert board.stage_for(_topic(), {"layout": "v2.6", "current_step": 5, "delivered": False}) == "edit"
    assert board.stage_for(_topic(), {"layout": "legacy", "current_step": None, "delivered": False}) == "edit"
    assert board.stage_for(_topic(), {"layout": "v2.6", "current_step": None, "delivered": True}) == "ready"


def test_next_action_puts_gates_and_failed_openings_on_park() -> None:
    gated = board.card(_topic(), {"layout": "v2.6", "current_step": 5, "delivered": False, "summary": "Step 5", "gate": {"key": "H1", "title": "选 Hook"}})
    assert gated["stage"] == "edit" and gated["next"] == {"text": "等你拍板：H1 选 Hook", "mine": True}
    ready = board.card(_topic(), {"layout": "v2.6", "current_step": None, "delivered": True, "gate": None}, {"passed": False, "stated_at": None})
    assert ready["stage"] == "ready" and "开头 15 秒没过" in ready["next"]["text"]
    assert board.card(_topic(outline_state="running"), None)["next"]["mine"] is False
    assert board.is_shipped(_topic(published_video_id="v")) and not board.is_shipped(_topic(status="published"))


def test_next_action_defers_to_a_failing_qa_verdict_instead_of_calling_it_ready() -> None:
    # Regression: the card used to say "提纲好了，可以录" even when the QA panel right
    # below it said "素材太薄" — Park had no way to tell which one to trust.
    topic = _topic(outline_path="o.md")
    plain = board.card(topic, None)
    assert plain["next"]["text"] == "提纲好了，可以录"
    thin = board.card(topic, None, None, {"total": 7, "verdict": "thin"})
    assert thin["next"] == {"text": "素材太薄，先补一处再录", "mine": True}
    patch = board.card(topic, None, None, {"total": 10, "verdict": "patch"})
    assert patch["next"]["text"] == "三点没过，先补再录"
    go = board.card(topic, None, None, {"total": 13, "verdict": "go"})
    assert go["next"]["text"] == "提纲好了，可以录"
    # A linked project overrides "可以录" regardless of stage; QA no longer applies once录制开始.
    recording = board.card(topic, {"layout": "fresh", "current_step": None, "delivered": False}, None, {"total": 7, "verdict": "thin"})
    assert recording["next"]["text"] == "录完把粗剪和字幕放进项目文件夹"
