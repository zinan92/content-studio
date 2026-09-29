'use strict';
/* 今天：ABC 三件事，就这三件（逻辑在 driver.py）。
 * A 出摊：抖音、视频号、小红书发视频，X、公众号发文字；B 回私信；C X 互动，回 20 条。
 * 没做到当天各减 1 分，左边栏一直显示。触达是结果，不在这一页看（在「已发出」）。
 * 9/29 Park：「你只需要告诉我，我今天要做的 ABC 三件事就好了……感觉今天这个页面太散了。」
 * 拍什么他定：「接下来要拍的」收在 A 里面；只有他点「我今天不知道拍什么」才建议。 */
window.VIEWS = window.VIEWS || {};

const TD = { data: null, poll: null, skipOpen: false, bfOpen: null, prev: null, bfAll: false };

async function loadToday() { TD.data = await api('/api/today'); return TD.data; }
window.refreshTodayBadge = async () => { try { await loadToday(); } catch (_) { /* ignore */ } paintTodayBadge(); };

function paintTodayBadge() {
  const b = $('#navToday');
  if (!b || !TD.data) return;
  const n = TD.data.demerits;
  b.textContent = n ? `减 ${n}` : '';
  b.classList.toggle('bad', !!n);
}

const DOW = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
function dayTitle(key) {
  const d = new Date(key + 'T00:00:00');
  return `${d.getMonth() + 1}月${d.getDate()}日 ${DOW[d.getDay()]}`;
}

const DOT_TIP = { ok: '做到了', miss: '没做到，减 1 分', pending: '今天还没过完', 'n/a': '还没开始算' };
const dots = (days, f) => `<span class="td-days">${days.map((d) => `<i class="${d[f]}" title="${d.day}：${DOT_TIP[d[f]]}">${Number(d.day.slice(8))}</i>`).join('')}</span>`;
const miss = (days, f) => days.filter((d) => d[f] === 'miss').length;

/* 每一行右上角的状态：做到了 / 减了几分 / 今天还没 */
function rowState(days, f, doneToday) {
  const m = miss(days, f);
  return `<span class="td-state ${doneToday ? 'ok' : ''}">${doneToday ? '✓ 今天做到了' : '今天还没'}${m ? `<b>本周减 ${m}</b>` : ''}</span>`;
}

function actionButtons(it) {
  let action = '';
  if (it.inputs === 'start_note') action = `<button class="btn go" type="button" data-td-start="${esc(it.key.split(':')[1])}">开始做</button>`;
  else if (it.inputs === 'focus_notes') action = '<button class="btn go" type="button" data-td-focusnotes>写一条</button>';
  else if (it.url) action = `<a class="btn go" href="${esc(it.url)}" target="_blank" rel="noopener">${esc(it.button)} ↗</a>`;
  else if (it.go) action = `<button class="btn go" type="button" data-td-go="${esc(it.go)}">${esc(it.button)} →</button>`;
  const manual = it.manual ? `<button class="btn" type="button" data-td-done="${esc(it.key)}">${it.rung === 'client' ? '发了' : '做完了'}</button>` : '';
  const skip = TD.skipOpen === it.key
    ? `<form class="td-skip" data-skip-form="${esc(it.key)}"><input maxlength="200" placeholder="为什么今天不做？一句话" autocomplete="off"><button class="btn" type="submit">跳过</button><button class="btn quiet" type="button" data-td-skipcancel>算了，去做</button></form>`
    : `<button class="btn quiet" type="button" data-td-skip="${esc(it.key)}">跳过（写一句为什么）</button>`;
  return `<div class="btns">${action}${manual}${skip}</div>`;
}

const nextLine = (it) => it ? `<div class="td-next"><b>${esc(it.text)}</b>${it.why ? `<small>${esc(it.why)}</small>` : ''}${actionButtons(it)}</div>` : '';

function firstBlock(list) {
  if (!list.length) return '';
  return `<section class="td-first"><h3>先处理</h3>${list.map((it) => `<div class="td-next"><span class="k">${esc(it.rung_label)}</span><b>${esc(it.text)}</b>${it.why ? `<small>${esc(it.why)}</small>` : ''}${actionButtons(it)}</div>`).join('')}</section>`;
}

function shipRow(d) {
  const s = d.ship;
  const plat = (p) => `<span class="td-plat ${p.shipped ? 'on' : ''} ${p.core ? '' : 'rest'}" title="${esc(p.label)}${p.shipped ? '：发了' : p.skipped ? '：这条不发' : '：还没发'}">${p.shipped ? '✓' : p.skipped ? '–' : '○'} ${esc(p.label)}</span>`;
  const FORM = { video: '发视频', text: '发文字', cards: '发图文', audio: '发音频' };
  const groups = ['video', 'text', 'cards', 'audio'].map((f) => [f, s.platforms.filter((p) => p.form === f)]).filter(([, ps]) => ps.length);
  const notes = s.notes.map((n, i) => `<li class="${i === 0 ? 'top' : ''}"><span>${esc(n.text)}${n.topic_id ? ' <small class="tag">在做</small>' : ''}</span>
    <span class="acts"><button type="button" class="linklike" data-note-up="${n.id}" ${i === 0 ? 'disabled' : ''} aria-label="上移">↑</button><button type="button" class="linklike" data-note-down="${n.id}" ${i === s.notes.length - 1 ? 'disabled' : ''} aria-label="下移">↓</button><button type="button" class="linklike" data-note-del="${n.id}" aria-label="删掉">×</button></span></li>`).join('');
  const sg = s.suggest;
  let sug = '<button class="btn small" type="button" id="tdSuggest">我今天不知道拍什么</button>';
  if (sg && sg.running) sug = '<span class="td-note"><span class="spin"></span> 在你的选题池里挑一条…</span>';
  else if (sg && sg.error) sug = `<span class="td-note warn">${esc(sg.error)}</span> <button class="btn small" type="button" id="tdSuggest">再挑一次</button>`;
  else if (sg && sg.topic_id) sug = `<div class="td-sug"><b>建议拍：${esc(sg.title)}</b><span>${esc(sg.why)}</span><div class="btns"><button class="btn go" type="button" id="tdTake">就拍这条</button><button class="btn quiet" type="button" id="tdSuggest">换一条</button></div></div>`;
  return `<section class="td-row ${s.done ? 'done' : ''}">
    <div class="td-h"><span class="td-letter">A</span><h2>出摊</h2>${rowState(d.days, 'ship', s.done)}${dots(d.days, 'ship')}</div>
    <div class="td-plats">${s.topic ? `<span class="td-topic">《${esc(s.topic.title)}》</span>` : ''}${groups.map(([f, ps]) => `<span class="td-form">${FORM[f]}</span>${ps.map(plat).join('')}`).join('')}</div>
    ${nextLine(s.next)}
    <details class="td-notes" ${s.notes.length ? '' : 'open'}><summary>接下来要拍的 · 你定${s.notes.length ? ` <span class="num">${s.notes.length}</span>` : ''}</summary>
      ${notes ? `<ol>${notes}</ol>` : '<p class="td-note">还没写。想好要拍什么就写在这里，最上面那条就是下一次出摊要拍的。</p>'}
      <form class="td-add" id="tdAdd"><input id="tdAddText" maxlength="200" placeholder="写一条要拍的，回车加到最后" autocomplete="off"></form>
      ${sug}</details>
  </section>`;
}

function dmRow(d) {
  const e = d.dm.entry || {};
  const done = d.dm.entry && e.replied >= e.received;
  return `<section class="td-row ${done ? 'done' : ''}">
    <div class="td-h"><span class="td-letter">B</span><h2>回私信</h2>${rowState(d.days, 'dm', done)}${dots(d.days, 'dm')}</div>
    <p class="td-why">当天收到的当天回完，每条都往「动手」引。${d.dm.target ? `目标每天收到 ${d.dm.target} 条。` : `收到多少先记到 ${esc(d.dm.baseline_until.slice(5).replace('-', '/'))} 摸底，再定目标。`}</p>
    <form class="td-dm" id="tdDm"><label>收到 <input id="tdDmRecv" type="number" min="0" inputmode="numeric" value="${e.received ?? ''}"></label>
      <label>回了 <input id="tdDmRep" type="number" min="0" inputmode="numeric" value="${e.replied ?? ''}"></label>
      <button class="btn ${done ? '' : 'go'}" type="submit">${d.dm.entry ? '改' : '记下'}</button>${done ? '' : d.dm.entry ? `<small class="td-note">还差 ${e.received - e.replied} 条</small>` : ''}</form>
  </section>`;
}

function xrRow(d) {
  const n = d.xr.count, t = d.xr.target;
  const done = n != null && n >= t;
  return `<section class="td-row ${done ? 'done' : ''}">
    <div class="td-h"><span class="td-letter">C</span><h2>X 互动 · 回 ${t} 条</h2>${rowState(d.days, 'xr', done)}${dots(d.days, 'xr')}</div>
    <p class="td-why">在你这个领域的中文大号帖子下面回一句有立场的话，不带链接。你在 X 上被看到过的，全是回复。</p>
    <form class="td-dm" id="tdXr"><a class="btn" href="https://x.com/home" target="_blank" rel="noopener">打开 X ↗</a>
      <label>今天回了 <input id="tdXrN" type="number" min="0" inputmode="numeric" value="${n ?? ''}"> / ${t}</label>
      <button class="btn ${done ? '' : 'go'}" type="submit">${n != null ? '改' : '记下'}</button>${n != null && !done ? `<small class="td-note">还差 ${t - n} 条</small>` : ''}</form>
  </section>`;
}

/* D 补发：提前打好的包，今天挑一条发到剩下的平台。数据还是记在全平台追踪。
 * 看 → 就地展开（封面、文案、文章开头、插图、完整排版另开一页）；改 → 去打包页；发 → 一声令下。 */
const PF = { channels: '视频号', xiaohongshu: '小红书', bilibili: 'B 站', youtube: 'YouTube', x: 'X', wechat_mp: '公众号' };
const AUTO = ['bilibili', 'youtube', 'x'];
const STEP_LABEL = { copy: '文案', cover: '封面', article: '文章', figs: '插图', wx: '排版' };

function packRow(p) {
  const open = TD.bfOpen === p.topic_id;
  const steps = Object.entries(p.steps).map(([k, v]) => `<span class="td-step ${v}">${STEP_LABEL[k]}</span>`).join('');
  return `<div class="td-pack ${open ? 'open' : ''}">
    <button type="button" class="td-pack-h" data-bf-open="${p.topic_id}">
      ${p.cover ? `<img src="${esc(p.cover)}" alt="" loading="lazy">` : '<span class="td-nocover"></span>'}
      <span class="t"><b>${esc(p.title)}</b><small>${p.multiple != null ? `${p.multiple}× · ` : ''}${esc((p.published_at || '').slice(0, 10))} · 差 ${p.missing_labels.join('、')}</small>
        <span class="td-steps">${steps}${p.machine ? '<i>机器定稿，你没看过</i>' : ''}</span></span>
      <span class="chev">${open ? '收起' : '看一眼'}</span>
    </button>
    ${open ? `<div class="td-preview" id="tdPrev">${TD.prev && TD.prev.topic_id === p.topic_id ? previewHtml(TD.prev, p) : '<p class="td-note"><span class="spin"></span> 读包里的东西…</p>'}</div>` : ''}
  </div>`;
}

function previewHtml(v, p) {
  const auto = p.missing.filter((k) => AUTO.includes(k)).map((k) => PF[k]);
  const hand = p.missing.filter((k) => !AUTO.includes(k)).map((k) => PF[k]);
  return `<div class="td-pv-covers">${['portrait', 'landscape', 'wide'].filter((k) => v.covers[k]).map((k) => `<a href="${esc(v.covers[k])}" target="_blank" rel="noopener"><img class="${k}" src="${esc(v.covers[k])}" alt=""></a>`).join('')}</div>
    <div class="td-pv-copy"><b>${esc(v.title)}</b>${v.body ? `<p>${esc(v.body)}</p>` : ''}${v.tags.length ? `<small>${v.tags.map((t) => '#' + esc(t)).join(' ')}</small>` : ''}</div>
    ${v.article_title ? `<div class="td-pv-art"><h4>${esc(v.article_title)}</h4>${v.article_head.map((x) => `<p>${esc(x)}</p>`).join('')}
      ${v.figs.length ? `<div class="td-pv-figs">${v.figs.map((u) => `<a href="${esc(u)}" target="_blank" rel="noopener"><img src="${esc(u)}" alt="" loading="lazy"></a>`).join('')}</div>` : ''}
      ${v.layout_url ? `<a class="btn" href="${esc(v.layout_url)}" target="_blank" rel="noopener">看完整公众号排版 ↗</a>` : ''}</div>` : ''}
    <div class="td-pv-go">
      <p class="td-note">点「发这条」就是你的确认：${auto.length ? `<b>${auto.join('、')}</b> 自己发出去` : ''}${auto.length && hand.length ? '；' : ''}${hand.length ? `<b>${hand.join('、')}</b> 备好，你来点（公众号群发、视频号和小红书扫码上传）` : ''}。</p>
      <div class="btns"><button class="btn go" type="button" data-bf-go="${p.topic_id}">发这条</button><button class="btn" type="button" data-td-go="pack/${p.topic_id}">去改 →</button></div>
    </div>`;
}

function todayPack(t) {
  const JOB = { running: '发送中…', done: '已发出', failed: '失败了', awaiting_confirm: '等确认' };
  const cells = t.missing.concat(Object.keys(PF).filter((k) => !t.missing.includes(k) && k in PF)).filter((k, i, a) => a.indexOf(k) === i);
  const cell = (k) => {
    const shipped = !t.missing.includes(k);
    const j = (t.jobs || {})[k];
    const state = shipped ? '✓ 发了' : j ? (j.draft ? '草稿好了，去点发布' : JOB[j.state] || j.state) : AUTO.includes(k) ? '—' : '等你';
    return `<span class="td-plat ${shipped ? 'on' : j && j.state === 'failed' ? 'bad' : ''}" title="${esc((j && j.message) || '')}">${PF[k]} · ${state}</span>`;
  };
  return `<div class="td-next"><b>今天补发《${esc(t.title)}》：${t.done_count}/${t.total}</b>
      <div class="td-plats">${cells.map(cell).join('')}</div>
      <small>剩下的去发布台：公众号群发，视频号、小红书的上传文件夹里视频、封面、文案都齐了。</small>
      <div class="btns"><button class="btn go" type="button" data-td-go="publish/${t.topic_id}">去发布台 →</button><button class="btn quiet" type="button" data-bf-unpick>换一条</button></div></div>`;
}

function backfillRow(d) {
  const b = d.backfill;
  const done = b.today && b.today.missing.length === 0;
  const list = b.ready.slice(0, TD.bfAll ? 50 : 3).map(packRow).join('');
  return `<section class="td-row ${done ? 'done' : ''}">
    <div class="td-h"><span class="td-letter">D</span><h2>补发</h2><span class="td-state ${done ? 'ok' : ''}">${done ? '✓ 今天补完了' : b.today ? '今天在补' : `包打好 ${b.ready_count} 条${b.waiting_count ? ` · 还在打 ${b.waiting_count} 条` : ''}`}</span></div>
    <p class="td-why">没拍新视频的日子，挑一条旧的发到剩下的平台。B 站、YouTube、X 自己发出去；公众号、视频号、小红书你来点，十几分钟。</p>
    ${b.today ? todayPack(b.today) : ''}
    ${!b.today || done ? `<div class="td-packs">${list || '<p class="td-note">还没有打好的包。</p>'}</div>
      ${b.ready.length > 3 ? `<button class="btn quiet" type="button" data-bf-all>${TD.bfAll ? '只看前三条' : `看全部 ${b.ready.length} 条`}</button>` : ''}` : ''}
  </section>`;
}

function wrapBlock(d) {
  const rows = d.wrap.map((it) => `<div class="td-next small"><b>${esc(it.text)}</b>${actionButtons(it)}</div>`).join('');
  const skipped = d.skipped.map((s) => `<div class="td-q skip"><span class="n">跳</span><b>${esc(s.key)}</b><small>${esc(s.reason || '')}</small></div>`).join('');
  if (!rows && !skipped) return '';
  return `<section class="td-wrap"><h3>杂事</h3>${rows}${skipped}</section>`;
}

async function tdAct(fn) {
  try { await fn(); } catch (err) { toast(err.message); }
  TD.skipOpen = false;
  $('#todayBody').dataset.sig = '';
  window.VIEWS.today.render();
}

function goHash(h) { location.hash = '#' + h; go(readHash(), { push: false }); }

window.VIEWS.today = {
  async render() {
    const body = $('#todayBody');
    let d;
    try { d = await loadToday(); } catch (err) { body.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`; return; }
    paintTodayBadge();
    $('#todayDay').textContent = `今天 · ${dayTitle(d.day)}`;
    $('#todayScore').innerHTML = d.demerits ? `本周减 <b>${d.demerits}</b> 分` : '本周没减分';
    if (document.activeElement && body.contains(document.activeElement) && document.activeElement.matches('input')) return;
    const sig = JSON.stringify([d, TD.skipOpen, TD.bfOpen, TD.prev && TD.prev.topic_id, TD.bfAll]);
    if (body.dataset.sig === sig) return;
    body.dataset.sig = sig;
    body.innerHTML = `${firstBlock(d.first)}${shipRow(d)}${dmRow(d)}${xrRow(d)}${backfillRow(d)}${wrapBlock(d)}
      <p class="td-note td-foot">触达是结果，不算你的分，在「已发出」里看：7 天平均 ${fmt(d.reach.avg7 || 0)} / 目标 ${fmt(d.reach.target)}（${esc(d.reach.by.slice(5).replace('-', '/'))} 前）。</p>`;

    $$('[data-td-go]', body).forEach((b) => (b.onclick = () => goHash(b.dataset.tdGo)));
    $$('[data-td-done]', body).forEach((b) => (b.onclick = () => tdAct(() => api('/api/today/done', { method: 'POST', body: { key: b.dataset.tdDone } }))));
    $$('[data-td-start]', body).forEach((b) => (b.onclick = () => tdAct(async () => { const r = await api(`/api/today/notes/${b.dataset.tdStart}/start`, { method: 'POST' }); goHash(`work/${r.topic.id}`); })));
    $$('[data-td-focusnotes]', body).forEach((b) => (b.onclick = () => { const dt = $('.td-notes', body); if (dt) dt.open = true; $('#tdAddText').focus(); }));
    $$('[data-td-skip]', body).forEach((b) => (b.onclick = () => { TD.skipOpen = b.dataset.tdSkip; body.dataset.sig = ''; this.render().then(() => { const i = $('[data-skip-form] input', body); if (i) i.focus(); }); }));
    $$('[data-td-skipcancel]', body).forEach((b) => (b.onclick = () => { TD.skipOpen = false; body.dataset.sig = ''; this.render(); }));
    $$('[data-skip-form]', body).forEach((f) => (f.onsubmit = (e) => { e.preventDefault(); tdAct(() => api('/api/today/skip', { method: 'POST', body: { key: f.dataset.skipForm, reason: $('input', f).value } })); }));
    $('#tdDm').onsubmit = (e) => {
      e.preventDefault();
      if ($('#tdDmRecv').value === '' || $('#tdDmRep').value === '') { toast('两个数都填上，0 也算'); return; }
      tdAct(() => api('/api/today/dm', { method: 'PUT', body: { received: Number($('#tdDmRecv').value), replied: Number($('#tdDmRep').value) } }));
    };
    $('#tdXr').onsubmit = (e) => {
      e.preventDefault();
      if ($('#tdXrN').value === '') { toast('填今天回了几条，0 也算'); return; }
      tdAct(() => api('/api/today/x-replies', { method: 'PUT', body: { value: Number($('#tdXrN').value) } }));
    };
    $('#tdAdd').onsubmit = (e) => { e.preventDefault(); const text = $('#tdAddText').value.trim(); if (!text) return; $('#tdAddText').value = ''; tdAct(() => api('/api/today/notes', { method: 'POST', body: { text } })); };
    $$('[data-note-up]', body).forEach((b) => (b.onclick = () => tdAct(() => api(`/api/today/notes/${b.dataset.noteUp}`, { method: 'PATCH', body: { move: -1 } }))));
    $$('[data-note-down]', body).forEach((b) => (b.onclick = () => tdAct(() => api(`/api/today/notes/${b.dataset.noteDown}`, { method: 'PATCH', body: { move: 1 } }))));
    $$('[data-note-del]', body).forEach((b) => (b.onclick = () => tdAct(() => api(`/api/today/notes/${b.dataset.noteDel}`, { method: 'DELETE' }))));
    $$('[data-bf-open]', body).forEach((b) => (b.onclick = async () => {
      const id = Number(b.dataset.bfOpen);
      TD.bfOpen = TD.bfOpen === id ? null : id;
      body.dataset.sig = '';
      this.render();
      if (TD.bfOpen && !(TD.prev && TD.prev.topic_id === id)) {
        try { TD.prev = await api(`/api/today/backfill/${id}/preview`); } catch (err) { toast(err.message); }
        body.dataset.sig = '';
        this.render();
      }
    }));
    $$('[data-bf-go]', body).forEach((b) => (b.onclick = () => tdAct(async () => {
      b.disabled = true;
      const r = await api(`/api/today/backfill/${b.dataset.bfGo}/go`, { method: 'POST' });
      TD.bfOpen = null;
      toast(r.errors.length ? `有 ${r.errors.length} 个没起来：${r.errors[0]}` : '发出去了的在发，剩下的备好了');
    })));
    const unpick = $('[data-bf-unpick]', body);
    if (unpick) unpick.onclick = () => tdAct(() => api('/api/today/backfill', { method: 'DELETE' }));
    const all = $('[data-bf-all]', body);
    if (all) all.onclick = () => { TD.bfAll = !TD.bfAll; body.dataset.sig = ''; this.render(); };
    const sugBtn = $('#tdSuggest');
    if (sugBtn) sugBtn.onclick = () => tdAct(() => api('/api/today/suggest', { method: 'POST' }));
    const take = $('#tdTake');
    if (take) take.onclick = () => tdAct(() => api('/api/today/suggest/take', { method: 'POST' }));

    clearTimeout(TD.poll);
    const sending = d.backfill.today && Object.values(d.backfill.today.jobs || {}).some((j) => j.state === 'running');
    if ((d.ship.suggest && d.ship.suggest.running) || sending) TD.poll = setTimeout(() => { if (S.view === 'today') this.render(); }, sending ? 8000 : 3000);
  },
};
