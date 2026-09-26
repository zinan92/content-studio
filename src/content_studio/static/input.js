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

const C = { tab: 'all', days: 1, items: null, since: null, open: null, note: null, dailies: {}, loadedAt: 0 };

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

/* ---- 把三种来源归一成同一种行 ---- */
const noteRow = (i) => ({
  // 对标转录显示博主的名字；其余笔记显示它来自哪个文件夹。
  id: 'n:' + i.path, path: i.path, title: i.title, sub: i.author || i.source_label,
  at: i.is_new ? i.created_at : i.modified_at, summary: i.summary,
  // 标过「不做了」的选题不算「已拿走」——那篇笔记重新是可选的。
  taken: (i.used_by && i.used_by.dropped) ? '' : (i.triage || (i.used_by ? 'topic' : '')),
  topicId: i.used_by ? i.used_by.topic_id : null, shipped: i.used_by ? i.used_by.shipped : false,
  dropped: Boolean(i.used_by && i.used_by.dropped),
  url: i.url || null, hot: i.breakout || null,
});
const dailyRow = (d) => ({
  id: 'd:' + d.path, path: d.path, title: d.title, sub: d.label, at: d.day || d.modified_at, summary: '',
  taken: '', topicId: null, shipped: false, external: d.kind === 'html' ? d.path : null,
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
  C.open = path;
  C.note = null;
  if (S.view !== 'input') go('input');
  else renderView();
  try {
    C.note = await api(`/api/vault/note?path=${encodeURIComponent(path)}`);
  } catch (err) {
    C.note = { error: err.message };
  }
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
const TRIAGE_LABEL = { shot: '拍过了', ignored: '已忽略', topic: '已入选题池' };

function rowActions(r) {
  // 唯一没有按钮的情况：它真的在加工中或已发出，那颗 chip 本身就是入口。
  if (r.taken === 'topic' && r.topicId) {
    return r.shipped ? '<span class="chip-state shipped">已发出</span>'
      : `<button class="chip-state working" type="button" data-work="${r.topicId}">在加工中 →</button>`;
  }
  const again = `<button class="btn small primary" type="button" data-pool="${esc(r.id)}">${r.dropped || r.taken ? '再捡回来' : '入选题池'}</button>`;
  if (r.dropped) return `<span class="chip-state">标过不做了</span>${again}`;
  // 标过拍过了 / 已忽略：说清楚是哪一种（以前一律写成「已入选题池」，是错的），并留一条回头路。
  return r.taken ? `<span class="chip-state">${TRIAGE_LABEL[r.taken] || r.taken}</span>${again}` : again;
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
      if (def.kind === 'daily') await loadDaily(C.tab, false);
    } catch (err) { body.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`; return; }

    const rows = rowsFor(C.tab);
    const fresh = (C.items || []).filter((i) => !i.triage && !i.used_by).length;
    $('#navIn').textContent = fresh || '';

    // 宽屏时右边不留空盒子：自动打开第一条可读的。
    if (!C.open && window.innerWidth > 900) {
      const first = rows.find((r) => r.path);
      if (first) { openNote(first.path); return; }
    }

    const sig = JSON.stringify([C.tab, C.days, C.open, Boolean(C.note), C.loadedAt, rows.map((r) => [r.id, r.taken, r.topicId])]);
    if (body.dataset.sig === sig) return;
    body.dataset.sig = sig;

    const count = (t) => {
      if (t.kind === 'note') return (C.items || []).filter((i) => i.source === t.key && !i.triage && !i.used_by).length;
      if (t.kind === 'all') return (C.items || []).filter((i) => i.source !== 'raw' && !i.triage && !i.used_by).length;
      return 0;
    };

    const list = rows.length ? rows.map((r) => `<div class="in-row ${C.open === r.path ? 'on' : ''} ${r.taken ? 'state-' + r.taken : ''} ${r.hot ? 'blew' : ''}" ${r.path ? `data-note="${esc(r.path)}" role="button" tabindex="0"` : ''}>
        ${r.hot ? `<span class="blew-x" title="${esc(r.hot.account || '')}平时中位 ${fmt(r.hot.median)} 赞，这条 ${fmt(r.hot.likes)}">${r.hot.multiple.toFixed(1)}×</span>` : ''}
        <div class="in-meta"><span class="src">${esc(r.sub)}</span><span class="num">${hm(r.at)}</span></div>
        <b class="clamp">${esc(r.title)}</b>
        ${r.hot ? `<small class="blew-why">爆了 · 平时中位 ${fmt(r.hot.median)} 赞，这条 ${fmt(r.hot.likes)}</small>` : ''}
        ${r.summary ? `<p class="clamp">${esc(r.summary)}</p>` : ''}
        <div class="acts">${rowActions(r)}${r.url ? `<a class="btn small ghost" href="${esc(r.url)}" target="_blank" rel="noopener">去抖音 ↗</a>` : ''}</div>
      </div>`).join('')
      : `<div class="empty"><b>这里暂时没有东西</b><span>${C.tab === 'benchmark' ? '对标账号发了新视频，工作台会自动下载、转文字，转完就出现在这里。预告、开播这类没内容的不会进来。' : C.tab === 'raw' ? '你写的东西都会出现在这里，不看时间——写过、还没拍的都在。' : def.kind === 'daily' ? '这份日报还没有出过。' : `从 ${hm(C.since)} 起没有新的。换一个时间范围看看。`}</span></div>`;

    let reader = `<div class="empty reader-empty"><span>${rows.length ? '点左边任意一条，在这里读原文。' : '这个 tab 暂时没有可读的。'}</span></div>`;
    if (C.open) {
      const n = C.note;
      if (!n) reader = '<div class="empty"><span class="spin"></span></div>';
      else if (n.error) reader = `<div class="empty"><b>${esc(n.error)}</b></div>`;
      else reader = `<div class="reader-h"><h2>${esc(n.title)}</h2><div class="acts">${n.meta && (n.meta.source || n.meta.url) ? `<a class="btn small" href="${esc(n.meta.source || n.meta.url)}" target="_blank" rel="noopener">原文 ↗</a>` : ''}</div><small>${esc(n.path)}</small></div><article class="md">${renderMarkdown(n.body || '')}</article>`;
    }

    body.innerHTML = `<div class="in-bar">
        <div class="in-tabs" role="tablist" aria-label="来源">${TABS.map((t) => { const n = count(t); return `<button type="button" role="tab" class="${C.tab === t.key ? 'on' : ''}" data-tab="${t.key}">${t.label}${n ? `<b class="num">${n}</b>` : ''}</button>`; }).join('')}</div>
        ${def.kind === 'daily' ? '' : `<div class="seg-toggle" role="group" aria-label="时间">${DAY_TABS.map(([d, l]) => `<button type="button" class="${C.days === d ? 'on' : ''}" data-days="${d}">${l}</button>`).join('')}</div>`}
      </div>
      <p class="in-note">${C.tab === 'raw' ? '你写的东西不看时间：写过、还没拍的都在这儿等着 · 只读 Obsidian' : '数字是还没入选题池的条数 · 收藏的 / Clippings 按你加进去的时间算，对标按作者发布时间算 · 只读 Obsidian'}</p>
      <div class="in-grid"><div class="panel in-list">${list}</div><div class="panel reader">${reader}</div></div>`;

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
  },
};
