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

## 2026-09-14 — 热点不接抖音站内搜索（#20）

**Decision:** 热点只用三类不需额外抓取的来源：对标账号 48 小时爆款、Park 自己的 AI/财经日报头条、剪藏与日报里重复出现的话题（本地统计）。

**Why:** 用已签名客户端对 `/aweme/v1/web/search/item/` 发 1 次请求即返回 `antispam_check / hit_shark`。North Star 要求遇风控立即停止、不绕过；浏览器自动化抓搜索同样属于绕过。

**Gotchas:** 同一条新闻会在日报的「快讯」「深读」「视频更新」重复出现，头条和话题计数都按标题前 16 个字去重；英文词过滤月份缩写等噪声。

## 2026-09-14 — 文章线：卡兹克写作出草稿，研习室手动导入（#22）

**Decision:** 选题「写文章」在后台调用本机 `claude -p --model opus`，允许 Skill/Read/Glob/Grep，提示词要求使用 khazix-writer 写法、作者是 Park；草稿存 `~/.config/content-studio/drafts/topic-<id>/`，不写回 Obsidian。「交给研习室」= 复制正文 + 打开设置里的研习室电脑后台地址 + 状态改待发；发布仍由 Park 在研习室完成。

**Why:** 研习室的 device intake 接口（Obsidian 插件用的那条）真实环境验收仍未通过（wechat-xingqiu#207），现在接自动入草稿箱会建立在未验证的合同上。

**Gotchas:** khazix-writer 默认会带卡兹克本人的署名、邮箱和固定结尾，提示词明确禁止，`extract_article` 再做一道检查（命中即重试）。launchd 下调用 claude CLI 需要环境里有 USER/LOGNAME。真实测试：一篇 2700 字的文章约 2 分钟。

## 2026-09-14 — 口播 workflow 以「读产物」方式嵌入（#40）

**Decision:** 工作台不运行 ask-park-video，只读项目目录：按 workflow v2.6 每一步的完成证据判断当前 Step 与审批门（H1/H2/H3），project.json 的状态标签只在该步没有必需产物时才算数；给出一键复制的继续命令。唯一的写操作是「新建项目文件夹」（README + 拍摄提纲副本）。

**Why:** 口播 workflow 是长任务、要改媒体文件、有三个人工审批门，由 Claude/Codex 在前台跑更安全；工作台负责让 Park 随时知道剪到哪、下一步做什么。后台代跑列为 P3-2，需 Park 确认。

**Gotchas:** 现有项目在外接硬盘 `/Volumes/Phone SSD/视频/exports`，都是 v2.6 之前的目录（无 project.json，成片叫 final-video.mp4 或 delivery/final-video.mp4），按旧版只识别是否有成片；硬盘没接时页面提示而不报错。worktable.html 以 `CSP: sandbox allow-scripts allow-downloads` 返回，能用但碰不到工作台 API。

## 2026-09-14 — worktable 导入由浏览器读文件（#40 后续）

**Decision:** H1 阶段在工作台里「选择导出的 worktable.json」或粘贴 JSON 导入到 `analysis/worktable.json`，校验 schema `park-video-worktable/v1` 与项目名，不默认覆盖。`analysis/worktable.html` 不加沙箱返回。

**Why:** worktable 把 Park 的选择存在 localStorage，沙箱源里不可用，刷新会丢；该页面由 Park 自己的 skill 生成，可信。

**Gotchas:** launchd 下的 Python 读 `~/Downloads` 会触发 macOS 隐私授权弹窗并阻塞请求（实测卡死），所以服务端永远不扫描「下载」文件夹。

## 2026-09-14 — 后台代跑口播 workflow，审批在工作台里点（#56）

**Decision:** Park 授权后，工作台可以在后台用 `claude -p --model opus`（允许 Skill/Bash/Read/Write/Edit/Glob/Grep，工作目录与 --add-dir 都是项目目录）跑 ask-park-video 到下一个审批门；一次只跑一个，进程组独立于服务（重启不打断），退出码写在日志旁边，可中止。H1/H2/H3 在工作台里看材料后点批准，写入 project.json 的 approvals（by Park / via content-studio）并追加 process-log。项目停在审批门时不允许启动。

**Why:** Park 在外面也要能推进剪辑；三个审批门仍然由 Park 本人决定。

**Gotchas:** H1 批准要求 worktable.json 已导入；旧版目录（无 project.json）不能代跑。

## 2026-09-14 — 一键发布必须 Park 确认；堵住跨站写请求（#57）

**Decision:** 发布分两段：准备（冻结成片路径、平台文案、草稿/公开方式）→ Park 在工作台点「确认发布」才执行，确认窗口 30 分钟，服务端没有确认不执行。通道复用 content-ops 的视频号 / B 站 / YouTube 脚本（视频号 headless），登录只看凭据文件日期，不代登录。所有非 GET 的 `/api` 请求要求 `X-Content-Studio: 1` 且 Origin 同源；后台代跑额外禁用 WebFetch/WebSearch。

**Why:** Park 授权「替我做决策，每次发布需要我确认」。安全复查指出：工作台经密码代理暴露在外网，浏览器缓存的 Basic Auth 会让其他网站能用简单表单 POST 触发代跑或确认发布。

**Gotchas:** 2026-09 时视频号、B 站 cookie 与 YouTube token 都是 5 月的，第一次发布大概率需要 Park 在电脑上重新登录。

## 2026-09-15 — 简化版：每天只看读 / 拍 / 发（#62）

**Decision:** 首页主线从 8 步收成 3 组（读、拍、发），其余步骤作为小字挂在组下，判定规则不变；首页加「连续拍摄天数」，断了标红。左侧主导航只留 今天 / 每日统筹 / 选题 / 视频 / 文章 / 每周复盘，其余放进「更多」。热点页取消，对标爆款和日报头条放到统筹页下方，并作为统筹的输入。Skills 并入设置页。文案只自动生成抖音、视频号、研习室，其余平台收在「更多平台」手填，已有记录保留。每周复盘只留数据表、做对 / 问题和「下周只改一件事」。对标爆款自动拆解只拆 ≥5×（独立设置 auto_enqueue_threshold），每天最多 2 条；对标报告 7 天没看，读列表时自动归档（不开后台定时任务）。

**Why:** 第一性原理复盘：瓶颈是拍摄，不是信息。Park 说「确实有点复杂，按你的建议先改一个版本」。

**Gotchas:** `/api/hot`、`hot.py`、七个平台的 PLATFORMS 和发布记录都保留，只是界面收起；旧书签 #hot / #skills 分别落到统筹和设置。

## 2026-09-15 — 开头 15 秒检查读项目字幕，不另做转写（#64）

**Decision:** 视频页的剪辑进度里加「开头 15 秒」：读口播项目里已有的字幕（成片 final-video.srt 优先，其次 Hook 剪辑，再次原始录音 source.srt），取前 60 秒，和提纲「主线」一起交给 sonnet 判断主张第一次出现的秒数；≤15 秒算过。秒数必须对上某句字幕开头、引用必须是字幕原文，否则重试。只抛话题（「今天聊聊……区别」）不算说出主线。结果存 drafts/topic-N/opening.json，不改项目文件。

**Why:** 复盘数据：Park 的观众平均只看 14–26 秒，2 秒跳出 35–39%，跑题越少表现越好。录完就能知道开头有没有问题，比发出去 48 小时后再拆解早。

**Gotchas:** 第一版提示词把「抛出话题」判成说出主线（9/7《AI用法变化》误判为 1.4 秒通过），已改提示词，同一条复测为「前 60 秒没说出主线」。

## 2026-09-15 — 工作台按「进项 → 加工中 → 已发出」重组（#66）

**Decision:** 不再按时间（今天 / 每日统筹）组织，按内容所处阶段组织：进项（Newsletter、Clippings、我收藏的、我写的）、加工中（一条条视频，提纲 → 录制 → 剪辑 → 待发，列由文件证据自动决定）、已发出（数据与复盘）。文章和视频不再分开入口，新选题一律 formats=both；`formats` 列保留不删。每天 08:30 后日报一出，服务端自动生成「今天推荐拍」，每天只跑一次，失败不自动重试。进项里已经做成视频的笔记标「已在做 / 已发出」；Park 在工作台外拍过的笔记可以标「拍过了」，推荐不再使用它。「剪藏 / 收藏 / 原始输出」改名为 Clippings / 我收藏的 / 我写的（内部 key 不变）。推荐去重读近 90 天全部已发视频标题。

**Why:** Park 2026-09-15：「前、中、后，即 Input、Processing 和 Output」「文章和视频其实是同样的」「自动出今天推荐拍」；并指出推荐里的「问卷」其实前两天已经拍过（9/11 FDE 那条）。

**Gotchas:** 标题相似度认不出「问卷」和「给每一个业务匹配一个 FDE」是同一条，所以用手动「拍过了」而不是自动猜。

## 2026-09-15 — 三段界面上线：进项 / 加工中 / 已发出（#68）

**Decision:** 左侧只剩三段（深色导轨上连成一条线，进项靛蓝、加工中钨丝橙、已发出信号绿，页面强调色跟着阶段走）加设置。删掉 今天 / 每日统筹 / 选题 / 文章 / 热点 页面和对应代码（today.js、topics.js、briefing.js、hot.js、recent.js、review.js、collect.js，`/api/today/plan`、`/api/hot`、日报头条与高频话题统计）。文章变成一条视频的页签；复盘、我的视频、对标雷达、拆解报告收在「已发出」的子导航，拆解队列折叠在报告页底部。已发出概览用图表：每条视频倍数（90 天时间轴）、2 秒跳出 / 平均观看 / 涨粉 / 收藏赞走势。只有挂上抖音视频才算「已发出」，文章先发不让卡片离开看板。

**Why:** Park：「前、中、后，即 Input、Processing 和 Output」「页面太普通」「复盘可以放 dashboard、charts」。

**Gotchas:** 真实数据截图不进公开仓库（README 旧截图已删，没有换成真实数据截图）。「问卷」那条笔记正是看板上《越会用 AI 的人，越容易做出没人要的东西》的来源，Park 说已经以 9/11 FDE 那条拍过，已归档该选题并把笔记标「拍过了」。
