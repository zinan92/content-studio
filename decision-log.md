# Decision log — content-studio

> Keep only durable decisions. A functional PR records its decision and
> Gotchas; a pure deploy/status change is exempt unless it changes a durable
> operating fact.

## 2026-09-13 — content-studio 地基与 M1 边界

- **Context:** Park 批准新建 `zinan92/content-studio`，需求说明要求先复用已有仓库并在 M1 先保存创作者后台数据。
- **Decision:** `content-downloader` 是唯一下载入口但必须先修抖音 `_sanitize_cookies` 导入错误；`content-extractor` 是唯一转写入口；`content-intelligence` 与 `content-workbench` 只作参考，不作为依赖或扩建基座。
- **Why:** 2026-09-13 实测结果显示下载器和转写器已有可复用能力，另外两仓库的归因逻辑或产品目标不同；保持单一下载链路可减少数据和风控边界分叉。
- **Alternatives rejected:** `douyin-downloader`、`douyin-downloader-1`、`MediaCrawler` 不在范围内；不在 `content-workbench` 上扩建。
- **Evidence:** [`docs/spec.md`](docs/spec.md) 第 3 节“复用边界”；样稿 [`docs/prototype/index.html`](docs/prototype/index.html)。
- **Gotchas:** cookies 仅存仓库外本机；抖音抓取低频串行；出现验证码/风控立即停止；content-extractor 只收视频、不收纯音频，且拆解台不依赖其 LLM 摘要。

## 2026-09-13 — 对标库与报告规则

- **Context:** 需要固定 M1–M3 的对标对象和报告表达边界，避免把样稿假设写成产品规则。
- **Decision:** 初始对标账号为 dontbesilent 聊赚钱、千雪AI、柱子哥TzFilm；蜗牛学长移除；前端“粘贴主页链接加入对标账号”是必做；标签与“四步结构检查”只作为待验证参考维度。
- **Why:** 需求说明已批准名单、移除项和前端入口；公开数据无法验证对标账号涨粉，因此标签不应控制爆款判定。
- **Alternatives rejected:** 不把后台加入账号作为唯一入口；不把“5 类生态位”或四步评分作为自动判定门槛。
- **Evidence:** [`docs/spec.md`](docs/spec.md) 第 2、4、5、6 节；线上样稿 [Claude artifact](https://claude.ai/code/artifact/6d9672af-68eb-45cc-b65e-98fd07bea1dd)。
- **Gotchas:** 爆款倍数必须除以账号自己的点赞中位数，默认门槛 5×；M1 闸门是 Park 读完三份样本报告并确认“说中了”，此前不开始 M2。

## 2026-09-13 — M1 报告证据边界

- **Context:** content-extractor 的可选 LLM 重构/摘要因本机 OAuth 不可用而降级，但 M1 要求仍能以转写文字完成结构拆解。
- **Decision:** M1 报告使用 content-extractor 真实生成的带时间戳转写作为主材料；结构标签、跑题标记和“为什么爆/为什么散”由本地确定性规则生成，并在每条结论中保留原文时间点；LLM 摘要不是流水线依赖。
- **Why:** 真实转写已成功（千雪AI 69 段、柱子哥 198 段、Park 898 段），而可选 LLM 服务返回 auth unavailable；把两者分开使报告仍可复验且不把未验证推断写成事实。
- **Alternatives rejected:** 不用样稿里的静态报告数组冒充真实结果；不因摘要服务不可用而伪造“完成”；不把标签或四步结构检查作为爆款判定规则。
- **Evidence:** M1-3 PR [#4](https://github.com/zinan92/content-studio/pull/4)；本机报告回执 `~/.config/content-studio/m1/pipeline-run.json`；[需求说明](docs/spec.md) 第 3、4、5 节。
- **Gotchas:** 报告只在本机保存；每次结论必须能追到转写时间点；M1 三份报告必须由 Park 阅读确认后才允许进入 M2。

---
