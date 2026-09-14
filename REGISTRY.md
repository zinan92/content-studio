# Registry — content-studio

> Current snapshot only. Put dated history in `daily/`; put why a durable
> decision was made in `decision-log.md`.

**Last verified:** 2026-09-14 16:40 CST

**State authority:** this file for this project's current state
**North Star:** [NORTH_STAR.md](NORTH_STAR.md)

## What we are building

见 [NORTH_STAR.md](NORTH_STAR.md)：Park 自己的内容生产工作台，每天一条主线。规划见 [docs/roadmap.md](docs/roadmap.md)。

## Where we are now

P1（文章线）和 P2（视频线与全流程）都已交付并在真实数据上跑过：每日统筹（真实：6 条先读、4 条可拍，首选是 Park 的原始输出）→ 选题 → 拍摄提纲（真实 5 段提纲）→ 口播 workflow 剪辑进度（读外接硬盘上的项目，按 14 步产物判断，H1 worktable 导入）→ 发出与数据（快照、24h/72h/7 天、48 小时拆解）→ 7 个平台文案（真实全部通过长度校验）→ 每周复盘。首页主线 8 步全部由数据判定。测试 146 个全绿。

运行：launchd `com.wendy.content-studio` 常驻 `127.0.0.1:8780`，外网经密码代理访问（见 [docs/operations.md](docs/operations.md)）。

仍待 Park：① 读拆解报告确认「说中了」；② 设置里填研习室电脑后台地址；③ 是否启用每日同步；④ P3：是否让工作台后台代跑口播 workflow、是否接自动发布。

## Milestone position

| Milestone | Status | Evidence |
| --- | --- | --- |
| M1–M3 拆解台 | built | PR #4 #7 #8 #9 |
| P1 内容生产工作台 | built | PR #24–#35 |
| P2 视频线与全流程 | built | PR #44–#53，Issue #38–#43 |
| P3 研习室自动草稿 / 后台代跑 / 自动发布 | not started | #31；后两项待 Park 确认 |
| M4 扩平台数据 | not started | 抖音站内搜索因反作弊不做（#20） |

## Next

1. Park 实际用一天后按反馈调整统筹与提纲的写法。
2. wechat-xingqiu#207 验收通过后做 #31。
3. P3-2/P3-3 等 Park 决定。
