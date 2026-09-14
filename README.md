# content-studio

内容拆解台是 Park 的本地优先抖音内容监控与拆解工具。它的主材料是视频转写文字，账号自身的点赞中位数用于爆款基准；cookies、后台数据和下载产物只存本机。

## 一条命令启动

```bash
cd ~/work/content-studio
python3 -m content_studio serve
```

打开 <http://127.0.0.1:8780>（只监听本机）。关掉终端即停止；数据保存在 `~/.config/content-studio/`，重启后都在。如果提示端口被占用，说明常驻服务已经在跑，直接打开链接即可。

在 Park 的 Mac 上它作为常驻服务运行（launchd `com.wendy.content-studio`，开机自启、崩溃自动拉起），并通过带密码的 `https://studio.park-ai-intel.com`（网站入口 `park-ai-intel.com/studio`）从外网访问；接入方式见 park-ai-intel 仓库 `deploy/content-studio/README.md`。改完代码后重启：`launchctl kickstart -k gui/$(id -u)/com.wendy.content-studio`。拆解需要本机 `claude` 命令行处于登录状态。

报告文件在 `~/.config/content-studio/studio/reports/<视频编号>/`；M1 阶段生成的样本报告在 `~/.config/content-studio/m1/reports/`，网页会同时读取两处。

四个页面：

| 页面 | 能做什么 |
| --- | --- |
| 我的视频 | 首次打开粘贴自己的抖音主页链接完成连接；看粉丝、近 10 条播放中位数、近 5 条涨粉、平均观看时长；作品表可排序，含后台涨粉 / 5 秒完播 / 2 秒跳出 / 平均观看；每条可一键拆解或看报告。 |
| 对标雷达 | 「加入对标账号」粘贴主页链接（抖音立即同步；小红书 / X / 视频号入库并标"抓取待接入"）；账号卡片显示点赞走势、中位数、爆款数、同步状态；门槛滑块实时筛选爆款；超过门槛的作品自动进入拆解队列（同时最多 8 条）。 |
| 拆解队列 | 粘贴视频链接或分享口令入队；显示下载 → 转文字 → 结构拆解 → 报告四个阶段和失败原因；排队中的可取消，失败的可重试；服务重启后未完成的任务自动恢复。 |
| 拆解报告 | 数据（倍数、收藏/赞、转发/赞、评论/赞、后台指标）、主线一句话、自己视频的"观众平均看到的前 N 秒"、可点击的分段时间轴（斜纹 = 不服务主线）、为什么爆 / 为什么散（每条附原文时间点）、逐段原文、每段语速。 |

## 首次准备

```bash
python3 -m pip install -e '.[dev]'
```

- 需要本机有 `~/work/content-downloader`（抖音下载与签名请求）和已安装的 `content-extractor`（转写）。下载器路径可用环境变量 `CONTENT_DOWNLOADER_PATH` 改。
- 抖音登录 cookies：在浏览器登录抖音网页版和创作者中心后导出到 `~/.config/content-studio/douyin-cookies.json`，权限 `600`。页面顶部会提示 cookies 缺失或不安全。
- 拆解调用本机已登录的 `claude` 命令行；可用 `CONTENT_STUDIO_LLM_CMD` 换成其他命令。

## 命令行

| 命令 | 作用 |
| --- | --- |
| `python3 -m content_studio serve` | 启动网页（默认端口 8780）并在后台串行处理拆解队列 |
| `python3 -m content_studio sync` | 一次性同步：所有抖音账号作品 + 自己的后台数据 + 自动入队爆款；遇到抖音验证立即停止 |
| `python3 -m content_studio work` | 不开网页，把队列跑完后退出 |
| `python3 -m content_studio add-account <主页链接> [--self]` | 命令行加账号 |
| `python3 -m content_studio creator-sync` | 只抓自己的创作者后台数据（最近 90 天） |
| `python3 -m content_studio pipeline --url <视频链接>` | 不入库，直接对链接出报告 |
| `python3 -m content_studio write-schedule` | 生成每日同步的 launchd 配置文件，**只写文件不启用**；输出里有启用 / 停用命令 |

## 创作者后台数据

`creator-sync` 从 `creator.douyin.com` 的作品列表读取最近 90 天记录，保存播放、完播率、5s 完播、封面点击率、2s 跳出、平均观看时长、点赞、分享、评论、收藏、主页访问和粉丝增量，按作品 ID 幂等更新；串行分页、页间等待。

## 拆解流水线

把任意抖音视频链接串成：下载（`content-downloader`）→ 转写（`content-extractor`）→ 结构拆解（模型）→ 报告。

```bash
PYTHONPATH=~/work/content-downloader python3 -m content_studio pipeline \
  --url https://www.douyin.com/video/7651653378111540495 \
  --cookies ~/.config/content-studio/douyin-cookies.json \
  --data-dir ~/.config/content-studio/m1 \
  --downloads-dir ~/.config/content-studio/downloads
```

- **判断与计算分离**：主线、按意思分段、每段是否服务主线（附理由）、"为什么爆 / 为什么散"由模型给出；收藏/赞、转发/赞、评论/赞、账号点赞中位数倍数等数字由代码算好再交给模型，结论必须引用数字，不合格会带错误重试一次。
- **证据可复验**：每条结论的引文由代码按时间点回查真实转写，不采用模型复述。
- **账号基准**：按作者近 60 条非置顶作品的点赞中位数计算倍数，缓存 24 小时（`data-dir/baselines/`）。
- **自己的视频**：若 `creator-sync` 已存该视频后台数据，报告增加"观众平均看到的前 N 秒"一节；对标视频没有这一节。
- **模型**：默认调用本机已登录的 `claude -p --model sonnet`（禁用所有工具）；可用环境变量 `CONTENT_STUDIO_LLM_CMD` 换成其他命令，命令需从标准输入读提示词、向标准输出写 JSON。
- **转写纠错**：`config/glossary.json` 词表，增删不需要改代码。

报告写入 `data-dir/reports/<content_id>/report.json` 与 `report.md`。结构标签和结论是待验证假设，不是爆款判定规则。

## 输入 / 输出 / 失败合同

```text
in   external browser-export cookies JSON + manual creator-sync command
out  local SQLite records keyed by video_id, with fetched_at and raw_json
fail missing/unsafe cookies -> clear error
fail expired session -> clear re-login message
fail CAPTCHA/risk control -> stop immediately and report
```

数据库表 `creator_video_metrics` 的每行对应一条作品，`raw_json` 保存该作品的原始后台字段；数据库默认在仓库外的 `~/.config/content-studio/data/`，目录权限为 `700`，数据库权限为 `600`。

## 验证

```bash
python3 -m pytest -q
git diff --check
```

项目需求合同在 [`docs/spec.md`](docs/spec.md)，视觉与交互基线在 [`docs/prototype/index.html`](docs/prototype/index.html)。不要把样稿里的静态数组当作接口合同。

## 边界

- 不发布内容、评论、私信或代操作账号。
- 不自动启用任何定时任务：每日同步需要 Park 本人运行 `write-schedule` 输出里的启用命令。
- 抖音同步每账号最多 3 页、页间 ≥1.5 秒、串行；遇到验证页立即停止并在页面上提示。
- 不把 cookies、原始响应或本机数据库提交到 GitHub。
- “5 类生态位”和“四步结构检查”只允许作为待验证报告维度，不能成为爆款判定规则。
