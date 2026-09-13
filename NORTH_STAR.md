# North Star — content-studio

> Stable intent. Change this only when Park explicitly changes the product
> destination, approved baseline, or success definition.

## What we are building

内容拆解台是 Park 使用的本地优先内容分析产品：监控自己的抖音视频、对标账号视频和手动贴入的链接，用语音转写、截图、节奏和账号自身点赞中位数，回答“一条视频为什么爆 / 为什么不爆”。

## Done looks like

Park 可以从真实抖音链接一路得到可读的拆解报告；自己的创作者后台逐条数据已在本机存档；四个页面（我的视频、对标雷达、拆解队列、拆解报告）显示真实数据并保持样稿的交互；M1 的三份样本报告经 Park 阅读后认为“说中了”。视觉与交互基线见 [`docs/prototype/index.html`](docs/prototype/index.html)，线上基线为 [Claude artifact](https://claude.ai/code/artifact/6d9672af-68eb-45cc-b65e-98fd07bea1dd)。

## Approved foundations

| Item | Canonical artifact / reference | Decision date | Do not reinvent |
| --- | --- | --- | --- |
| 视觉与交互基线 | [`docs/prototype/index.html`](docs/prototype/index.html) · [线上样稿](https://claude.ai/code/artifact/6d9672af-68eb-45cc-b65e-98fd07bea1dd) | 2026-09-13 | yes |
| 对标库初始名单 | dontbesilent 聊赚钱、千雪AI、柱子哥TzFilm | 2026-09-13 | yes |
| 爆款基准 | 账号自身点赞中位数 × 倍数门槛，默认 5×，可调 | 2026-09-13 | yes |
| 能力复用 | `content-downloader` 是唯一下载入口（先修抖音适配）；`content-extractor` 是唯一转写入口；`content-intelligence` 与 `content-workbench` 只作参考 | 2026-09-13 | yes |

## Milestones to the intent

| # | Milestone | Evidence that it is complete | Status |
| --- | --- | --- | --- |
| 1 | M1：拆解跑通 + 后台数据开始存档 | 三条样本各有一份报告，Park 读完认可；自己的创作者后台数据已落库 | in progress — preflight |
| 2 | M2：对标监控 | 对标账号每日新作品入库，超过账号自身门槛的作品自动进入队列 | not started |
| 3 | M3：前端接真实数据 | 本机打开四个页面，全部显示真实数据，交互与样稿一致 | not started |
| 4 | M4：扩平台 | 小红书、X、视频号分别完成采集调研并单独立项；接入前仅入库并标记待接入 | not started |

## Non-negotiables

- 只做监控与拆解，不代 Park 发布内容、评论、私信或操作账号。
- 登录态抓取低频、串行、带间隔；出现验证码或风控立即停止并回帖报告，不绕过。
- cookies 和登录凭据不进仓库；数据只存本机。
- “5 类生态位”标签与“四步结构检查”是待验证假设，只能作为报告参考维度，不能成为爆款判定规则。
- `douyin-downloader`、`douyin-downloader-1`、`MediaCrawler` 不得加入下载链路；不得在 `content-workbench` 上扩建。

## Change control

`REGISTRY.md` may report progress through these milestones but cannot redefine
them. Record the rationale for a North Star change in `decision-log.md` and
link the approving decision.
