# AGENTS.md — content-studio

## Operating pointer

Read `NORTH_STAR.md`, `REGISTRY.md`, and the latest relevant entry in `daily/`
before planning or changing this repository. This file is self-contained: an
agent working from a clone needs nothing outside this repository.

## How work lands here

- One task = one GitHub issue = one PR onto `main`; branch names `feat/…` / `fix/…`.
- Commit subject in Chinese, imperative, says what changed for the person using it
  (see `git log`); body says why.
- Before opening a PR: `git diff --check` and `python3 -m pytest -q` must pass; CI runs both.
- `decision-log.md` gets an entry when a durable choice is made (format: 面对什么 / 定了什么 /
  为什么 / 怎么验证 / 踩了什么坑). `daily/` is dated progress; `REGISTRY.md` is the current snapshot.

## Project delta

- **Repository purpose:** 本地优先监控和拆解抖音长视频，回答一条视频为什么爆、为什么不爆。
- **Local non-negotiables:** `docs/spec.md` 是需求合同；视觉与交互基线是 North Star 里的线上样稿，不是接口合同；转写文字是拆解主材料；抖音登录 cookies 只在仓库外本机使用。
- **Verify with:** `git diff --check`；项目测试命令；`gitleaks detect --source . --no-banner`（若已安装）。
- **Do not:** 不发布、评论、私信或代操作任何账号；不把 cookies、登录凭据或本机数据上传到仓库或第三方；不把“5 类生态位”标签和“四步结构检查”写成爆款判定规则。

Update this file only when the project needs a durable exception or operating
instruction.

## Agent skills

### Issue tracker

Issues for this repo live on GitHub at `zinan92/content-studio`; use the `gh`
CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the canonical five labels mapped in `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repository. See `docs/agents/domain.md` for the
consumer rules.
