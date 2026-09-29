"""打包页定稿：锁住那一版；上一步没定稿不能定；改过（包括依赖的上一步改过）定稿自动作废。"""
from __future__ import annotations

from pathlib import Path

import pytest

from content_studio import approvals


def _fps(tmp_path: Path, *, title: str = "标题", article: str | None = "正文", figs: bool = True) -> dict:
    cover = tmp_path / "竖封面.png"
    cover.write_bytes(b"c")
    fig = tmp_path / "01.png"
    fig.write_bytes(b"f")
    return approvals.fingerprints(copy={"douyin": {"title": title, "body": "d", "tags": []}}, covers=[cover],
                                  article=article, figs=[fig] if figs else [], wx={"has_layout": True, "generated_at": "t"},
                                  xhs={"images": ["01.png"], "generated_at": "t"})


def test_lock_in_step_by_step(tmp_path: Path) -> None:
    folder = tmp_path / "topic-1"
    fps = _fps(tmp_path)
    with pytest.raises(approvals.ApprovalError, match="上一步"):
        approvals.set_approval(folder, "cover", True, fps)
    approvals.set_approval(folder, "copy", True, fps)
    st = approvals.set_approval(folder, "cover", True, fps)
    assert st["cover"] == {**st["cover"], "approved": True, "valid": True}
    st = approvals.set_approval(folder, "cover", False, fps)  # 「改这一步」
    assert st["cover"]["approved"] is False


def test_changing_the_title_voids_the_cover_approval(tmp_path: Path) -> None:
    folder = tmp_path / "topic-1"
    fps = _fps(tmp_path)
    approvals.set_approval(folder, "copy", True, fps)
    approvals.set_approval(folder, "cover", True, fps)
    st = approvals.status(folder, _fps(tmp_path, title="换了标题"))
    assert st["copy"]["valid"] is False and st["cover"]["approved"] is True and st["cover"]["valid"] is False


def test_cannot_lock_a_step_that_is_not_made(tmp_path: Path) -> None:
    fps = _fps(tmp_path, article=None, figs=False)
    with pytest.raises(approvals.ApprovalError, match="还没做好"):
        approvals.set_approval(tmp_path / "t", "article", True, fps)
    assert fps["figs"] is None and fps["wx"] is None and "x" not in fps
