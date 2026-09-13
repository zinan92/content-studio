# Registry — content-studio

> Current snapshot only. Put dated history in `daily/`; put why a durable
> decision was made in `decision-log.md`.

**Last verified:** 2026-09-13 17:09 CST

**State authority:** this file for this project's current state
**North Star:** [NORTH_STAR.md](NORTH_STAR.md)

## What we are building

见 [NORTH_STAR.md](NORTH_STAR.md)：本地优先回答抖音长视频为什么爆、为什么不爆的内容监控与拆解台。

## Where we are now

M1 已完成真实执行但未过 Park 闸门：M1-1 的抖音下载修复已合并到 `content-downloader`（`f0b7e09`）；M1-2 已完成手动后台快照实现，PR [#3](https://github.com/zinan92/content-studio/pull/3) 因 GitHub merge API 502 仍开放；M1-3 PR [#4](https://github.com/zinan92/content-studio/pull/4) 已生成 3 份本机报告并回帖。报告、转写、下载和数据库均在仓库外本机；等待 Park 阅读三份报告并确认“说中了”。

## Milestone position

**0/4 complete** — M1 的代码和真实样本已跑通，业务验收闸门仍等待 Park 确认；在此之前不开始 M2。

| Milestone | Status | Evidence |
| --- | --- | --- |
| M1 | in progress — Park gate pending | [Issue #2](https://github.com/zinan92/content-studio/issues/2)、[PR #4](https://github.com/zinan92/content-studio/pull/4)、本机 `~/.config/content-studio/m1/pipeline-run.json` |

## Next move

1. Park 阅读 [M1-3 Issue #2](https://github.com/zinan92/content-studio/issues/2) 中的三份本机报告并确认是否“说中了”。
2. GitHub merge API 恢复后合并 [M1-2 PR #3](https://github.com/zinan92/content-studio/pull/3) 与 [M1-3 PR #4](https://github.com/zinan92/content-studio/pull/4)；确认前不开始 M2。

## ETA

unknown — no reliable basis

## Project pulse

| Field | Value | Source / as-of |
| --- | --- | --- |
| Latest merged PR | none — initial scaffold `1c96e17` is on main; M1 PRs open | 2026-09-13 |
| Merged PRs, last 30 days | 0 | GitHub remote as-of 2026-09-13 |
| Merged PRs, yesterday | 0 | GitHub remote as-of 2026-09-13 |
| Project age / activity | initial scaffold pushed; 3 M1 issues, 2 implementation PRs, 3 local reports | 2026-09-13 |
| Token/cost summary | unavailable | TokenRouter source + cutoff not queried |

Token/cost values here are project-level summaries. Raw token runs and session
accounting remain in TokenRouter; do not copy a raw ledger into this file.

## Evidence and history

- Latest daily record: [daily/2026-09-13.md](daily/2026-09-13.md)
- Decision rationale: [decision-log.md](decision-log.md)
- Project identity mapping: Park OS `registry/projects.yml` (identity only; not
  a second state registry)
