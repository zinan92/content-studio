# content-studio

内容拆解台是 Park 的本地优先抖音内容监控与拆解工具。它的主材料是视频转写文字，账号自身的点赞中位数用于爆款基准；cookies、后台数据和下载产物只存本机。

## 当前能力

M1-2 已提供手动 creator 后台数据快照：从 `creator.douyin.com` 的作品列表读取最近 90 天记录，保存播放、完播率、5s 完播、封面点击率、2s 跳出、平均观看时长、点赞、分享、评论、收藏、主页访问和粉丝增量，并按作品 ID 幂等更新。

## 快速开始

```bash
python3 -m pip install -e '.[dev]'
python3 -m content_studio creator-sync \
  --cookies ~/.config/content-studio/douyin-cookies.json \
  --db ~/.config/content-studio/data/creator-metrics.sqlite3
```

默认命令会串行分页请求并在页间等待 1 秒。可用 `--days`、`--delay-seconds` 和 `--page-size` 调整窗口与节奏。cookies 文件必须在仓库外且权限为 `600` 或更严；没有登录态时重新由 Park 在浏览器登录并导出，不尝试绕过验证。

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
- 不开启 M2 定时调度；当前只支持手动触发。
- 不把 cookies、原始响应或本机数据库提交到 GitHub。
- “5 类生态位”和“四步结构检查”只允许作为待验证报告维度，不能成为爆款判定规则。
