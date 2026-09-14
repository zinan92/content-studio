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

## 2026-09-14 — M1-3 返工：结构判断交给模型，数字由代码算

- **Context:** Park 验收 M1-3 时发现报告"没说中"。核查代码：主线和"为什么爆"按标题关键词返回写死的句子；跑题靠一张取自样稿示例文字的关键词表；分段是固定 45 秒窗口；`_metric_value` 实际对所有指标返回空，报告没有引用任何数字。结果是只对三条验收样本看起来成立，Park 视频里的主论点（不要搭 harness）反被标跑题。
- **Decision:** 取代上一条"M1 报告证据边界"中"本地确定性规则生成结构"的做法。改为：通读全部带时间戳转写后由模型给出主线、按意思分段、逐段判断是否服务主线并写理由、写"为什么爆 / 为什么散"；所有数字（收藏/赞、转发/赞、评论/赞、账号点赞中位数倍数、后台 2 秒跳出/平均观看等）由代码计算后喂给模型，结论必须引用数字，否则带校验错误重试一次、仍不合格则该条失败；证据引文由代码按时间点回查真实转写，不采用模型复述的原文；Park 自己的视频额外分析"观众平均看到的前 N 秒"。模型调用可注入，默认走本机已登录的 `claude -p`（可用 `CONTENT_STUDIO_LLM_CMD` 替换）。转写纠错用 `config/glossary.json` 词表。来源链接只保留 `douyin.com/video/<id>`。
- **Why:** 结构判断需要理解语义，关键词规则必然对着样本过拟合；而数字和引文如果交给模型会被编造，所以判断与计算分离。
- **Alternatives rejected:** 继续扩充关键词表（无法泛化）；让模型自己读数和引用原文（不可复验）；走 CLI Proxy（本机代理密钥与配置文件不一致，调用被拒）。
- **Evidence:** PR [#4](https://github.com/zinan92/content-studio/pull/4) 返工提交；测试 `tests/test_structure.py` 含"源码不得出现样本专属字符串"的守卫；泛化样本 dontbesilent `7651653378111540495`。
- **Gotchas:** 不得为了让某条样本"看起来对"而在代码里加任何标题、关键词或写死结论——守卫测试会拦；报告质量问题改提示词或校验规则，不改成特例。对标账号没有后台数据，"前 N 秒"一节必须缺省而不是编造。

## 2026-09-14 — M2/M3 在 Park 夜间授权下连续交付

- **Context:** Park 睡前要求"做到 production ready，明早看到完整产品，做完自己验收"。原计划 M1 闸门需 Park 确认"说中了"才进 M2。
- **Decision:** 视为 Park 对连续推进 M2、M3 的明确授权，但 M1 的"说中了"仍需 Park 本人确认，验收报告单列四份样本报告请他判断。M2 用本地 SQLite（账号 / 作品 / 任务 / 设置）；抖音账号资料用 `/aweme/v1/web/user/profile/other/`、作品列表复用 content-downloader 签名客户端；爆款 = 点赞 ÷ 该账号非置顶作品点赞中位数；自动入队按"当前等待中的自动任务数"封顶（默认 8），已有报告的作品不入队。M3 用 FastAPI + 原生 JS，直接沿用样稿的样式与四页结构，只监听 127.0.0.1，默认端口 8780（8765 被本机其他服务占用）。
- **Why:** 单用户本机工具，SQLite + 无构建前端最少依赖、重启即恢复；按"等待中"封顶可以防止多账号各自触发导致一次入队几十条、通宵占满模型调用。
- **Alternatives rejected:** 自动加载 launchd 定时任务（违反零无人值守管理自动化，且 Park 不在场）；在 content-workbench 上扩建（已批准只作参考）；前端框架 + 构建链（对单用户本机工具是负担）。
- **Evidence:** PR [#7](https://github.com/zinan92/content-studio/pull/7)（M2）、M3 PR；本机真实数据：4 个账号、160 条作品、17 条 ≥5× 爆款、队列自动产出报告。
- **Gotchas:** 置顶作品不计入中位数但仍可能是爆款；图文作品不算爆款；对标视频播放量抖音不公开（显示为空，不是 0）；`write-schedule` 只写 plist，启用命令要 Park 本人执行；页面轮询时报告页不重绘，避免打断阅读。

## 2026-09-14 — "为什么散"允许纯结构原因

- **Context:** 真实队列里 1/8 的任务因"为什么散"连续三次没有引用数字而失败（例如"三条路径之间缺少清晰过渡"这类结构问题本身没有对应指标）。
- **Decision:** "为什么爆"至少一条必须引用数据；"为什么散"能用数据就引用，纯结构原因可不带数字（报告仍会附上代码计算的跑题秒数）。失败提示改为中文并提示可重试。
- **Why:** 强制给结构问题配数字会逼模型硬凑数据或反复失败，两者都比没有数字更糟。
- **Alternatives rejected:** 继续加重试次数（浪费调用且不解决问题）；由代码替模型补一条数字结论（把代码结论冒充模型判断）。
- **Evidence:** 本 PR 测试 `test_scatter_reasons_may_be_structural_without_numbers`；失败任务重试。
- **Gotchas:** 不要再把"每条结论必须带数字"加回来。

---


## 2026-09-14 — 升级为内容生产工作台（Epic #16）

**Decision:** Park 批准把内容拆解台升级为自己的内容生产工作台（方案 https://claude.ai/code/artifact/bb2c26c5-4d36-4acd-acba-3bc9d56e5686）：网页形态；左侧主题（今天/收集/选题/加工/发出/复盘/工具），首页固定「今天」；「我的账号」可以有多个；别人写的 skill 只链接署名不复制；仓库公开。

**Why:** Park 的内容链路（Obsidian 剪藏与原始输出 → 卡兹克写作 → 研习室；口播 → 剪辑 → 抖音）零件都在，缺每天打开就知道做什么的主线。检验标准：是否让 Park 每天多发一篇、多拍一条。

**Gotchas:** 前端按模块拆文件（`today.js` 等先于 `app.js` 加载，向 `window.VIEWS` / `window.TODAY_CARDS` 注册，运行时才使用 `app.js` 的全局 helper）；今日卡片按 `data-card` 复用节点，轮询重绘不会闪。
