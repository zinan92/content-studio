# AGENTS.md — content-studio

## Operating pointer

Read `NORTH_STAR.md`, `REGISTRY.md`, and the latest relevant entry in `daily/`
before planning or changing this repository. The cross-project operating rules
live in the canonical Park Operating System manual; this file holds only this
project's local delta.

## Project delta

- **Repository purpose:** 本地优先监控和拆解抖音长视频，回答一条视频为什么爆、为什么不爆。
- **Local non-negotiables:** `docs/spec.md` 是需求合同；视觉与交互基线是 North Star 里的线上样稿，不是接口合同；转写文字是拆解主材料；抖音登录 cookies 只在仓库外本机使用。
- **Verify with:** `git diff --check`；项目测试命令；`gitleaks detect --source . --no-banner`（若已安装）。
- **Do not:** 不发布、评论、私信或代操作任何账号；不把 cookies、登录凭据或本机数据上传到仓库或第三方；不把“5 类生态位”标签和“四步结构检查”写成爆款判定规则。

Do not copy the company operating manual here. Update this local delta only
when the project needs a durable exception or operating instruction.

## Agent skills

### Issue tracker

Issues for this repo live on GitHub at `zinan92/content-studio`; use the `gh`
CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the canonical five labels mapped in `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repository. See `docs/agents/domain.md` for the
consumer rules.
