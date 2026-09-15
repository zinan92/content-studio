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
