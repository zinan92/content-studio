'use strict';
/* 01 进项：今天的 Newsletter + Obsidian 里新进来的 Clippings / 我收藏的 / 我写的（只读） */
window.VIEWS = window.VIEWS || {};

const C = { days: 1, source: '', items: null, since: null, open: null, note: null, dailies: null, loadedAt: 0 };
const SOURCE_TABS = [['', '全部'], ['clipping', 'Clippings'], ['saved', '我收藏的'], ['raw', '我写的']];
const DAY_TABS = [[1, '昨天到现在'], [7, '7 天'], [30, '30 天']];

async function loadInbox(force) {
  if (!force && C.items && Date.now() - C.loadedAt < 60000) return;
  const res = await api(`/api/vault/inbox?days=${C.days}${C.source ? `&source=${C.source}` : ''}`);
  C.items = res.items;
  C.since = res.since;
  C.loadedAt = Date.now();
}

async function loadDailies(force) {
  const today = new Date().toLocaleDateString('sv-SE');
  if (!force && C.dailies && C.dailies.day === today) return;
  C.dailies = await api(`/api/today/dailies?day=${today}`);
}

function renderMarkdown(md) {
  if (window.marked && window.DOMPurify) {
    const html = window.marked.parse(md.replace(/!\[\[([^\]]+)\]\]/g, '（附件：$1）'), { breaks: true });
    return window.DOMPurify.sanitize(html, { ADD_ATTR: ['target'] });
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

async function setTriage(path, status) {
  try {
    const res = await api('/api/vault/triage', { method: 'PUT', body: { path, status } });
    toast(status === 'topic' ? `已进加工中：${res.topic ? res.topic.title.slice(0, 18) : ''}` : status === 'shot' ? '已标拍过了，推荐不会再用它' : status === 'ignored' ? '已忽略' : '已恢复');
    await loadInbox(true);
    if (window.refreshBoard) window.refreshBoard();
    renderView();
  } catch (err) { toast(err.message); }
}

const hm = (iso) => { const d = new Date(iso); return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`; };
const TRIAGE_NAME = { topic: '已拿来做', shot: '拍过了', ignored: '已忽略' };

function rowState(i) {
  if (i.used_by) return i.used_by.shipped ? 'shipped' : 'working';
  return i.triage || '';
}

function rowActions(i) {
  if (i.used_by) {
    return i.used_by.shipped
      ? '<span class="chip-state shipped">已发出</span>'
      : `<button class="chip-state working" type="button" data-work="${i.used_by.topic_id}">在加工中 →</button>`;
  }
  if (i.triage) return `<span class="chip-state">${TRIAGE_NAME[i.triage]}</span><button class="linklike" type="button" data-untriage="${esc(i.path)}">撤销</button>`;
  return `<button class="btn small primary" type="button" data-take="${esc(i.path)}">拿来做</button>
    <button class="btn small ghost" type="button" data-shot="${esc(i.path)}" title="在工作台外已经拍过了">拍过了</button>
    <button class="btn small ghost" type="button" data-ignore="${esc(i.path)}">忽略</button>`;
}

function newsletterStrip() {
  const d = C.dailies;
  if (!d) return '';
  const ready = d.items.filter((i) => i.path);
  const read = ready.filter((i) => i.checked_at).length;
  return `<section class="nl">
    <div class="nl-h"><h2>今天的 Newsletter</h2><span class="num">${read}/${ready.length || d.items.length} 读完</span></div>
    <div class="nl-row">${d.items.map((i) => `<article class="nl-tile ${i.checked_at ? 'read' : ''} ${i.path ? '' : 'missing'}">
      <div class="nl-top"><b>${esc(i.label)}</b>${i.path ? `<label class="nl-check"><input type="checkbox" data-check="${i.key}" ${i.checked_at ? 'checked' : ''}><span>${i.checked_at ? '读完了' : '没读'}</span></label>` : '<span class="muted">还没出</span>'}</div>
      ${i.path ? (i.kind === 'html'
        ? `<a class="nl-open" href="/api/vault/raw?path=${encodeURIComponent(i.path)}" target="_blank" rel="noopener">打开 ↗</a>`
        : `<button class="nl-open" type="button" data-read="${esc(i.path)}">在右边读</button>`) : ''}
    </article>`).join('')}</div>
  </section>`;
}

window.VIEWS.input = {
  async render() {
    const body = $('#inputBody');
    if (!S.state.vault.ok) {
      body.innerHTML = `<div class="panel empty"><b>${esc(S.state.vault.message)}</b><span><button class="btn small" type="button" onclick="go('settings')">去设置</button></span></div>`;
      return;
    }
    if (!C.items) body.innerHTML = '<div class="panel empty"><span class="spin"></span><span>正在读 Obsidian…</span></div>';
    try { await Promise.all([loadInbox(false), loadDailies(false)]); } catch (err) { body.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`; return; }
    const fresh = C.items.filter((i) => !i.triage && !i.used_by);
    $('#navIn').textContent = C.days === 1 && !C.source ? (fresh.length || '') : $('#navIn').textContent;
    const sig = JSON.stringify([C.source, C.days, C.open, Boolean(C.note), C.loadedAt, C.items.map((i) => [i.triage, Boolean(i.used_by)]), C.dailies && C.dailies.items.map((i) => i.checked_at)]);
    if (body.dataset.sig === sig) return;
    body.dataset.sig = sig;

    const bySource = SOURCE_TABS.slice(1).map(([k, l]) => [l, C.items.filter((i) => i.source === k && !i.triage && !i.used_by).length]);
    $('#inFigs').innerHTML = C.source ? '' : bySource.map(([l, n]) => `<div class="fig"><b class="num">${n}</b><span>${l}</span></div>`).join('');

    const list = C.items.length
      ? C.items.map((i) => `<div class="in-row ${C.open === i.path ? 'on' : ''} state-${rowState(i)}" data-note="${esc(i.path)}" role="button" tabindex="0">
          <div class="in-meta"><span class="src src-${i.source}">${esc(i.source_label)}</span><span class="num">${hm(i.is_new ? i.created_at : i.modified_at)}</span>${i.is_new ? '' : '<span class="muted">改过</span>'}</div>
          <b class="clamp">${esc(i.title)}</b>
          <p class="clamp">${esc(i.summary || '（没有正文）')}</p>
          <div class="acts">${rowActions(i)}</div>
        </div>`).join('')
      : `<div class="empty"><b>这段时间没有新东西进来</b><span>从 ${hm(C.since)} 起，Clippings、我收藏的、我写的都没有变化。</span></div>`;

    let reader = '<div class="empty reader-empty"><span>点左边任意一条，在这里读原文。</span></div>';
    if (C.open) {
      const n = C.note;
      if (!n) reader = '<div class="empty"><span class="spin"></span></div>';
      else if (n.error) reader = `<div class="empty"><b>${esc(n.error)}</b></div>`;
      else reader = `<div class="reader-h"><h2>${esc(n.title)}</h2><div class="acts">${n.meta && (n.meta.source || n.meta.url) ? `<a class="btn small" href="${esc(n.meta.source || n.meta.url)}" target="_blank" rel="noopener">原文 ↗</a>` : ''}</div><small>${esc(n.path)}</small></div><article class="md">${renderMarkdown(n.body || '')}</article>`;
    }

    body.innerHTML = `${newsletterStrip()}
      <div class="controls">
        <div class="seg-toggle" role="group" aria-label="来源">${SOURCE_TABS.map(([k, l]) => `<button type="button" class="${C.source === k ? 'on' : ''}" data-src="${k}">${l}</button>`).join('')}</div>
        <div class="seg-toggle" role="group" aria-label="时间">${DAY_TABS.map(([d, l]) => `<button type="button" class="${C.days === d ? 'on' : ''}" data-days="${d}">${l}</button>`).join('')}</div>
        <span class="sync-note">${C.items.length} 条 · ${fresh.length} 条还没处理 · 只读，不会改你的笔记</span>
      </div>
      <div class="in-grid"><div class="panel in-list">${list}</div><div class="panel reader">${reader}</div></div>`;

    $$('[data-src]', body).forEach((b) => (b.onclick = () => { C.source = b.dataset.src; C.items = null; renderView(); }));
    $$('[data-days]', body).forEach((b) => (b.onclick = () => { C.days = Number(b.dataset.days); C.items = null; renderView(); }));
    $$('[data-note]', body).forEach((row) => {
      row.onclick = () => openNote(row.dataset.note);
      row.onkeydown = (e) => { if (e.key === 'Enter') openNote(row.dataset.note); };
    });
    const stop = (fn) => (e) => { e.stopPropagation(); fn(e.currentTarget); };
    $$('[data-take]', body).forEach((b) => (b.onclick = stop((el) => setTriage(el.dataset.take, 'topic'))));
    $$('[data-shot]', body).forEach((b) => (b.onclick = stop((el) => setTriage(el.dataset.shot, 'shot'))));
    $$('[data-ignore]', body).forEach((b) => (b.onclick = stop((el) => setTriage(el.dataset.ignore, 'ignored'))));
    $$('[data-untriage]', body).forEach((b) => (b.onclick = stop((el) => setTriage(el.dataset.untriage, null))));
    $$('[data-work]', body).forEach((b) => (b.onclick = stop((el) => openWork(Number(el.dataset.work)))));
    $$('[data-read]', body).forEach((b) => (b.onclick = () => openNote(b.dataset.read)));
    $$('[data-check]', body).forEach((box) => (box.onchange = async () => {
      try {
        await api('/api/today/checks', { method: 'PUT', body: { day: C.dailies.day, key: box.dataset.check, checked: box.checked } });
        await loadDailies(true);
        renderView();
      } catch (err) { toast(err.message); }
    }));
  },
};
