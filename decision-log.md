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

---
