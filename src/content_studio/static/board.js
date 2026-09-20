'use strict';
/* 02 加工中：左边选题池，右边正在做的这一条（进度条）+ 机器在做的。
   任何时候只做一条；选题池只能从进项「入选题池」进来，这里不手动加。 */
window.VIEWS = window.VIEWS || {};

const BD = { data: null, at: 0, showSnoozed: false };
const QA_SHORT = { go: '可以拍', patch: '先补再拍', thin: '素材太薄' };
// 每个阶段一个图标，选题池的行和进度条上用的是同一套，所以一眼能对上。
const MS_ICON = { topic: '◎', outline: '▤', record: '▶', edit: '✂', ready: '⏳', shipped: '✓' };

async function loadBoard(force) {
  const running = BD.data && BD.data.cards.some((c) => c.next.text === '提纲生成中');
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

/* ---- 正在做的这一条 ---- */
function milestoneBar(ms, index) {
  return `<ol class="ms" aria-label="进度">${ms.map((m, i) => `<li class="${i < index ? 'done' : i === index ? 'now' : ''}">
    <i aria-hidden="true">${MS_ICON[m.key] || ''}</i><span>${m.label}</span></li>`).join('')}</ol>`;
}

function focusBlock(d) {
  const c = d.focus;
  if (!c) {
    return `<section class="focus-card empty-focus"><div class="fc-h"><h2>正在做的这一条</h2></div>
      <div class="fc-empty"><b>还没定今天做哪条</b><span>从左边选题池里点「做这条」。任何时候只做一条，其他的都在池子里等。</span></div></section>`;
  }
  const canStepBack = c.stage === 'record' && !c.project;
  const stepped = c.manual_stage === 'outline';
  const badges = [
    c.qa ? `<span class="badge ${c.qa.verdict === 'go' ? 'ok' : 'bad'}">${QA_SHORT[c.qa.verdict] || ''} ${c.qa.total}/15</span>` : '',
    c.opening ? `<span class="badge ${c.opening.passed ? 'ok' : 'bad'}">开头${c.opening.passed ? '✓' : '✗'}</span>` : '',
    c.gate ? `<span class="badge gate">${esc(c.gate.key)}</span>` : '',
  ].join('');
  return `<section class="focus-card"><div class="fc-h"><h2>正在做的这一条</h2><small>只做这一条，做完再换</small></div>
    ${milestoneBar(d.milestones, c.milestone)}
    <div class="fc-body">
      <h3>${esc(c.title)}</h3>
      <p class="work-next ${c.next.mine ? 'mine' : ''}"><i></i>${esc(c.next.text)}</p>
      ${badges ? `<div class="card-badges">${badges}</div>` : ''}
      <div class="fc-acts">
        <button class="btn primary" type="button" data-work="${c.id}">打开</button>
        ${stepped ? `<button class="btn" type="button" data-stage-clear="${c.id}">提纲改好了，去录</button>` : canStepBack ? `<button class="btn" type="button" data-stage-back="${c.id}">退回提纲</button>` : ''}
        <span class="spacer"></span>
        <button class="btn ghost" type="button" data-unfocus="${c.id}">放回选题池</button>
      </div>
    </div></section>`;
}

/* ---- 选题池 ---- */
function poolRow(c, milestones) {
  const m = milestones[c.milestone] || milestones[0];
  return `<div class="pool-row">
    <button class="linklike pool-title" type="button" data-work="${c.id}">
      <span class="ms-chip s-${m.key}" title="进度：${m.label}"><i aria-hidden="true">${MS_ICON[m.key] || ''}</i>${m.label}</span>
      <b>${esc(c.title)}</b>
      <small>${c.qa ? `${QA_SHORT[c.qa.verdict] || ''} ${c.qa.total}/15` : c.has_outline ? '提纲已写' : '还没提纲'}</small>
    </button>
    <div class="acts"><button class="btn small primary" type="button" data-focus="${c.id}">做这条</button><button class="btn small ghost" type="button" data-archive="${c.id}">不做了</button></div>
  </div>`;
}

function machineRow(c) {
  return `<button class="machine-row" type="button" data-work="${c.id}"><span class="badge">${c.stage === 'edit' ? '剪辑' : '待发'}</span><b>${esc(c.title)}</b><small>${esc(c.next.text)}</small></button>`;
}

function attentionBlock(items) {
  if (!items.length) return '';
  return `<section class="panel attn"><div class="panel-h"><h2>对标这周爆了</h2><small>超过门槛的新爆款</small></div>
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
    if (body.dataset.sig === sig) return;
    body.dataset.sig = sig;
    const k = d.streak;
    const today = new Date().toLocaleDateString('sv-SE');
    $('#boardFigs').innerHTML = `${streakChip(k)}<label class="shot-toggle"><input type="checkbox" id="shotToday" ${k.today_done ? 'checked' : ''}><span>今天拍完了</span></label>`;

    body.innerHTML = `<div class="wk-grid">
      <section class="panel pool"><div class="panel-h"><h2>选题池 <span class="num">${d.pool.length}</span></h2><small>只从「进项」进来</small></div>
        ${d.pool.map((c) => poolRow(c, d.milestones)).join('') || '<div class="col-empty">池子是空的。去「进项」挑一条，点「入选题池」。</div>'}
        ${d.snoozed.length ? `<button class="linklike fold" type="button" id="snoozedFold">${BD.showSnoozed ? '收起' : '暂缓的'} ${d.snoozed.length} 条</button>${BD.showSnoozed ? d.snoozed.map((c) => `<div class="pool-row snoozed"><button class="linklike pool-title" type="button" data-work="${c.id}"><b>${esc(c.title)}</b><small>暂缓到 ${c.snoozed_until}</small></button><div class="acts"><button class="btn small" type="button" data-unsnooze="${c.id}">恢复</button></div></div>`).join('') : ''}` : ''}
      </section>
      <div class="wk-right">
        ${focusBlock(d)}
        <section class="panel machine"><div class="panel-h"><h2>剪辑和待发 <span class="num">${d.machine.length}</span></h2><small>这两步不用你盯</small></div>
          ${d.machine.map(machineRow).join('') || '<div class="col-empty">—</div>'}
          ${d.project_root_ok ? '' : '<p class="sync-note">外接硬盘上的视频项目目录没找到，剪辑进度暂时读不到。</p>'}
        </section>
        ${attentionBlock(d.attention || [])}
      </div>
    </div>`;

    $$('[data-work]', body).forEach((b) => (b.onclick = () => openWork(Number(b.dataset.work))));
    $$('[data-focus]', body).forEach((b) => (b.onclick = () => act(`/api/topics/${b.dataset.focus}/focus`, { message: (r) => (r.previous ? `换成做这条了，《${r.previous.slice(0, 14)}》回到选题池` : '今天就做这条') })));
    $$('[data-unfocus]', body).forEach((b) => (b.onclick = () => act(`/api/topics/${b.dataset.unfocus}/focus`, { method: 'DELETE', message: '放回选题池了' })));
    $$('[data-unsnooze]', body).forEach((b) => (b.onclick = () => act(`/api/topics/${b.dataset.unsnooze}/snooze`, { method: 'DELETE', message: '已恢复到选题池' })));
    $$('[data-archive]', body).forEach((b) => (b.onclick = async () => { if (confirm('不做了？会从池子里拿掉，笔记和文件都不删。')) await window.patchTopic(Number(b.dataset.archive), { archived: true }, '已拿掉'); }));
    $$('[data-stage-back]', body).forEach((b) => (b.onclick = () => act(`/api/topics/${b.dataset.stageBack}/stage`, { body: { stage: 'outline' }, message: '退回提纲了' })));
    $$('[data-stage-clear]', body).forEach((b) => (b.onclick = () => act(`/api/topics/${b.dataset.stageClear}/stage`, { body: { stage: null }, message: '回到录制' })));
    const fold = $('#snoozedFold');
    if (fold) fold.onclick = () => { BD.showSnoozed = !BD.showSnoozed; body.dataset.sig = ''; renderView(); };
    if (typeof bindTeardownButtons === 'function') bindTeardownButtons(body);
    $('#shotToday').onchange = async (e) => {
      try {
        await api('/api/today/checks', { method: 'PUT', body: { day: today, key: 'video_shot', checked: e.target.checked } });
        await window.refreshBoard();
        renderView();
      } catch (err) { toast(err.message); }
    };
  },
};
