# 运行与维护（Park 的 Mac）

- 常驻服务：launchd `com.wendy.content-studio`，开机自启、崩溃自动拉起，监听 `127.0.0.1:8780`。
- 改完代码后重启：`launchctl kickstart -k gui/$(id -u)/com.wendy.content-studio`
- 自动上线（2026-10-01）：`main` 要两个 CI 检查都过才能合并；开 PR 以后 `gh pr merge --auto --squash`，CI 过了 GitHub 自己合。
  本机 launchd `com.wendy.content-studio-autodeploy` 每 5 分钟跑 `~/.local/bin/content-studio-autodeploy`：
  `~/work/content-studio` 在 main、没有没提交的改动时快进拉取；改到程序（不只是页面、文档）才走 `content-studio-restart`
  （有发布、写作、出图、转写在跑就等下一轮）。避开 09:25–09:50、22:25–22:35 和整点半点前后一分钟。日志 `~/Library/Logs/ContentStudio/autodeploy.log`。
- 日志：`~/Library/Logs/ContentStudio/content-studio.{stdout,stderr}.log`
- 外网访问走带密码的反向代理与 Cloudflare Tunnel，配置在 park-ai-intel 仓库 `deploy/content-studio/`（私有）。
- launchd 环境需要 `USER` / `LOGNAME`，否则 `claude` CLI 找不到钥匙串里的登录信息。
- 数据：`~/.config/content-studio/`（`data/studio.sqlite3`、`studio/reports/`、`m1/reports/` 旧样本、`drafts/`）。
- 每日同步：`python3 -m content_studio write-schedule` 只生成 plist，是否启用由 Park 决定。
- 所有会改数据的 `/api` 请求必须带请求头 `X-Content-Studio: 1`，并且 Origin（如有）必须是本站；命令行调试用 `curl -H 'X-Content-Studio: 1' ...`。这是为了防止别的网站借浏览器里保存的代理密码替 Park 触发后台代跑或确认发布。
