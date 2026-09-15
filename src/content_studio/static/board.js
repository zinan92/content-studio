'use strict';
/* 02 加工中：今天推荐拍 + 提纲 → 录制 → 剪辑 → 待发 看板 */
window.VIEWS = window.VIEWS || {};

const BD = { data: null, at: 0 };
const EFFORT_NAME = { 低: '好拍', 中: '要准备', 高: '费劲' };

async function loadBoard(force) {
  const running = BD.data && (BD.data.recommend.state === 'running' || BD.data.cards.some((c) => c.next.text === '提纲生成中'));
  if (!force && BD.data && Date.now() - BD.at < (running ? 4000 : 20000)) return BD.data;
  BD.data = await api(`/api/board?day=${new Date().toLocaleDateString('sv-SE')}`);
  BD.at = Date.now();
  const waiting = BD.data.cards.filter((c) => c.next.mine).length;
  $('#navWork').innerHTML = BD.data.cards.length ? `${BD.data.cards.length}${waiting ? `<i class="wait" title="${waiting} 条在等你"></i>` : ''}` : '';
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

function streakChip(k) {
  if (!k) return '';
  if (k.today_done) return `<div class="streak ok"><b class="num">${k.days}</b><span>天连续拍摄</span></div>`;
  if (k.days > 0) return `<div class="streak warn"><b class="num">${k.days}</b><span>天连续 · 今天还没拍</span></div>`;
  return `<div class="streak broken"><b class="num">${k.days_since_last ?? '—'}</b><span>天没拍了</span></div>`;
}

function recommendBlock(r) {
  const head = `<div class="rec-h"><h2>今天推荐拍</h2><small>${r.generated_at ? `根据今天的 Newsletter 和你写的东西 · ${hmTime(r.generated_at)}` : ''}</small></div>`;
  if (r.state === 'running') return `<section class="rec">${head}<div class="rec-wait"><span class="spin"></span>正在读今天的 Newsletter 和你最近写的东西，挑两条…</div></section>`;
  if (r.state === 'failed' && !r.items.length) return `<section class="rec">${head}<div class="rec-wait bad">${esc(r.error || '推荐失败')} <button class="btn small" type="button" data-rec-generate>再试一次</button></div></section>`;
  if (!r.items.length) return `<section class="rec">${head}<div class="rec-wait">每天早上日报出来后（约 9:00）会自动推荐。<button class="btn small" type="button" data-rec-generate>现在就推荐</button></div></section>`;
  return `<section class="rec">${head}<div class="rec-row">${r.items.map((v) => `<article class="rec-card ${v.primary ? 'primary' : ''}">
      <div class="rec-top"><span class="rec-tag">${v.primary ? '首选' : '备选'}</span>${v.effort ? `<span class="rec-effort">${EFFORT_NAME[v.effort] || v.effort}</span>` : ''}</div>
      <h3>${esc(v.title)}</h3>
      ${v.hook ? `<blockquote>${esc(v.hook)}</blockquote>` : ''}
      <p>${esc(v.why)}</p>
      <div class="rec-foot">${v.dropped
        ? '<span class="chip-state">已经拍过 / 不做了</span>'
        : v.topic_id
        ? `<button class="btn small" type="button" data-work="${v.topic_id}">已在看板里 →</button>`
        : `<button class="btn small primary" type="button" data-take-rec="${v.index}">拿来做</button>`}</div>
    </article>`).join('')}</div></section>`;
}

function hmTime(iso) {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function boardCard(c) {
  const badges = [
    c.gate ? `<span class="badge gate">${esc(c.gate.key)}</span>` : '',
    c.opening ? `<span class="badge ${c.opening.passed ? 'ok' : 'bad'}">开头${c.opening.passed ? '✓' : '✗'}</span>` : '',
    c.has_article ? '<span class="badge">文章</span>' : '',
  ].join('');
  return `<button type="button" class="card ${c.next.mine ? 'mine' : ''}" data-work="${c.id}">
    <b>${esc(c.title)}</b>
    <span class="card-next"><i></i>${esc(c.next.text)}</span>
    ${badges ? `<span class="card-badges">${badges}</span>` : ''}
  </button>`;
}

window.VIEWS.board = {
  async render() {
    const body = $('#boardBody');
    let d;
    try { d = await loadBoard(false); } catch (err) { body.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`; return; }
    const sig = JSON.stringify([BD.at]);
    if (body.dataset.sig === sig || (document.activeElement && document.activeElement.id === 'newIn')) return;
    body.dataset.sig = sig;
    const k = d.streak;
    $('#boardFigs').innerHTML = `${streakChip(k)}<label class="shot-toggle"><input type="checkbox" id="shotToday" ${k.today_done ? 'checked' : ''}><span>今天拍完了</span></label>`;
    const columns = d.stages.map((stage) => {
      const cards = d.cards.filter((c) => c.stage === stage.key);
      return `<div class="col col-${stage.key}">
        <div class="col-h"><b>${stage.label}</b><span class="num">${cards.length}</span></div>
        ${stage.key === 'outline' ? '<form class="new-card" id="newForm"><input id="newIn" placeholder="＋ 自己加一条" aria-label="新视频标题" autocomplete="off"></form>' : ''}
        ${cards.map(boardCard).join('') || '<div class="col-empty">—</div>'}
      </div>`;
    }).join('');
    body.innerHTML = `${recommendBlock(d.recommend)}<div class="board">${columns}</div>
      ${d.project_root_ok ? '' : '<p class="sync-note">外接硬盘上的视频项目目录没找到，录制和剪辑的进度暂时读不到。</p>'}`;

    $$('[data-work]', body).forEach((b) => (b.onclick = () => openWork(Number(b.dataset.work))));
    $$('[data-take-rec]', body).forEach((b) => (b.onclick = async () => {
      b.disabled = true;
      try {
        const res = await api('/api/briefing/topic', { method: 'POST', body: { day: d.recommend.day, index: Number(b.dataset.takeRec) } });
        toast('已放进看板');
        await window.refreshBoard();
        renderView();
        return res;
      } catch (err) { toast(err.message); b.disabled = false; }
    }));
    $$('[data-rec-generate]', body).forEach((b) => (b.onclick = async () => {
      try { const r = await api('/api/briefing/generate', { method: 'POST', body: { day: d.recommend.day } }); toast(r.message || '开始推荐'); await window.refreshBoard(); renderView(); } catch (err) { toast(err.message); }
    }));
    $('#newForm').onsubmit = async (e) => {
      e.preventDefault();
      const title = $('#newIn').value.trim();
      if (!title) return;
      try {
        await api('/api/topics', { method: 'POST', body: { title, formats: 'both', account_id: S.mine && S.mine.account ? S.mine.account.id : null } });
        $('#newIn').value = '';
        $('#newIn').blur();
        toast('已加到提纲');
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
