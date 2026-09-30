"""Wendy：Park 的老板，在「今天」页最上面的那张卡片里。

9/30 Park：「在这个页面放一个 Wendy 给我的 message……我每次只要点开今天的页面，就知道我当下需要做什么。
如果很长时间她没有得到我的反馈，她会给我发一个 notification 在微信。」

卡片上有三样：
- **现在做这一件**：driver.now_item，从「今天」的数据直接算，不经过模型，什么时候打开都是当下该做的。
- **她说的话**：早上、晚上、催他的那几条是微信那边（Hermes 的定时任务）写的，这里只把它们读出来显示，
  字和微信里一模一样；他在卡片里回她，工作台自己跑一轮模型答他。
- **回复框**：和 Anna 一样，模型关掉所有工具，只说话。工作台挂在带密码的外网入口后面，
  一个能跑命令的对话框等于给拿到密码的人一个 shell，所以回复绝不转给带终端的 agent 去答。

她给他看的数字只有一份来源：brief()。微信那边的脚本也是来这里取同一段，两边说的分数对得上。
催不催由 nudge_due() 定（纯函数）；微信那边每半小时来问一次，不到时候就不叫醒模型。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import re
from typing import Any, Callable

from .anna import _strip_frontmatter, cli_turn

ROLE_ENV = "CONTENT_STUDIO_WENDY_ROLE"
HERMES_ENV = "CONTENT_STUDIO_HERMES_HOME"
# 仓库自带的是通用版；profile.yaml 的 wendy.role 指到你自己的 Markdown 才是你的 Wendy。
DEFAULT_ROLE = Path(__file__).resolve().parent / "examples" / "wendy" / "Wendy.md"
DEFAULT_HERMES = Path("~/.hermes")
JOB_PREFIX = "wendy-"  # Hermes 里她的定时任务都叫 wendy-xxx
JOB_LABEL = {"wendy-morning": "早上", "wendy-evening": "晚上", "wendy-weekly": "周日", "wendy-nudge": "来催你"}
KPI = (("rd", "读日报"), ("ship", "出摊"), ("dm", "回私信"), ("xr", "X 互动"))
PLATFORM = {"douyin": "抖音", "x": "X", "xiaohongshu": "小红书", "bilibili": "B 站", "youtube": "YouTube",
            "channels": "视频号", "wechat_mp": "公众号", "miniprogram": "小程序"}
WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

# 催他的规则（9/30 Park 点头的三个数）
NUDGE_QUIET_HOURS = 3   # 这么久没动静才催
NUDGE_FROM, NUDGE_UNTIL = 10, 22  # 只在这个钟点之间
NUDGE_MAX_PER_DAY = 3

TurnFn = Callable[[str, str, str | None], dict]


class WendyError(RuntimeError):
    """这一轮没答上来；原因显示在卡片里。"""


def load_role() -> dict[str, Any]:
    path = Path(os.environ.get(ROLE_ENV) or DEFAULT_ROLE).expanduser()
    try:
        return {"text": _strip_frontmatter(path.read_text(encoding="utf-8")), "path": str(path)}
    except OSError:
        return {"text": "# Wendy\n\n你是 Park 的老板。计划定了以后，你盯着他做，你验收。不讨好，没做到就说没做到。", "path": str(path)}


DESK_RULES = """## 你在内容工作台的「今天」页

Park 打开「今天」页，最上面就是你。他在这里回你的话，你在这里答他。每一轮消息里的 <工作台> 块是此刻的真实数据。

- 全中文，短句，像一个老板在说话。最多五六行。不用 Markdown 的表格、标题、加粗。
- 只用 <工作台> 块里的数字和事项，一个数字都不许编或推算；块里没有的就说「工作台里没有这个数」。
- 今天做什么、按什么顺序，以 <工作台> 里的为准，不重排、不加新任务、不推荐选题。哪天拍哪条是 Park 自己在周历里排的，你只转述和催他排。
- 他给理由，你判断这是改方向还是不想做：是不想做，就点破，要他说今天几点做；是真的做不了，就要一个具体的新时间。不接受「明天补」。
- 他说做完了而 <工作台> 里还没显示：让他去那一行填数或点一下，工作台认了才算。
- 你只动嘴。你不能替他点按钮、填数、发布。
- 内容好不好（选题、提纲、这条为什么没流量）不归你，让他问右边的 Anna。交易不归你。"""


def system_prompt() -> str:
    return f"{load_role()['text']}\n\n---\n\n{DESK_RULES}"


# -- 她给他看的数字：只有这一份 ---------------------------------------------------------

def _status(day: dict[str, Any], key: str) -> str:
    """一项 KPI 这一天的结果，没填数的单独说清楚。"""
    state = day.get(key)
    if state == "ok":
        if key == "xr" and day.get("xr_count") is not None:
            return f"做到（{day['xr_count']} 条）"
        if key == "dm" and day.get("dm_entry"):
            return f"做到（收到 {day['dm_entry']['received']}，回了 {day['dm_entry']['replied']}）"
        return "做到"
    if state == "n/a":
        return "那天还不算分"
    if state == "pending":
        if key == "xr" and day.get("xr_count") is not None:
            return f"还没做完（已 {day['xr_count']} 条）"
        return "还没做"
    if key == "dm" and day.get("dm_entry") is None:
        return "没填数，按规则算没做到"
    if key == "xr" and day.get("xr_count") is None:
        return "没填数，按规则算没做到"
    return "没做到"


def _reach_line(row: dict[str, Any] | None) -> str:
    if not row:
        return "没有数据"
    parts = [f"{PLATFORM.get(k, k)} {v:,}" for k, v in sorted(row["by_platform"].items(), key=lambda kv: -kv[1]) if v]
    return f"{row['total']:,}（{'，'.join(parts) or '各平台都是 0'}）"


def _plan_lines(week: dict[str, Any], today: str) -> list[str]:
    """这一周他自己排的：今天拍哪条、还有什么事；后面哪几天还没排。只转述，不替他排。"""
    out, empty = ["[这一周他自己排的计划]"], []
    for i, d in enumerate(week["days"]):
        if d["day"] < today:
            late = [n["text"] for n in d["planned"] if not n["done"]]
            if late:
                out.append(f"{WEEKDAYS[i]} {d['day'][5:]}：排了没拍——{'；'.join(late)}")
            continue
        label = "今天" if d["day"] == today else WEEKDAYS[i]
        shoot = [n["text"] for n in d["planned"] if not n["done"]]
        todo = [it["text"] for it in d["items"] if not it["done"]]
        if shoot or todo:
            out.append(f"{label} {d['day'][5:]}：" + "；".join([f"拍「{x}」" for x in shoot] + [f"别的事（不算分）：{x}" for x in todo]))
        if not shoot and d["ship"] != "ok":
            empty.append(label)
    if empty:
        out.append("还没排拍哪条的日子：" + "、".join(empty))
    return out


def brief(today: dict[str, Any], reach: dict[str, Any], now_item: dict[str, Any] | None) -> str:
    """此刻的账：现在该做哪一件、他在哪条线上、昨天的分、触达、今天的清单、这一周的计划。
    today 是 /api/today 的结果，reach 是 /api/reach 的结果。"""
    tkey = today["day"]
    yesterday = (date.fromisoformat(tkey) - timedelta(days=1)).isoformat()
    week, streak = today["week"], today["streak"]
    cells = {d["day"]: d for d in [*today["days"], *week["days"]]}
    by_day = {d["day"]: d for d in reach.get("days") or []}
    out = [f"今天是 {tkey}。以下数字全部来自内容工作台，读取于现在。", "",
           "[现在做这一件] " + (f"{now_item['text']}" + (f"（{now_item['why']}）" if now_item.get("why") else "") if now_item else "今天算分的事都做完了，没有在等他的事。")]

    line = []
    if streak.get("days"):
        line.append(f"连续出摊 {streak['days']} 天" if streak["kind"] == "ok" else f"连续 {streak['days']} 天没出摊")
    line.append(f"这一周（周一起）出摊 {week['shipped']}/{week['ship_days']} 天，减 {week['demerits']} 分")
    out.append("[现在在哪条线上] " + "；".join(line))

    y = cells.get(yesterday)
    if y:
        scored = [(name, _status(y, key)) for key, name in KPI if y.get(key) not in ("n/a", "future")]
        done = sum(1 for _, s in scored if s.startswith("做到"))
        out += ["", f"[昨天 {yesterday} 的分] {done}/{len(scored)} 项做到，减 {len(scored) - done} 分", *[f"- {name}：{s}" for name, s in scored]]
    skips = today.get("skipped") or []
    if skips:
        out.append("今天写过的跳过理由：" + "；".join(f"{s.get('key')}——{s.get('reason')}" for s in skips))

    out += ["", *_plan_lines(week, tkey)]

    r = today.get("reach") or {}
    out += ["", f"[触达] 昨天 {_reach_line(by_day.get(yesterday))}", f"今天到现在 {_reach_line(by_day.get(tkey))}",
            f"7 天平均 {r.get('avg7') or 0:,}；工作台里定的目标是每天 {r.get('target') or 0:,}（到 {r.get('by')}）"]

    out += ["", "[今天要做的，顺序照工作台「今天」页]"]
    n = 0
    for item in today.get("first") or []:
        n += 1
        out.append(f"{n}. 先处理：{item['text']}" + (f"（{item['why']}）" if item.get("why") else ""))
    d = cells[tkey]
    reads = (today.get("rd") or {}).get("items") or []
    if reads:
        unread = [i["label"] for i in reads if i.get("exists") and not i.get("read_at")]
        n += 1
        out.append(f"{n}. 读日报：" + ("已读完" if not unread else "还没读 " + "、".join(unread)))
    ship = today.get("ship") or {}
    n += 1
    if ship.get("done"):
        out.append(f"{n}. 出摊：今天已经发了")
    else:
        nxt = (ship.get("next") or {}).get("text")
        notes = [x["text"] for x in ship.get("notes") or [] if not x.get("done_at")][:3]
        out.append(f"{n}. 出摊：今天还没发抖音" + (f"。工作台排的下一步：{nxt}" if nxt else "")
                   + (f"。「接下来要拍的」清单：{'；'.join(notes)}" if notes else ""))
    n += 1
    out.append(f"{n}. 回私信：{_status(d, 'dm')}")
    n += 1
    out.append(f"{n}. X 互动：{_status(d, 'xr')}，目标 {(today.get('xr') or {}).get('target')} 条")
    for item in today.get("wrap") or []:
        n += 1
        out.append(f"{n}. 收尾：{item['text']}")
    ready = (today.get("backfill") or {}).get("ready") or []
    if ready and not ship.get("done"):
        out.append(f"补发（不算分，今天不出摊时保触达用）：打好包的有 {len(ready)} 条，排最前的是《{ready[0]['title'][:24]}》")
    return "\n".join(out)


def review_brief(review: dict[str, Any]) -> str:
    """周日用：这一周的复盘（按 Anna 的标准写的）和「下周只改一件事」。"""
    data = review.get("data") or {}
    if review.get("state") != "done" or not data:
        return f"[周复盘] 这一周（{review.get('week')}）的周复盘还没生成（状态：{review.get('state')}）。要 Park 在工作台「已发出」页点一下生成。"
    out = [f"[周复盘 {review.get('week')}，{data.get('since')} 到 {data.get('until')}，生成于 {data.get('generated_at')}]", f"一句话：{data.get('summary')}"]
    out += [f"问题：{p['text']}" for p in data.get("problems") or []]
    out += [f"做对的：{w['text']}" for w in data.get("wins") or []]
    out += [f"下周只改一件事：{x}" for x in data.get("next_week") or []]
    return "\n".join(out)


def thread_brief(messages: list[dict[str, Any]], limit: int = 8) -> str:
    """卡片里最近说过的话：微信那边的她看了，才知道他在工作台回过什么。"""
    if not messages:
        return "[工作台卡片里的对话] 还没有。"
    rows = [f"- {m['at'][5:16].replace('T', ' ')} {'Park' if m['who'] == 'park' else 'Wendy'}：{' '.join(m['text'].split())[:300]}" for m in messages[-limit:]]
    return "[工作台卡片里最近的对话，旧的在上]\n" + "\n".join(rows)


# -- 微信那边她说过的话：只读出来显示 ---------------------------------------------------

_STAMP = re.compile(r"(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})-(\d{2})\.md$")


def hermes_messages(home: Path | None = None, *, days: int = 3, now: datetime | None = None) -> list[dict[str, Any]]:
    """Hermes 定时任务（wendy-*）每次跑完留下的那段话。读不到就是空，不报错：卡片照样有「现在做这一件」。"""
    home = (home or Path(os.environ.get(HERMES_ENV) or DEFAULT_HERMES)).expanduser()
    since = (now or datetime.now()) - timedelta(days=days)
    try:
        jobs = json.loads((home / "cron" / "jobs.json").read_text(encoding="utf-8")).get("jobs") or []
    except (OSError, ValueError, AttributeError):
        return []
    out: list[dict[str, Any]] = []
    for job in jobs:
        name = str(job.get("name") or "")
        folder = home / "cron" / "output" / str(job.get("id") or "")
        if not name.startswith(JOB_PREFIX) or not folder.is_dir():
            continue
        for path in folder.iterdir():
            m = _STAMP.search(path.name)
            if not m:
                continue
            at = datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}:{m.group(3)}:{m.group(4)}")
            if at < since:
                continue
            try:
                body = path.read_text(encoding="utf-8")
            except OSError:
                continue
            text = body.split("## Response", 1)[1].strip() if "## Response" in body else ""
            if not text or "[SILENT]" in text.upper():
                continue
            out.append({"who": "wendy", "source": name, "label": JOB_LABEL.get(name, "微信"), "text": text,
                        "at": at.astimezone().isoformat(timespec="seconds"), "ref": f"hermes:{job.get('id')}:{path.name}"})
    return sorted(out, key=lambda x: x["at"])


# -- 催不催 -------------------------------------------------------------------------------

def nudge_due(now: datetime, *, pending: list[str], last_activity: datetime | None, last_contact: datetime | None,
              nudges_today: int) -> dict[str, Any]:
    """要不要去微信催他。算分的事还没做完，而他这么久没动静、她也这么久没找过他，才催；
    只在白天，一天有上限。计时从「他最后一次动静」和「她最后一次找他」里晚的那个起算——
    不然一满三小时，每半小时催一次，一个钟头就把一天的次数用完。"""
    if not pending:
        return {"due": False, "why": "算分的事今天都做完了"}
    if not NUDGE_FROM <= now.hour < NUDGE_UNTIL:
        return {"due": False, "why": f"只在 {NUDGE_FROM} 点到 {NUDGE_UNTIL} 点之间催"}
    if nudges_today >= NUDGE_MAX_PER_DAY:
        return {"due": False, "why": f"今天已经催过 {nudges_today} 次"}
    marks = [t for t in (last_activity, last_contact) if t is not None]
    quiet = (now - max(marks)).total_seconds() / 3600 if marks else None
    if quiet is not None and quiet < NUDGE_QUIET_HOURS:
        return {"due": False, "why": f"离上一次动静才 {quiet:.1f} 小时", "quiet_hours": round(quiet, 1)}
    return {"due": True, "why": f"还没做完：{'、'.join(pending)}；" + (f"已经 {quiet:.1f} 小时没动静" if quiet is not None else "今天还没有任何动静"),
            "quiet_hours": round(quiet, 1) if quiet is not None else None}


# -- 他在卡片里回她：工作台自己跑一轮 ---------------------------------------------------

def compose(brief_text: str, thread: list[dict[str, Any]], message: str) -> str:
    said = message.strip() or "（他没说话，点了「让她看一眼现在」。用两三句话说：他现在在哪条线上，现在该做哪一件。）"
    return f"<工作台>\n{brief_text}\n\n{thread_brief(thread)}\n</工作台>\n\nPark：{said}"


def run_turn(brief_text: str, thread: list[dict[str, Any]], message: str, *, turn_fn: TurnFn | None = None) -> str:
    """一轮对话，返回她说的话。模型所有工具都关着（用的是 Anna 那条命令）。"""
    try:
        result = (turn_fn or cli_turn)(system_prompt(), compose(brief_text, thread, message), None)
    except Exception as exc:  # noqa: BLE001 - 卡片里显示
        raise WendyError(str(exc).replace("Anna", "Wendy")[:300] or type(exc).__name__) from exc
    text = str(result.get("text") or "").strip()
    if not text:
        raise WendyError("Wendy 没有回话，再说一次试试")
    return text
