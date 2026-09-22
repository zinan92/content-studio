<div align="center">

# 内容工作台 · content-studio

**把一个人的内容生产分成四段：进项 → 加工中 → 发布 → 已发出**

[![Python](https://img.shields.io/badge/python-3.11+-3776AB.svg?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-local_web-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![SQLite](https://img.shields.io/badge/SQLite-local_only-003B57.svg?logo=sqlite&logoColor=white)](https://sqlite.org)
[![Claude Code](https://img.shields.io/badge/Claude_Code-skills-D97757.svg)](https://docs.anthropic.com/en/docs/claude-code)
[![CI](https://github.com/zinan92/content-studio/actions/workflows/ci.yml/badge.svg)](https://github.com/zinan92/content-studio/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

</div>

---

<p align="center"><img src="docs/screenshots/hero-board.png" alt="加工中：今天做哪一条" width="920"></p>
<p align="center"><sub>02 · 加工中——任何时候只做一条。选题 → 骨架 → 录制是你的，剪辑和待发交给机器。</sub></p>

```
in   Obsidian 库（Newsletter / Clippings / 我收藏的 / 我写的） + 口播 workflow 项目目录 + 抖音账号与视频
out  选题池 + 加工看板（提纲 → 录制 → 剪辑 → 待发，自动归列） + 拍摄提纲 + 开头 15 秒检查 + 剪辑进度 + 各平台发布 + 研习室文章 + 发出后数据图表 + 拆解报告 + 每周复盘

fail Obsidian 路径不存在      → 页面提示去设置，其它功能照常
fail 抖音 cookies 缺失/过期   → 顶部提示重新导出，不发请求
fail 抖音验证页 / 反作弊      → 立即停止抓取并显示原因，不绕过
fail 本机 claude 未登录       → 任务标失败并写明「重新登录后点重试」，不空转重试
fail 模型输出不合格          → 带错误重试，仍失败则保留原因可手动重试
```

它只在本机运行：笔记只读、cookies 与数据不出本机；发布只在你逐次确认后执行。

## 长什么样

四段各一个页面，左栏永远是同一条线。深浅色各一套，Anna 在任何一页都能叫过来。

### 01 · 进项——进来了什么

| | |
|---|---|
| ![进项](docs/screenshots/01-input.jpg) | ![进项 · Anna 在旁边](docs/screenshots/01-input-anna.jpg) |
| 左边是最近进来的笔记，对标爆款带倍数排最前；右边直接读原文。值得做的点「入选题池」。 | 问 Anna「今天有什么值得拿来做的」，她按三点判断给结论，建议变成按钮。 |
| ![进项 · 深色](docs/screenshots/01-input-dark.jpg) | |
| 深色。 | |

<details><summary>整页：按来源分页签（AI 日报 / 财经日报 / K 线日报 / 对标 / 我写的 / 我收藏的 / Clippings）</summary>
<p align="center"><img src="docs/screenshots/01-input-full.jpg" width="900"></p>
</details>

### 02 · 加工中——今天做哪一条

| | |
|---|---|
| ![加工中](docs/screenshots/02-board.jpg) | ![选题池 · 暂缓](docs/screenshots/02-board-snoozed.jpg) |
| 六步进度条只有一条在走。橙点 = 在等你。「5 天没拍了」直接写在脸上。 | 不想拍的放回池子或暂缓两周；到期自动回来。 |
| ![骨架 · 三点评分](docs/screenshots/02-video-outline.jpg) | ![三点评分展开](docs/screenshots/02-video-qa.jpg) |
| 一条视频四个页签：骨架 → 剪辑进度 → 发布 → 文章。骨架不是逐字稿：一句主线、5–10 条开头候选、论点 + 证据。 | 痛点具象度 / 认知反差度 / 交付可行性，每分必须引用骨架或素材原话；素材太薄直接说「先补再拍」。 |
| ![骨架 · 编辑](docs/screenshots/02-video-outline-edit.jpg) | ![素材太薄](docs/screenshots/02-video-thin.jpg) |
| 预览 / 编辑一键切换，Markdown 原文可改可复制可重写。 | 另一条被判「素材太薄，先补一处再录」——它不会让你带着空证据去录。 |
| ![剪辑进度](docs/screenshots/02-video-edit-progress.jpg) | ![研习室文章](docs/screenshots/02-video-article.jpg) |
| 口播 workflow 14 步 / 5 阶段 / 3 个审批门，按项目目录里的产物判断走到哪；「让机器跑到下一个审批门」在这台 Mac 后台代跑。 | 视频录完，同一条素材可选做成文章：交给 khazix-writer，作者是你。 |
| ![Anna 看着这条视频](docs/screenshots/02-video-anna.jpg) | ![加工中 · 深色](docs/screenshots/02-video-dark.jpg) |
| 「我录完了，下一步该做什么」——Anna 看得见这条的骨架、评分和剪辑进度，回答是具体的下一步。 | 深色。 |
| ![加工中 · Anna](docs/screenshots/02-board-anna.jpg) | |
| 在看板上问「整体什么情况，一句话」。 | |

<details><summary>整页：一份完整的一勾式骨架（8 条开头候选 · 5 个论点带证据 · 一句结尾）</summary>
<p align="center"><img src="docs/screenshots/02-video-outline-full.jpg" width="900"></p>
</details>

### 03 · 发布——这一条发到哪

| | |
|---|---|
| ![发布台](docs/screenshots/03-publish.jpg) | ![还没有能发的成片](docs/screenshots/03-publish-empty.jpg) |
| 9 个平台各一张它自己上传页的缩影：灰的没发，彩的发了。手动的复制文案去粘贴，能机器发的扫码后代发，公众号交给既有管线。 | 成片没出来时它告诉你在等什么，而不是给你一排灰按钮。 |
| ![发布台 · 深色](docs/screenshots/03-publish-dark.jpg) | |
| 平台状态五种而不是两种：「平台限制了」≠「没连上」，「凭据就绪」≠「通道已连」。一个永远亮不起来的灯就是骗人。 | |

<details><summary>整页：九个平台</summary>
<p align="center"><img src="docs/screenshots/03-publish-full.jpg" width="900"></p>
</details>

### 04 · 已发出——这一周怎么样

| | |
|---|---|
| ![概览](docs/screenshots/04-output.jpg) | ![留存与复盘](docs/screenshots/04-output-retention.jpg) |
| 触达是第一个数。每个数字旁边的「?」说明它怎么算的；倍数图用账号自己的中位数做基准。 | 2 秒跳出、平均观看秒数、每条涨粉、收藏/赞——然后「复盘这一周」：定下周只改的一件事。 |
| ![全部作品](docs/screenshots/04-mine.jpg) | ![对标雷达](docs/screenshots/04-radar.jpg) |
| 时长 × 播放散点，金色 = 超过自己中位数 3 倍；下面是每条的完播、跳出、均看、倍数。 | 每个对标账号一张卡：作品折线 + 爆款打点，各用它自己的中位数。门槛拖一下，全页跟着变。 |
| ![拆解报告](docs/screenshots/04-report.jpg) | ![Anna 看着数据](docs/screenshots/04-output-anna.jpg) |
| 一条爆款为什么爆：模型通读转写判断主线 / 分段 / 跑题，代码算数字，每个结论回查原文时间点。 | Anna 在「已发出」看得见近 90 天数据和复盘。 |
| ![概览 · 深色](docs/screenshots/04-output-dark.jpg) | ![拆解报告 · 深色](docs/screenshots/04-report-dark.jpg) |
| 深色。 | 深色。 |

<details><summary>整页：一份完整的拆解报告（主线结构时间轴 · 为什么爆 · 为什么散 · 语速节奏）</summary>
<p align="center"><img src="docs/screenshots/04-report-full.jpg" width="900"></p>
<p align="center"><sub>钩子 / 承诺 / 案例 / 论点 / 引导，斜纹 = 不服务主线。底部一行提醒：这些是待验证假设，不是爆款判定规则。</sub></p>
</details>

<details><summary>整页：概览 · 全部作品 · 对标雷达</summary>
<p align="center"><img src="docs/screenshots/04-output-full.jpg" width="900"></p>
<p align="center"><img src="docs/screenshots/04-mine-full.jpg" width="900"></p>
<p align="center"><img src="docs/screenshots/04-radar-full.jpg" width="900"></p>
</details>

全部截图（含更多整页与深色版本）在 [`docs/screenshots/`](docs/screenshots/)。

## UX Journey

![UX Journey](docs/assets/ux-journey.svg)

一天的路径是固定的，所以左栏永远是这四段，不会因为功能多了就多一个入口。每段只回答一个问题：

| 段 | 你打开它时想知道 | 页面第一眼给你 | 你在这一页做的唯一动作 |
|---|---|---|---|
| 01 进项 | 进来了什么 | 按倍数排的对标爆款 + 昨天到现在的笔记 | 拿来做 / 拍过了 / 忽略 |
| 02 加工中 | 今天做哪一条 | 正在做的这条走到第几步、在等谁 | 打开它，把这一步做完 |
| 03 发布 | 这一条发到哪 | 九个平台哪些发了 | 复制去粘贴，或确认机器发 |
| 04 已发出 | 这一周怎么样 | 触达一个大数 + 每条的倍数 | 读报告，定下周改的一件事 |

Anna 不是第五段，是贯穿四段的那个人：她看着你在哪一页，就只谈那一页的事。

## 设计理念

这些不是口号，每一条背后都有一次返工，记在 [`decision-log.md`](decision-log.md)。

1. **一屏只回答一个问题。** 加工中只回答「现在轮到谁」，发布只回答「发到哪了」。想看别的，换一页，不叠加。
2. **任何时候只做一条。** 选题池可以很多，正在做的永远是一条。第二条想进来，先把第一条放回去。连续拍摄天数和「N 天没拍了」直接写在页面上。
3. **数字由代码算，判断由模型做，结论回查原文。** 拆解报告里没有一个数字是模型写的；每一句「为什么爆」都带原文时间点。三点评分每一分必须引用骨架或素材原话，引不出来就是「素材太薄」。
4. **能直接问就别猜。** 通道状态一度用 cookie 文件的日期猜，同一个毛病犯了三次。现在是真去问平台。平台状态五种而不是两种，因为「平台限制了」和「没连上」对你意味着完全不同的下一步。
5. **机器只走到审批门。** 剪辑 14 步可以后台代跑，但 H1 选 Hook、H2 视觉、H3 终审停下来等你。发布每次都要你确认。Anna 只动嘴，建议变成按钮，你点了才执行。
6. **不能证明有用就删。** 「今天推荐拍」每天烧一次大模型，前端从来没用它的一半输出，删掉。「老师」和「对标」分成两类的唯一理由随着推荐功能一起消失，收回去。
7. **数据本机，笔记只读。** cookies、SQLite、报告、草稿都在 `~/.config/content-studio/`；Obsidian 只开六个白名单文件夹，拒绝 `..` 和软链逃逸。抓取串行、带间隔，遇验证页立即停，不绕过。
8. **拆解结论是假设。** 结构标签和「为什么爆」是待验证的参考维度，页面底部写着这句话。它们永远不会变成「爆款判定规则」。

## 适合谁

这是从 Park 一个人的内容工作流里长出来的，判断口味（三点评分、时间窗、爆款门槛）都按他调过。
它假设你也是**一个人做内容**，并且：

| 前提 | 没有会怎样 |
|---|---|
| 一个 **Obsidian 库**（或任何 Markdown 文件夹），素材和自己写的东西都在里面 | 「进项」是空的；其它功能照常 |
| 一个**抖音号**，能在浏览器登录网页版和创作者中心 | 数据同步、对标雷达、拆解队列不可用 |
| 本机装好并登录 **Claude Code**（`claude` 命令） | 提纲、评分、写文章、Anna、复盘全部不可用 |
| macOS（转写用 mlx-whisper，发布用本机浏览器） | Linux 上网页和看板能跑，转写和机器代发不能 |

不适合：多人团队、要部署到服务器、要接 API key 而不是本机 CLI。

## 三段怎么用

| 段 | 在哪 | 看什么 / 做什么 |
|---|---|---|
| 01 进项 | 左侧「进项」 | 今天的 Newsletter（读完勾掉）；昨天到现在进来的 Clippings、我收藏的、我写的。值得做的点「拿来做」，工作台外拍过的点「拍过了」，其余忽略。已经做成视频的笔记会标出来。 |
| 02 加工中 | 左侧「加工中」 | 左边是选题池（只从「进项」进来，不自动加），右边是正在做的那一条：提纲 → 录制 → 剪辑 → 待发，按提纲文件和口播项目 14 步证据自动归列，橙点表示在等你。任何时候只做一条。点开一条视频：拍摄提纲、剪辑进度（含开头 15 秒检查）、发布、研习室文章。 |
| 03 发布 | 左侧「发布」 | 一条内容铺在所有平台上：每个平台一张它自己的上传页（抖音、视频号、小红书、公众号、小程序、X、B 站、YouTube、小宇宙），灰的还没发、彩色的发了、正在发的闪。点开一张，右边是这个平台该做的事：手动的复制裁好的文案去粘贴，扫码登录的机器代发（Park 逐次确认），全自动的直接发，公众号交给既有的 wechat-package 管线。发完回来记一笔。 |
| 04 已发出 | 左侧「已发出」 | 概览：近 30 天条数、连续拍摄、倍数、涨粉、平均观看；每条视频的倍数图，2 秒跳出 / 平均观看 / 涨粉 / 收藏赞走势；这周复盘（下周只改一件事）。另有我的视频、对标雷达、拆解报告（拆解队列在报告页底部）。 |

文章和视频不分开：每条都先做视频。一条视频只有四个页签：拍摄提纲 → 剪辑进度 → 发布 → 研习室文章（可选）。

## 架构

```
┌─────────────── Obsidian 库（只读，6 个白名单文件夹）───────────────┐
│ 002_对标内容 · 002_clippings · 002_个人收藏 · 003_park原始输出 · 三种日报 │
└───────────────┬───────────────────────────────────────────────────┘
                ▼
┌──────────────────────────── FastAPI（127.0.0.1:8780）────────────────────────────┐
│ vault.py 进项   board.py 看板   qa.py 三点评分   opening.py 开头   writer.py 文章 │
│ accounts.py 账号同步  worker.py 拆解队列  transcripts.py 对标转写  store.py SQLite │
│ anna.py 常驻主编   publisher.py 各平台发布   handoff.py 交接公众号管线      │
└──────┬───────────────────────┬──────────────────────────┬────────────────────────┘
       ▼                       ▼                          ▼
 content-downloader      content-extractor           本机 claude CLI
 抖音作品/下载（签名）    mlx-whisper 转写            结构判断 · khazix-writer 写作
       │                                                  │
       └──────────── ~/.config/content-studio/ ───────────┘
                     studio.sqlite3 · reports/ · drafts/（权限 600/700）
```

前端是原生 JS：`input.js`（进项）、`board.js`（加工看板）、`video.js` + 各页签文件（一条视频）、`publishdesk.js`（发布台）、`output.js`（已发出概览），注册到 `window.VIEWS` / `window.VIDEO_TABS`。

## 快速开始

```bash
# 1. 克隆并安装
git clone https://github.com/zinan92/content-studio.git
cd content-studio
python3 -m pip install -e .            # 要跑测试加 '.[dev]'

# 2. 告诉它你是谁：复制模板，按里面的 [必填] / [可选] 填
cp profile.example.yaml profile.yaml
python3 -m content_studio check        # 逐项核对，❌ 是必填没过，○ 是可选没填

# 3. 两个本机能力（抖音下载、视频转写）
git clone https://github.com/zinan92/content-downloader.git ~/work/content-downloader   # 或设 CONTENT_DOWNLOADER_PATH
python3 -m pip install git+https://github.com/zinan92/content-extractor.git

# 4. 启动
python3 -m content_studio serve
# 打开 http://127.0.0.1:8780
```

`check` 没过的时候 `serve` 照样能起，页面顶部会挂一条横幅列出还缺什么——第一次装的人不用对着空白页猜。

**profile.yaml 里有什么**（模板里每一项都标了必填/可选）：

| 一节 | 装什么 | 必填 |
|---|---|---|
| `me` | 你的名字、你自己的抖音主页链接、其他平台的账号名 | 名字、抖音链接 |
| `ai` | 后台跑提纲/评分/Anna 的模型。目前只支持本机登录的 Claude Code | `backend` |
| `benchmarks` | 对标账号的主页链接，一行一个 | — |
| `vault` | Obsidian 库在哪、「我写的东西」在库里哪个文件夹、剪藏/收藏/日报各在哪 | 库路径、我写的东西 |
| `video_projects_root` | 口播视频项目目录 | — |
| `anna` | Anna 的角色文件和提纲框架文件夹；不填用仓库自带的通用版（`src/content_studio/examples/anna/`），想要「你的」Anna 就复制出去改 | — |
| `secrets_file` | 公众号 / X 的密钥文件位置（密钥本身不进 profile） | — |

启动时 profile 只填空不覆盖：设置页里手改过的值优先。对标账号只登记不同步，你自己点「同步全部账号」。

- 抖音功能需要浏览器登录抖音网页版与创作者中心后，把 cookies 导出到 `~/.config/content-studio/douyin-cookies.json`（权限 `600`）。
- 拆解和写文章调用本机已登录的 [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI；写文章需要安装 [khazix-writer](https://github.com/KKKKhazix/khazix-skills) skill。

## 拿去用

这个仓库是 Park 自己在用的，main 分支随时在变。想用它，**fork 到你自己的账号**，在 fork 里改：

```bash
gh repo fork zinan92/content-studio --clone      # 或在网页上点 Fork 再 clone
cd content-studio
python3 -m pip install -e .
cp profile.example.yaml profile.yaml             # 按 [必填] / [可选] 填成你的
python3 -m content_studio check
python3 -m content_studio serve
```

装完先做这三件事，不然它还是照 Park 的习惯在判断：

1. `profile.yaml` 里 `me` / `vault` / `benchmarks` 换成你的
2. 把 `src/content_studio/examples/anna/` 里的两个文件复制到你的笔记库，按你的账号改，`anna.role` / `anna.workflows` 指过去
3. 设置页里改爆款门槛（默认 5×，按你账号的点赞中位数调）

想要后续更新：fork 里 `git pull https://github.com/zinan92/content-studio.git main`。
改出了通用的东西想合回来：开 PR。直接给这个仓库推代码是不行的，也不需要——你的 fork 就是你的。

给 Agent 的一句话：`fork zinan92/content-studio，clone 到本地，读 README「拿去用」和「适合谁」，按 profile.example.yaml 让我填必填项，然后 check → serve。不要往 zinan92 的仓库推。`

## 功能一览

| 功能 | 说明 | 状态 |
|---|---|---|
| 进项 | 今天的 Newsletter + 只读 Obsidian（Clippings / 我收藏的 / 我写的），拿来做 / 拍过了 / 忽略，已做成视频的会标出 | 已完成 |
| 加工中 | 单焦点 pipeline：任何时候只有一条在做（选题 → 提纲 → 录制 → 剪辑 → 待发 → 已发出，可退回提纲）；其余在选题池，可「暂不拍」两周；推荐可直接「今天做这条」；对标本周爆款直接顶到看板 | 已完成 |
| 拍摄提纲 | 一句主线 + 4–8 条要点（第一条就讲主线），不写逐字稿，可编辑 | 已完成 |
| Anna（悬浮窗，右侧居中） | 内容主编。Park 在哪一页她就看着哪一页：进项看今天的 AI 日报和新笔记，加工中看这条视频的素材、提纲、三点评分、剪辑进度和发出后的数据，已发出看近 90 天数据和复盘。角色、原则、知识全是 Obsidian 里的 Markdown（`~/park-hands/001_role/content_editor Anna.md` 及其 knowledge），改文件就改人。她只动嘴：建议变成按钮（存进备注 / 重写提纲 / 按三点评分 / 拿来做），Park 点了才执行。一条贯穿所有页面的对话，每条消息标着在哪一页说的，可清空。悬浮窗可拖动、可拉四边改大小并记住；rail 上「叫她过来」，窗里「去忙吧」收起 | 已完成 |
| 三点评分 | 提纲写完自动按 痛点具象度 / 认知反差度 / 交付可行性 打分，每分必须引用提纲或素材原话，素材太薄直接说。标准读本机的 `park-content-qa` skill（原则 `principles.md` 排在评分标准之前），找不到时用简版 | 已完成 |
| 开头 15 秒检查 | 读项目已有字幕，判断主线第一次出现的秒数，给改法 | 已完成 |
| 剪辑进度 | 口播 workflow 14 步 / 5 阶段 / H1–H3 审批门；worktable 导入；后台代跑到审批门停下 | 已完成 |
| 发布 · 标题和简介 | 一个标题 + 一段简介，所有平台共用，只提示各平台字数；可「用提纲填」；视频号 / B 站 / YouTube 可标为已发 | 已完成 |
| 一键发布 | 视频号 / B 站 / YouTube，每次都要 Park 确认 | 已完成 |
| 发布台 | 独立一页：每个平台一张缩小的上传页，灰=没发、彩=发了；点开一张做这个平台的事（复制 / 机器发 / 交接 / 记一笔）；候选是加工中走到待发的和最近发出的 | 已完成 |
| 研习室文章 | 可选：卡兹克写作出草稿，编辑、复制、下载 .md、交给研习室 | 已完成 |
| 触达 KPI | 第一 KPI：今天各平台播放合计、近 7 天日均、按这个节奏 30 天；抖音按每日快照自动算，视频号/小红书/公众号/小程序/X/B 站/YouTube/小宇宙先手填今天的播放；每天 9:30 自动同步抖音 | 已完成 |
| 已发出 · 概览 | 这一周：触达 hero、近 7 天发了 / 播放 / 点赞评论收藏 / 涨粉与总粉丝 / 平均观看，每个数字有「?」说明怎么算；倍数图、留存走势、这周复盘 | 已完成 |
| 已发出 · 总览 | 全部作品明细 + 创作者后台（涨粉、完播、跳出、均看） | 已完成 |
| 对标雷达 | 账号自身中位数算倍数；默认只看这一周，更早的在「全部」；页面门槛管显示，自动拆解另有 ≥5× 门槛、每天最多 2 条；本周爆款直接顶到加工中看板 | 已完成 |
| 拆解报告与队列 | 下载 → 转写 → 模型判断结构 → 代码算数 → 原文回查；7 天没看的对标报告自动归档 | 已完成 |
| 多账号 | 我的账号可以有多个，左下角切换 | 已完成 |
| Skills | 在设置页，注册表 + 本机安装检测 + 调用方式 | 已完成 |
| 研习室自动进草稿箱 | 走研习室设备接口 | 计划中（[#31](https://github.com/zinan92/content-studio/issues/31)） |
| 抖音站内热搜 | 搜索接口触发反作弊，按规则不做 | 不做 |

## 用到的 Skills

别人写的 skill 只列名字、作者和原仓库，代码不复制进本仓库（有测试守护）。

| Skill | 用在哪一步 | 作者 | 原仓库 |
|---|---|---|---|
| ask-park-video | 加工 · 口播视频 | Park | [zinan92/park-koubo-workflow](https://github.com/zinan92/park-koubo-workflow) |
| khazix-writer | 加工 · 文章 | 数字生命卡兹克 | [KKKKhazix/khazix-skills](https://github.com/KKKKhazix/khazix-skills) |
| dbs-content / dbs-deconstruct / dbs-diagnosis / dbs-wechat-html | 选题 · 发出 · 复盘 | dontbesilent | [dontbesilent2025/dbskill](https://github.com/dontbesilent2025/dbskill) |
| video-shotcraft | 加工 · 产品视频 | Vincentwei1021 | [Vincentwei1021/video-shotcraft](https://github.com/Vincentwei1021/video-shotcraft) |
| gzh-design | 发出 · 公众号排版 | isjiamu | [isjiamu/gzh-design-skill](https://github.com/isjiamu/gzh-design-skill) |
| x-mentor-skill | 选题 · X | alchaincyf | [alchaincyf/x-mentor-skill](https://github.com/alchaincyf/x-mentor-skill) |
| baoyu-post-to-wechat | 发出 · 公众号 | 宝玉 | [JimLiu/baoyu-skills](https://github.com/JimLiu/baoyu-skills) |

完整名单与调用方式见 [`config/skills.json`](config/skills.json)。

## 边界

- **笔记只读**：只开放 6 个白名单文件夹，拒绝 `..`、绝对路径和软链逃逸；库里其它文件夹（包括密钥目录）不可达。库里的 HTML 以 `CSP: sandbox` 返回。
- **不代发布**：文章交给研习室由 Park 发布；抖音只读数据，不发、不评、不私信。
- **抓取克制**：串行、页间 ≥1.5 秒、每账号最多 3 页；遇验证页或反作弊立即停止。
- **数据本机**：cookies、SQLite、报告、草稿都在 `~/.config/content-studio/`，不进仓库。
- **拆解结论是假设**：结构标签与「为什么爆」是待验证的参考，不是爆款判定规则。

## 命令行

| 命令 | 作用 |
|---|---|
| `python3 -m content_studio serve` | 启动网页（默认 8780）并在后台串行处理拆解队列 |
| `python3 -m content_studio sync` | 同步所有抖音账号作品 + 自己的后台数据 + 自动入队爆款 |
| `python3 -m content_studio work` | 不开网页，把拆解队列跑完后退出 |
| `python3 -m content_studio add-account <主页链接> [--self]` | 命令行加账号 |
| `python3 -m content_studio creator-sync` | 只抓自己的创作者后台数据（最近 90 天） |
| `python3 -m content_studio pipeline --url <视频链接>` | 不入库，直接对链接出报告 |
| `python3 -m content_studio write-schedule` | 生成每日同步的 launchd 配置，只写文件不启用 |
| `python3 -m content_studio check` | 核对 profile.yaml，列出必填/可选各缺什么；必填齐了退出码 0 |
## API 参考

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/board` | 选题池、正在做的那一条、连续拍摄天数 |
| `GET` | `/api/today/dailies` · `PUT /api/today/checks` | 当天日报与「已看」 |
| `GET` | `/api/publish/desk?topic_id=` | 发布台：候选内容、选中的那条、每个平台的状态 / 对待方式 / 裁好的文案 / 发布记录 / 进行中的发布 |
| `GET` | `/api/vault/inbox?days=1&source=` | 最近进项（Clippings / 我收藏的 / 我写的），带「已做成视频」标记 |
| `GET` | `/api/vault/note?path=` | 读一条笔记（白名单内） |
| `PUT` | `/api/vault/triage` | 拿来做 / 拍过了 / 忽略 / 撤销 |
| `GET` `POST` `PATCH` | `/api/topics` · `/api/topics/{id}` | 选题 |
| `POST` | `/api/topics/{id}/write` | 后台写文章 |
| `GET` `PUT` | `/api/topics/{id}/article` · `GET …/article.md` | 草稿读写与下载 |
| `POST` | `/api/topics/{id}/handoff` | 交给研习室（状态改待发，返回后台地址） |
| `POST` `GET` `PUT` | `/api/topics/{id}/outline` | 拍摄提纲 |
| `GET` `POST` | `/api/topics/{id}/qa` | 三点评分（读结果 / 重评） |
| `POST` `DELETE` | `/api/topics/{id}/focus` · `/api/topics/{id}/snooze` · `POST /api/topics/{id}/stage` | 做这条 / 放回池子 · 暂不拍 / 恢复 · 退回提纲 |
| `GET` `PUT` | `/api/reach?days=14` | 触达：每天各平台合计、日均、30 天节奏；手填某平台某天的播放 |
| `GET` `POST` `DELETE` | `/api/anna?scope=input\|board\|work:{id}\|output` | Anna 对话：读线程 / 发一句 / 清空 |
| `GET` `PUT` `POST` | `/api/topics/{id}/video-project` · `…/worktable` · `/api/video-projects` | 口播项目进度与 worktable 导入 |
| `GET` `PUT` | `/api/topics/{id}/publish` | 关联已发视频与数据 |
| `GET` `PUT` | `/api/topics/{id}/copy` · `PUT /api/topics/{id}/platforms` | 发布标题和简介（各平台共用）与发布状态 |
| `GET` `POST` | `/api/review` · `/api/review/generate` | 每周复盘 |
| `GET` `POST` | `/api/topics/{id}/opening` | 开头 15 秒检查 |
| `GET` | `/api/skills` | Skills |
| `GET` `POST` | `/api/accounts` · `/api/mine` · `/api/outliers` | 账号、我的视频、爆款 |
| `GET` `POST` | `/api/jobs` · `/api/reports` | 拆解队列与报告 |

## 配置

| 项 | 说明 | 默认值 |
|---|---|---|
| 设置 · Obsidian 库路径 | 读取进项的库；一般写在 profile.yaml 的 `vault.path` | 空 |
| 设置 · 研习室电脑后台地址 | 「交给研习室」时打开 | 空 |
| 设置 · 口播视频项目目录 | ask-park-video 项目所在目录；一般写在 profile.yaml 的 `video_projects_root` | `~/Movies/口播项目` |
| 设置 · 爆款门槛 | 点赞 ÷ 账号自身中位数 | `5×` |
| `CONTENT_STUDIO_HOME` | 工作台自己的文件放哪（SQLite、报告、草稿、cookies、运行日志） | `~/.config/content-studio` |
| `CONTENT_STUDIO_PROFILE` | profile.yaml 的位置 | 仓库根目录 → `$CONTENT_STUDIO_HOME/profile.yaml` |
| `CONTENT_DOWNLOADER_PATH` | content-downloader 路径 | `~/work/content-downloader` |
| `CONTENT_STUDIO_LLM_CMD` | 结构拆解命令（stdin 提示词 → stdout JSON） | `claude -p --model sonnet …` |
| `CONTENT_STUDIO_WRITER_CMD` | 写文章命令 | `claude -p --model opus …`（允许 Skill/Read） |
| `CONTENT_STUDIO_BRIEF_CMD` · `…_OUTLINE_CMD` · `…_QA_CMD` · `…_REVIEW_CMD` | 推荐 / 提纲 / 三点评分 / 复盘命令 |
| `CONTENT_STUDIO_ANNA_CMD` | Anna 用的命令（默认本机 `claude -p --model sonnet --output-format json`，全部工具禁用；换 Codex 改这一项） | 本机 `claude -p`，禁用工具 |
| `CONTENT_STUDIO_ANNA_ROLE` · `CONTENT_STUDIO_WORKFLOWS` | Anna 的角色文件、提纲框架文件夹；一般写在 profile.yaml 的 `anna:` 里，这两个环境变量只是显式覆盖 | 仓库自带的通用版 |

## For AI Agents

```yaml
name: content-studio
version: 0.1.0
capability:
  summary: Local daily content-production workbench for one creator — Obsidian inbox to topics, khazix-writer article drafts, and Douyin breakout teardowns.
  in: Obsidian vault folders (read-only) + Douyin profile/video URLs
  out: today plan, topics, article drafts (Markdown), teardown reports (JSON/Markdown)
  fail:
    - "vault path missing → 404 with Chinese guidance"
    - "Douyin verification or anti-spam → stop, no retry"
    - "claude CLI logged out → task failed with re-login message"
api_base_url: http://127.0.0.1:8780
endpoints:
  - path: /api/today/plan
    method: GET
    description: six steps of today's line with done flags
  - path: /api/topics
    method: POST
    description: create a topic
    body:
      content_type: application/json
      schema:
        title: string
        formats: article|video|both
        note_paths: list[string]
  - path: /api/topics/{id}/write
    method: POST
    description: start writing an article draft in the background
install_command: python3 -m pip install -e .
start_command: python3 -m content_studio serve
health_check: GET /api/state
```

```python
import httpx, time

base = "http://127.0.0.1:8780"
plan = httpx.get(f"{base}/api/today/plan").json()
topic = httpx.post(f"{base}/api/topics", json={"title": "为什么用了 AI 反而更累", "formats": "article"}).json()
httpx.post(f"{base}/api/topics/{topic['id']}/write")
while httpx.get(f"{base}/api/topics").json()[0]["write_state"] == "running":
    time.sleep(10)
draft = httpx.get(f"{base}/api/topics/{topic['id']}/article").json()["markdown"]
```

## 想看这些决定是怎么做出来的

[`decision-log.md`](decision-log.md) 记着 56 条，每条都是同一个格式：当时面对什么、
定了什么、为什么、怎么验证的、踩了什么坑。按时间累积，最新的在最后。

几条能说明这里的取舍口味：

| | |
|---|---|
| [老师和对标合成一类](decision-log.md) | 先分开，后来发现分类的唯一理由随着推荐功能一起消失了，于是收回去 |
| [删掉「今天推荐拍」](decision-log.md) | 每天烧一次大模型，但前端从来没用它的一半输出——不能证明有用就删 |
| [平台状态五种而不是两种](decision-log.md) | 「没有通道」不等于「没连上」，「平台封禁」不等于「登录过期」。一个永远亮不起来的灯就是骗人 |
| [通道状态改成真探测](decision-log.md) | 同一个毛病犯了三次：用 cookie 文件的日期猜。能直接问就别猜 |
| [写死日期的时间炸弹](decision-log.md) | 一个测试在第 7 天必然失败，跟代码无关。附带一个把时钟拨快的排查工具 |

## 相关项目

| 项目 | 关系 |
|---|---|
| [content-downloader](https://github.com/zinan92/content-downloader) | 抖音作品列表与视频下载的唯一入口 |
| [content-extractor](https://github.com/zinan92/content-extractor) | 视频转写（mlx-whisper） |
| [park-koubo-workflow](https://github.com/zinan92/park-koubo-workflow) | Park 的口播视频工作流 skill |
| [content-production](https://github.com/zinan92/content-production) | Content 宇宙注册表 |

## 跨仓库的契约

工作台不装、不改口播 workflow，只按约定**读**一个项目目录里的产物来判断 14 步走到哪（`video_project.py`，`SUPPORTED_LAYOUT = "v2.6"`），
并在后台用本机 `claude` 代跑到下一个审批门（`workflow_runner.py`）。skill 本身没有版本字段，所以这条契约靠测试守：
[park-koubo-workflow](https://github.com/zinan92/park-koubo-workflow) 改了产物名或步骤编号，`tests/test_video_project.py` 会先红，再一起改 `SUPPORTED_LAYOUT`。

## License

[MIT](LICENSE)。拿去用、拿去改都可以；里面的判断口味（三点评分、时间窗、爆款门槛）是照着一个人的习惯调的，装完先在设置页和 `profile.yaml` 里改成你的。
