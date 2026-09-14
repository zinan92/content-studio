# North Star — content-studio

> Stable intent. Change this only when Park explicitly changes the product
> destination, approved baseline, or success definition.

## What we are building

内容工作台是 Park 自己的内容生产工作台（2026-09-14 由「内容拆解台」升级，Park 批准方案：https://claude.ai/code/artifact/bb2c26c5-4d36-4acd-acba-3bc9d56e5686）：每天打开「今天」就知道收了什么、做什么、发哪里；把 Obsidian 进项 → 选题 → 文章 / 视频 → 发出 → 爆款复盘串成一条主线。爆款拆解（监控自己与对标账号、转写、账号自身中位数倍数）是这条线的头和尾。

## Done looks like

Park 每天用它完成 看日报 → 回顾进项 → 选题 → 文章交给 Park 研习室 → 拍视频 → 复盘；文章线全程在工作台内完成；视频线接入同一主线；支持多个自己的账号。检验标准只有一条：有了它，Park 是否每天多发一篇、多拍一条。

## Approved foundations

| Item | Canonical artifact / reference | Decision date | Do not reinvent |
| --- | --- | --- | --- |
| 视觉与交互基线 | [线上样稿](https://claude.ai/code/artifact/6d9672af-68eb-45cc-b65e-98fd07bea1dd) | 2026-09-13 | yes |
| 对标库初始名单 | dontbesilent 聊赚钱、千雪AI、柱子哥TzFilm | 2026-09-13 | yes |
| 爆款基准 | 账号自身点赞中位数 × 倍数门槛，默认 5×，可调 | 2026-09-13 | yes |
| 形态与布局 | 网页；左侧主题（今天/收集/选题/加工/发出/复盘/工具），首页固定「今天」 | 2026-09-14 | yes |
| 第三方 skill | 只链接署名，不复制进仓库 | 2026-09-14 | yes |
| 能力复用 | `content-downloader` 是唯一下载入口（先修抖音适配）；`content-extractor` 是唯一转写入口；`content-intelligence` 与 `content-workbench` 只作参考 | 2026-09-13 | yes |

## Milestones to the intent

| # | Milestone | Evidence that it is complete | Status |
| --- | --- | --- | --- |
| 1 | M1：拆解跑通 + 后台数据开始存档 | 三条样本各有一份报告，Park 读完认可；自己的创作者后台数据已落库 | built — Park 确认"说中了"待定 |
| 2 | M2：对标监控 | 对标账号每日新作品入库，超过账号自身门槛的作品自动进入队列 | built — 每日定时需 Park 启用 |
| 3 | M3：前端接真实数据 | 本机打开四个页面，全部显示真实数据，交互与样稿一致 | built — 自验收通过 |
| 5 | P1：内容生产工作台 | Epic #16：今天、素材库、选题、热点、文章线、Skills、公开仓库 | built — 2026-09-14 |
| 6 | P2：视频线 + 研习室自动草稿 | 口播稿、剪辑、抖音发出记录；#31 | not started |
| 4 | M4：扩平台 | 小红书、X、视频号分别完成采集调研并单独立项；接入前仅入库并标记待接入 | not started |

## Non-negotiables

- 不代 Park 发布任何平台内容、评论、私信或操作账号；文章只交给研习室，由 Park 发布。
- Obsidian 笔记只读，只开放白名单文件夹。
- 登录态抓取低频、串行、带间隔；出现验证码或风控立即停止并回帖报告，不绕过。
- cookies 和登录凭据不进仓库；数据只存本机。
- “5 类生态位”标签与“四步结构检查”是待验证假设，只能作为报告参考维度，不能成为爆款判定规则。
- `douyin-downloader`、`douyin-downloader-1`、`MediaCrawler` 不得加入下载链路；不得在 `content-workbench` 上扩建。

## Change control

`REGISTRY.md` may report progress through these milestones but cannot redefine
them. Record the rationale for a North Star change in `decision-log.md` and
link the approving decision.
