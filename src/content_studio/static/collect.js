'use strict';
/* 收集：只读 Obsidian —— 今日日报、最近进项、阅读器 */
window.VIEWS = window.VIEWS || {};
window.TODAY_CARDS = window.TODAY_CARDS || [];

const C = { days: 1, source: '', items: null, since: null, open: null, note: null, dailies: null, loadedAt: 0 };
const SOURCE_TABS = [['', '全部'], ['clipping', '剪藏'], ['saved', '收藏'], ['raw', '原始输出']];

async function loadInbox(force) {
  if (!force && C.items && Date.now() - C.loadedAt < 60000) return;
  const res = await api(`/api/vault/inbox?days=${C.days}${C.source ? `&source=${C.source}` : ''}`);
  C.items = res.items;
  C.since = res.since;
  C.loadedAt = Date.now();
}

async function loadDailies(force) {
  if (!force && C.dailies && C.dailies.day === new Date().toLocaleDateString('sv-SE')) return;
  C.dailies = await api(`/api/today/dailies?day=${new Date().toLocaleDateString('sv-SE')}`);
}

function renderMarkdown(md) {
  if (window.marked && window.DOMPurify) {
    const html = window.marked.parse(md.replace(/!\[\[([^\]]+)\]\]/g, '（附件：$1）'), { breaks: true });
    return window.DOMPurify.sanitize(html, { ADD_ATTR: ['target'] });
  }
  return `<pre class="plain">${esc(md)}</pre>`;
}

async function setTriage(path, status) {
  try {
    await api('/api/vault/triage', { method: 'PUT', body: { path, status } });
    const item = (C.items || []).find((i) => i.path === path);
    if (item) item.triage = status;
    toast(status === 'topic' ? '已做成选题，在「选题」里继续' : status === 'ignored' ? '已忽略' : '已恢复');
    if (window.refreshTopics) { await window.refreshTopics(); return; }
    renderView();
  } catch (err) { toast(err.message); }
}

async function openNote(path) {
  C.open = path;
  C.note = null;
  if (S.view !== 'collect') go('collect');
  else renderView();
  try {
    C.note = await api(`/api/vault/note?path=${encodeURIComponent(path)}`);
  } catch (err) {
    C.note = { error: err.message };
  }
  if (S.view === 'collect') renderView();
}

const triageButtons = (item) => item.triage
  ? `<span class="stage-pill ${item.triage === 'topic' ? 'running' : 'queued'}">${item.triage === 'topic' ? '已标选题' : '已忽略'}</span><button class="btn small ghost" type="button" data-untriage="${esc(item.path)}">撤销</button>`
  : `<button class="btn small" type="button" data-topic="${esc(item.path)}">做成选题</button><button class="btn small ghost" type="button" data-ignore="${esc(item.path)}">忽略</button>`;

function bindTriage(root) {
  $$('[data-topic]', root).forEach((b) => (b.onclick = (e) => { e.stopPropagation(); setTriage(b.dataset.topic, 'topic'); }));
  $$('[data-ignore]', root).forEach((b) => (b.onclick = (e) => { e.stopPropagation(); setTriage(b.dataset.ignore, 'ignored'); }));
  $$('[data-untriage]', root).forEach((b) => (b.onclick = (e) => { e.stopPropagation(); setTriage(b.dataset.untriage, null); }));
  $$('[data-note]', root).forEach((b) => (b.onclick = () => openNote(b.dataset.note)));
}

const hm = (iso) => { const d = new Date(iso); return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`; };

window.VIEWS.collect = {
  async render() {
    const body = $('#collectBody');
    if (!S.state.vault.ok) {
      body.innerHTML = `<div class="panel empty"><b>${esc(S.state.vault.message)}</b><span><button class="btn small" type="button" onclick="go('settings')">去设置</button></span></div>`;
      return;
    }
    if (!C.items) body.innerHTML = '<div class="panel empty"><span class="spin"></span><span>正在读取 Obsidian…</span></div>';
    try { await loadInbox(false); } catch (err) { body.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`; return; }
    const pending = C.items.filter((i) => !i.triage).length;
    // Polling re-renders every few seconds; keep the reader's scroll position when nothing changed.
    const sig = JSON.stringify([C.source, C.days, C.open, Boolean(C.note), C.loadedAt, C.items.map((i) => i.triage)]);
    if (body.dataset.sig === sig) return;
    body.dataset.sig = sig;
    const list = C.items.length
      ? C.items.map((i) => `<div class="inbox-row ${C.open === i.path ? 'on' : ''} ${i.triage ? 'done' : ''}" data-note="${esc(i.path)}" role="button" tabindex="0">
          <div class="inbox-meta"><span class="src-tag src-${i.source}">${esc(i.source_label)}</span><span>${i.is_new ? '新增' : '修改'} ${hm(i.is_new ? i.created_at : i.modified_at)}</span></div>
          <b class="clamp">${esc(i.title)}</b>
          <p class="clamp">${esc(i.summary || '（没有正文）')}</p>
          <div class="acts">${triageButtons(i)}</div>
        </div>`).join('')
      : `<div class="empty"><b>这段时间没有新进项</b><span>从 ${hm(C.since)} 起，剪藏、收藏、原始输出都没有变化。</span></div>`;
    let reader = '<div class="empty"><span>点左边任意一条，在这里阅读原文。</span></div>';
    if (C.open) {
      const n = C.note;
      if (!n) reader = '<div class="empty"><span class="spin"></span></div>';
      else if (n.error) reader = `<div class="empty"><b>${esc(n.error)}</b></div>`;
      else reader = `<div class="reader-h"><h2>${esc(n.title)}</h2><div class="acts">${n.meta && (n.meta.source || n.meta.url) ? `<a class="btn small" href="${esc(n.meta.source || n.meta.url)}" target="_blank" rel="noopener">原文 ↗</a>` : ''}</div><small>${esc(n.path)}</small></div><article class="md">${renderMarkdown(n.body || '')}</article>`;
    }
    body.innerHTML = `<div class="controls">
        <div class="seg-toggle" role="group" aria-label="来源">${SOURCE_TABS.map(([k, l]) => `<button type="button" class="${C.source === k ? 'on' : ''}" data-src="${k}">${l}</button>`).join('')}</div>
        <div class="seg-toggle" role="group" aria-label="时间">${[[1, '昨天到现在'], [7, '最近 7 天']].map(([d, l]) => `<button type="button" class="${C.days === d ? 'on' : ''}" data-days="${d}">${l}</button>`).join('')}</div>
        <span class="sync-note">${C.items.length} 条 · ${pending} 条没处理 · 只读，不会改你的笔记</span>
      </div>
      <div class="collect-grid"><div class="panel inbox-list">${list}</div><div class="panel reader">${reader}</div></div>`;
    $$('[data-src]', body).forEach((b) => (b.onclick = async () => { C.source = b.dataset.src; C.items = null; renderView(); }));
    $$('[data-days]', body).forEach((b) => (b.onclick = async () => { C.days = Number(b.dataset.days); C.items = null; renderView(); }));
    bindTriage(body);
    $('#navCollect').textContent = C.source || C.days !== 1 ? '' : pending || '';
  },
};

window.TODAY_CARDS.push({
  id: 'dailies',
  order: 10,
  title: '今天的日报',
  async render(el) {
    if (!S.state.vault.ok) { el.innerHTML = `<div class="panel-h"><h2>今天的日报</h2></div><div class="empty"><span>${esc(S.state.vault.message)}</span></div>`; return; }
    try { await loadDailies(false); } catch (err) { el.innerHTML = `<div class="panel-h"><h2>今天的日报</h2></div><div class="empty"><span>${esc(err.message)}</span></div>`; return; }
    const d = C.dailies;
    const done = d.items.filter((i) => i.checked_at).length;
    el.innerHTML = `<div class="panel-h"><h2>今天的日报</h2><small>${done}/${d.items.length} 已看</small></div>
      <div class="check-list">${d.items.map((i) => `<div class="check-row ${i.checked_at ? 'checked' : ''}">
        <label><input type="checkbox" data-check="${i.key}" ${i.checked_at ? 'checked' : ''} ${i.path ? '' : 'disabled'}><span>${esc(i.label)}</span></label>
        ${i.path ? (i.kind === 'html' ? `<a class="btn small" href="/api/vault/raw?path=${encodeURIComponent(i.path)}" target="_blank" rel="noopener">打开 ↗</a>` : `<button class="btn small" type="button" data-read="${esc(i.path)}">阅读</button>`) : '<span class="muted">今天还没出</span>'}
      </div>`).join('')}</div>`;
    $$('[data-check]', el).forEach((box) => (box.onchange = async () => {
      try {
        await api('/api/today/checks', { method: 'PUT', body: { day: d.day, key: box.dataset.check, checked: box.checked } });
        await loadDailies(true);
        renderView();
      } catch (err) { toast(err.message); }
    }));
    $$('[data-read]', el).forEach((b) => (b.onclick = () => openNote(b.dataset.read)));
  },
});
