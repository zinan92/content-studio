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
