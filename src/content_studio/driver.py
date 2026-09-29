"""「今天」：用 KPI 驱动 Park，一次只给一件事。

9/29 Park（读他 7/13 的《请主动让 AI 夺舍你的身体》）：「在这个闭环之内，由你来 drive 我……你来定义 KPI，
我一定要 comply。」「我只需要一件事，就是 just keep uploading，准时出摊。」

- KPI 分两类。**他的**：出摊（每天抖音发 1 条）、回私信（当天收到的当天回完）——做不到当天各减 1 分。
  **结果**：触达（7 天平均）、收到私信——每天会跳，不算他的分；没达标是 Claude 去改他每天的动作。
- 一次只给一件事。顺序写死（Park 拍板）：机器卡住 → 客户交付 → 出摊 → 回私信 → 收尾和杂事。
  今天已经出摊了，「明天出摊」排到回私信后面。
- 做完尽量由工作台自己看出来（有了链接、定了稿、填了数）；看不到的才要他点「做完了」。
- 跳过可以，但要写一句为什么，记进 driver_log，周复盘把重复的借口摆出来。
- 不推荐选题、不往选题池加东西：拍什么看他自己写的「接下来要拍的」清单；只有他点
  「我今天不知道拍什么」才建议。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

# (key, 名字)——顺序就是优先级
RUNGS = (
    ("blocker", "机器卡住了"),
    ("client", "客户交付"),
    ("ship", "出摊"),
    ("dm", "回私信"),
    ("tomorrow", "明天出摊"),
    ("wrap", "收尾和杂事"),
)
RUNG_ORDER = {k: i for i, (k, _) in enumerate(RUNGS)}
RUNG_LABEL = dict(RUNGS)
WINDOW = 7


def kpi_days(today: date, *, posted: set[str], dms: dict[str, dict[str, int]], started: str) -> list[dict[str, Any]]:
    """最近 7 天每天两项 KPI 的结果。today 还没过完：没做到不算减分（pending），做到了算过。

    出摊从有数据起就算（发没发抖音一直看得到）；私信从 KPI 开始那天（started）起算，
    之前没记过，不能倒扣。"""
    out = []
    for i in range(WINDOW - 1, -1, -1):
        d = today - timedelta(days=i)
        key = d.isoformat()
        is_today = i == 0
        ship = "ok" if key in posted else ("pending" if is_today else "miss")
        entry = dms.get(key)
        if key < started:
            dm = "n/a"
        elif entry is not None and entry["replied"] >= entry["received"]:
            dm = "ok"
        else:
            dm = "pending" if is_today else "miss"
        out.append({"day": key, "ship": ship, "dm": dm, "dm_entry": entry})
    return out


def demerits(days: list[dict[str, Any]]) -> int:
    return sum((d["ship"] == "miss") + (d["dm"] == "miss") for d in days)


def order(items: list[dict[str, Any]], *, skipped: set[str], done: set[str]) -> list[dict[str, Any]]:
    """去掉今天跳过的、手动点了做完的，按梯子排。同一格里保持加入的先后。"""
    live = [it for it in items if it["key"] not in skipped and it["key"] not in done]
    ranked = sorted(enumerate(live), key=lambda p: (RUNG_ORDER[p[1]["rung"]], p[0]))
    return [{**it, "rung_label": RUNG_LABEL[it["rung"]]} for _, it in ranked]


def item(rung: str, key: str, text: str, *, why: str = "", go: str | None = None, url: str | None = None,
         button: str = "去做", manual: bool = False, inputs: str | None = None) -> dict[str, Any]:
    """一件事。go 是工作台里的页面（#hash），url 是外面的网址；manual=True 要他自己点「做完了」。"""
    return {"rung": rung, "key": key, "text": text, "why": why, "go": go, "url": url,
            "button": button, "manual": manual, "inputs": inputs}
