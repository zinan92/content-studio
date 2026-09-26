'use strict';
/* 01 进项：所有进来的东西在一排 tab 里，左边列表、右边读原文。
   一条进项只有一个动作：入选题池。 */
window.VIEWS = window.VIEWS || {};

// tab key → 它从哪来。daily 走 /api/vault/dailies，followed 走对标账号的新作品，其余是 Obsidian 笔记。
const NOTE_TABS = [
  { key: 'benchmark', label: '对标', kind: 'note' },
  { key: 'raw', label: 'Park 原始输出', kind: 'note' },
  { key: 'saved', label: '我收藏的', kind: 'note' },
  { key: 'clipping', label: 'Clippings', kind: 'note' },
];
// 日报 tab 由 profile.yaml 的 dailies 决定（/api/state.daily_sources）；没配的日报不出现。
const TABS = [{ key: 'all', label: '全部', kind: 'all' }];
function syncTabs() {
  const dailies = (S.state && S.state.daily_sources) || [];
  TABS.length = 1;
  dailies.forEach((d) => TABS.push({ key: d.key, label: d.label, kind: 'daily' }));
  NOTE_TABS.forEach((t) => TABS.push(t));
  if (!TABS.some((t) => t.key === C.tab)) C.tab = 'all';
}
const DAY_TABS = [[1, '1 天'], [3, '3 天'], [7, '7 天'], [30, '30 天']];

const C = { tab: 'all', days: 1, items: null, since: null, open: null, note: null, dailies: {}, loadedAt: 0, groups: {} };

const tabDef = (key) => TABS.find((t) => t.key === key) || TABS[0];

async function loadInbox(force) {
  if (!force && C.items && Date.now() - C.loadedAt < 60000) return;
  const res = await api(`/api/vault/inbox?days=${C.days}`);
  C.items = res.items;
  C.since = res.since;
  C.loadedAt = Date.now();
}

async function loadDaily(key, force) {
  if (!force && C.dailies[key]) return;
  C.dailies[key] = (await api(`/api/vault/dailies?key=${key}&limit=40`)).items;
}

/* ---- 一条进项的生命周期：只有五种状态 ----
 *   fresh    还没处理   → 入选题池（往前） / 拍过了 / 暂不拍（放到底下）
 *   working  在加工中   （在看板上，从那边管）
 *   shipped  已发出     （变成了视频，去已发出看数据）
 *   shot     拍过了     → 捡回来
 *   ignored  暂不拍     → 捡回来（标过「不做了」的选题也在这里）
 * 从底下两组只能捡回来，不能一步跳进选题池。 */
function noteState(i) {
  const u = i.used_by;
  if (u && u.shipped) return 'shipped';
  if (u && !u.dropped) return 'working';
  if (i.triage === 'shot') return 'shot';
  if (i.triage === 'ignored') return 'ignored';
  if (i.triage === 'back') return 'fresh';
  if (u && u.dropped) return 'ignored';
  return 'fresh';
}

/* ---- 把三种来源归一成同一种行 ---- */
const noteRow = (i) => ({
  // 对标转录显示博主的名字；其余笔记显示它来自哪个文件夹。
  id: 'n:' + i.path, path: i.path, title: i.title, sub: i.author || i.source_label,
  at: i.is_new ? i.created_at : i.modified_at, summary: i.summary,
  state: noteState(i),
  taken: noteState(i) === 'working' ? 'topic' : '',
  topicId: i.used_by ? i.used_by.topic_id : null, shipped: noteState(i) === 'shipped',
  videoId: i.used_by ? i.used_by.video_id : null,
  // 主窗口只放现在要看的。发出去的和拍过了在一组，标过不做了和暂不拍在一组。
  park: ['shipped', 'shot'].includes(noteState(i)) ? 'shot' : noteState(i) === 'ignored' ? 'ignored' : '',
  source: i.source,
  url: i.url || null, hot: i.breakout || null,
});
const dailyRow = (d) => ({
  id: 'd:' + d.path, path: d.path, title: d.title, sub: d.label, at: d.day || d.modified_at, summary: '',
  taken: '', topicId: null, shipped: false, park: '', source: 'daily', external: d.kind === 'html' ? d.path : null,
});

// 爆的排前面，其余保持时间顺序（sort 是稳定的）。时间窗仍然由上面的 3/7/30 决定——
// 这里只改窗口内的先后，不会把窗口外的东西捞进来。
const hotFirst = (rows) => rows.slice().sort((a, b) => (b.hot ? 1 : 0) - (a.hot ? 1 : 0));

function rowsFor(tab) {
  const def = tabDef(tab);
  if (def.kind === 'daily') return (C.dailies[tab] || []).map(dailyRow);
  if (def.kind === 'note') return hotFirst((C.items || []).filter((i) => i.source === tab).map(noteRow));
  // 全部 = 这段时间「新进来的」。Park 原始输出不受时间窗限制（素材库，不是新闻流），
  // 67 条全塞进来会把当天真正新的东西压到看不见，所以它只在自己那一页整片出现。
  // 日报同理：一份摘要装着很多条，放进来也会淹掉别的。
  return hotFirst((C.items || []).filter((i) => i.source !== 'raw').map(noteRow));
}

function renderMarkdown(md) {
  if (window.marked && window.DOMPurify) {
    const html = window.marked.parse(md.replace(/!\[\[([^\]]+)\]\]/g, '（附件：$1）'), { breaks: true });
    // Clipped web pages carry inline styles (absolute-positioned videos) that break the reader.
    return window.DOMPurify.sanitize(html, { ADD_ATTR: ['target'], FORBID_ATTR: ['style'] });
  }
  return `<pre class="plain">${esc(md)}</pre>`;
}

async function openNote(path) {
  const here = S.view === 'input';
  C.open = path;
  C.note = null;
  C.keepScroll = here;
  if (!here) go('input');
  else renderView();
  try {
    C.note = await api(`/api/vault/note?path=${encodeURIComponent(path)}`);
  } catch (err) {
    C.note = { error: err.message };
  }
  C.keepScroll = true;
  if (S.view === 'input') renderView();
}

/** 唯一的动作：把这一条放进选题池。笔记走 triage，对标视频直接建选题。 */
async function intoPool(row) {
  try {
    const res = await api('/api/vault/triage', { method: 'PUT', body: { path: row.path, status: 'topic' } });
    toast(`已入选题池：${res.topic ? res.topic.title.slice(0, 18) : ''}`);
    await loadInbox(true);
    if (window.refreshBoard) window.refreshBoard();
    if (window.refreshTopics) await window.refreshTopics();
    renderView();
  } catch (err) { toast(err.message); }
}

const hm = (iso) => {
  if (!iso) return '';
  if (/^\d{4}-\d{2}-\d{2}$/.test(iso)) return iso.slice(5).replace('-', '/');
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
};

// 这三个状态都是 Park 自己手点的，所以每一个都得能反悔。
const TRIAGE_LABEL = { shot: '拍过了', ignored: '暂不拍', topic: '已入选题池', back: '捡回来' };
// 标过「拍过了」「暂不拍」的收到列表最下面两组里，默认折起来；点开仍能读原文、仍能捡回来。
const PARKED = ['ignored', 'shot'];

function rowActions(r) {
  if (r.state === 'working') return `<button class="chip-state working" type="button" data-work="${r.topicId}">在加工中 →</button>`;
  // 已经是视频了：去已发出看它的数据，不回加工中。
  if (r.state === 'shipped') return `<span class="chip-state shipped">已发出</span><button class="chip-state working" type="button" data-shipped="${esc(r.videoId || '')}">看数据 →</button>`;
  // 底下两组只有一个动作：捡回来，回到还没处理。
  if (r.state === 'shot' || r.state === 'ignored') return `<span class="chip-state">${r.state === 'shot' ? '拍过了' : '暂不拍'}</span><button class="btn small" type="button" data-mark="back" data-path="${esc(r.path)}">捡回来</button>`;
  // 还没处理的笔记：三个动作。
  const pool = `<button class="btn small primary" type="button" data-pool="${esc(r.id)}">入选题池</button>`;
  const park = r.path ? `<button class="btn small ghost" type="button" data-mark="shot" data-path="${esc(r.path)}">拍过了</button><button class="btn small ghost" type="button" data-mark="ignored" data-path="${esc(r.path)}">暂不拍</button>` : '';
  return pool + park;
}

window.VIEWS.input = {
  async render() {
    const body = $('#inputBody');
    if (!S.state.vault.ok) {
      body.innerHTML = `<div class="panel empty"><b>${esc(S.state.vault.message)}</b><span><button class="btn small" type="button" onclick="go('settings')">去设置</button></span></div>`;
      return;
    }
    syncTabs();
    const def = tabDef(C.tab);
    if (!C.items) body.innerHTML = '<div class="panel empty"><span class="spin"></span><span>正在读 Obsidian…</span></div>';
    try {
      await loadInbox(false);
    } catch (err) { body.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`; return; }
    // 日报不是笔记列表：一期整页铺开，一条条快讯各自入选题池。
    if (def.kind === 'daily') { await renderDaily(body); return; }

    const rows = rowsFor(C.tab);
    const fresh = (C.items || []).filter((i) => noteState(i) === 'fresh').length;
    $('#navIn').textContent = fresh || '';

    // 宽屏时右边不留空盒子：自动打开第一条可读的。
    if (!C.open && window.innerWidth > 900) {
      const first = rows.find((r) => r.path && !r.park) || rows.find((r) => r.path);
      if (first) { openNote(first.path); return; }
    }

    const sig = JSON.stringify([C.tab, C.days, C.open, Boolean(C.note), C.loadedAt, rows.map((r) => [r.id, r.taken, r.topicId])]);
    if (body.dataset.sig === sig) return;
    body.dataset.sig = sig;

    const count = (t) => {
      if (t.kind === 'note') return (C.items || []).filter((i) => i.source === t.key && noteState(i) === 'fresh').length;
      if (t.kind === 'all') return (C.items || []).filter((i) => i.source !== 'raw' && noteState(i) === 'fresh').length;
      return 0;
    };

    const rowHtml = (r) => `<div class="in-row ${C.open === r.path ? 'on' : ''} ${r.park ? 'state-' + r.park : r.taken ? 'state-' + r.taken : ''} ${r.hot ? 'blew' : ''}" ${r.path ? `data-note="${esc(r.path)}" role="button" tabindex="0"` : ''}>
        ${r.hot ? `<span class="blew-x" title="${esc(r.hot.account || '')}平时中位 ${fmt(r.hot.median)} 赞，这条 ${fmt(r.hot.likes)}">${r.hot.multiple.toFixed(1)}×</span>` : ''}
        <div class="in-meta"><span class="src">${esc(r.sub)}</span><span class="num">${hm(r.at)}</span></div>
        <b class="clamp">${esc(r.title)}</b>
        ${r.hot ? `<small class="blew-why">爆了 · 平时中位 ${fmt(r.hot.median)} 赞，这条 ${fmt(r.hot.likes)}</small>` : ''}
        ${r.summary ? `<p class="clamp">${esc(r.summary)}</p>` : ''}
        <div class="acts">${rowActions(r)}${r.url && r.source === 'benchmark' ? `<a class="btn small ghost" href="${esc(r.url)}" target="_blank" rel="noopener">去抖音 ↗</a>` : r.url && (r.source === 'saved' || r.source === 'clipping') ? `<a class="btn small ghost" href="${esc(r.url)}" target="_blank" rel="noopener">原文 ↗</a>` : ''}</div>
      </div>`;
    const active = rows.filter((r) => !r.park);
    const parked = PARKED.map((k) => [k, rows.filter((r) => r.park === k)]).filter(([, rs]) => rs.length);
    const groups = parked.map(([k, rs]) => `<details class="in-group" data-group="${k}" ${C.groups[k] ? 'open' : ''}><summary><span>${k === 'shot' ? '拍过了 · 已发出' : '暂不拍'}</span><b class="num">${rs.length}</b></summary>${rs.map(rowHtml).join('')}</details>`).join('');
    const list = rows.length ? (active.length ? active.map(rowHtml).join('') : `<div class="empty small"><span>没处理的都处理完了。</span></div>`) + groups
      : `<div class="empty"><b>这里暂时没有东西</b><span>${C.tab === 'benchmark' ? '对标账号发了新视频，工作台会自动下载、转文字，转完就出现在这里。预告、开播这类没内容的不会进来。' : C.tab === 'raw' ? '你写的东西都会出现在这里，不看时间——写过、还没拍的都在。' : def.kind === 'daily' ? '这份日报还没有出过。' : `从 ${hm(C.since)} 起没有新的。换一个时间范围看看。`}</span></div>`;

    let reader = `<div class="empty reader-empty"><span>${rows.length ? '点左边任意一条，在这里读原文。' : '这个 tab 暂时没有可读的。'}</span></div>`;
    if (C.open) {
      const n = C.note;
      if (!n) reader = '<div class="empty"><span class="spin"></span></div>';
      else if (n.error) reader = `<div class="empty"><b>${esc(n.error)}</b></div>`;
      else reader = `<div class="reader-h"><h2>${esc(n.title)}</h2><div class="acts">${n.meta && (n.meta.source || n.meta.url) ? `<a class="btn small" href="${esc(n.meta.source || n.meta.url)}" target="_blank" rel="noopener">原文 ↗</a>` : ''}</div><small>${esc(n.path)}</small></div><article class="md">${renderMarkdown(n.body || '')}</article>`;
    }

    // 点「暂不拍 / 捡回来」或点开一条读原文，列表停在原地；换 tab、换时间段才回到顶上。
    const keep = C.keepScroll ? { list: ($('.in-list', body) || {}).scrollTop || 0, win: window.scrollY } : null;
    C.keepScroll = false;
    body.innerHTML = `<div class="in-bar">
        <div class="in-tabs" role="tablist" aria-label="来源">${TABS.map((t) => { const n = count(t); return `<button type="button" role="tab" class="${C.tab === t.key ? 'on' : ''}" data-tab="${t.key}">${t.label}${n ? `<b class="num">${n}</b>` : ''}</button>`; }).join('')}</div>
        ${def.kind === 'daily' ? '' : `<div class="seg-toggle" role="group" aria-label="时间">${DAY_TABS.map(([d, l]) => `<button type="button" class="${C.days === d ? 'on' : ''}" data-days="${d}">${l}</button>`).join('')}</div>`}
      </div>
      <p class="in-note">${C.tab === 'raw' ? '你写的东西不看时间：写过、还没拍的都在这儿等着 · 只读 Obsidian' : '数字是还没入选题池的条数 · 收藏的 / Clippings 按你加进去的时间算，对标按作者发布时间算 · 只读 Obsidian'}</p>
      <div class="in-grid"><div class="panel in-list">${list}</div><div class="panel reader">${reader}</div></div>`;

    if (keep) { const l = $('.in-list', body); if (l) l.scrollTop = keep.list; window.scrollTo(0, keep.win); }
    $$('[data-tab]', body).forEach((b) => (b.onclick = () => { C.tab = b.dataset.tab; C.open = null; C.note = null; renderView(); }));
    $$('[data-days]', body).forEach((b) => (b.onclick = () => { C.days = Number(b.dataset.days); C.items = null; C.open = null; C.note = null; renderView(); }));
    $$('[data-note]', body).forEach((row) => {
      row.onclick = () => openNote(row.dataset.note);
      row.onkeydown = (e) => { if (e.key === 'Enter') openNote(row.dataset.note); };
    });
    const stop = (fn) => (e) => { e.stopPropagation(); fn(e.currentTarget); };
    $$('[data-pool]', body).forEach((b) => (b.onclick = stop((el) => {
      const row = rowsFor(C.tab).find((r) => r.id === el.dataset.pool);
      if (row) intoPool(row);
    })));
    $$('[data-work]', body).forEach((b) => (b.onclick = stop((el) => openWork(Number(el.dataset.work)))));
    $$('[data-mark]', body).forEach((b) => (b.onclick = stop((el) => markNote(el.dataset.path, el.dataset.mark || null))));
    $$('[data-shipped]', body).forEach((b) => (b.onclick = stop((el) => { S.mineFocus = el.dataset.shipped || null; go('mine'); })));
    $$('details.in-group', body).forEach((d) => (d.ontoggle = () => { C.groups[d.dataset.group] = d.open; }));
  },
};

/** 拍过了 / 暂不拍 / 捡回来（status 为空）。只改进项里这一条的状态，不动选题。 */
async function markNote(path, status) {
  try {
    await api('/api/vault/triage', { method: 'PUT', body: { path, status } });
    C.keepScroll = true;
    toast(status === 'back' ? '已捡回来' : `已标${TRIAGE_LABEL[status]}`);
    await loadInbox(true);
    renderView();
  } catch (err) { toast(err.message); }
}


/* ================= 日报：今天这一期整页铺开，单条入选题池 ================= */
const D = { issue: {}, path: {}, open: {}, originals: {}, busy: {} };

function tabBar() {
  const count = (t) => {
    if (t.kind === 'note') return (C.items || []).filter((i) => i.source === t.key && noteState(i) === 'fresh').length;
    if (t.kind === 'all') return (C.items || []).filter((i) => i.source !== 'raw' && noteState(i) === 'fresh').length;
    return 0;
  };
  return `<div class="in-bar"><div class="in-tabs" role="tablist" aria-label="来源">${TABS.map((t) => { const n = count(t); return `<button type="button" role="tab" class="${C.tab === t.key ? 'on' : ''}" data-tab="${t.key}">${t.label}${n ? `<b class="num">${n}</b>` : ''}</button>`; }).join('')}</div></div>`;
}

async function loadIssue(key, path) {
  const q = `/api/vault/daily/issue?key=${encodeURIComponent(key)}${path ? `&path=${encodeURIComponent(path)}` : ''}`;
  D.issue[key] = await api(q);
  D.path[key] = D.issue[key].path;
}

function dailyItemHtml(key, it) {
  const open = D.open[it.id];
  const orig = D.originals[it.id];
  let action;
  if (it.topic_id && !it.topic_archived) action = `<button class="chip-state working" type="button" data-work="${it.topic_id}">在选题池 →</button>`;
  else action = `<button class="btn small primary" type="button" data-dpick="${esc(it.id)}" ${D.busy[it.id] ? 'disabled' : ''}>${it.topic_archived ? '再捡回来' : '入选题池'}</button>`;
  const badge = it.has_original ? '' : '<span class="d-thin" title="日报管道只留最近几天的原文；这一条入选题池时只能带上摘要">只有摘要</span>';
  let more = '';
  if (open) {
    if (!orig) more = '<div class="d-orig"><span class="spin"></span></div>';
    else more = `<div class="d-orig">${orig.deep ? `<div class="d-deep"><b>深读</b>${renderMarkdown(orig.deep)}</div>` : ''}${orig.body ? `<div class="md">${renderMarkdown(orig.body)}</div>` : '<p class="d-none">原文已经不在日报管道里了，只有上面的摘要。</p>'}</div>`;
  }
  return `<div class="d-item ${open ? 'open' : ''}" data-ditem="${esc(it.id)}">
    <div class="d-head"><span class="d-src">${esc(it.source)}</span>${badge}</div>
    <div class="d-title"><button class="linklike" type="button" data-dtoggle="${esc(it.id)}">${esc(it.title)}</button>${it.url ? ` <a class="d-link" href="${esc(it.url)}" target="_blank" rel="noopener">原文 ↗</a>` : ''}</div>
    ${it.summary ? `<p class="d-sum">${esc(it.summary)}</p>` : ''}
    <div class="acts">${action}<button class="btn small ghost" type="button" data-dtoggle="${esc(it.id)}">${open ? '收起原文' : '展开原文'}</button></div>
    ${more}
  </div>`;
}

async function renderDaily(body) {
  const key = C.tab;
  try { if (!D.issue[key]) await loadIssue(key, D.path[key]); } catch (err) {
    body.innerHTML = tabBar() + `<div class="panel empty"><b>${esc(err.message)}</b></div>`; bindTabs(body); return;
  }
  const iss = D.issue[key];
  const latest = iss.history[0] && iss.history[0].path === iss.path;
  const note = latest ? (iss.is_today ? '今天这一期' : `今天的还没出，这是最近一期（${iss.day}）`) : `历史一期 · ${iss.day}`;
  const sections = iss.sections.map((s) => {
    if (s.kind === 'markdown') return s.markdown ? `<details class="d-sec md-sec"><summary>${esc(s.name)}</summary><div class="md">${renderMarkdown(s.markdown)}</div></details>` : '';
    let group = null;
    const rows = s.items.map((it) => {
      const head = it.group && it.group !== group ? `<div class="d-group">${esc(it.group)}</div>` : '';
      group = it.group;
      return head + dailyItemHtml(key, it);
    }).join('');
    return `<section class="d-sec"><h3>${esc(s.name)} <small>${s.items.length} 条</small></h3>${rows}</section>`;
  }).join('');
  const hist = iss.history.map((h) => `<button type="button" class="d-hist ${h.path === iss.path ? 'on' : ''}" data-dissue="${esc(h.path)}">${esc(h.day)}</button>`).join('');
  body.innerHTML = tabBar() + `
    <div class="panel d-issue">
      <div class="d-top"><div><div class="d-eyebrow">${esc(note)}</div><h2>${esc(iss.title)}</h2></div>${latest ? '' : `<button class="btn small" type="button" data-dissue="${esc(iss.history[0].path)}">回到最新一期</button>`}</div>
      <p class="in-note">每条快讯单独入选题池：放进去的是那一条的原文（有深读就带上深读），不是整份日报。</p>
      ${sections}
    </div>
    <details class="panel d-history" ${D.histOpen ? 'open' : ''}><summary>历史日报 <small>${iss.history.length} 期</small></summary><div class="d-hist-list">${hist}</div></details>`;
  bindTabs(body);
  $$('[data-dtoggle]', body).forEach((b) => (b.onclick = () => toggleOriginal(key, b.dataset.dtoggle)));
  $$('[data-dpick]', body).forEach((b) => (b.onclick = () => pickDaily(key, b.dataset.dpick)));
  $$('[data-work]', body).forEach((b) => (b.onclick = () => openWork(Number(b.dataset.work))));
  $$('[data-dissue]', body).forEach((b) => (b.onclick = async () => { D.path[key] = b.dataset.dissue; D.issue[key] = null; D.open = {}; D.originals = {}; window.scrollTo(0, 0); renderView(); }));
  const hd = $('.d-history', body); if (hd) hd.ontoggle = () => { D.histOpen = hd.open; };
}

function bindTabs(body) {
  $$('[data-tab]', body).forEach((b) => (b.onclick = () => { C.tab = b.dataset.tab; C.open = null; C.note = null; body.dataset.sig = ''; renderView(); }));
}

async function toggleOriginal(key, id) {
  D.open[id] = !D.open[id];
  renderView();
  if (D.open[id] && !D.originals[id]) {
    try { D.originals[id] = await api(`/api/vault/daily/original?key=${encodeURIComponent(key)}&path=${encodeURIComponent(D.path[key])}&item=${encodeURIComponent(id)}`); }
    catch (err) { D.originals[id] = { body: '', deep: '', error: err.message }; toast(err.message); }
    renderView();
  }
}

async function pickDaily(key, id) {
  D.busy[id] = true; renderView();
  try {
    const r = await api('/api/vault/daily/pick', { method: 'POST', body: { key, path: D.path[key], item: id } });
    toast(r.again ? '已经在选题池里了' : r.quality === '只有摘要' ? '已入选题池（只找到摘要）' : '已入选题池，带上了原文');
    D.issue[key] = null;
    if (window.refreshBoard) window.refreshBoard();
    if (window.refreshTopics) await window.refreshTopics();
  } catch (err) { toast(err.message); }
  D.busy[id] = false;
  renderView();
}
