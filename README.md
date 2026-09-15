<div align="center">

# 内容工作台 · content-studio

**把一个人的内容生产分成三段：进项 → 加工中 → 已发出**

[![Python](https://img.shields.io/badge/python-3.11+-3776AB.svg?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-local_web-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![SQLite](https://img.shields.io/badge/SQLite-local_only-003B57.svg?logo=sqlite&logoColor=white)](https://sqlite.org)
[![Claude Code](https://img.shields.io/badge/Claude_Code-skills-D97757.svg)](https://docs.anthropic.com/en/docs/claude-code)
[![License](https://img.shields.io/badge/license-not_specified-lightgrey.svg)](#license)

</div>

---

```
in   Obsidian 库（Newsletter / Clippings / 我收藏的 / 我写的） + 口播 workflow 项目目录 + 抖音账号与视频
out  今天推荐拍 + 加工看板（提纲 → 录制 → 剪辑 → 待发，自动归列） + 拍摄提纲 + 开头 15 秒检查 + 剪辑进度 + 文案 + 文章 + 发出后数据图表 + 拆解报告 + 每周复盘

fail Obsidian 路径不存在      → 页面提示去设置，其它功能照常
fail 抖音 cookies 缺失/过期   → 顶部提示重新导出，不发请求
fail 抖音验证页 / 反作弊      → 立即停止抓取并显示原因，不绕过
fail 本机 claude 未登录       → 任务标失败并写明「重新登录后点重试」，不空转重试
fail 模型输出不合格          → 带错误重试，仍失败则保留原因可手动重试
```

这是 Park 自己的内容工作流，不追求普适。它只在本机运行：笔记只读、cookies 与数据不出本机；发布只在 Park 逐次确认后执行。

## 三段怎么用

| 段 | 在哪 | 看什么 / 做什么 |
|---|---|---|
| 01 进项 | 左侧「进项」 | 今天的 Newsletter（读完勾掉）；昨天到现在进来的 Clippings、我收藏的、我写的。值得做的点「拿来做」，工作台外拍过的点「拍过了」，其余忽略。已经做成视频的笔记会标出来。 |
| 02 加工中 | 左侧「加工中」 | 顶部「今天推荐拍」（日报出来后自动生成，每天一次）；下面是看板：提纲 → 录制 → 剪辑 → 待发，按提纲文件和口播项目 14 步证据自动归列，橙点表示在等你。点卡片进一条视频：拍摄提纲、剪辑进度（含开头 15 秒检查）、文案与平台、发出与数据、文章。 |
| 03 已发出 | 左侧「已发出」 | 概览：近 30 天条数、连续拍摄、倍数、涨粉、平均观看；每条视频的倍数图，2 秒跳出 / 平均观看 / 涨粉 / 收藏赞走势；这周复盘（下周只改一件事）。另有我的视频、对标雷达、拆解报告（拆解队列在报告页底部）。 |

文章和视频不分开：每条都先做视频，文章是这条视频的一个页签。

## 架构

```
┌─────────────── Obsidian 库（只读，6 个白名单文件夹）───────────────┐
│  Clippings · 002_个人收藏 · 003_park原始输出 · 006/007/009 日报    │
└───────────────┬───────────────────────────────────────────────────┘
                ▼
┌──────────────────────────── FastAPI（127.0.0.1:8780）────────────────────────────┐
│ vault.py 进项   board.py 看板   briefing.py 推荐   opening.py 开头   writer.py 文章 │
│ accounts.py 账号同步   worker.py 拆解队列   structure.py 结构拆解   store.py SQLite │
└──────┬───────────────────────┬──────────────────────────┬────────────────────────┘
       ▼                       ▼                          ▼
 content-downloader      content-extractor           本机 claude CLI
 抖音作品/下载（签名）    mlx-whisper 转写            结构判断 · khazix-writer 写作
       │                                                  │
       └──────────── ~/.config/content-studio/ ───────────┘
                     studio.sqlite3 · reports/ · drafts/（权限 600/700）
```

前端是原生 JS：`input.js`（进项）、`board.js`（加工看板）、`video.js` + 各页签文件（一条视频）、`output.js`（已发出概览），注册到 `window.VIEWS` / `window.VIDEO_TABS`。

## 快速开始

```bash
# 1. 克隆并安装
git clone https://github.com/zinan92/content-studio.git
cd content-studio
python3 -m pip install -e '.[dev]'

# 2. 依赖的两个本机能力
git clone https://github.com/zinan92/content-downloader.git ~/work/content-downloader   # 或设 CONTENT_DOWNLOADER_PATH
python3 -m pip install git+https://github.com/zinan92/content-extractor.git

# 3. 启动
python3 -m content_studio serve
# 打开 http://127.0.0.1:8780 ，在「设置」里填 Obsidian 库路径
```

- 抖音功能需要浏览器登录抖音网页版与创作者中心后，把 cookies 导出到 `~/.config/content-studio/douyin-cookies.json`（权限 `600`）。
- 拆解和写文章调用本机已登录的 [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI；写文章需要安装 [khazix-writer](https://github.com/KKKKhazix/khazix-skills) skill。

## 功能一览

| 功能 | 说明 | 状态 |
|---|---|---|
| 进项 | 今天的 Newsletter + 只读 Obsidian（Clippings / 我收藏的 / 我写的），拿来做 / 拍过了 / 忽略，已做成视频的会标出 | 已完成 |
| 今天推荐拍 | 日报出来后自动生成 1 首选 + 1 备选，来源必须来自真实材料，避开近 90 天已发视频和已有选题 | 已完成 |
| 加工看板 | 提纲 → 录制 → 剪辑 → 待发，自动归列，每张卡写明在等什么 | 已完成 |
| 拍摄提纲 | 前 15 秒 + 3–5 段 + 结尾 + 不要讲过头，可编辑 | 已完成 |
| 开头 15 秒检查 | 读项目已有字幕，判断主线第一次出现的秒数，给改法 | 已完成 |
| 剪辑进度 | 口播 workflow 14 步 / 5 阶段 / H1–H3 审批门；worktable 导入；后台代跑到审批门停下 | 已完成 |
| 文案与平台 | 自动写抖音、视频号、研习室；其他平台可手填 | 已完成 |
| 一键发布 | 视频号 / B 站 / YouTube，每次都要 Park 确认 | 已完成 |
| 文章 | 卡兹克写作出草稿，编辑、复制、下载 .md、交给研习室 | 已完成 |
| 已发出概览 | KPI + 倍数图 + 留存与涨粉走势 + 这周复盘 + 满 48 小时待拆解 | 已完成 |
| 我的视频 | 作品数据 + 创作者后台（涨粉、完播、跳出、均看） | 已完成 |
| 对标雷达 | 账号自身中位数算倍数；≥5× 自动拆解，每天最多 2 条 | 已完成 |
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

## API 参考

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/board` | 加工看板、今天推荐拍、连续拍摄天数 |
| `GET` | `/api/today/dailies` · `PUT /api/today/checks` | 当天日报与「已看」 |
| `GET` | `/api/vault/inbox?days=1&source=` | 最近进项（Clippings / 我收藏的 / 我写的），带「已做成视频」标记 |
| `GET` | `/api/vault/note?path=` | 读一条笔记（白名单内） |
| `PUT` | `/api/vault/triage` | 拿来做 / 拍过了 / 忽略 / 撤销 |
| `GET` `POST` `PATCH` | `/api/topics` · `/api/topics/{id}` | 选题 |
| `POST` | `/api/topics/{id}/write` | 后台写文章 |
| `GET` `PUT` | `/api/topics/{id}/article` · `GET …/article.md` | 草稿读写与下载 |
| `POST` | `/api/topics/{id}/handoff` | 交给研习室（状态改待发，返回后台地址） |
| `GET` `POST` | `/api/briefing` · `/api/briefing/generate` · `/api/briefing/topic` | 今天推荐拍（每天早上自动生成） |
| `POST` `GET` `PUT` | `/api/topics/{id}/outline` | 拍摄提纲 |
| `GET` `PUT` `POST` | `/api/topics/{id}/video-project` · `…/worktable` · `/api/video-projects` | 口播项目进度与 worktable 导入 |
| `GET` `PUT` | `/api/topics/{id}/publish` | 关联已发视频与数据 |
| `POST` `GET` `PUT` | `/api/topics/{id}/copy` · `PUT /api/topics/{id}/platforms` | 各平台文案与发布状态 |
| `GET` `POST` | `/api/review` · `/api/review/generate` | 每周复盘 |
| `GET` `POST` | `/api/topics/{id}/opening` | 开头 15 秒检查 |
| `GET` | `/api/skills` | Skills |
| `GET` `POST` | `/api/accounts` · `/api/mine` · `/api/outliers` | 账号、我的视频、爆款 |
| `GET` `POST` | `/api/jobs` · `/api/reports` | 拆解队列与报告 |

## 配置

| 项 | 说明 | 默认值 |
|---|---|---|
| 设置 · Obsidian 库路径 | 读取进项的库 | `~/park-hands` |
| 设置 · 研习室电脑后台地址 | 「交给研习室」时打开 | 空 |
| 设置 · 口播视频项目目录 | ask-park-video 项目所在目录 | `/Volumes/Phone SSD/视频/exports` |
| 设置 · 爆款门槛 | 点赞 ÷ 账号自身中位数 | `5×` |
| `CONTENT_DOWNLOADER_PATH` | content-downloader 路径 | `~/work/content-downloader` |
| `CONTENT_STUDIO_LLM_CMD` | 结构拆解命令（stdin 提示词 → stdout JSON） | `claude -p --model sonnet …` |
| `CONTENT_STUDIO_WRITER_CMD` | 写文章命令 | `claude -p --model opus …`（允许 Skill/Read） |
| `CONTENT_STUDIO_BRIEF_CMD` · `…_OUTLINE_CMD` · `…_COPY_CMD` · `…_REVIEW_CMD` | 统筹 / 提纲 / 文案 / 复盘命令 | 本机 `claude -p`，禁用工具 |

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
install_command: python3 -m pip install -e '.[dev]'
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

## 相关项目

| 项目 | 关系 |
|---|---|
| [content-downloader](https://github.com/zinan92/content-downloader) | 抖音作品列表与视频下载的唯一入口 |
| [content-extractor](https://github.com/zinan92/content-extractor) | 视频转写（mlx-whisper） |
| [park-koubo-workflow](https://github.com/zinan92/park-koubo-workflow) | Park 的口播视频工作流 skill |
| [content-production](https://github.com/zinan92/content-production) | Content 宇宙注册表 |

## License

未指定。
