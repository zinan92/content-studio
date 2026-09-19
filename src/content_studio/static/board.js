'use strict';
/* 02 加工中：今天推荐拍 → 正在做的这一条（选题 → 提纲 → 录制 → 剪辑 → 待发 → 已发出）→ 选题池 → 机器在做的 */
window.VIEWS = window.VIEWS || {};

const BD = { data: null, at: 0, showSnoozed: false };
const EFFORT_NAME = { 低: '好拍', 中: '要准备', 高: '费劲' };
const QA_SHORT = { go: '可以拍', patch: '先补再拍', thin: '素材太薄' };

async function loadBoard(force) {
  const running = BD.data && (BD.data.recommend.state === 'running' || BD.data.cards.some((c) => c.next.text === '提纲生成中'));
  if (!force && BD.data && Date.now() - BD.at < (running ? 4000 : 20000)) return BD.data;
  BD.data = await api(`/api/board?day=${new Date().toLocaleDateString('sv-SE')}`);
  BD.at = Date.now();
  const waiting = (BD.data.focus ? 1 : 0) + BD.data.pool.length;
  $('#navWork').innerHTML = waiting ? `${waiting}${BD.data.focus && BD.data.focus.next.mine ? '<i class="wait" title="正在做的这条在等你"></i>' : ''}` : '';
  return BD.data;
}

window.refreshBoard = async () => { BD.data = null; try { await loadBoard(true); } catch (_) { /* shown on render */ } };
window.refreshTopics = async () => { await window.refreshBoard(); if (window.invalidateWork) window.invalidateWork(); renderView(); };
window.patchTopic = async (id, body, message) => {
  try {
    await api(`/api/topics/${id}`, { method: 'PATCH', body });
    if (message) toast(message);
    await window.refreshTopics();
  } catch (err) { toast(err.message); }
};

function openWork(id) {
  S.workId = id;
  if (window.invalidateWork) window.invalidateWork();
  go('work');
}
window.openWork = openWork;

async function act(path, { method = 'POST', body, message } = {}) {
  try {
    const res = await api(path, { method, body });
    if (message) toast(typeof message === 'function' ? message(res) : message);
    await window.refreshTopics();
    return res;
  } catch (err) { toast(err.message); return null; }
}

function streakChip(k) {
  if (!k) return '';
  if (k.today_done) return `<div class="streak ok"><b class="num">${k.days}</b><span>天连续拍摄</span></div>`;
  if (k.days > 0) return `<div class="streak warn"><b class="num">${k.days}</b><span>天连续 · 今天还没拍</span></div>`;
  return `<div class="streak broken"><b class="num">${k.days_since_last ?? '—'}</b><span>天没拍了</span></div>`;
}

function hmTime(iso) {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function qaChips(qa) {
  if (!qa) return '';
  return `<div class="rec-qa">${[['pain', '痛点'], ['contrast', '反差'], ['delivery', '交付']].map(([k, l]) => `<span class="${qa[k] <= 2 ? 'low' : ''}">${l} <b class="num">${qa[k]}</b></span>`).join('')}${qa.note ? `<small>${esc(qa.note)}</small>` : ''}</div>`;
}

/* ---- 今天推荐拍 ---- */
function recFoot(v, hasFocus) {
  if (v.dropped) return '<span class="chip-state">不做了</span>';
  if (v.focus) return `<button class="btn small" type="button" data-work="${v.topic_id}">正在做这条 →</button>`;
  if (v.snoozed) return `<span class="chip-state">已暂缓两周</span><button class="linklike" type="button" data-unsnooze="${v.topic_id}">恢复</button>`;
  if (v.topic_id) return `<button class="btn small primary" type="button" data-focus="${v.topic_id}">今天做这条</button><button class="btn small" type="button" data-work="${v.topic_id}">在选题池 →</button>`;
  return `<button class="btn small primary" type="button" data-rec-focus="${v.index}">${hasFocus ? '换成做这条' : '今天做这条'}</button>
    <button class="btn small" type="button" data-rec-take="${v.index}">放进选题池</button>
    <button class="btn small ghost" type="button" data-rec-snooze="${v.index}">暂不拍</button>`;
}

function recommendBlock(r, hasFocus) {
  const head = `<div class="rec-h"><h2>今天推荐拍</h2><small>${r.generated_at ? `根据今天的日报和你写的东西 · ${hmTime(r.generated_at)}` : ''}</small><span class="spacer"></span>${r.items.length ? '<button class="linklike" type="button" data-rec-generate>重新推荐</button>' : ''}</div>`;
  if (r.state === 'running') return `<section class="rec">${head}<div class="rec-wait"><span class="spin"></span>正在读今天的日报和你最近写的东西，挑两条…</div></section>`;
  if (r.state === 'failed' && !r.items.length) return `<section class="rec">${head}<div class="rec-wait bad">${esc(r.error || '推荐失败')} <button class="btn small" type="button" data-rec-generate>再试一次</button></div></section>`;
  if (!r.items.length) return `<section class="rec">${head}<div class="rec-wait">每天早上日报出来后（约 9:00）会自动推荐。<button class="btn small" type="button" data-rec-generate>现在就推荐</button></div></section>`;
  return `<section class="rec">${head}<div class="rec-row">${r.items.map((v) => `<article class="rec-card ${v.primary ? 'primary' : ''}">
      <div class="rec-top"><span class="rec-tag">${v.primary ? '首选' : '备选'}</span>${v.effort ? `<span class="rec-effort">${EFFORT_NAME[v.effort] || v.effort}</span>` : ''}</div>
      <h3>${esc(v.title)}</h3>
      ${v.hook ? `<blockquote>${esc(v.hook)}</blockquote>` : ''}
      ${qaChips(v.qa)}
      <p>${esc(v.why)}</p>
      <div class="rec-foot">${recFoot(v, hasFocus)}</div>
    </article>`).join('')}</div></section>`;
}

/* ---- 正在做的这一条 ---- */
function milestoneBar(ms, index, c) {
  return `<ol class="ms" aria-label="进度">${ms.map((m, i) => `<li class="${i < index ? 'done' : i === index ? 'now' : ''}${i > 2 ? ' auto' : ''}"><i></i><span>${m.label}</span></li>`).join('')}</ol>`;
}

function focusBlock(d) {
  const c = d.focus;
  if (!c) {
    return `<section class="focus-card empty-focus"><div class="fc-h"><h2>正在做的这一条</h2></div>
      <div class="fc-empty"><b>还没定今天做哪条</b><span>从上面的推荐里点「今天做这条」，或者去选题池里挑一条。任何时候只做一条，其他的都在池子里等。</span></div></section>`;
  }
  const canStepBack = c.stage === 'record' && !c.project;
  const stepped = c.manual_stage === 'outline';
  const badges = [
    c.qa ? `<span class="badge ${c.qa.verdict === 'go' ? 'ok' : 'bad'}">${QA_SHORT[c.qa.verdict] || ''} ${c.qa.total}/15</span>` : '',
    c.opening ? `<span class="badge ${c.opening.passed ? 'ok' : 'bad'}">开头${c.opening.passed ? '✓' : '✗'}</span>` : '',
    c.gate ? `<span class="badge gate">${esc(c.gate.key)}</span>` : '',
  ].join('');
  return `<section class="focus-card"><div class="fc-h"><h2>正在做的这一条</h2><small>只做这一条，做完再换</small></div>
    ${milestoneBar(d.milestones, c.milestone, c)}
    <div class="fc-body">
      <h3>${esc(c.title)}</h3>
      <p class="work-next ${c.next.mine ? 'mine' : ''}"><i></i>${esc(c.next.text)}</p>
      ${badges ? `<div class="card-badges">${badges}</div>` : ''}
      <div class="fc-acts">
        <button class="btn primary" type="button" data-work="${c.id}">打开</button>
        ${stepped ? `<button class="btn" type="button" data-stage-clear="${c.id}">提纲改好了，去录</button>` : canStepBack ? `<button class="btn" type="button" data-stage-back="${c.id}">退回提纲</button>` : ''}
        <span class="spacer"></span>
        <button class="btn ghost" type="button" data-unfocus="${c.id}">放回选题池</button>
        <button class="btn ghost" type="button" data-snooze="${c.id}">暂不拍</button>
      </div>
    </div></section>`;
}

/* ---- 选题池 / 机器在做 / 需要你看 ---- */
function poolRow(c) {
  return `<div class="pool-row">
    <button class="linklike pool-title" type="button" data-work="${c.id}"><b>${esc(c.title)}</b><small>${c.has_outline ? '提纲已写' : '还没提纲'}${c.qa ? ` · ${QA_SHORT[c.qa.verdict] || ''} ${c.qa.total}/15` : ''}</small></button>
    <div class="acts"><button class="btn small primary" type="button" data-focus="${c.id}">做这条</button><button class="btn small ghost" type="button" data-snooze="${c.id}">暂不拍</button><button class="btn small ghost" type="button" data-archive="${c.id}">不做了</button></div>
  </div>`;
}

function machineRow(c) {
  return `<button class="machine-row" type="button" data-work="${c.id}"><span class="badge">${c.stage === 'edit' ? '剪辑' : '待发'}</span><b>${esc(c.title)}</b><small>${esc(c.next.text)}</small></button>`;
}

function attentionBlock(items) {
  if (!items.length) return '';
  return `<section class="attn"><div class="fc-h"><h2>对标这周爆了</h2><small>超过门槛的新爆款，不用去雷达里翻</small></div>
    ${items.map((v) => `<div class="attn-row"><span class="pill hot">${v.multiple.toFixed(1)}×</span>
      <div class="attn-main"><b class="clamp">${esc(cleanTitle(v.title))}</b><small>${esc(v.account || '')} · ${day(v.published_at)} · ${fmt(v.likes)} 赞</small></div>
      <div class="acts">${typeof teardownButton === 'function' ? teardownButton(v, { source: `看板 · 对标本周爆款 · ${v.account || ''}` }) : ''}</div></div>`).join('')}</section>`;
}

window.VIEWS.board = {
  async render() {
    const body = $('#boardBody');
    let d;
    try { d = await loadBoard(false); } catch (err) { body.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`; return; }
    const sig = JSON.stringify([BD.at, BD.showSnoozed]);
    if (body.dataset.sig === sig || (document.activeElement && document.activeElement.id === 'newIn')) return;
    body.dataset.sig = sig;
    const k = d.streak;
    $('#boardFigs').innerHTML = `${streakChip(k)}<label class="shot-toggle"><input type="checkbox" id="shotToday" ${k.today_done ? 'checked' : ''}><span>今天拍完了</span></label>`;

    body.innerHTML = `${recommendBlock(d.recommend, Boolean(d.focus))}
      ${focusBlock(d)}
      ${attentionBlock(d.attention || [])}
      <div class="pool-grid">
        <section class="panel pool"><div class="panel-h"><h2>选题池 <span class="num">${d.pool.length}</span></h2><small>挑一条做，其他的先等着</small></div>
          <form class="new-card" id="newForm"><input id="newIn" placeholder="＋ 自己加一条" aria-label="新视频标题" autocomplete="off"></form>
          ${d.pool.map(poolRow).join('') || '<div class="col-empty">池子是空的：从进项页「拿来做」，或上面自己加一条</div>'}
          ${d.snoozed.length ? `<button class="linklike fold" type="button" id="snoozedFold">${BD.showSnoozed ? '收起' : '暂缓的'} ${d.snoozed.length} 条</button>${BD.showSnoozed ? d.snoozed.map((c) => `<div class="pool-row snoozed"><button class="linklike pool-title" type="button" data-work="${c.id}"><b>${esc(c.title)}</b><small>暂缓到 ${c.snoozed_until}</small></button><div class="acts"><button class="btn small" type="button" data-unsnooze="${c.id}">恢复</button></div></div>`).join('') : ''}` : ''}
        </section>
        <section class="panel machine"><div class="panel-h"><h2>剪辑和待发 <span class="num">${d.machine.length}</span></h2><small>这两步不用你盯</small></div>
          ${d.machine.map(machineRow).join('') || '<div class="col-empty">—</div>'}
          ${d.project_root_ok ? '' : '<p class="sync-note">外接硬盘上的视频项目目录没找到，剪辑进度暂时读不到。</p>'}
        </section>
      </div>`;

    $$('[data-work]', body).forEach((b) => (b.onclick = () => openWork(Number(b.dataset.work))));
    $$('[data-focus]', body).forEach((b) => (b.onclick = () => act(`/api/topics/${b.dataset.focus}/focus`, { message: (r) => (r.previous ? `换成做这条了，《${r.previous.slice(0, 14)}》回到选题池` : '今天就做这条') })));
    $$('[data-unfocus]', body).forEach((b) => (b.onclick = () => act(`/api/topics/${b.dataset.unfocus}/focus`, { method: 'DELETE', message: '放回选题池了' })));
    $$('[data-snooze]', body).forEach((b) => (b.onclick = () => act(`/api/topics/${b.dataset.snooze}/snooze`, { body: { days: 14 }, message: '两周内不再出现' })));
    $$('[data-unsnooze]', body).forEach((b) => (b.onclick = () => act(`/api/topics/${b.dataset.unsnooze}/snooze`, { method: 'DELETE', message: '已恢复到选题池' })));
    $$('[data-archive]', body).forEach((b) => (b.onclick = async () => { if (confirm('不做了？会从池子里拿掉，笔记和文件都不删。')) await window.patchTopic(Number(b.dataset.archive), { archived: true }, '已拿掉'); }));
    $$('[data-stage-back]', body).forEach((b) => (b.onclick = () => act(`/api/topics/${b.dataset.stageBack}/stage`, { body: { stage: 'outline' }, message: '退回提纲了' })));
    $$('[data-stage-clear]', body).forEach((b) => (b.onclick = () => act(`/api/topics/${b.dataset.stageClear}/stage`, { body: { stage: null }, message: '回到录制' })));
    const recAct = (attr, extra, message) => $$(`[${attr}]`, body).forEach((b) => (b.onclick = async () => {
      b.disabled = true;
      const res = await act('/api/briefing/topic', { body: { day: d.recommend.day, index: Number(b.getAttribute(attr)), ...extra }, message });
      if (!res) b.disabled = false;
    }));
    recAct('data-rec-focus', { focus: true }, '今天就做这条');
    recAct('data-rec-take', {}, '已放进选题池');
    recAct('data-rec-snooze', { snooze: true }, '两周内不再推这条');
    $$('[data-rec-generate]', body).forEach((b) => (b.onclick = async () => {
      try { const r = await api('/api/briefing/generate', { method: 'POST', body: { day: d.recommend.day } }); toast(r.message || '开始推荐'); await window.refreshBoard(); renderView(); } catch (err) { toast(err.message); }
    }));
    const fold = $('#snoozedFold');
    if (fold) fold.onclick = () => { BD.showSnoozed = !BD.showSnoozed; body.dataset.sig = ''; renderView(); };
    if (typeof bindTeardownButtons === 'function') bindTeardownButtons(body);
    $('#newForm').onsubmit = async (e) => {
      e.preventDefault();
      const title = $('#newIn').value.trim();
      if (!title) return;
      try {
        await api('/api/topics', { method: 'POST', body: { title, formats: 'both', account_id: S.mine && S.mine.account ? S.mine.account.id : null } });
        $('#newIn').value = '';
        $('#newIn').blur();
        toast('已加进选题池');
        await window.refreshBoard();
        renderView();
      } catch (err) { toast(err.message); }
    };
    $('#shotToday').onchange = async (e) => {
      try {
        await api('/api/today/checks', { method: 'PUT', body: { day: d.recommend.day, key: 'video_shot', checked: e.target.checked } });
        await window.refreshBoard();
        renderView();
      } catch (err) { toast(err.message); }
    };
  },
};
