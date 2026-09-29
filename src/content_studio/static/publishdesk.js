'use strict';
/* 04 发布台：一条内容 × 每个平台。只管发——封面、文案、文章在 03 打包里备好（pack.js）。每个平台一张它自己的上传页（720×480 的画布，瓦片里缩小、
   弹窗里放大）。灰的还没发，彩色的发了；正在发的闪。点开一张，右边是这个平台该做的事：
   手动的复制文案去粘贴，扫码的机器代发（Park 先确认），全自动的直接发，公众号交给流水线；
   抖音半自动：机器开 Chrome 填好，停在「发布」前，最后一下 Park 点。 */
window.VIEWS = window.VIEWS || {};

// pagePoll / dialogPoll：发布中时各只留一个定时刷新。9/29 以前每次重画都再挂一个，越叠越多，弹窗一秒闪好几下。
const PD = { data: null, at: 0, topicId: null, open: null, ro: null, pagePoll: null, dialogPoll: null };
const PD_STATE = { linked: ['通道已连', 'ok'], ready: ['凭据就绪', 'ok'], stale: ['要重新登录', 'warn'], blocked: ['平台限制了', 'warn'], setup: ['差一步配置', 'warn'], manual: ['手动', ''] };
const PJ_TEXT = { awaiting_confirm: '等你确认', running: '发布中', done: '已完成', failed: '失败', cancelled: '已取消', unknown: '结果不确定' };
const CANVAS_W = 720;

async function loadDesk(force) {
  const live = PD.data && PD.data.platforms.some((p) => p.job && p.job.state === 'running');
  if (!force && PD.data && PD.data.topic && PD.data.topic.id === PD.topicId && Date.now() - PD.at < (live ? 4000 : 15000)) return PD.data;
  PD.data = await api('/api/publish/desk' + (PD.topicId ? `?topic_id=${PD.topicId}` : ''));
  PD.at = Date.now();
  if (PD.data.topic) PD.topicId = PD.data.topic.id;
  paintPublishNav(PD.data);
  return PD.data;
}
window.invalidatePublish = () => { PD.data = null; PD.at = 0; };

/* 「发布完毕」：这条结了，从加工中拿掉。没发的平台（比如小宇宙）以后照样能在这里补。 */
function closeBar(d) {
  const t = d.topic;
  const sent = (d.platforms || []).filter((p) => p.shipped).length;
  if (t.closed_at) {
    return `<div class="pub-close done"><b>✓ 这条已经发布完毕</b><span>不在「加工中」了。还有没发的平台，照样可以在下面补。</span>
      <button class="linklike" type="button" data-pd-close="reopen">撤销，放回加工中</button></div>`;
  }
  if (!sent) return '';
  return `<div class="pub-close"><button class="btn primary" type="button" data-pd-close="close">✓ 发布完毕</button>
    <span>发完了就点一下，这条就结了，「加工中」里不再显示它。没发的平台以后还能在这儿补。</span></div>`;
}

async function closeTopic(id, reopen) {
  try {
    await api(`/api/topics/${id}/close`, { method: reopen ? 'DELETE' : 'POST' });
    toast(reopen ? '已放回加工中' : '发布完毕，这条结了');
    if (window.refreshTopics) await window.refreshTopics(); else { PD.data = null; renderView(); }
  } catch (err) { toast(err.message); }
}
window.refreshPublishNav = async () => { try { paintPublishNav(await api('/api/publish/desk')); } catch (_) { /* rail count only */ } };

function paintPublishNav(d) {
  const el = $('#navPub');
  if (!el) return;
  const waiting = d.candidates.filter((c) => c.stage === 'ready').length;
  const confirming = d.platforms.some((p) => p.job && p.job.state === 'awaiting_confirm');
  el.innerHTML = waiting ? `${waiting}${confirming ? '<i class="wait" title="有一条在等你确认"></i>' : ''}` : (confirming ? '<i class="wait" title="有一条在等你确认"></i>' : '');
}

/* ================= 每个平台的上传页 ================= */
const R = {
  top: (logo, items, right = '', dark = false) => `<div class="rc-top ${dark ? 'dark' : ''}"><span class="rc-logo">${logo}</span>${items.map((t, i) => `<span class="rc-nav ${i === 0 ? 'on' : ''}">${t}</span>`).join('')}<span class="spacer"></span>${right}</div>`,
  me: (handle) => `<span class="rc-me"><span class="rc-avatar"></span>${esc(handle || '我的账号')}</span>`,
  f: (label, inner, req = false, stack = false) => `<div class="rc-f ${stack ? 'stack' : ''}"><span class="rc-l">${label}${req ? '<i>*</i>' : ''}</span><div class="rc-v">${inner}</div></div>`,
  input: (val, ph, count = '', cls = '') => `<div class="rc-in ${cls}">${val ? `<span>${esc(val)}</span>` : `<span class="rc-ph">${ph}</span>`}${count ? `<em>${count}</em>` : ''}</div>`,
  area: (val, ph, count = '', lines = 4, cls = '') => `<div class="rc-in rc-ta ${cls}" style="--lines:${lines};min-height:${lines * 18 + 14}px">${val ? `<span>${esc(val)}</span>` : `<span class="rc-ph">${ph}</span>`}${count ? `<em>${count}</em>` : ''}</div>`,
  sel: (text) => `<div class="rc-in rc-sel"><span class="rc-ph">${text}</span><b>⌄</b></div>`,
  cover: (label, w, h, cls = '') => `<div class="rc-cover ${cls}" style="width:${w}px;height:${h}px">${label}</div>`,
  tags: (tags, cls = 'p') => tags.map((t) => `<span class="rc-chip ${cls}">#${esc(t)}</span>`).join(''),
  btn: (label, cls = '') => `<span class="rc-btn ${cls}">${label}</span>`,
  bar: (pct) => `<div class="rc-bar"><i style="--w:${pct}%"></i></div>`,
  count: (s, cap) => `${(s || '').length}/${cap}`,
  // 真的文章正文：只露前几段，后面淡出（全文在右边「点开看全文」）
  doc: (text, lines = 8) => `<div class="rc-doc" style="--lines:${lines}">${esc(text).split('\n\n').map((t) => `<p>${t}</p>`).join('')}</div>`,
};

function progressState(ctx) {
  // 发了 = 100%；正在发 = 动画条；其他 = 刚开始的样子（像 Park 截图里的 1%）
  if (ctx.shipped) return { pct: 100, text: '上传完成', speed: '' };
  if (ctx.live) return { pct: 35, text: '正在上传…', speed: '' };
  return { pct: 2, text: '1%', speed: '448.4KB/s · 剩余 20 分 52 秒' };
}

const REPLICA = {
  douyin(c) {
    const p = progressState(c);
    return `${R.top('抖音', ['发布视频', '发布图文', '发布全景视频'], R.me(c.handle))}
    <div class="rc-body" style="grid-template-columns:1fr 200px">
      <div class="rc-card"><h4>基础信息<span>快速填写</span></h4>
        ${R.f('设置封面', `<div class="rc-row nowrap">${R.cover('选择封面<br>横封面 4:3', 96, 72)}${R.cover('选择封面<br>竖封面 3:4', 54, 72)}${R.cover('AI 智能推荐封面', 100, 72, 'light')}</div>`, true)}
        ${R.f('作品描述', `${R.input(c.fill.title, '填写作品标题，为作品获得更多流量', R.count(c.fill.title, c.caps.title))}${R.area(c.fill.body, '添加作品简介', R.count(c.fill.body, c.caps.body), 3)}<div class="rc-row"><span class="rc-chip">#添加话题</span><span class="rc-chip">@好友</span>${R.tags(c.fill.tags)}</div>`)}
        ${R.f('官方活动', `<div class="rc-row nowrap"><span class="rc-chip outline">♪ 找要结合以要为主</span><span class="rc-chip outline">♪ 原来我也是自然的一…</span><span class="rc-chip outline">+16</span></div>`)}
        ${R.f('添加合集', `<div class="rc-row nowrap">${R.sel('合集')}${R.sel('请选择合集')}</div>`)}
      </div>
      <div style="display:flex;flex-direction:column;gap:12px">
        <div class="rc-card" style="align-items:center;text-align:center;gap:8px;padding-top:22px">
          <div style="font-size:30px;font-weight:900;color:#111">♪</div>
          <b style="font-size:12px;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(c.video ? c.video.name : '打造个人知识库….mp4')}</b>
          <small style="color:#EF4444;font-size:10.5px">上传过程中请不要删除/移动文件</small>
          ${R.bar(p.pct)}
          <div class="rc-mini">已上传：${c.shipped ? esc(c.video ? c.video.mb : '553.1') + 'MB' : '4.9MB'}/${esc(c.video ? c.video.mb : '553.1')}MB · ${p.text}<br>${p.speed || '&nbsp;'}</div>
        </div>
        <div class="rc-card" style="flex-direction:row;justify-content:space-between;align-items:center"><b style="font-size:12.5px">▤ 发文助手</b><span class="rc-ph">⌃</span></div>
      </div>
    </div>
    <div class="rc-foot">${R.btn('发布')}${R.btn('暂存离开', 'ghost')}</div>`;
  },
  channels(c) {
    return `${R.top('视频号', ['发表视频', '发表图文', '发起直播'], R.me(c.handle))}
    <div class="rc-body" style="grid-template-columns:170px 1fr">
      <div class="rc-phone">${R.cover('', 150, 0)}<p>${esc([c.fill.title, c.fill.body].filter(Boolean).join(' ') || '描述会显示在这里')}</p></div>
      <div class="rc-card">
        ${R.f('视频', `<div class="rc-row">${R.cover(c.video ? esc(c.video.name) : '拖拽或点击上传视频', 200, 56, 'light')}</div>`, true)}
        ${R.f('描述', `${R.area([c.fill.title, c.fill.body].filter(Boolean).join('\n'), '添加描述', R.count(c.fill.title + c.fill.body, c.caps.body), 3)}<div class="rc-row"><span class="rc-chip"># 话题</span><span class="rc-chip">@ 提到</span>${R.tags(c.fill.tags)}</div>`)}
        ${R.f('位置', R.sel('不显示位置'))}
        ${R.f('原创声明', `<div class="rc-row"><span class="rc-tg on"></span><span class="rc-mini">声明后可获得原创标识</span></div>`)}
        ${R.f('添加到合集', R.sel('选择合集'))}
      </div>
    </div>
    <div class="rc-foot">${R.btn('发表')}${R.btn('保存草稿', 'ghost')}</div>`;
  },
  xiaohongshu(c) {
    return `${R.top('小红书', ['发布笔记', '笔记管理', '数据看板'], R.me(c.handle))}
    <div class="rc-body" style="grid-template-columns:1fr">
      <div class="rc-card">
        <div class="rc-row" style="gap:16px;border-bottom:1px solid #E5E7EB;padding-bottom:8px"><span class="rc-nav on" style="padding:0">上传视频</span><span class="rc-nav" style="padding:0">上传图文</span></div>
        <div class="rc-row nowrap">${R.cover(c.video ? '视频封面' : '添加封面', 84, 112, c.video ? 'pic' : 'light')}${R.cover('横版 3:4', 84, 112, 'light')}${R.cover('竖版 4:3', 84, 112, 'light')}</div>
        ${R.f('标题', R.input(c.fill.title, '填写标题会有更多赞哦～', R.count(c.fill.title, c.caps.title)), false, true)}
        ${R.f('正文', `${R.area(c.fill.body, '输入正文描述，真诚有价值的分享予人温暖', R.count(c.fill.body, c.caps.body), 3)}<div class="rc-row"><span class="rc-chip"># 话题</span><span class="rc-chip">@ 用户</span><span class="rc-chip">☺ 表情</span>${R.tags(c.fill.tags)}</div>`, false, true)}
        <div class="rc-row"><span class="rc-mini">添加地点</span>${R.sel('选择地点')}<span class="rc-mini" style="margin-left:12px">权限设置</span><span class="rc-radio on">公开可见</span><span class="rc-radio">仅自己可见</span></div>
      </div>
    </div>
    <div class="rc-foot">${R.btn('发布')}${R.btn('暂存离开', 'ghost')}</div>`;
  },
  bilibili(c) {
    const p = progressState(c);
    return `${R.top('bilibili', ['视频投稿', '专栏投稿', '音频投稿', '互动视频'], R.me(c.handle))}
    <div class="rc-body" style="grid-template-columns:1fr">
      <div class="rc-card">
        <div class="rc-file"><b>${esc(c.video ? c.video.name : '还没有成片.mp4')}</b>${R.bar(p.pct)}<span class="rc-mini" style="white-space:nowrap">${c.shipped ? '上传完成' : p.pct > 2 ? '上传中' : '等待上传'}</span></div>
        <div style="display:grid;grid-template-columns:140px 1fr;gap:14px">
          ${R.cover('封面<br>拖拽或点击更换', 140, 88, c.shipped ? 'pic' : 'light')}
          <div class="rc-v">
            ${R.f('标题', R.input(c.fill.title, '请输入稿件标题', R.count(c.fill.title, c.caps.title)), true)}
            ${R.f('类型', `<div class="rc-row"><span class="rc-radio on">自制</span><span class="rc-radio">转载</span><span class="rc-check">未经作者授权禁止转载</span></div>`, true)}
            ${R.f('分区', R.sel('知识 › 科学科普'), true)}
          </div>
        </div>
        ${R.f('标签', `<div class="rc-row">${R.tags(c.fill.tags, 'p') || '<span class="rc-ph">按回车键 Enter 创建标签</span>'}<span class="rc-chip outline">+ 添加标签</span></div>`, true)}
        ${R.f('简介', R.area(c.fill.body, '填写更全面的相关信息，让更多的人能找到你的视频吧', R.count(c.fill.body, c.caps.body), 2))}
      </div>
    </div>
    <div class="rc-foot">${R.btn('立即投稿')}${R.btn('存草稿', 'ghost')}</div>`;
  },
  youtube(c) {
    return `${R.top('▶ Studio', [], R.me(c.handle))}
    <div class="rc-body" style="grid-template-columns:1fr;padding-top:10px">
      <div class="rc-card" style="gap:8px">
        <h4 style="font-size:15px">${esc(c.fill.title || 'Upload video')}</h4>
        <div class="rc-steps"><span class="on">Details</span><span>Video elements</span><span>Checks</span><span>Visibility</span></div>
        <div style="display:grid;grid-template-columns:1fr 190px;gap:16px">
          <div class="rc-v">
            ${R.input(c.fill.title, 'Title (required)', R.count(c.fill.title, c.caps.title), 'white')}
            ${R.area(c.fill.body, 'Tell viewers about your video', '', 3, 'white')}
            <div class="rc-mini">Thumbnail</div>
            <div class="rc-row nowrap">${R.cover('Upload file', 72, 42, c.shipped ? 'pic' : 'light')}${R.cover('Auto-generated', 72, 42, 'light')}${R.cover('Test & compare', 72, 42, 'light')}</div>
            <div class="rc-row"><span class="rc-mini">Audience</span><span class="rc-radio">Yes, it's made for kids</span><span class="rc-radio on">No, it's not made for kids</span></div>
          </div>
          <div class="rc-v">${R.cover(c.video ? '' : 'Uploading…', 190, 106, 'pic')}<div class="rc-mini">Video link<br><span style="color:#065FD4">https://youtu.be/…</span><br>Filename<br>${esc(c.video ? c.video.name : '—')}</div></div>
        </div>
      </div>
    </div>
    <div class="rc-foot"><span class="rc-mini">${c.shipped ? '✓ Checks complete. No issues found.' : 'Checks will run after upload.'}</span><span class="spacer"></span>${R.btn('Next', 'pill')}</div>`;
  },
  x(c) {
    const text = [c.fill.body, c.fill.tags.map((t) => '#' + t).join(' ')].filter(Boolean).join('\n');
    return `${R.top('X', [], '<span class="rc-mini">Drafts</span>', true)}
    <div class="rc-body" style="grid-template-columns:1fr;padding:22px 26px">
      <div class="rc-card" style="flex-direction:row;gap:12px;align-items:flex-start;min-height:190px">
        <span class="rc-avatar" style="width:40px;height:40px"></span>
        <div class="rc-v" style="flex:1;gap:10px">
          <div class="rc-chip outline" style="align-self:flex-start;border-radius:999px;color:var(--p);border-color:var(--p)">Everyone ⌄</div>
          ${c.article ? `<b style="font-size:19px">${esc(c.article.title)}</b>${R.doc(c.article.text, 7)}` : `<div style="font-size:17px;line-height:1.45;min-height:90px;white-space:pre-wrap;overflow:hidden;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:5;word-break:break-all">${text ? esc(text) : '<span class="rc-ph">What is happening?!</span>'}</div>`}
          <div class="rc-mini" style="color:var(--p)">🌐 Everyone can reply</div>
          <div class="rc-row" style="border-top:1px solid #E5E7EB;padding-top:10px"><span class="rc-icons">🖼 GIF ☰ ☺ 📅 📍</span><span class="spacer" style="flex:1"></span><span class="rc-ring"></span>${R.btn('Post', 'pill')}</div>
        </div>
      </div>
    </div>`;
  },
  wechat_mp(c) {
    const a = c.article;
    return `${R.top('公众平台', ['图文消息', '素材库', '发表记录'], R.me(c.handle))}
    <div class="rc-body" style="grid-template-columns:1fr 200px">
      <div class="rc-card" style="gap:8px">
        ${R.input(a ? a.title : c.fill.title, '请在这里输入标题', '', 'big')}
        <div class="rc-row"><span class="rc-mini">作者</span>${R.input(c.handle || 'Park', '请输入作者', '', '')}</div>
        <div class="rc-tools"><i>B</i><i>I</i><i>U</i><i>|</i><i>H1</i><i>H2</i><i>|</i><i>≡</i><i>⁝≡</i><i>|</i><i>🖼</i><i>🔗</i><i>❝</i></div>
        ${a ? R.doc(a.text, 11) : R.area(c.fill.body, '从这里开始写正文', '', 6, 'white')}
      </div>
      <div class="rc-v" style="gap:10px">
        <div class="rc-card" style="gap:8px"><b style="font-size:12px">封面和摘要</b>${R.cover('拖拽或选择封面 2.35:1', 168, 72, c.shipped ? 'pic' : 'light')}${R.area(a ? a.summary.slice(0, 54) : c.fill.body.slice(0, 60), '选填，不填会默认抓取正文前 54 字', '', 3)}</div>
        <div class="rc-card" style="gap:8px"><div class="rc-row" style="justify-content:space-between"><b style="font-size:12px">原创声明</b><span class="rc-tg on"></span></div><div class="rc-row" style="justify-content:space-between"><b style="font-size:12px">赞赏</b><span class="rc-tg"></span></div></div>
      </div>
    </div>
    <div class="rc-foot">${R.btn('保存为草稿', 'ghost')}${R.btn('发表')}<span class="spacer"></span><span class="rc-mini">${c.handoff_done ? '✓ 已交到排版管线' : '排版由既有管线完成'}</span></div>`;
  },
  miniprogram(c) {
    return `${R.top('小程序', ['内容推送', '素材', '数据'], R.me(c.handle))}
    <div class="rc-body" style="grid-template-columns:1fr 240px">
      <div class="rc-card">
        ${R.f('标题', R.input(c.fill.title, '推送标题', R.count(c.fill.title, c.caps.title)))}
        ${R.f('摘要', R.area(c.article ? c.article.summary : c.fill.body, '一句话说清这条讲什么', R.count(c.article ? c.article.summary : c.fill.body, c.caps.body), 3))}
        ${c.article ? R.f('正文', R.doc(c.article.text, 6)) : `${R.f('推送到', R.sel('全部订阅用户'))}${R.f('跳转', R.sel('本条视频详情页'))}`}
      </div>
      <div class="rc-card" style="gap:8px"><b style="font-size:11px;color:#6B7280">卡片预览</b>${R.cover('', 208, 96, 'pic')}<b style="font-size:12.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc((c.article && c.article.title) || c.fill.title || '标题会显示在这里')}</b><div class="rc-mini" style="display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:3;overflow:hidden">${esc((c.article && c.article.summary) || c.fill.body || '摘要会显示在这里')}</div></div>
    </div>
    <div class="rc-foot">${R.btn('推送')}${R.btn('先存着', 'ghost')}</div>`;
  },
  xiaoyuzhou(c) {
    const p = progressState(c);
    return `${R.top('小宇宙', ['发布单集', '节目管理', '数据'], R.me(c.handle))}
    <div class="rc-body" style="grid-template-columns:1fr">
      <div class="rc-card">
        ${R.f('音频文件', `<div class="rc-file"><b>${esc(c.video ? c.video.name.replace(/\.\w+$/, '.m4a') : '拖拽或选择音频（mp3 / m4a）')}</b>${R.bar(p.pct)}<span class="rc-mini" style="white-space:nowrap">${c.shipped ? '上传完成' : '等待上传'}</span></div>`, true)}
        ${R.f('单集标题', R.input(c.fill.title, '给这一集起个名字', R.count(c.fill.title, c.caps.title)), true)}
        ${R.f('单集简介', `${R.area(c.fill.body, 'Shownotes：这一集聊了什么、时间轴、提到的链接', R.count(c.fill.body, c.caps.body), 3)}<div class="rc-row">${R.tags(c.fill.tags)}</div>`)}
        ${R.f('单集封面', `<div class="rc-row">${R.cover('沿用节目封面', 64, 64, c.shipped ? 'pic' : 'light')}<span class="rc-mini">不选则沿用节目封面</span></div>`)}
        ${R.f('发布时间', `<div class="rc-row"><span class="rc-radio on">立即发布</span><span class="rc-radio">定时发布</span></div>`)}
      </div>
    </div>
    <div class="rc-foot">${R.btn('发布')}${R.btn('存草稿', 'ghost')}</div>`;
  },
};

function replica(p, d) {
  const ctx = { ...p, video: d.video, live: p.job && p.job.state === 'running', shipped: p.shipped, article: p.needs_article ? d.article : null };
  const draw = REPLICA[p.key] || REPLICA.miniprogram;
  return `<div class="rc" style="--p:${esc(p.hue)}">${draw(ctx)}</div><span class="rc-badge">预览 · 这里点不了，在右边操作</span>`;
}

function fitReplicas(root) {
  $$('.pub-shot, .rc-wrap', root).forEach((box) => {
    const w = box.clientWidth;
    if (w) box.style.setProperty('--s', (w / CANVAS_W).toFixed(4));
  });
}

/* ================= 瓦片 ================= */
function stateOf(p) {
  if (p.shipped) return ['已发', 'ok'];
  if (p.job && p.job.state === 'running') return ['发布中', 'hot'];
  if (p.job && p.job.state === 'awaiting_confirm') return ['等你确认', 'hot'];
  if (p.job && p.job.state === 'failed') return ['上次失败', 'warn'];
  if (!p.on) return ['没接这个号', ''];
  return PD_STATE[p.state] || [p.state, ''];
}

function tileAction(p, d) {
  if (p.shipped) return `<button class="btn small ghost" type="button" data-pd-open="${p.key}">看记录</button>`;
  if (p.job && p.job.state === 'awaiting_confirm') return `<button class="btn small primary" type="button" data-pd-open="${p.key}">去确认</button>`;
  if (p.job && p.job.state === 'running') return `<button class="btn small" type="button" data-pd-open="${p.key}"><span class="spin"></span> 发布中</button>`;
  if (!d.topic) return '';
  if (p.treatment === 'handoff') return `<button class="btn small" type="button" data-pd-open="${p.key}">${p.handoff_done ? '已交接 · 去发' : '交给流水线'}</button>`;
  if (p.can_auto && (d.video || p.no_video)) return `<button class="btn small primary" type="button" data-pd-open="${p.key}">机器发</button>`;
  return `<button class="btn small" type="button" data-pd-open="${p.key}">${p.admin ? '复制文案去发' : '打开'}</button>`;
}

function tile(p, d) {
  const [label, cls] = stateOf(p);
  const live = p.job && (p.job.state === 'running' || p.job.state === 'awaiting_confirm');
  const stamp = p.shipped ? `<span class="pub-stamp">✓ 已发${p.record && p.record.published_at ? ' · ' + day(p.record.published_at) : ''}</span>`
    : p.job && p.job.state === 'running' ? '<span class="pub-stamp live">发布中</span>'
      : p.job && p.job.state === 'awaiting_confirm' ? '<span class="pub-stamp wait">等你确认</span>' : '';
  const steps = d.platforms.filter((x) => x.on);
  const n = steps.indexOf(p) + 1;
  const isNext = d.topic && d.next === p.key;
  const skip = p.skipped ? '<span class="pub-stamp skip">这条不发</span>' : '';
  return `<article class="pub-tile ${p.shipped ? 'shipped' : ''} ${live ? 'live' : ''} ${p.on ? '' : 'off'} ${isNext ? 'next' : ''} ${p.skipped ? 'skipped' : ''}" data-key="${p.key}">
    ${n ? `<span class="pub-step">${isNext ? '下一步 · ' : ''}${n}</span>` : ''}
    <button class="pub-shot" type="button" data-pd-open="${p.key}" aria-label="打开${esc(p.label)}">${replica(p, d)}${stamp}${skip}</button>
    <div class="pub-cap"><i class="plat s-${p.state}"${p.state === 'manual' || p.state === 'blocked' ? '' : ` style="--plat:${esc(p.hue)}"`}>${esc(p.mark)}</i><b>${esc(p.label)}</b><small title="${esc(p.handle || '')}">${esc(p.handle || '')}</small></div>
    <div class="pub-how"><span class="ps ${cls}">${label}</span><span>${esc(p.treatment_label)}</span></div>
    <div class="pub-act">${tileAction(p, d)}</div>
  </article>`;
}

/* 按顺序带着走：这一条现在该发哪个平台 */
function guideBar(d) {
  const steps = d.platforms.filter((x) => x.on);
  const done = steps.filter((x) => x.shipped || x.skipped).length;
  const next = steps.find((x) => x.key === d.next);
  if (!next && d.topic.closed_at) return ''; // 已经发布完毕，上面那条已经说了，不再叠一条
  if (!next) return `<div class="pub-guide done"><b>✓ ${steps.length} 步都走完了</b><span>该发的都发了（跳过的不算）。下面点「这条发布完毕」收尾。</span></div>`;
  const i = steps.indexOf(next) + 1;
  // 9/29 Park：一进来就点了紫色「开始」，直接被带去抖音，可封面和文案还没做。没打包好，主按钮就是去打包。
  const missing = packMissing(d);
  if (missing.length && !done) {
    return `<div class="pub-guide pack-first"><span class="num">还没打包</span><b>先把${esc(missing.join('、'))}定稿</b>
      <small>备好了再发，每个平台点进去就是现成的</small><span class="spacer"></span>
      <button class="btn primary" type="button" data-pd-pack>去打包 →</button>
      <button class="btn ghost" type="button" data-pd-open="${next.key}">已经在外面备好了，直接发${esc(next.label)}</button></div>`;
  }
  return `<div class="pub-guide"><span class="num">第 ${i} 步 / 共 ${steps.length} 步</span><b>下一个：${esc(next.label)}</b>
    <small>${done} 个已经发了或跳过</small><span class="spacer"></span>
    <button class="btn primary" type="button" data-pd-open="${next.key}">${esc(stepVerb(next, d))} →</button>
    <button class="btn ghost" type="button" data-pd-skip="${next.key}">这条不发${esc(next.label)}，跳过</button></div>`;
}

/* 这一步点下去会发生什么，按钮上直接说：机器发，还是复制文案去平台自己传。 */
function stepVerb(p, d) {
  if (p.job && p.job.state === 'awaiting_confirm') return `去确认${p.label}`;
  if (p.treatment === 'handoff') return `把文章交给${p.label}流水线`;
  if (p.can_auto && (d.video || p.no_video)) return `发到${p.label}`;
  if (p.admin) return `复制文案，去${p.label}上传`;
  return `打开${p.label}`;
}

/* 打包还缺什么（视频要的那几样）。文字包缺了不挡：没写文章的平台，点进去会说。 */
function packMissing(d) {
  // 9/29 起按「定稿」算：做出来了但 Park 还没定稿的，也算没打包好
  if (d.approvals) {
    return [['copy', '标题和描述'], ['cover', '封面']].filter(([k]) => !(d.approvals[k] && d.approvals[k].approved && d.approvals[k].valid)).map(([, l]) => l);
  }
  const c = (d.release && d.release.covers) || {};
  const miss = [];
  if (!(c.landscape || c.portrait)) miss.push('封面');
  if (!d.has_copy) miss.push('标题和描述');
  return miss;
}

function goPack(topicId) {
  const dlg = $('#pubDlg');
  if (dlg && dlg.open) dlg.close();
  S.packId = topicId;
  go('pack');
}

async function setSkip(topicId, key, skip) {
  await api(`/api/topics/${topicId}/skip`, { method: 'PUT', body: { platform: key, skip } });
  PD.data = null; $('#publishBody').dataset.sig = '';
  await loadDesk(true);
}

/* 一个平台发完（或跳过）就接着打开下一个 */
function goNext() {
  const d = PD.data;
  const dlg = $('#pubDlg');
  if (d && d.next) { PD.open = d.next; renderDialog(); if (!dlg.open) dlg.showModal(); }
  else if (dlg.open) dlg.close();
}

/* ================= 页面 ================= */
window.resetDesk = () => { PD.data = null; PD.topicId = S.publishId; const b = $('#publishBody'); if (b) b.dataset.sig = ''; };

window.VIEWS.publish = {
  async render() {
    if (window.paintPubSubnav) { window.paintPubSubnav(); if (window.refreshBackfillCount && !window.__bfCounted) { window.__bfCounted = true; window.refreshBackfillCount(); } }
    const body = $('#publishBody');
    if (S.publishId && S.publishId !== PD.topicId) { PD.topicId = S.publishId; PD.data = null; }
    let d;
    try { d = await loadDesk(false); } catch (err) {
      // 工作台重启的那几秒会连不上：别就此停住，过一会儿再来（9/27 重启后「发布中」一直不变）
      if (!PD.data) body.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`;
      setTimeout(() => { if (S.view === 'publish') { PD.data = null; renderView(); } }, 5000);
      return;
    }
    // 只在内容真变了才重画：15 秒一次的刷新如果每次都重画，弹窗里正在输的链接会被抹掉。
    const sig = JSON.stringify([PD.topicId, d.has_copy, d.has_article, d.video && d.video.mb,
      d.candidates.map((c) => [c.id, c.stage, c.shipped_count]),
      d.next, d.platforms.map((p) => [p.shipped, p.skipped, p.state, p.on, p.handoff_done, p.job && p.job.id, p.job && p.job.state, p.job && p.job.message, p.fill.title, p.fill.body])]);
    if (body.dataset.sig === sig) return;
    body.dataset.sig = sig;
    const shipped = d.platforms.filter((p) => p.shipped).length;
    const on = d.platforms.filter((p) => p.on).length;
    $('#publishFigs').innerHTML = d.topic ? `<div class="pub-figs">
      <span>已发 <b>${shipped}</b> / ${on} 个平台</span>
      <span>成片 ${d.video ? `<b>${d.video.mb}</b> MB` : '<span class="bad">还没有</span>'}</span>
      <span>打包 ${packMissing(d).length ? `<span class="bad">还差${esc(packMissing(d).join('、'))}</span>` : '<b>✓</b>'}</span>
      <button class="linklike" type="button" data-pd-pack>${packMissing(d).length ? '去打包' : '改封面或文案'} →</button>
    </div>${releaseStrip(d.release)}` : '';
    const chip = (c, cur) => `<button class="pub-topic ${c.id === cur ? 'on' : ''}" type="button" data-pd-topic="${c.id}"><span class="ms-chip s-${c.stage}" title="${esc(c.stage_label || '')}"><i aria-hidden="true">${typeof MS_ICON !== 'undefined' ? (MS_ICON[c.stage] || '') : ''}</i>${esc(c.stage_label || '')}</span><b>${esc(c.title)}</b>${c.shipped_count === undefined ? '' : `<span class="num">${c.shipped_count}/${on}</span>`}</button>`;
    // 发不了的时候，说清最近那条卡在哪，别只说「没有」。
    const others = (d.others || []).length
      ? `<details class="pub-others"><summary>我已经有成片了，工作台还不知道</summary><div class="pub-topics">${d.others.map((c) => chip(c, null)).join('')}</div></details>` : '';
    if (!d.topic && (d.finished || !d.waiting)) {
      // 9/29：手上没有要发的。说清刚发完的是哪条（每个平台的链接能点）、下一条在哪，去全平台追踪看全貌。
      // （以前这里直接跳去全平台追踪，但跳之前已经记下「画过了」，再点「这一条」就是一片空白。）
      const f = d.finished;
      const w = d.waiting;
      body.innerHTML = `<div class="pub-idle">
          <div class="pub-idle-h"><b>手上没有要发的</b>${f ? `<span>最近一条《${esc(f.title)}》${f.shipped_count}/${f.on_count} 个平台都发完了</span>` : ''}</div>
          ${f ? `<div class="pub-idle-links">${Object.entries(f.links).sort(([a], [b]) => d.platforms.findIndex((x) => x.key === a) - d.platforms.findIndex((x) => x.key === b)).map(([, l]) => l.url
            ? `<a class="pub-idle-link" href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.label)} ↗</a>`
            : `<span class="pub-idle-link muted">${esc(l.label)} ✓</span>`).join('')}</div>` : ''}
          <p class="pub-idle-next">${w ? `下一条《${esc(w.title)}》还在<b>${esc(w.stage_label || w.stage)}</b>，剪完就会进打包。` : '「加工中」里还没有剪完的下一条。'}</p>
          <div class="pdl-acts">
            <button class="btn primary" type="button" data-pd-track>看全平台追踪 →</button>
            ${w ? `<button class="btn" type="button" data-pd-work="${w.id}">去看下一条</button>` : '<button class="btn" type="button" data-pd-board>去加工中</button>'}
            ${f ? `<button class="btn ghost" type="button" data-pd-topic="${f.id}">打开刚发完的这一条</button>` : ''}
          </div>
        </div>`;
      $$('[data-pd-track]', body).forEach((b) => (b.onclick = () => go('backfill')));
      $$('[data-pd-board]', body).forEach((b) => (b.onclick = () => go('board')));
      $$('[data-pd-work]', body).forEach((b) => (b.onclick = () => openWork(Number(b.dataset.pdWork))));
      $$('[data-pd-topic]', body).forEach((b) => (b.onclick = () => { PD.topicId = Number(b.dataset.pdTopic); S.publishId = PD.topicId; PD.data = null; history.replaceState(null, '', `#publish/${PD.topicId}`); renderView(); }));
      $('#publishFigs').innerHTML = '';
      return;
    }
    if (!d.topic) {
      const w = d.waiting;
      body.innerHTML = `<div class="pub-empty"><b>还没有能发的成片</b>
          ${w ? `<span>最近的一条是《${esc(w.title)}》，还在<b>${esc(w.stage_label || w.stage)}</b>。成片文件出现在视频项目目录里，它就会自己走到「待发」，然后出现在这儿。</span>
            <button class="btn small" type="button" data-pd-work="${w.id}">去看这一条 →</button>`
            : '<span>「加工中」里的一条走到「待发」，就会出现在这里。</span>'}
        </div>${others}
        <div class="pub-grid" style="margin-top:6px">${d.platforms.filter((p) => p.on).map((p) => tile(p, d)).join('')}</div>`;
    } else {
      const pick = d.candidates.filter((c) => c.id !== d.topic.id);
      body.innerHTML = `<div class="pub-head">
        <div class="pub-topics"><small>发这条</small>${chip({ ...d.topic, shipped_count: (d.candidates.find((c) => c.id === d.topic.id) || {}).shipped_count }, d.topic.id)}
        ${pick.map((c) => chip(c, d.topic.id)).join('')}</div>
        ${closeBar(d)}
      </div>${guideBar(d)}${others}
      <div class="pub-grid">${d.platforms.filter((p) => p.on).map((p) => tile(p, d)).join('')}</div>`;
    }
    fitReplicas(body);
    if (!PD.ro && window.ResizeObserver) { PD.ro = new ResizeObserver(() => fitReplicas(body)); PD.ro.observe(body); }
    $$('[data-pd-work]', body).forEach((b) => (b.onclick = () => openWork(Number(b.dataset.pdWork))));
    $$('[data-pd-close]', body).forEach((b) => (b.onclick = () => closeTopic(d.topic.id, b.dataset.pdClose === 'reopen')));
    $$('[data-pd-topic]', body).forEach((b) => (b.onclick = () => { PD.topicId = Number(b.dataset.pdTopic); S.publishId = PD.topicId; PD.data = null; history.replaceState(null, '', `#publish/${PD.topicId}`); renderView(); }));
    $$('[data-pd-open]', body).forEach((b) => (b.onclick = () => openPlatform(b.dataset.pdOpen)));
    $$('[data-pd-skip]', body).forEach((b) => (b.onclick = async () => { try { await setSkip(d.topic.id, b.dataset.pdSkip, true); renderView(); } catch (err) { toast(err.message); } }));
    $$('[data-pd-pack]').forEach((b) => (b.onclick = () => goPack(d.topic.id)));
    clearTimeout(PD.pagePoll);
    if (d.platforms.some((p) => p.job && p.job.state === 'running')) PD.pagePoll = setTimeout(() => { if (S.view === 'publish') { PD.data = null; renderView(); } }, 8000);
    if (PD.open) renderDialog();
  },
};

/* ================= 弹窗：这个平台该做的事 ================= */
function openPlatform(key) {
  PD.open = key;
  const dlg = $('#pubDlg');
  renderDialog();
  if (!dlg.open) dlg.showModal();
  dlg.onclose = () => { PD.open = null; };
  dlg.onclick = (e) => { if (e.target === dlg) dlg.close(); };
}

function copyAll(p) {
  const text = [p.fill.title, p.fill.body, p.fill.tags.map((t) => '#' + t).join(' ')].filter(Boolean).join('\n\n');
  return navigator.clipboard.writeText(text).then(() => toast('已复制，去粘贴'), () => toast('复制失败'));
}

/* 9/29 Park：「打包就是 package everything up，发布就是 send everything out。」发布台不再配图、排版、
   预览全文、写文章——这些在打包里做完、定稿。这里只说一句这个平台用的是打包里定稿的哪几样；
   没定稿就说回打包，不在这里就地补。 */
const PACK_NEEDS = {
  wechat_mp: ['article', 'figs', 'wx'], miniprogram: ['article', 'figs', 'wx'], x: ['article', 'figs'],
  xiaohongshu: ['copy', 'cover'], douyin: ['copy', 'cover'], channels: ['copy', 'cover'],
  bilibili: ['copy', 'cover'], youtube: ['copy', 'cover'], xiaoyuzhou: ['copy'],
};
const PACK_LABELS = { copy: '标题和描述', cover: '封面', article: '文章', figs: '插图', wx: '公众号排版' };

function packGaps(p, d) {
  if (!d.approvals) return [];
  return (PACK_NEEDS[p.key] || []).filter((k) => !(d.approvals[k] && d.approvals[k].approved && d.approvals[k].valid));
}

function packStatus(p, d) {
  const need = PACK_NEEDS[p.key] || [];
  if (!need.length || !d.approvals) return '';
  const gaps = packGaps(p, d);
  return gaps.length
    ? `<p class="pdl-note pack-need">打包里还没定稿：<b>${gaps.map((k) => PACK_LABELS[k]).join('、')}</b>。回「打包」定稿了再来发。</p>`
    : `<p class="pdl-ok">✓ 用打包里定稿的：${need.map((k) => PACK_LABELS[k]).join(' · ')}</p>`;
}

/* 文字平台和小红书：不管在哪一步，最上面都能看到那篇文章（没写就能就地写） */
/* 公众号、B 站发的时候要封面：没有就先做（补发的旧视频从来没做过） */
function needsCover(p, d) {
  const c = (d.release && d.release.covers) || {};
  if (p.key === 'wechat_mp') return !(c.wechat || c.landscape);
  if (p.key === 'bilibili') return !c.landscape;
  return false;
}

function sideFor(p, d) {
  const core = sideCore(p, d);
  const next = d.platforms.find((x) => x.key === d.next);
  const flow = p.skipped
    ? `<div class="pdl-flow"><b>这条不发${esc(p.label)}</b><button class="linklike" type="button" id="pdlUnskip">撤销，还是要发</button>${next ? `<button class="btn primary" type="button" id="pdlNext">下一个：${esc(next.label)} →</button>` : ''}</div>`
    : p.shipped
      ? (next ? `<div class="pdl-flow"><b>✓ ${esc(p.label)}发完了</b><button class="btn primary" type="button" id="pdlNext">下一个：${esc(next.label)} →</button></div>` : '<div class="pdl-flow"><b>✓ 顺序里的平台都走完了</b></div>')
      : `<div class="pdl-flow quiet"><button class="linklike" type="button" id="pdlSkip">这条不发${esc(p.label)}，跳过 →</button></div>`;
  const art = !p.shipped && !p.skipped ? packStatus(p, d) : '';
  return (p.shipped || p.skipped ? flow : '') + art + core + (p.shipped || p.skipped ? '' : flow);
}

function sideCore(p, d) {
  const t = d.topic;
  // 自动、扫码的平台发完自己记；只有手动传的才要「复制」和「记一笔」
  const manualish = p.treatment === 'manual' || p.state === 'blocked' || p.state === 'stale' || p.state === 'setup';
  const field = (label, value, hint) => value
    ? `<div class="pf-f"><span>${label}${hint ? `<i>${hint}</i>` : ''}</span><p>${esc(value)}</p><button class="btn small ghost" type="button" data-copy="${esc(value)}">复制</button></div>` : '';
  const fields = !manualish ? '' : d.has_copy ? `<h4>这个平台该填什么</h4><div class="pdl-fields">
      ${field('标题', p.fill.title, `最多 ${p.caps.title} 字${p.fill.title_trimmed ? ' · 已裁短' : p.fill.title_over ? ` · 现在 ${p.fill.title_units} 字，超了，发的时候删几个字` : ''}`)}
      ${field(p.key === 'wechat_mp' ? '正文开头' : p.key === 'x' ? '推文' : '简介', p.fill.body, `最多 ${p.caps.body} 字`)}
      ${field('话题', p.fill.tags.map((x) => '#' + x).join(' '), `最多 ${p.caps.tags} 个`)}
    </div>` : '';
  // 抖音、视频号这类手动传的：一键弹开装好视频和封面的文件夹，文案在下面复制（9/29 Park）
  const kit = { douyin: '视频 + 竖封面 + 横封面', channels: '视频 + 竖封面', xiaohongshu: '视频 + 竖封面', bilibili: '视频 + 16:9 封面', youtube: '视频 + 16:9 封面' }[p.key];
  const manual = `<div class="pdl-acts">
      ${kit && d.video ? `<button class="btn primary" type="button" id="pdlFolder">打开上传文件夹（${kit}）</button>` : ''}
      ${d.has_copy ? '<button class="btn" type="button" id="pdlCopyAll">复制全部文案</button>' : ''}
      ${p.admin ? `<a class="btn ${kit && d.video ? '' : 'primary'}" href="${esc(p.admin)}" target="_blank" rel="noopener" style="text-align:center" >打开${esc(p.label)}上传 ↗</a>` : ''}
    </div>`;
  const mark = !manualish ? '' : `<div class="pdl-mark"><h4>发完了？记一笔</h4><input id="pdlUrl" placeholder="${esc(p.label)}的链接（可留空）" autocomplete="off"><button class="btn" type="button" id="pdlMark">标为已发</button></div>`;
  const hist = (d.platforms.find((x) => x.key === p.key) || {}).job;
  const history = hist && !['awaiting_confirm', 'running'].includes(hist.state)
    ? `<ul class="pdl-hist"><li><span class="pill ${hist.state === 'done' ? 'hot' : 'low'}">${PJ_TEXT[hist.state] || hist.state}</span> ${esc(hist.mode_label)} · ${day(hist.created_at)}${hist.message ? ` <span class="bad">${esc(hist.message)}</span>` : ''}</li></ul>` : '';

  if (p.shipped) {
    return `<div class="pdl-done"><b>✓ 已发到${esc(p.label)}${p.record && p.record.published_at ? ' · ' + day(p.record.published_at) : ''}</b>
        ${p.record && p.record.url ? `<a href="${esc(p.record.url)}" target="_blank" rel="noopener">${esc(p.record.url)}</a>` : (p.key === 'douyin' && t.published_url ? `<a href="${esc(t.published_url)}" target="_blank" rel="noopener">${esc(t.published_url)}</a>` : '<small>没记链接</small>')}
        ${p.record ? '<button class="linklike" type="button" id="pdlUnmark">记错了，撤销</button>' : ''}</div>
      ${p.key === 'douyin' ? '<div id="pdlDouyin"></div>' : ''}${history}`;
  }
  // 存完草稿：工作台不知道他后来在后台发没发。请他发完回来点一下、贴链接（9/29 Park）
  if (p.job && p.job.draft) {
    return `<div class="pdl-draft"><b>✓ 草稿已存进${esc(p.label)}</b><small>${day(p.job.created_at)}</small>
        <p>去${esc(p.label)}后台看一眼、点发布。发出去以后回来点「发出去了」，把链接贴在这里——它会进「全平台追踪」那张表。</p>
        <input id="pdlUrl" value="${esc(p.job.draft_link || '')}" placeholder="${esc(p.label)}的链接（发出去以后的那个）" autocomplete="off">
        <div class="pdl-acts">${p.admin ? `<a class="btn" href="${esc(p.admin)}" target="_blank" rel="noopener" style="text-align:center">打开${esc(p.label)}后台 ↗</a>` : ''}<button class="btn primary" type="button" id="pdlMark">发出去了</button></div>
        ${p.job.draft_link ? '<small>链接已经按视频编号填好了，公开以后就能打开。</small>' : ''}
      </div>
      ${Object.keys(p.modes).length ? `<p class="pdl-note"><button class="linklike" type="button" data-pj-prepare="${Object.keys(p.modes)[0]}">草稿被删了？重新存一次</button></p>` : ''}`;
  }
  if (p.job && p.job.state === 'awaiting_confirm') {
    const pl = p.job.payload || {};
    return `<div class="pn-confirm"><b>确认发布到${esc(pl.platform_label || p.label)}：${esc(pl.mode_label || '')}</b>
        <dl><dt>标题</dt><dd>${esc(pl.title || '（无）')}</dd><dt>正文</dt><dd>${p.needs_article ? '打包里定稿的那篇文章（带插图）' : esc(pl.body || '（空）')}</dd><dt>话题</dt><dd>${esc((pl.tags || []).map((x) => '#' + x).join(' ') || '（无）')}</dd>${pl.video ? `<dt>视频</dt><dd>${esc(String(pl.video).split('/').pop())} · ${pl.video_mb} MB</dd>` : ''}</dl>
        <div class="acts"><button class="btn primary" type="button" data-pj-confirm="${p.job.id}">确认发布</button><button class="btn ghost" type="button" data-pj-cancel="${p.job.id}">取消</button></div></div>
      <p class="pdl-note">每次发布都要你看过上面的内容再点。发布后这张页会变成彩色。</p>`;
  }
  if (p.job && p.job.state === 'running') {
    return `<div class="pn-confirm running"><span class="spin"></span> 正在发布到${esc(p.label)}（${esc(p.job.mode_label)}），视频大的话要十几分钟。</div>${fields}`;
  }
  if (p.treatment === 'handoff') {
    return `<h4>${esc(p.treatment_label)}</h4>
      ${p.handoff_done
        ? '<div class="pdl-done"><b>✓ 正文已交到 004_内容加工中</b><small>配图排版走你原来的 wechat-package 流程，排好后到公众号发。</small></div>'
        : `<p class="pdl-note">工作台只负责到正文：写好的文章会放进 <code>004_内容加工中/…/wechat-package/</code>，配图排版走你原来的流程。</p>
           <div class="pdl-acts"><button class="btn primary" type="button" id="pdlHandoff" ${d.has_article ? '' : 'disabled'}>${d.has_article ? '交给公众号流水线' : '先在「研习室文章」写好正文'}</button></div>`}
      ${p.state === 'setup' ? `<p class="pdl-note bad">${esc(p.note)}</p>` : ''}
      <div class="pdl-acts">${p.admin ? `<a class="btn" href="${esc(p.admin)}" target="_blank" rel="noopener" style="text-align:center">打开公众号后台 ↗</a>` : ''}</div>
      ${mark}${history}${fields}`;
  }
  if (p.treatment === 'scan' || p.treatment === 'auto') {
    const ready = p.can_auto && (d.video || p.no_video) && (p.needs_article ? d.has_article : d.has_copy) && !packGaps(p, d).length;
    let block;
    if (p.state === 'blocked') {
      block = `<p class="pdl-note"><b>${esc(p.note)}</b>。通道留着，先按手动的方式发。</p>${manual}`;
    } else if (p.state === 'stale') {
      block = `<p class="pdl-note"><b>${esc(p.note)}</b><br>在电脑上运行下面这条重新扫码，回来这里就能机器发：</p><p class="pdl-note"><code>${esc(p.login_hint)}</code></p>${manual}`;
    } else if (p.state === 'setup') {
      block = `<p class="pdl-note"><b>${esc(p.note)}</b><br>${esc(p.login_hint)}</p>${manual}`;
    } else if (packGaps(p, d).length || (p.needs_article && !d.has_article) || (!p.needs_article && !d.has_copy) || needsCover(p, d)) {
      block = packGaps(p, d).length ? '' : '<p class="pdl-note pack-need">打包里还缺东西，回「打包」做完再来发。</p>';
    } else if (!d.video && !p.no_video) {
      block = '<p class="pdl-note">还没有成片：在「剪辑进度」关联视频项目并完成剪辑后，这里可以直接发。</p>';
    } else if (ready) {
      block = `<p class="pdl-note">${esc(p.note)}${p.needs_article ? ({ x: '。发的是打包里定稿的那篇文章和插图，封面按标题单独出一张纯文字的（不带人脸）；需要 X Premium', wechat_mp: '。发的是打包里定稿的那篇文章 + 公众号排版 + 封面，存进草稿箱，群发你在公众号后台自己点', miniprogram: '。发的是「研习室文章」那一篇，排版和网页后台导入一样；再发一次会更新同一篇' }[p.key] || '') : p.no_video ? '。发的是文字，不带视频' : `。会上传 ${esc(d.video.name)}（${d.video.mb} MB）${['bilibili', 'youtube'].includes(p.key) && d.release && d.release.covers ? (d.release.covers.wide ? '，封面用 16:9 那张' : d.release.covers.landscape ? '，封面用 4:3 横版（还没有 16:9 的，回打包重出封面会多出一张）' : '') : ''}`}。</p>
        <div class="pdl-acts">${Object.entries(p.modes).map(([mode, label]) => `<button class="btn primary" type="button" data-pj-prepare="${mode}">${esc(label)}</button>`).join('')}</div>
        <p class="pdl-note">点了之后先看摘要，再由你确认。</p>`;
    } else {
      block = `<p class="pdl-note">${esc(p.note)}</p>${manual}`;
    }
    return `<h4>${esc(p.treatment_label)}</h4>${block}${mark}${history}${fields}`;
  }
  return `<h4>${esc(p.treatment_label)}</h4>
    <p class="pdl-note">${esc(p.label)}没有自动通道：打开上传文件夹（视频、封面、文案都在里面），到${esc(p.label)}传，发完回来记一笔。</p>
    ${manual}${mark}${p.key === 'douyin' ? '<div id="pdlDouyin"></div>' : ''}${history}${fields}`;
}

/* 配图（小黑手绘，Codex 画）：文字版都过一遍。写完文章会自动配；这里看进度、看图、重配。 */
async function renderFigs(dlg, topicId) {
  const box = $('#pdlFigs', dlg);
  if (!box) return;
  let st;
  try { st = await api(`/api/topics/${topicId}/illustrate`); } catch (err) { box.innerHTML = `<p class="pdl-note bad">${esc(err.message)}</p>`; return; }
  if (window.prepTick) window.prepTick('figs', st);
  const thumbs = st.images.length ? `<div class="pdl-fig-grid">${st.images.map((i) => `<a href="${i.url}" target="_blank" rel="noopener" title="${esc(i.caption)}"><img src="${i.url}" alt="${esc(i.caption)}" loading="lazy"></a>`).join('')}</div>` : '';
  if (st.running) {
    box.innerHTML = `<p class="pdl-note"><span class="spin"></span> 正在配图（小黑手绘，一张一张画），一般 5–10 分钟。</p>${thumbs}`;
    setTimeout(() => { if (document.body.contains(box)) renderFigs(dlg, topicId); }, 8000);
    return;
  }
  box.innerHTML = `${st.error ? `<p class="pdl-note bad">配图失败：${esc(st.error)}</p>` : ''}
    <p class="pdl-note">${st.images.length ? `配图 ${st.images.length} 张，已经插在文章里` : '还没配图'}
    <button class="linklike" type="button" data-fig-go>${st.images.length ? '重新配图' : '配图（5–10 分钟）'}</button></p>${thumbs}`;
  box.querySelector('[data-fig-go]').onclick = async (e) => {
    if (st.images.length && !confirm('重新配图会换掉现在这几张，排好的公众号版式和小红书图也要重出。继续？')) return;
    e.target.disabled = true;
    try { await api(`/api/topics/${topicId}/illustrate`, { method: 'POST' }); } catch (err) { toast(err.message); }
    renderFigs(dlg, topicId);
  };
}

/* 公众号：先排版（gzh，5–10 分钟）→ 看公众号里的样子 → 存进草稿箱。状态就地显示，不靠 toast（弹窗会挡住它）。 */
function openWxPreview(topicId) {
  const box = document.createElement('dialog');
  box.className = 'wx-prev';
  box.innerHTML = `<div class="wx-prev-h"><b>公众号里的样子</b><button class="btn small" type="button">关掉</button></div><iframe src="/api/topics/${topicId}/wechat-preview.html?t=${Date.now()}" title="公众号预览"></iframe>`;
  document.body.appendChild(box);
  box.querySelector('button').onclick = () => box.close();
  box.onclose = () => box.remove();
  box.showModal();
}

async function renderWx(dlg, topicId) {
  const box = $('#pdlWx', dlg);
  if (!box) return;
  let st;
  try { st = await api(`/api/topics/${topicId}/layout`); } catch (err) { box.innerHTML = `<p class="bad">${esc(err.message)}</p>`; return; }
  if (window.prepTick) window.prepTick('wx', st);
  const fresh = st.has_layout && !st.stale;
  const preview = `<button class="btn ${fresh ? 'primary' : ''}" type="button" data-wx-preview>看公众号里的样子</button>`;
  if (st.running) {
    box.innerHTML = `<p class="pdl-note"><span class="spin"></span> 正在用 gzh 排版（橄榄手记），一般 5–10 分钟，排好这里会变。可以先关掉弹窗做别的。</p>`;
    const save = $('[data-pj-prepare="draft"]', dlg);
    if (save) { save.disabled = true; save.textContent = '排版中，排好再存'; }
    setTimeout(() => { if (document.body.contains(box)) renderWx(dlg, topicId); }, 5000);
    return;
  }
  box.innerHTML = fresh
    ? `<p class="pdl-note">✓ 已用 gzh 排好版（${esc(st.theme || '橄榄手记')}）。先看一眼，没问题再存草稿箱。</p><div class="pdl-acts">${preview}<button class="btn ghost" type="button" data-wx-layout>重新排版</button></div>`
    : `${st.error ? `<p class="pdl-note bad">上次排版失败：${esc(st.error)}</p>` : ''}
       <p class="pdl-note">${st.stale ? '文章改过了，之前的排版作废了。' : '还没排版。'}先用 gzh 排一下（5–10 分钟），排好能预览；不排也能发，用的是基础排版。</p>
       <div class="pdl-acts"><button class="btn primary" type="button" data-wx-layout>用 gzh 排版</button>${preview.replace('看公众号里的样子', '看基础排版的样子')}</div>`;
  // 存草稿按钮跟着排版走：排版中先别存（存进去就是基础排版）；没排就写明是基础排版
  const save = $('[data-pj-prepare="draft"]', dlg);
  if (save) {
    save.disabled = false;
    save.textContent = fresh ? '存进公众号草稿箱（gzh 排版）' : '存进公众号草稿箱（基础排版）';
  }
  box.querySelector('[data-wx-preview]').onclick = () => openWxPreview(topicId);
  box.querySelector('[data-wx-layout]').onclick = async (e) => {
    e.target.disabled = true;
    try { await api(`/api/topics/${topicId}/layout`, { method: 'POST' }); } catch (err) { box.insertAdjacentHTML('afterbegin', `<p class="pdl-note bad">${esc(err.message)}</p>`); }
    renderWx(dlg, topicId);
  };
}

/* 抖音单独有一块：把发出去的那条视频和这个选题对上。对上之后点赞和播放才会自己回来，
   卡片也才算「已发出」。以前这块在「加工中 → 发布」页签里，那个页签已经去掉了。 */
async function renderDouyinLink(dlg, topicId) {
  const box = $('#pdlDouyin', dlg);
  if (!box) return;
  box.innerHTML = '<p class="pdl-note"><span class="spin"></span> 正在找你发出去的视频…</p>';
  let d;
  try { d = await api(`/api/topics/${topicId}/publish`); } catch (err) { box.innerHTML = `<p class="pdl-note bad">${esc(err.message)}</p>`; return; }
  if (!d.account) { box.innerHTML = '<p class="pdl-note">还没设置自己的抖音号，先去设置里加。</p>'; return; }
  if (d.video) {
    box.innerHTML = `<div class="pdl-done"><b>✓ 已对上：${esc(cleanTitle(d.video.title))}</b>
      <small>${day(d.video.published_at)} · ${fmt(d.video.likes)} 赞</small>
      <button class="linklike" type="button" id="pdlUnlink">不是这条，解除</button></div>`;
    $('#pdlUnlink', box).onclick = async () => {
      try { await api(`/api/topics/${topicId}/publish`, { method: 'PUT', body: { video_id: null } }); toast('已解除'); renderDouyinLink(dlg, topicId); } catch (err) { toast(err.message); }
    };
    return;
  }
  const link = async (videoId) => {
    try { await api(`/api/topics/${topicId}/publish`, { method: 'PUT', body: { video_id: videoId } }); toast('对上了，数据会自己回来'); PD.data = null; $('#publishBody').dataset.sig = ''; renderDouyinLink(dlg, topicId); } catch (err) { toast(err.message); }
  };
  box.innerHTML = `<div class="pdl-mark"><h4>发到抖音了？对一下是哪条</h4>
    ${d.suggestions.length ? d.suggestions.map((v) => `<div class="hot-row"><span class="pill mid">${Math.round(v.score * 100)}%</span><div class="hot-main"><b class="clamp">${esc(cleanTitle(v.title))}</b><small>${day(v.published_at)} · ${fmt(v.likes)} 赞</small></div><div class="acts"><button class="btn small primary" type="button" data-dy="${esc(v.video_id)}">就是这条</button></div></div>`).join('')
      : `<p class="pdl-note">还没找到标题相近的新视频。刚发的话，${d.stale_sync ? '数据有点旧，' : ''}<button class="linklike" type="button" id="pdlSync">同步一下我的数据</button>；也可以在下面直接点。</p>`}
    ${d.recent.length ? `<h5 class="pdl-sub">最近发的</h5>${d.recent.slice(0, 5).map((v) => `<div class="hot-row"><span class="pill low">${day(v.published_at)}</span><div class="hot-main"><b class="clamp">${esc(cleanTitle(v.title))}</b><small>${fmt(v.likes)} 赞</small></div><div class="acts"><button class="btn small" type="button" data-dy="${esc(v.video_id)}">就是这条</button></div></div>`).join('')}` : ''}</div>`;
  $$('[data-dy]', box).forEach((b) => (b.onclick = () => link(b.dataset.dy)));
  const sync = $('#pdlSync', box);
  if (sync) sync.onclick = async () => {
    try { const r = await api('/api/sync', { method: 'POST' }); toast(r.message); } catch (err) { toast(err.message); }
  };
}

/* 交付包里的封面：项目 final/ 下现成的横版和竖版。 */
function releaseStrip(rel) {
  if (!rel || !rel.covers) return '';
  const shots = [['landscape', '横版'], ['portrait', '竖版'], ['wechat', '公众号']].filter(([k]) => rel.covers[k]);
  if (!shots.length) return '';
  return `<div class="pub-covers">${shots.map(([k, label]) => {
    const url = (rel.cover_urls || {})[k];
    return `<a class="pub-cover ${k}" href="${url}" target="_blank" rel="noopener" title="${esc(rel.covers[k])}"><img src="${url}" alt="${label}封面" loading="lazy"><small>${label}封面</small></a>`;
  }).join('')}</div>`;
}

function renderDialog() {
  const dlg = $('#pubDlg');
  const d = PD.data;
  if (!d || !PD.open) return;
  const p = d.platforms.find((x) => x.key === PD.open);
  if (!p) return;
  const [stLabel, stCls] = stateOf(p);
  const typed = $('#pdlUrl', dlg);
  const keep = typed ? { value: typed.value, focus: document.activeElement === typed } : null;
  // 刷新时沿用上一次的缩放和右栏滚动位置：不然每刷一次，左边预览先按原尺寸画出来再缩回去、右栏跳回顶上
  const prevWrap = $('.rc-wrap', dlg);
  const prevScale = prevWrap ? prevWrap.style.getPropertyValue('--s') : '';
  const prevScroll = ($('.pdl-side', dlg) || {}).scrollTop || 0;
  dlg.innerHTML = `<div class="pdl-h"><i class="plat s-${p.state}"${p.state === 'manual' || p.state === 'blocked' ? '' : ` style="--plat:${esc(p.hue)}"`}>${esc(p.mark)}</i><b>${esc(p.label)}</b><small>${esc(p.handle || '')}</small><span class="ps ${stCls}">${stLabel}</span><span class="ps">${esc(p.treatment_label)}</span><span class="spacer"></span><small>${d.topic ? esc(d.topic.title) : ''}</small><button class="pdl-x" type="button" id="pdlClose" aria-label="关闭">×</button></div>
    <div class="pdl-body">
      <div class="pdl-shot"><div class="rc-wrap ${p.shipped || (p.job && ['running', 'awaiting_confirm'].includes(p.job.state)) ? '' : 'dim'} ${p.job && p.job.state === 'running' ? 'live' : ''}">${replica(p, d)}</div></div>
      <div class="pdl-side">${d.topic ? sideFor(p, d) : '<p class="pdl-note">还没有能发的内容。</p>'}</div>
    </div>`;
  if (prevScale) $('.rc-wrap', dlg).style.setProperty('--s', prevScale);
  $('.pdl-side', dlg).scrollTop = prevScroll;
  fitReplicas(dlg);
  requestAnimationFrame(() => fitReplicas(dlg));
  const url = $('#pdlUrl', dlg);
  if (url && keep) { url.value = keep.value; if (keep.focus) url.focus(); }
  $('#pdlClose', dlg).onclick = () => dlg.close();
  if (!d.topic) return;
  const t = d.topic;
  const refresh = async () => { PD.data = null; $('#publishBody').dataset.sig = ''; try { await loadDesk(true); } catch (err) { toast(err.message); } renderView(); };
  $$('[data-copy]', dlg).forEach((b) => (b.onclick = () => navigator.clipboard.writeText(b.dataset.copy).then(() => toast('已复制'), () => toast('复制失败'))));
  const all = $('#pdlCopyAll', dlg); if (all) all.onclick = () => copyAll(p);
  const folderBtn = $('#pdlFolder', dlg);
  if (folderBtn) folderBtn.onclick = async () => {
    try {
      const r = await api(`/api/topics/${t.id}/upload-folder`, { method: 'POST', body: { platform: p.key } });
      toast(`文件夹打开了：${r.files.join('、')}${r.missing.length ? `（缺${r.missing.join('、')}）` : ''}`);
    } catch (err) { toast(err.message); }
  };
  const mark = $('#pdlMark', dlg);
  if (mark) mark.onclick = async () => {
    const url = $('#pdlUrl', dlg).value.trim() || null;
    if (url && !/^https?:\/\//.test(url)) { toast('链接要以 https:// 开头'); return; }
    try { await api(`/api/topics/${t.id}/platforms`, { method: 'PUT', body: { platform: p.key, published: true, url } }); toast(`${p.label} 记为已发`); await refresh(); goNext(); } catch (err) { toast(err.message); }
  };
  if (p.key === 'douyin') renderDouyinLink(dlg, t.id);
  if (t.write_state === 'running') setTimeout(() => { if (dlg.open && PD.open === p.key) refresh(); }, 8000);
  // 这个平台正在发：弹窗自己隔几秒问一次，发完立刻变，不靠整页刷新
  clearTimeout(PD.dialogPoll);
  if (p.job && p.job.state === 'running') {
    const jobId = p.job.id;
    PD.dialogPoll = setTimeout(async () => {
      if (!dlg.open || PD.open !== p.key) return;
      try {
        await loadDesk(true);
        const now = (PD.data.platforms.find((x) => x.key === p.key) || {}).job;
        if (!now || now.id !== jobId || now.state !== 'running') { $('#publishBody').dataset.sig = ''; renderView(); } else renderDialog();
      } catch (_) { renderDialog(); }
    }, 5000);
  }
  const nextBtn = $('#pdlNext', dlg); if (nextBtn) nextBtn.onclick = () => goNext();
  const skipBtn = $('#pdlSkip', dlg);
  if (skipBtn) skipBtn.onclick = async () => { try { await setSkip(t.id, p.key, true); toast(`这条不发${p.label}`); renderView(); goNext(); } catch (err) { toast(err.message); } };
  const unskip = $('#pdlUnskip', dlg);
  if (unskip) unskip.onclick = async () => { try { await setSkip(t.id, p.key, false); renderView(); renderDialog(); } catch (err) { toast(err.message); } };
  const unmark = $('#pdlUnmark', dlg);
  if (unmark) unmark.onclick = async () => {
    try { await api(`/api/topics/${t.id}/platforms`, { method: 'PUT', body: { platform: p.key, published: false, url: null } }); toast('已撤销'); await refresh(); } catch (err) { toast(err.message); }
  };
  const handoff = $('#pdlHandoff', dlg);
  if (handoff) handoff.onclick = async () => {
    handoff.disabled = true;
    try { const r = await api(`/api/topics/${t.id}/wechat-handoff`, { method: 'POST' }); toast(r.message || '已交接'); await refresh(); } catch (err) { toast(err.message); handoff.disabled = false; }
  };
  $$('[data-pj-prepare]', dlg).forEach((b) => (b.onclick = async () => {
    b.disabled = true;
    try { await api(`/api/topics/${t.id}/publish-jobs`, { method: 'POST', body: { platform: p.key, mode: b.dataset.pjPrepare } }); await refresh(); } catch (err) { toast(err.message); b.disabled = false; }
  }));
  $$('[data-pj-confirm]', dlg).forEach((b) => (b.onclick = async () => {
    if (!confirm(`确认发布到${p.label}？这会把内容提交到平台。`)) return;
    b.disabled = true;
    try { const r = await api(`/api/publish-jobs/${b.dataset.pjConfirm}/confirm`, { method: 'POST' }); toast(r.message); await refresh(); } catch (err) { toast(err.message); b.disabled = false; }
  }));
  $$('[data-pj-cancel]', dlg).forEach((b) => (b.onclick = async () => {
    try { await api(`/api/publish-jobs/${b.dataset.pjCancel}`, { method: 'DELETE' }); toast('已取消'); await refresh(); } catch (err) { toast(err.message); }
  }));
}
