# Registry — content-studio

> Current snapshot only. Put dated history in `daily/`; put why a durable
> decision was made in `decision-log.md`.

**Last verified:** 2026-09-14 01:00 CST

**State authority:** this file for this project's current state
**North Star:** [NORTH_STAR.md](NORTH_STAR.md)

## What we are building

见 [NORTH_STAR.md](NORTH_STAR.md)：本地优先回答抖音长视频为什么爆、为什么不爆的内容监控与拆解台。

## Where we are now

M1–M3 已交付并在真实数据上自验收：`python3 -m content_studio serve` 打开 <http://127.0.0.1:8780>，四个页面均为真实数据。本机库里 4 个账号（自己 + 3 个对标）、160 条作品、17 条 ≥5× 爆款；拆解队列在后台自动产出报告。拆解逻辑已从"按标题写死"返工为"模型判断 + 代码算数 + 原文回查"，并在一条从未见过的视频上验证泛化。

仍待 Park：① 读四份样本报告，确认是否"说中了"（M1 闸门）；② 合并 Park OS 身份映射 PR [#98](https://github.com/zinan92/park-operating-system/pull/98)；③ 决定是否启用每日同步（`write-schedule` 已生成配置，未加载）。

## Milestone position

**3/4 built** — M1 待 Park 业务确认，M2/M3 已交付，M4（扩平台）未开始。

| Milestone | Status | Evidence |
| --- | --- | --- |
| M1 | built — Park "说中了" pending | PR [#4](https://github.com/zinan92/content-studio/pull/4)、本机报告 `~/.config/content-studio/m1/reports/` |
| M2 | built — daily schedule not enabled | PR [#7](https://github.com/zinan92/content-studio/pull/7)、Issue [#5](https://github.com/zinan92/content-studio/issues/5) |
| M3 | built — self-accepted | Issue [#6](https://github.com/zinan92/content-studio/issues/6) |
| M4 | not started | — |

## Next move

1. Park 阅读四份样本报告并确认"说中了"，或指出哪里不对以调整拆解提示词。
2. Park 决定是否启用每日同步；启用后观察一周抓取是否触发风控。
3. M4：小红书 / X / 视频号采集方式调研，单独立项。

## ETA

M4 unknown — no reliable basis.

## Project pulse

| Field | Value | Source / as-of |
| --- | --- | --- |
| Latest merged PR | M3 web app PR (see GitHub) | 2026-09-14 |
| Merged PRs, last 30 days | 5 (#3, #4, #7, M3 PR, content-downloader #3) | GitHub as-of 2026-09-14 |
| Project age / activity | started 2026-09-13; 62 tests; 5+ real reports | 2026-09-14 |
| Token/cost summary | unavailable | TokenRouter not queried |

Token/cost values here are project-level summaries. Raw token runs and session
accounting remain in TokenRouter; do not copy a raw ledger into this file.

## Evidence and history

- Latest daily record: [daily/2026-09-14.md](daily/2026-09-14.md)
- Decision rationale: [decision-log.md](decision-log.md)
- Project identity mapping: Park OS `registry/projects.yml` (identity only; not
  a second state registry)
