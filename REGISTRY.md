# Registry — content-studio

> Current snapshot only. Put dated history in `daily/`; put why a durable
> decision was made in `decision-log.md`.

**Last verified:** 2026-09-14 15:45 CST

**State authority:** this file for this project's current state
**North Star:** [NORTH_STAR.md](NORTH_STAR.md)

## What we are building

见 [NORTH_STAR.md](NORTH_STAR.md)：Park 自己的内容生产工作台，每天一条主线。

## Where we are now

P1（Epic [#16](https://github.com/zinan92/content-studio/issues/16)）已交付并在真实数据上验证：左侧主题导航 + 「今天」（今日主线 6 步、日报、昨日进项、热点、进行中选题、工具栏）；素材库只读 Obsidian；选题看板；热点（对标 48h 爆款、日报头条、高频话题）；文章线（卡兹克写作草稿 → 编辑 → 交给研习室，真实文章 2,709 字约 2 分钟）；Skills 页；多个自己的账号。仓库已公开，GitHub 主页 Content OS 以本工作台为中心，6 个重叠旧仓库已归档。

运行：launchd `com.wendy.content-studio` 常驻 `127.0.0.1:8780`，外网经密码代理访问（见 [docs/operations.md](docs/operations.md)）。测试 103 个全绿。

仍待 Park：① 读拆解报告确认「说中了」；② 在设置里填研习室电脑后台地址；③ 是否启用每日同步。

## Milestone position

| Milestone | Status | Evidence |
| --- | --- | --- |
| M1–M3 拆解台 | built | PR #4 #7 #8 #9 |
| P1 内容生产工作台 | built | PR #24–#34，Issue #17–#23 |
| P2 视频线 + 研习室自动草稿 | not started | Issue [#31](https://github.com/zinan92/content-studio/issues/31)（依赖 wechat-xingqiu#207） |
| M4 扩平台 | not started | 抖音站内搜索因反作弊不做（#20） |

## Next

1. 视频线：选题 → 口播稿 → ask-park-video / 剪映 → 抖音发出记录回收到「我的视频」。
2. wechat-xingqiu#207 验收通过后做 #31。
3. content-production 注册表由 Park OS 快照生成，下一次快照时纳入 content-studio。
