'use strict';
/* 今天：用 KPI 驱动 Park，一次只给一件事（逻辑在 driver.py，顺序 Park 9/29 拍板）。
 * 上面 KPI 条：出摊、回私信算他的分（没做到减分），触达是结果。中间「现在做这件事」只有一件，
 * 按钮直接带他去做；后面几件灰着排队。右边「接下来要拍的」他自己写、自己排——选题他定。
 * 这一页不放单条视频的数据（Park：I need to be indifferent about my numbers）。 */
window.VIEWS = window.VIEWS || {};

const TD = { data: null, poll: null, skipOpen: false };

async function loadToday() { TD.data = await api('/api/today'); return TD.data; }
window.refreshTodayBadge = async () => { try { await loadToday(); } catch (_) { /* ignore */ } paintTodayBadge(); };

function paintTodayBadge() {
  const b = $('#navToday');
  if (!b || !TD.data) return;
  const n = TD.data.kpi.demerits;
  b.textContent = n ? `减 ${n}` : '';
  b.classList.toggle('bad', !!n);
}

const DOW = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
function dayTitle(key) {
  const d = new Date(key + 'T00:00:00');
  return `${d.getMonth() + 1}月${d.getDate()}日 ${DOW[d.getDay()]}`;
}

function kpiBar(k) {
  const cell = (d, f) => `<i class="${d[f]}" title="${d.day}：${{ ok: '做到了', miss: '没做到，减 1 分', pending: '今天还没过完', 'n/a': '还没开始算' }[d[f]]}">${Number(d.day.slice(8))}</i>`;
  const dmMiss = k.days.filter((d) => d.dm === 'miss').length;
  const shipMiss = k.days.filter((d) => d.ship === 'miss').length;
  const dm = k.dm_today ? `${k.dm_today.replied} / ${k.dm_today.received}` : '—';
  const pct = k.reach_target ? Math.min(100, Math.round(((k.reach_avg7 || 0) / k.reach_target) * 100)) : 0;
  return `<div class="td-kpis">
    <div class="td-kpi ${shipMiss ? 'bad' : 'ok'}"><span class="l">出摊 · 最近 7 天</span>
      <span class="v num">${k.posted_7} / 7${shipMiss ? ` <small>减 ${shipMiss}</small>` : ''}</span>
      <span class="td-days">${k.days.map((d) => cell(d, 'ship')).join('')}</span></div>
    <div class="td-kpi ${dmMiss ? 'bad' : ''}"><span class="l">回私信 · 今天回了 / 收到</span>
      <span class="v num">${dm}${dmMiss ? ` <small>减 ${dmMiss}</small>` : ''}</span>
      <span class="td-days">${k.days.map((d) => cell(d, 'dm')).join('')}</span></div>
    <div class="td-kpi"><span class="l">触达 · 7 天平均 / 目标（${esc(k.reach_by.slice(5).replace('-', '/'))} 前）</span>
      <span class="v num">${fmt(k.reach_avg7 || 0)} <small>/ ${fmt(k.reach_target)}</small></span>
      <span class="td-bar"><b style="width:${pct}%"></b></span></div>
  </div>
  <p class="td-rule">出摊、回私信是你的分，没做到当天各减 1 分。触达是结果，不算你的分：没达标我来改你每天要做的事。${k.dm_target ? `收到私信目标：每天 ${k.dm_target} 条。` : `收到私信先记到 ${esc(k.dm_baseline_until.slice(5).replace('-', '/'))} 摸底，再定目标。`}</p>`;
}

function nowCard(it) {
  if (!it) return `<div class="td-now clear"><div class="k">现在</div><div class="act">今天的事都做完了</div><div class="td-why">KPI 都过了。想多做一条，就从右边清单里拿第一条开始。</div></div>`;
  let action = '';
  if (it.inputs === 'dm') {
    const e = (TD.data.kpi.dm_today) || {};
    action = `<form class="td-dm" id="tdDm"><label>收到 <input id="tdDmRecv" type="number" min="0" inputmode="numeric" value="${e.received ?? ''}"></label>
      <label>回了 <input id="tdDmRep" type="number" min="0" inputmode="numeric" value="${e.replied ?? ''}"></label>
      <button class="btn go" type="submit">记下</button></form>`;
  } else if (it.inputs === 'start_note') {
    action = `<button class="btn go" type="button" data-td-start="${esc(it.key.split(':')[1])}">开始做</button>`;
  } else if (it.inputs === 'focus_notes') {
    action = '<button class="btn go" type="button" data-td-focusnotes>写一条</button>';
  } else if (it.url) {
    action = `<a class="btn go" href="${esc(it.url)}" target="_blank" rel="noopener">${esc(it.button)} ↗</a>`;
  } else if (it.go) {
    action = `<button class="btn go" type="button" data-td-go="${esc(it.go)}">${esc(it.button)} →</button>`;
  }
  const manual = it.manual ? `<button class="btn" type="button" data-td-done="${esc(it.key)}">${it.rung === 'client' ? '发了' : '做完了'}</button>` : '';
  const skip = TD.skipOpen
    ? `<form class="td-skip" id="tdSkip"><input id="tdSkipWhy" maxlength="200" placeholder="为什么今天不做？一句话" autocomplete="off"><button class="btn" type="submit">跳过</button><button class="btn quiet" type="button" data-td-skipcancel>算了，去做</button></form>`
    : '<button class="btn quiet" type="button" data-td-skip>跳过（写一句为什么）</button>';
  return `<div class="td-now"><div class="k">现在 · ${esc(it.rung_label)}</div>
    <div class="act">${esc(it.text)}</div>${it.why ? `<div class="td-why">${esc(it.why)}</div>` : ''}
    <div class="btns">${action}${manual}${skip}</div></div>`;
}

function queueList(d) {
  const rows = d.queue.map((it, i) => `<div class="td-q"><span class="n num">${i + 2}</span><b>${esc(it.text)}</b><small>${esc(it.rung_label)}</small></div>`).join('');
  const skipped = d.skipped.map((s) => `<div class="td-q skip"><span class="n">跳</span><b>${esc(s.key)}</b><small>${esc(s.reason || '')}</small></div>`).join('');
  const done = d.shipped_today ? '<div class="td-q done"><span class="n">✓</span><b>今天出摊了：抖音发出新视频</b><small>自己看到的</small></div>' : '';
  if (!rows && !skipped && !done) return '';
  return `<div class="td-queue">${rows ? `<div class="qh">接下来</div>${rows}` : ''}${done || skipped ? `<div class="qh">今天</div>${done}${skipped}` : ''}</div>
    ${rows ? '<p class="td-note">接下来那几件只是排着，一次只做最上面那件。</p>' : ''}`;
}

function notesPanel(d) {
  const s = d.suggest;
  const list = d.notes.map((n, i) => `<li class="${i < 1 ? 'top' : ''}"><span>${esc(n.text)}${n.topic_id ? ' <small class="tag">在做</small>' : ''}</span>
    <span class="acts"><button type="button" class="linklike" data-note-up="${n.id}" ${i === 0 ? 'disabled' : ''} aria-label="上移">↑</button><button type="button" class="linklike" data-note-down="${n.id}" ${i === d.notes.length - 1 ? 'disabled' : ''} aria-label="下移">↓</button><button type="button" class="linklike" data-note-del="${n.id}" aria-label="删掉">×</button></span></li>`).join('');
  let sug = '<button class="btn" type="button" id="tdSuggest">我今天不知道拍什么</button>';
  if (s && s.running) sug = '<span class="td-note"><span class="spin"></span> 在你的选题池里挑一条…</span>';
  else if (s && s.error) sug = `<span class="td-note warn">${esc(s.error)}</span><button class="btn" type="button" id="tdSuggest">再挑一次</button>`;
  else if (s && s.topic_id) sug = `<div class="td-sug"><b>建议拍：${esc(s.title)}</b><span>${esc(s.why)}</span><div class="btns"><button class="btn go" type="button" id="tdTake">就拍这条</button><button class="btn quiet" type="button" id="tdSuggest">换一条</button></div></div>`;
  return `<div class="td-notes" id="tdNotes"><h3>接下来要拍的 · 你定</h3>
    ${list ? `<ol>${list}</ol>` : '<p class="td-note">还没写。想好要拍什么就写在这里，最上面那条就是下一次出摊要拍的。</p>'}
    <form class="td-add" id="tdAdd"><input id="tdAddText" maxlength="200" placeholder="写一条要拍的，回车加到最后" autocomplete="off"></form>
    ${sug}
    <p class="td-note">只有你点「我今天不知道拍什么」，我才从选题池里挑一条给你。</p></div>`;
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
    if (document.activeElement && body.contains(document.activeElement) && document.activeElement.matches('input')) return;
    const sig = JSON.stringify([d, TD.skipOpen]);
    if (body.dataset.sig === sig) return;
    body.dataset.sig = sig;
    body.innerHTML = `${kpiBar(d.kpi)}
      <div class="td-two"><div class="td-main">${nowCard(d.now)}${queueList(d)}</div>${notesPanel(d)}</div>`;

    const it = d.now;
    $$('[data-td-go]', body).forEach((b) => (b.onclick = () => goHash(b.dataset.tdGo)));
    $$('[data-td-done]', body).forEach((b) => (b.onclick = () => tdAct(() => api('/api/today/done', { method: 'POST', body: { key: b.dataset.tdDone } }))));
    $$('[data-td-start]', body).forEach((b) => (b.onclick = () => tdAct(async () => { const r = await api(`/api/today/notes/${b.dataset.tdStart}/start`, { method: 'POST' }); goHash(`work/${r.topic.id}`); })));
    $$('[data-td-focusnotes]', body).forEach((b) => (b.onclick = () => $('#tdAddText').focus()));
    const skipBtn = $('[data-td-skip]', body);
    if (skipBtn) skipBtn.onclick = () => { TD.skipOpen = true; body.dataset.sig = ''; this.render().then(() => { const i = $('#tdSkipWhy'); if (i) i.focus(); }); };
    const cancel = $('[data-td-skipcancel]', body);
    if (cancel) cancel.onclick = () => { TD.skipOpen = false; body.dataset.sig = ''; this.render(); };
    const skipForm = $('#tdSkip');
    if (skipForm) skipForm.onsubmit = (e) => { e.preventDefault(); tdAct(() => api('/api/today/skip', { method: 'POST', body: { key: it.key, reason: $('#tdSkipWhy').value } })); };
    const dm = $('#tdDm');
    if (dm) dm.onsubmit = (e) => {
      e.preventDefault();
      const received = Number($('#tdDmRecv').value), replied = Number($('#tdDmRep').value);
      if ($('#tdDmRecv').value === '' || $('#tdDmRep').value === '') { toast('两个数都填上，0 也算'); return; }
      tdAct(() => api('/api/today/dm', { method: 'PUT', body: { received, replied } }));
    };
    $('#tdAdd').onsubmit = (e) => { e.preventDefault(); const text = $('#tdAddText').value.trim(); if (!text) return; $('#tdAddText').value = ''; tdAct(() => api('/api/today/notes', { method: 'POST', body: { text } })); };
    $$('[data-note-up]', body).forEach((b) => (b.onclick = () => tdAct(() => api(`/api/today/notes/${b.dataset.noteUp}`, { method: 'PATCH', body: { move: -1 } }))));
    $$('[data-note-down]', body).forEach((b) => (b.onclick = () => tdAct(() => api(`/api/today/notes/${b.dataset.noteDown}`, { method: 'PATCH', body: { move: 1 } }))));
    $$('[data-note-del]', body).forEach((b) => (b.onclick = () => tdAct(() => api(`/api/today/notes/${b.dataset.noteDel}`, { method: 'DELETE' }))));
    const sugBtn = $('#tdSuggest');
    if (sugBtn) sugBtn.onclick = () => tdAct(() => api('/api/today/suggest', { method: 'POST' }));
    const take = $('#tdTake');
    if (take) take.onclick = () => tdAct(() => api('/api/today/suggest/take', { method: 'POST' }));

    clearTimeout(TD.poll);
    if (d.suggest && d.suggest.running) TD.poll = setTimeout(() => { if (S.view === 'today') this.render(); }, 3000);
  },
};
