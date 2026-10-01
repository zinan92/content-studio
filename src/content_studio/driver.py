"""「今天」：用 KPI 驱动 Park，一次只给一件事。

9/29 Park（读他 7/13 的《请主动让 AI 夺舍你的身体》）：「在这个闭环之内，由你来 drive 我……你来定义 KPI，
我一定要 comply。」「我只需要一件事，就是 just keep uploading，准时出摊。」

- 9/30 Park：「每天最重要的事就是我要去读每日的日报，要不然日报存在的意义就没了。」读日报排第一（A），
  其余往后错：A 读日报、B 出摊、C 回私信、D X 互动。（E「整条补发」10/1 拿掉了，补发全走补发工作台。）
- KPI 分两类。**他的**：读日报（AI 日报、K 线日报，出了的都读完）、出摊（每天抖音发 1 条）、回私信（当天收到的当天回完）、X 互动（每天在别人的帖子下回
  20 条，9/29 定）——做不到当天各减 1 分。页面就是这 ABC 三件事（9/29 Park：「你只需要告诉我，我今天要做的 ABC
  三件事就好了……感觉今天这个页面太散了」）。
  **结果**：触达（7 天平均）、收到私信——每天会跳，不算他的分；没达标是 Claude 去改他每天的动作。
- 一次只给一件事。顺序写死（Park 拍板）：机器卡住 → 客户交付 → 出摊 → 回私信 → 收尾和杂事。
  今天已经出摊了，「明天出摊」排到回私信后面。
- 做完尽量由工作台自己看出来（有了链接、定了稿、填了数）；看不到的才要他点「做完了」。
- 跳过可以，但要写一句为什么，记进 driver_log，周复盘把重复的借口摆出来。
- 9/30 Park 定了阶段：现在是「追平」——把发送连贯起来，把过去没发的都发出去。
  **每天要么发一条新视频，要么补发 4 格旧内容**（一条内容发到一个平台算一格）：两种都算当天出摊，都不减分，
  连续天数都接着算。早上先问他今天发不发新的；不发，就在补发工作台自己挑格子（10/1 Park：「我要每天看大家的情绪和
  mood……自己想好今天最适合发什么」，原来是每天随机抽 4 格）。算分只看结果：发了新视频，或者当天挑够 4 格并且都发完。再加一条每周下限：一周至少 3 条新视频，
  少一条减 1 分（周过完才扣，不倒扣）。出关：旧内容清完，并且连续出摊 14 天（`stage`）。
  之后的阶段是客户（每周两三个）、成交，那时再改算分的项，现在不拿来打分。
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


def kpi_days(today: date, *, posted: set[str], dms: dict[str, dict[str, int]], started: str,
             x_replies: dict[str, int] | None = None, x_target: int = 0,
             reads: dict[str, bool] | None = None, read_started: str = "9999") -> list[dict[str, Any]]:
    """最近 7 天每天三项 KPI 的结果：ship 出摊、dm 回私信、xr X 回复。
    posted 是「出摊了的日子」：发了新视频的，加上补发当天的格子都发完的（调用的人并好）。
    today 还没过完：没做到不算减分（pending），做到了算过。

    出摊从有数据起就算（发没发抖音一直看得到）；私信和 X 回复从 KPI 开始那天（started）起算，
    之前没记过，不能倒扣。"""
    return kpi_range(today - timedelta(days=WINDOW - 1), today, today, posted=posted, dms=dms, started=started,
                     x_replies=x_replies, x_target=x_target, reads=reads, read_started=read_started)


def kpi_range(since: date, until: date, today: date, *, posted: set[str], dms: dict[str, dict[str, int]], started: str,
              x_replies: dict[str, int] | None = None, x_target: int = 0,
              reads: dict[str, bool] | None = None, read_started: str = "9999", ship_started: str = "") -> list[dict[str, Any]]:
    """since 到 until 每一天每项 KPI 的结果（周历用：哪一周都能算）。规则和 kpi_days 同一套：
    今天没做到是 pending，不减分；还没到的日子每一项都是 future。
    ship_started：出摊从哪天起算（周历传他第一次发抖音那天，翻到更早的周不倒扣）；不传就一直算。"""
    out = []
    for i in range((until - since).days + 1):
        d = since + timedelta(days=i)
        key = d.isoformat()
        entry, count = dms.get(key), (x_replies or {}).get(key)
        if d > today:
            out.append({"day": key, "rd": "future", "ship": "future", "dm": "future", "xr": "future", "dm_entry": None, "xr_count": None})
            continue
        is_today = d == today
        ship = "ok" if key in posted else ("pending" if is_today else "miss" if key >= ship_started else "n/a")
        if key < started:
            dm = xr = "n/a"
        else:
            dm = "ok" if entry is not None and entry["replied"] >= entry["received"] else ("pending" if is_today else "miss")
            xr = "ok" if x_target and count is not None and count >= x_target else ("pending" if is_today else "miss")
        # 读日报（9/30 起）：reads[day] = 那天出了的日报都读完了没有；那天一份都没出，不算
        if key < read_started or key not in (reads or {}):
            rd = "n/a"
        else:
            rd = "ok" if reads[key] else ("pending" if is_today else "miss")
        out.append({"day": key, "rd": rd, "ship": ship, "dm": dm, "xr": xr, "dm_entry": entry, "xr_count": count})
    return out


def plan_order(notes: list[dict[str, Any]], target_day: str) -> list[dict[str, Any]]:
    """下一条拍哪条：排在这一天的先，然后是排过但已经过期的（最早的先），然后是没排日子的（照清单顺序），
    排在以后的最后。哪条排哪天只由 Park 定，这里只决定先提哪条。"""
    def rank(note: dict[str, Any]) -> tuple[int, str]:
        day = note.get("planned_day")
        if not day:
            return (2, "")
        return (0, "") if day == target_day else (1, day) if day < target_day else (3, day)
    return [n for _, n in sorted(enumerate(notes), key=lambda p: (*rank(p[1]), p[0]))]


def now_item(t: dict[str, Any]) -> dict[str, Any] | None:
    """现在做这一件（Wendy 卡片最上面那一句）：照「今天」页的顺序，取第一件还没做完的。
    t 是 /api/today 的结果。不经过模型，他做完一件，下一次打开就是下一件。
    row 说的是这件事在页面上哪一行（first / rd / ship / dm / xr / wrap），卡片上的按钮带他过去。"""
    for it in t.get("first") or []:
        return {**it, "row": "first"}
    unread = [i["label"] for i in (t.get("rd") or {}).get("items") or [] if i.get("exists") and not i.get("read_at")]
    if unread:
        return {**item("kpi", "rd", f"读日报：{'、'.join(unread)}还没读", why="每天第一件事。日报不读，就白出了。"), "row": "rd"}
    ship = t.get("ship") or {}
    cell = (t.get("days") or [{}])[-1]
    out = t.get("out") or {}
    if cell.get("ship") != "ok":  # 今天还没发出去：新视频，或者补发
        cells = out.get("cells") or []
        left = [c for c in cells if not c["sent"]]
        need = int(out.get("need") or 4)
        if out.get("mode") is None and (cells or out.get("left")):
            return {**item("ship", "mode", "今天发不发新视频？", why=f"发，就去拍；不发，就在补发工作台挑 {need} 格旧内容现场发。两种都算今天出摊。", inputs="mode"), "row": "ship"}
        if out.get("mode") == "backfill":
            if out.get("running"):
                return {**item("ship", "bw", "补发工作台正在一格一格发", why=f"今天排了 {len(cells)} 格，已发 {len(cells) - len(left)} 格。", inputs="bw"), "row": "ship"}
            if left:
                hands = "、".join(dict.fromkeys(c["label"] for c in left))
                return {**item("ship", "bw", f"补发：还有 {len(left)} 格没发出去（{hands}）",
                               why="在补发工作台看每一格到哪一步了：B 站、YouTube、X 工作台自己发；视频号、小红书要你传，公众号要你群发，发完点「发了」。", inputs="bw"), "row": "ship"}
            if len(cells) < need:
                more = f"再挑 {need - len(cells)} 格" if cells else f"挑 {need} 格"
                return {**item("ship", "bw", f"打开补发工作台，{more}", why=f"看今天大家的情绪，自己挑发哪条、发到哪。挑够 {need} 格、都发出去，今天就算出摊。", inputs="bw"), "row": "ship"}
        if ship.get("next"):
            return {**ship["next"], "row": "ship"}
    if cell.get("dm") == "pending":
        entry = (t.get("dm") or {}).get("entry")
        left = f"还差 {entry['received'] - entry['replied']} 条没回" if entry else "回完把收到几条、回了几条填上"
        return {**item("kpi", "dm", f"回私信：{left}", why="当天收到的当天回完；不填数，明天按没做到算。"), "row": "dm"}
    if cell.get("xr") == "pending":
        xr = t.get("xr") or {}
        left = f"还差 {xr['target'] - xr['count']} 条" if xr.get("count") is not None else f"回 {xr.get('target')} 条，回完填数"
        return {**item("kpi", "xr", f"X 互动：{left}", why="在别人的帖子下面回一句有立场的话；不填数，明天按没做到算。"), "row": "xr"}
    if ship.get("done") and ship.get("next"):  # 今天发了新视频：剩下的平台，或者明天那条
        return {**ship["next"], "row": "ship"}
    for it in t.get("wrap") or []:
        return {**it, "row": "wrap"}
    return None


def stage(*, backlog: int, streak: dict[str, Any], streak_target: int) -> dict[str, Any]:
    """现在在哪个阶段（9/30 Park）。追平：把发送连贯起来，把过去没发的都发出去。backlog 是还没发的格数（一条内容一个平台算一格）。
    出关 = 旧内容清完，并且连续出摊到数。出关以后换哪个阶段、算分的项怎么改，是 Park 拍板的事，这里只报到没到。"""
    run = streak["days"] if streak.get("kind") == "ok" else 0
    return {"key": "catchup", "label": "追平", "backlog": backlog, "streak": run, "streak_target": streak_target,
            "done": backlog == 0 and run >= streak_target, "next": "客户：每周服务两三个客户"}


def week_start(day: date) -> date:
    """那一周的周一。"""
    return day - timedelta(days=day.weekday())


def ship_streak(today: date, posted: set[str]) -> dict[str, Any]:
    """现在在哪条线上：连续出摊几天，或者连续几天没出摊。今天发了算进去；今天还没发不算断，从昨天往回数。"""
    if not posted:
        return {"kind": "none", "days": 0}
    d = today if today.isoformat() in posted else today - timedelta(days=1)
    kind = "ok" if d.isoformat() in posted else "miss"
    first = date.fromisoformat(min(posted))
    n = 0
    while d >= first and (d.isoformat() in posted) == (kind == "ok"):
        n += 1
        d -= timedelta(days=1)
    return {"kind": kind, "days": n}


def demerits(days: list[dict[str, Any]]) -> int:
    return sum((d["rd"] == "miss") + (d["ship"] == "miss") + (d["dm"] == "miss") + (d["xr"] == "miss") for d in days)


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
