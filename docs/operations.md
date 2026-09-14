# 运行与维护（Park 的 Mac）

- 常驻服务：launchd `com.wendy.content-studio`，开机自启、崩溃自动拉起，监听 `127.0.0.1:8780`。
- 改完代码后重启：`launchctl kickstart -k gui/$(id -u)/com.wendy.content-studio`
- 日志：`~/Library/Logs/ContentStudio/content-studio.{stdout,stderr}.log`
- 外网访问走带密码的反向代理与 Cloudflare Tunnel，配置在 park-ai-intel 仓库 `deploy/content-studio/`（私有）。
- launchd 环境需要 `USER` / `LOGNAME`，否则 `claude` CLI 找不到钥匙串里的登录信息。
- 数据：`~/.config/content-studio/`（`data/studio.sqlite3`、`studio/reports/`、`m1/reports/` 旧样本、`drafts/`）。
- 每日同步：`python3 -m content_studio write-schedule` 只生成 plist，是否启用由 Park 决定。
