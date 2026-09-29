# Registry — content-studio

> Current snapshot only. Put dated history in `daily/`; put why a durable
> decision was made in `decision-log.md`.

**Last verified:** 2026-09-29 15:30 CST

**State authority:** this file for this project's current state
**North Star:** [NORTH_STAR.md](NORTH_STAR.md)

## What we are building

见 [NORTH_STAR.md](NORTH_STAR.md)：Park 自己的内容生产工作台，每天一条主线。规划见 [docs/roadmap.md](docs/roadmap.md)。

## Where we are now

打开工作台首先是「今天」（9/29）：KPI 驱动，一次只给一件事——出摊、回私信算 Park 的分（没做到当天各减 1 分），触达 7 天平均是结果（目标 10/31 前 1 万/天，到了换 2 万）；选题由他写在「接下来要拍的」清单里。下面五站：01 进项 → 02 加工中 → 03 打包 → 04 发布 → 05 已发出（9/29 从四站拆出「打包」）。9/28 那条视频（topic 33）在 9/29 用新流程完整走了一遍，7 个平台都发了、链接都在「已发出 → 链接」。

- **打包**：先写 标题 · 描述 · 简介 · 话题（「保存并定稿」），再出封面（Codex image_gen，4K 原片取帧，竖 3:4 / 横 4:3 / YouTube 16:9，照 ask-park-video 的风格参考）；文字包：X 图文文章（照剪映导出的字幕 SRT 写，没有 SRT 不写）→ 插图 → 公众号排版 / 小红书图文。每一步「定稿」锁住（approvals.json，按指纹判断，上一步改了下一步自动作废），上一步没定稿下一步不开始。
- **发布**：只管发。小红书 9/29 起发视频；每个平台「发什么」是设置（`reach.FORM_CHOICES`，小红书可选视频 / 图文）。顺序 抖音 → 视频号 → B 站 → YouTube → X → 小红书 → 公众号。公众号、X、YouTube（私享）、视频号只存草稿，Park 去后台发、回来点「发出去了」贴链接；B 站直接投稿；小红书、抖音手动传。YouTube 传完自动设 16:9 封面。每个平台有流量话题（设置里，抖音 4 个已填）。
- **已发出 → 链接**：每条内容 × 每个平台一条公开链接，存在 publish_records 一处，能改能下载。
- 研习室、小宇宙在设置里关掉了（通道和数据都在）。

运行：launchd `com.wendy.content-studio` 常驻 `127.0.0.1:8780`。**重启只走 `~/.local/bin/content-studio-restart`**（有发布、写作、转写在跑就不重启）；9/29 直接 `launchctl kickstart` 打断过一次 YouTube 上传。

仍待 Park：见 Next 里标「拍板」的。

## Milestone position

| Milestone | Status | Evidence |
| --- | --- | --- |
| M1–M3 拆解台 | built | PR #4 #7 #8 #9 |
| P1 内容生产工作台 | built | PR #24–#35 |
| P2 视频线与全流程 | built | PR #44–#53，Issue #38–#43 |
| P3 后台代跑 + 审批 · 一键发布 | built | PR #58 #59，Issue #56 #57 |
| P4 9/22 复盘八项（发布台认成片、iCloud 拦截、进度可见、H2 进工作台、封面、标题、Hook 拼接、手机预览） | built | PR #152–#160，park-koubo-workflow#12 |
| P3-1 研习室自动草稿 | waiting | #31（依赖 wechat-xingqiu#207） |
| M4 扩平台数据 | not started | 抖音站内搜索因反作弊不做（#20） |
| P6 「今天」驱动页（KPI、减分、一次一件、接下来要拍的） | built | Issue #300 |
| P5 9/29 用一条真视频重走流程（打包站、定稿、图像生成封面、只管发的发布台、链接簿） | built | PR #258 #261 #263 #265 #269 #271 #273 #274 #276 #277 #279 #281 #283 |

## Next

1. 【拍板】抖音半自动：现在的按钮开的是一个独立的 Chrome（Park 担心风控）。9/29 实际是在 Park 自己的 Chrome 里手动传的。要么拿掉这个按钮回到「复制文案去抖音」，要么改成在 Park 自己的 Chrome 里填（Codex 的 Chrome 插件或 Claude in Chrome；视频 718 MB 超过 Claude in Chrome 10 MB 的上传上限，只能由 Park 拖视频）。
2. 【暂缓，Park 9/29】产品化（哪些做成客户自己的选择，清单在 9/29 daily）：等 Park 自己的流程跑稳了再一项项抽成设置，现在做只会多出没用的复杂度。
3. 视频号、小红书、B 站、YouTube、X 的流量话题还空着，Park 看到活动话题就填进设置。
4. 剪辑进度里没有提醒「剪映导出时勾上字幕 SRT」，文章要等 SRT；9/28 那条的文章是照机器转写写的（Park 已定稿、已发）。
5. CI 上两个老测试一直红（icloud 在 Linux 上、缺 python-multipart），已开任务。
