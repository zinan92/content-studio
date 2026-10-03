# 运行与维护（Park 的 Mac）

- 常驻服务：launchd `com.wendy.content-studio`，开机自启、崩溃自动拉起，监听 `127.0.0.1:8780`。
- 改完代码后重启：`launchctl kickstart -k gui/$(id -u)/com.wendy.content-studio`
- 自动上线（2026-10-01）：`main` 要两个 CI 检查都过才能合并；开 PR 以后 `gh pr merge --auto --squash`，CI 过了 GitHub 自己合。
  本机 launchd `com.wendy.content-studio-autodeploy` 每 5 分钟跑 `~/.local/bin/content-studio-autodeploy`：
  `~/work/content-studio` 在 main、没有没提交的改动时快进拉取；改到程序（不只是页面、文档）才走 `content-studio-restart`
  （有发布、写作、出图、转写在跑就等下一轮）。避开 09:25–09:50、22:25–22:35、23:50–00:05（23:55 日结）和整点半点前后一分钟。日志 `~/Library/Logs/ContentStudio/autodeploy.log`。
- 日志：`~/Library/Logs/ContentStudio/content-studio.{stdout,stderr}.log`
- 外网访问走带密码的反向代理与 Cloudflare Tunnel，配置在 park-ai-intel 仓库 `deploy/content-studio/`（私有）。
- launchd 环境需要 `USER` / `LOGNAME`，否则 `claude` CLI 找不到钥匙串里的登录信息。
- 数据：`~/.config/content-studio/`（`data/studio.sqlite3`、`studio/reports/`、`m1/reports/` 旧样本、`drafts/`）。
- 每日同步：`python3 -m content_studio write-schedule` 只生成 plist，是否启用由 Park 决定。
- 证据图（2026-10-02 起点按钮才找）：打包页「插图」那一步下面「找证据图」，后台跑 2–4 分钟，
  只写提案（文章旁边的 `evidence/`、`evidence/proposal.json`、`article.evidence.md`）；他在同一处一张张挑，
  「放进文章」才改 `article.md`（放之前那一版存成 `article.before-evidence.md`，「撤回」靠它），公众号排版随之要重排。
  提案没挑之前，补发工作台里这篇的 X、公众号、小程序格子是「发不了」。要视频在（作品库那块 SSD 插着）。
  10/1 那晚的 launchd `com.park.content-studio.evidence`（01:30 批量跑）10/2 停了，plist 挪到
  `~/Library/LaunchAgents/disabled/`；要批量补跑：`python3 -m content_studio evidence`（单篇加 `--topic 35`）。
- 所有会改数据的 `/api` 请求必须带请求头 `X-Content-Studio: 1`，并且 Origin（如有）必须是本站；命令行调试用 `curl -H 'X-Content-Studio: 1' ...`。这是为了防止别的网站借浏览器里保存的代理密码替 Park 触发后台代跑或确认发布。


## 日结（10/3 起）

- 工作台自己在 23:55 读一次自己的抖音号和 B 站 / X / YouTube / 研习室（不碰对标、不开读数小 App），读完冻结当天的概览（`dayclose.py`，表 `day_close`），同时写一份 `~/.config/content-studio/day-close/YYYY-MM-DD.json`。存过的不改。
- 服务没开、Mac 睡着错过了：下次启动补存（kind=late，没有「各平台累计」）。10/3 以前的日子从原始读数重算（kind=rebuilt）。
- 一天按本机时区（北京）0 点到 24 点算（`reach.local_day`）。小红书只有每天 9:25 截图那一次读数，它的「一天」实际是早上到早上。
- 每天 9:30 的 launchd 同步（`com.park.content-studio.daily-sync`，`content_studio write-schedule` 生成）照旧。
