'use strict';
/* 03 发布台：一条内容 × 每个平台。每个平台一张它自己的上传页（720×480 的画布，瓦片里缩小、
   弹窗里放大）。灰的还没发，彩色的发了；正在发的闪。点开一张，右边是这个平台该做的事：
   手动的复制文案去粘贴，扫码的机器代发（Park 先确认），全自动的直接发，公众号交给流水线。 */
window.VIEWS = window.VIEWS || {};

const PD = { data: null, at: 0, topicId: null, open: null, ro: null };
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
          <div style="font-size:17px;line-height:1.45;min-height:90px;white-space:pre-wrap;overflow:hidden;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:5;word-break:break-all">${text ? esc(text) : '<span class="rc-ph">What is happening?!</span>'}</div>
          <div class="rc-mini" style="color:var(--p)">🌐 Everyone can reply</div>
          <div class="rc-row" style="border-top:1px solid #E5E7EB;padding-top:10px"><span class="rc-icons">🖼 GIF ☰ ☺ 📅 📍</span><span class="spacer" style="flex:1"></span><span class="rc-ring"></span>${R.btn('Post', 'pill')}</div>
        </div>
      </div>
    </div>`;
  },
  wechat_mp(c) {
    return `${R.top('公众平台', ['图文消息', '素材库', '发表记录'], R.me(c.handle))}
    <div class="rc-body" style="grid-template-columns:1fr 200px">
      <div class="rc-card" style="gap:8px">
        ${R.input(c.fill.title, '请在这里输入标题', '', 'big')}
        <div class="rc-row"><span class="rc-mini">作者</span>${R.input(c.handle || 'Park', '请输入作者', '', '')}</div>
        <div class="rc-tools"><i>B</i><i>I</i><i>U</i><i>|</i><i>H1</i><i>H2</i><i>|</i><i>≡</i><i>⁝≡</i><i>|</i><i>🖼</i><i>🔗</i><i>❝</i></div>
        ${R.area(c.fill.body, '从这里开始写正文', '', 6, 'white')}
      </div>
      <div class="rc-v" style="gap:10px">
        <div class="rc-card" style="gap:8px"><b style="font-size:12px">封面和摘要</b>${R.cover('拖拽或选择封面 2.35:1', 168, 72, c.shipped ? 'pic' : 'light')}${R.area(c.fill.body.slice(0, 60), '选填，不填会默认抓取正文前 54 字', '', 3)}</div>
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
        ${R.f('摘要', R.area(c.fill.body, '一句话说清这条讲什么', R.count(c.fill.body, c.caps.body), 3))}
        ${R.f('推送到', R.sel('全部订阅用户'))}
        ${R.f('跳转', R.sel('本条视频详情页'))}
      </div>
      <div class="rc-card" style="gap:8px"><b style="font-size:11px;color:#6B7280">卡片预览</b>${R.cover('', 208, 96, 'pic')}<b style="font-size:12.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(c.fill.title || '标题会显示在这里')}</b><div class="rc-mini" style="display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:3;overflow:hidden">${esc(c.fill.body || '摘要会显示在这里')}</div></div>
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
  const ctx = { ...p, video: d.video, live: p.job && p.job.state === 'running', shipped: p.shipped };
  const draw = REPLICA[p.key] || REPLICA.miniprogram;
  return `<div class="rc" style="--p:${esc(p.hue)}">${draw(ctx)}</div>`;
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
  return `<article class="pub-tile ${p.shipped ? 'shipped' : ''} ${live ? 'live' : ''} ${p.on ? '' : 'off'}" data-key="${p.key}">
    <button class="pub-shot" type="button" data-pd-open="${p.key}" aria-label="打开${esc(p.label)}">${replica(p, d)}${stamp}</button>
    <div class="pub-cap"><i class="plat s-${p.state}"${p.state === 'manual' || p.state === 'blocked' ? '' : ` style="--plat:${esc(p.hue)}"`}>${esc(p.mark)}</i><b>${esc(p.label)}</b><small title="${esc(p.handle || '')}">${esc(p.handle || '')}</small></div>
    <div class="pub-how"><span class="ps ${cls}">${label}</span><span>${esc(p.treatment_label)}</span></div>
    <div class="pub-act">${tileAction(p, d)}</div>
  </article>`;
}

/* ================= 页面 ================= */
window.VIEWS.publish = {
  async render() {
    const body = $('#publishBody');
    if (S.publishId && S.publishId !== PD.topicId) { PD.topicId = S.publishId; PD.data = null; }
    let d;
    try { d = await loadDesk(false); } catch (err) { body.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`; return; }
    const sig = JSON.stringify([PD.at, PD.topicId]);
    if (body.dataset.sig === sig) return;
    body.dataset.sig = sig;
    const shipped = d.platforms.filter((p) => p.shipped).length;
    const on = d.platforms.filter((p) => p.on).length;
    $('#publishFigs').innerHTML = d.topic ? `<div class="pub-figs">
      <span>已发 <b>${shipped}</b> / ${on} 个平台</span>
      <span>成片 ${d.video ? `<b>${d.video.mb}</b> MB` : '<span class="bad">还没有</span>'}</span>
      <span>文案 ${d.has_copy ? '<b>✓</b>' : '<span class="bad">还没写</span>'}</span>
      <button class="linklike" type="button" id="pdEditCopy">${d.has_copy ? '改文案' : '去写文案'} →</button>
    </div>` : '';
    if (!d.topic) {
      body.innerHTML = `<div class="pub-empty"><b>还没有能发的内容</b><span>「加工中」里的一条走到「待发」，或者写好了文案，就会出现在这里。</span></div>
        <div class="pub-grid" style="margin-top:6px">${d.platforms.map((p) => tile(p, d)).join('')}</div>`;
    } else {
      body.innerHTML = `<div class="pub-head">
        <div class="pub-topics"><small>发哪条</small>${d.candidates.map((c) => `<button class="pub-topic ${c.id === d.topic.id ? 'on' : ''}" type="button" data-pd-topic="${c.id}"><span class="ms-chip s-${c.stage}" title="${esc(c.stage_label)}"><i aria-hidden="true">${typeof MS_ICON !== 'undefined' ? (MS_ICON[c.stage] || '') : ''}</i>${esc(c.stage_label)}</span><b>${esc(c.title)}</b><span class="num">${c.shipped_count}/${on}</span></button>`).join('')}
        ${d.candidates.some((c) => c.id === d.topic.id) ? '' : `<button class="pub-topic on" type="button"><b>${esc(d.topic.title)}</b></button>`}</div>
      </div>
      <div class="pub-grid">${d.platforms.map((p) => tile(p, d)).join('')}</div>`;
    }
    fitReplicas(body);
    if (!PD.ro && window.ResizeObserver) { PD.ro = new ResizeObserver(() => fitReplicas(body)); PD.ro.observe(body); }
    $$('[data-pd-topic]', body).forEach((b) => (b.onclick = () => { PD.topicId = Number(b.dataset.pdTopic); S.publishId = PD.topicId; PD.data = null; history.replaceState(null, '', `#publish/${PD.topicId}`); renderView(); }));
    $$('[data-pd-open]', body).forEach((b) => (b.onclick = () => openPlatform(b.dataset.pdOpen)));
    const edit = $('#pdEditCopy');
    if (edit) edit.onclick = () => { if (typeof VD !== 'undefined') { VD.topicId = d.topic.id; VD.outline = null; VD.tab = 'publish'; } openWork(d.topic.id); };
    if (d.platforms.some((p) => p.job && p.job.state === 'running')) setTimeout(() => { if (S.view === 'publish') { PD.data = null; renderView(); } }, 8000);
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
}

function copyAll(p) {
  const text = [p.fill.title, p.fill.body, p.fill.tags.map((t) => '#' + t).join(' ')].filter(Boolean).join('\n\n');
  return navigator.clipboard.writeText(text).then(() => toast('已复制，去粘贴'), () => toast('复制失败'));
}

function sideFor(p, d) {
  const t = d.topic;
  const field = (label, value, hint) => value
    ? `<div class="pf-f"><span>${label}${hint ? `<i>${hint}</i>` : ''}</span><p>${esc(value)}</p><button class="btn small ghost" type="button" data-copy="${esc(value)}">复制</button></div>` : '';
  const fields = d.has_copy ? `<h4>这个平台该填什么</h4><div class="pdl-fields">
      ${field('标题', p.fill.title, `最多 ${p.caps.title} 字${p.fill.title_over ? ' · 已裁短' : ''}`)}
      ${field(p.key === 'wechat_mp' ? '正文开头' : p.key === 'x' ? '推文' : '简介', p.fill.body, `最多 ${p.caps.body} 字`)}
      ${field('话题', p.fill.tags.map((x) => '#' + x).join(' '), `最多 ${p.caps.tags} 个`)}
    </div>` : `<p class="pdl-note">还没写文案。<button class="linklike" type="button" id="pdlWrite">去写标题和简介 →</button></p>`;
  const manual = `<div class="pdl-acts">
      ${d.has_copy ? '<button class="btn" type="button" id="pdlCopyAll">复制全部文案</button>' : ''}
      ${p.admin ? `<a class="btn primary" href="${esc(p.admin)}" target="_blank" rel="noopener" style="text-align:center">打开${esc(p.label)}上传 ↗</a>` : ''}
    </div>`;
  const mark = `<div class="pdl-mark"><h4>发完了？记一笔</h4><input id="pdlUrl" placeholder="${esc(p.label)}的链接（可留空）" autocomplete="off"><button class="btn" type="button" id="pdlMark">标为已发</button></div>`;
  const hist = (d.platforms.find((x) => x.key === p.key) || {}).job;
  const history = hist && !['awaiting_confirm', 'running'].includes(hist.state)
    ? `<ul class="pdl-hist"><li><span class="pill ${hist.state === 'done' ? 'hot' : 'low'}">${PJ_TEXT[hist.state] || hist.state}</span> ${esc(hist.mode_label)} · ${day(hist.created_at)}${hist.message ? ` <span class="bad">${esc(hist.message)}</span>` : ''}</li></ul>` : '';

  if (p.shipped) {
    return `<div class="pdl-done"><b>✓ 已发到${esc(p.label)}${p.record && p.record.published_at ? ' · ' + day(p.record.published_at) : ''}</b>
        ${p.record && p.record.url ? `<a href="${esc(p.record.url)}" target="_blank" rel="noopener">${esc(p.record.url)}</a>` : (p.key === 'douyin' && t.published_url ? `<a href="${esc(t.published_url)}" target="_blank" rel="noopener">${esc(t.published_url)}</a>` : '<small>没记链接</small>')}
        ${p.record ? '<button class="linklike" type="button" id="pdlUnmark">记错了，撤销</button>' : ''}</div>
      ${p.key === 'douyin' ? '<p class="pdl-note">抖音的数据在「加工中 → 这条视频 → 发布」页签里关联后自动来。</p>' : ''}${history}${fields}`;
  }
  if (p.job && p.job.state === 'awaiting_confirm') {
    const pl = p.job.payload || {};
    return `<div class="pn-confirm"><b>确认发布到${esc(pl.platform_label || p.label)}：${esc(pl.mode_label || '')}</b>
        <dl><dt>标题</dt><dd>${esc(pl.title || '（无）')}</dd><dt>正文</dt><dd>${esc(pl.body || '（空）')}</dd><dt>话题</dt><dd>${esc((pl.tags || []).map((x) => '#' + x).join(' ') || '（无）')}</dd>${pl.video ? `<dt>视频</dt><dd>${esc(String(pl.video).split('/').pop())} · ${pl.video_mb} MB</dd>` : ''}</dl>
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
    const ready = p.can_auto && (d.video || p.no_video) && d.has_copy;
    let block;
    if (p.state === 'blocked') {
      block = `<p class="pdl-note"><b>${esc(p.note)}</b>。通道留着，先按手动的方式发。</p>${manual}`;
    } else if (p.state === 'stale') {
      block = `<p class="pdl-note"><b>${esc(p.note)}</b><br>在电脑上运行下面这条重新扫码，回来这里就能机器发：</p><p class="pdl-note"><code>${esc(p.login_hint)}</code></p>${manual}`;
    } else if (p.state === 'setup') {
      block = `<p class="pdl-note"><b>${esc(p.note)}</b><br>${esc(p.login_hint)}</p>${manual}`;
    } else if (!d.has_copy) {
      block = '<p class="pdl-note">先写好标题和简介，机器才知道发什么。</p>';
    } else if (!d.video && !p.no_video) {
      block = '<p class="pdl-note">还没有成片：在「剪辑进度」关联视频项目并完成剪辑后，这里可以直接发。</p>';
    } else if (ready) {
      block = `<p class="pdl-note">${esc(p.note)}${p.no_video ? '。发的是文字，不带视频' : `。会上传 ${esc(d.video.name)}（${d.video.mb} MB）`}。</p>
        <div class="pdl-acts">${Object.entries(p.modes).map(([mode, label]) => `<button class="btn primary" type="button" data-pj-prepare="${mode}">${esc(label)}</button>`).join('')}</div>
        <p class="pdl-note">点了之后先看摘要，再由你确认。</p>`;
    } else {
      block = `<p class="pdl-note">${esc(p.note)}</p>${manual}`;
    }
    return `<h4>${esc(p.treatment_label)}</h4>${block}${mark}${history}${fields}`;
  }
  return `<h4>${esc(p.treatment_label)}</h4>
    <p class="pdl-note">${esc(p.label)}没有自动通道：复制文案、到${esc(p.label)}传视频、粘贴，发完回来记一笔。</p>
    ${manual}${mark}${history}${fields}`;
}

function renderDialog() {
  const dlg = $('#pubDlg');
  const d = PD.data;
  if (!d || !PD.open) return;
  const p = d.platforms.find((x) => x.key === PD.open);
  if (!p) return;
  const [stLabel, stCls] = stateOf(p);
  dlg.innerHTML = `<div class="pdl-h"><i class="plat s-${p.state}"${p.state === 'manual' || p.state === 'blocked' ? '' : ` style="--plat:${esc(p.hue)}"`}>${esc(p.mark)}</i><b>${esc(p.label)}</b><small>${esc(p.handle || '')}</small><span class="ps ${stCls}">${stLabel}</span><span class="ps">${esc(p.treatment_label)}</span><span class="spacer"></span><small>${d.topic ? esc(d.topic.title) : ''}</small><button class="pdl-x" type="button" id="pdlClose" aria-label="关闭">×</button></div>
    <div class="pdl-body">
      <div class="pdl-shot"><div class="rc-wrap ${p.shipped || (p.job && ['running', 'awaiting_confirm'].includes(p.job.state)) ? '' : 'dim'} ${p.job && p.job.state === 'running' ? 'live' : ''}">${replica(p, d)}</div></div>
      <div class="pdl-side">${d.topic ? sideFor(p, d) : '<p class="pdl-note">还没有能发的内容。</p>'}</div>
    </div>`;
  fitReplicas(dlg);
  requestAnimationFrame(() => fitReplicas(dlg));
  $('#pdlClose', dlg).onclick = () => dlg.close();
  if (!d.topic) return;
  const t = d.topic;
  const refresh = async () => { PD.data = null; $('#publishBody').dataset.sig = ''; try { await loadDesk(true); } catch (err) { toast(err.message); } renderView(); };
  $$('[data-copy]', dlg).forEach((b) => (b.onclick = () => navigator.clipboard.writeText(b.dataset.copy).then(() => toast('已复制'), () => toast('复制失败'))));
  const all = $('#pdlCopyAll', dlg); if (all) all.onclick = () => copyAll(p);
  const write = $('#pdlWrite', dlg); if (write) write.onclick = () => { dlg.close(); if (typeof VD !== 'undefined') { VD.topicId = t.id; VD.outline = null; VD.tab = 'publish'; } openWork(t.id); };
  const mark = $('#pdlMark', dlg);
  if (mark) mark.onclick = async () => {
    const url = $('#pdlUrl', dlg).value.trim() || null;
    if (url && !/^https?:\/\//.test(url)) { toast('链接要以 https:// 开头'); return; }
    try { await api(`/api/topics/${t.id}/platforms`, { method: 'PUT', body: { platform: p.key, published: true, url } }); toast(`${p.label} 记为已发`); await refresh(); } catch (err) { toast(err.message); }
  };
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
