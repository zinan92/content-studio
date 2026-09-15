'use strict';
/* 选题 + 今日主线 */
window.VIEWS = window.VIEWS || {};
window.TODAY_CARDS = window.TODAY_CARDS || [];

const TP = { topics: null, plan: null, planAt: 0, loadedAt: 0 };
const STATUS_COLS = [['todo', '待写'], ['drafting', '草稿中'], ['ready', '待发'], ['published', '已发出']];
const FORMAT_NAME = { article: '文章', video: '视频', both: '文章 + 视频' };
window.TOPIC_ACTIONS = window.TOPIC_ACTIONS || []; // later modules add buttons: (topic) => html

async function loadTopics(force) {
  const writingNow = TP.topics && TP.topics.some((t) => t.write_state === 'running' || t.outline_state === 'running');
  if (!force && TP.topics && Date.now() - TP.loadedAt < (writingNow ? 4000 : 15000)) return;
  TP.topics = await api('/api/topics');
  TP.loadedAt = Date.now();
}

async function loadPlan(force) {
  if (!force && TP.plan && Date.now() - TP.planAt < 15000) return;
  TP.plan = await api(`/api/today/plan?day=${new Date().toLocaleDateString('sv-SE')}`);
  TP.planAt = Date.now();
}

async function patchTopic(id, body, message) {
  try {
    await api(`/api/topics/${id}`, { method: 'PATCH', body });
    if (message) toast(message);
    await Promise.all([loadTopics(true), loadPlan(true)]);
    renderView();
  } catch (err) { toast(err.message); }
}
window.patchTopic = patchTopic;
window.refreshTopics = async () => { await Promise.all([loadTopics(true), loadPlan(true)]); renderView(); };

function topicCard(t) {
  const notes = t.note_paths.map((p) => `<button type="button" class="linklike note-link clamp" data-note="${esc(p)}">📄 ${esc(p.split('/').pop().replace(/\.md$/, ''))}</button>`).join('');
  const extra = window.TOPIC_ACTIONS.map((fn) => fn(t)).join('');
  return `<div class="topic" data-topic-id="${t.id}">
    <b class="clamp">${esc(t.title)}</b>
    <div class="topic-meta"><span class="src-tag">${FORMAT_NAME[t.formats] || t.formats}</span>${t.published_url ? `<a href="${esc(t.published_url)}" target="_blank" rel="noopener">发出链接 ↗</a>` : ''}</div>
    ${notes ? `<div class="topic-notes">${notes}</div>` : ''}
    <div class="acts">
      ${extra}
      <select data-status="${t.id}" aria-label="状态">${STATUS_COLS.map(([k, l]) => `<option value="${k}" ${t.status === k ? 'selected' : ''}>${l}</option>`).join('')}</select>
      <select data-format="${t.id}" aria-label="形式">${Object.entries(FORMAT_NAME).map(([k, l]) => `<option value="${k}" ${t.formats === k ? 'selected' : ''}>${l}</option>`).join('')}</select>
      <button class="btn small ghost" type="button" data-archive-topic="${t.id}">归档</button>
    </div>
  </div>`;
}

function bindTopicCards(root) {
  $$('[data-status]', root).forEach((sel) => (sel.onchange = async () => {
    let body = { status: sel.value };
    if (sel.value === 'published') {
      const url = prompt('发出链接（研习室或抖音，可留空）', '');
      if (url === null) { sel.value = TP.topics.find((t) => t.id === Number(sel.dataset.status)).status; return; }
      if (url.trim()) body.published_url = url.trim();
    }
    patchTopic(Number(sel.dataset.status), body, '已更新状态');
  }));
  $$('[data-format]', root).forEach((sel) => (sel.onchange = () => patchTopic(Number(sel.dataset.format), { formats: sel.value }, '已更新形式')));
  $$('[data-archive-topic]', root).forEach((b) => (b.onclick = () => patchTopic(Number(b.dataset.archiveTopic), { archived: true }, '已归档选题')));
  $$('[data-note]', root).forEach((b) => (b.onclick = () => openNote(b.dataset.note)));
}

window.VIEWS.topics = {
  async render() {
    const body = $('#topicsBody');
    try { await loadTopics(false); } catch (err) { body.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`; return; }
    const sig = JSON.stringify([TP.loadedAt]);
    if (body.dataset.sig === sig) return;
    body.dataset.sig = sig;
    const topics = TP.topics;
    body.innerHTML = `<div class="panel">
        <form class="linkbox" id="topicForm">
          <input id="topicIn" placeholder="新选题，例如：为什么用了 AI 反而更累" aria-label="选题标题" autocomplete="off">
          <select id="topicFmt" aria-label="形式">${Object.entries(FORMAT_NAME).map(([k, l]) => `<option value="${k}" ${k === 'both' ? 'selected' : ''}>${l}</option>`).join('')}</select>
          <button class="btn primary" type="submit">加选题</button>
        </form>
        <div class="hint">也可以在「素材库」里点「做成选题」，会自动带上原笔记。</div>
      </div>
      <div class="kanban">${STATUS_COLS.map(([k, l]) => {
        const col = topics.filter((t) => t.status === k);
        return `<div class="kanban-col"><div class="kanban-h"><b>${l}</b><span class="num">${col.length}</span></div>${col.map(topicCard).join('') || '<div class="kanban-empty">—</div>'}</div>`;
      }).join('')}</div>`;
    $('#topicForm').onsubmit = async (e) => {
      e.preventDefault();
      try {
        await api('/api/topics', { method: 'POST', body: { title: $('#topicIn').value, formats: $('#topicFmt').value, account_id: S.mine.account ? S.mine.account.id : null } });
        toast('已加选题');
        await Promise.all([loadTopics(true), loadPlan(true)]);
        renderView();
      } catch (err) { toast(err.message); }
    };
    bindTopicCards(body);
    $('#navTopics').textContent = topics.filter((t) => t.status !== 'published').length || '';
  },
};

window.TODAY_CARDS.push({
  id: 'plan',
  order: 0,
  wide: true,
  title: '今天：读 · 拍 · 发',
  async render(el) {
    try { await loadPlan(false); } catch (err) { el.innerHTML = `<div class="panel-h"><h2>今天：读 · 拍 · 发</h2></div><div class="empty"><span>${esc(err.message)}</span></div>`; return; }
    const p = TP.plan;
    const firstOpen = p.groups.findIndex((g) => !g.done);
    const k = p.streak;
    const streak = k.today_done
      ? `<span class="streak ok">连续拍摄 <b>${k.days}</b> 天</span>`
      : k.days > 0
        ? `<span class="streak warn">已连续 <b>${k.days}</b> 天 · 今天还没拍</span>`
        : `<span class="streak broken">连拍断了${k.days_since_last ? ` · 已 <b>${k.days_since_last}</b> 天没拍` : ''}</span>`;
    const subList = (g) => g.sub.length ? `<ul class="plan-sub">${g.sub.map((s) => `<li class="${s.done ? 'done' : ''}">${s.done ? '✓' : '·'} ${esc(s.title)}：${esc(s.detail)}${!s.done && s.go && s.go !== 'today' ? ` <button class="linklike" type="button" data-go="${s.go}">去</button>` : ''}</li>`).join('')}</ul>` : '';
    el.innerHTML = `<div class="panel-h"><h2>今天：读 · 拍 · 发</h2><small>${streak}</small></div>
      <ol class="plan plan-3">${p.groups.map((g, i) => `<li class="${g.done ? 'done' : i === firstOpen ? 'now' : ''} ${g.attention ? 'attention' : ''}">
        <span class="plan-dot">${g.done ? '✓' : esc(g.title)}</span>
        <div class="plan-body"><b>${esc(g.title)}</b><span>${esc(g.detail)}</span>${subList(g)}</div>
        <div class="acts">${g.manual ? `<label class="manual"><input type="checkbox" data-manual="${g.manual_key}" ${p.steps.find((s) => s.key === g.manual_key && s.done) ? 'checked' : ''}> 拍完了</label>` : ''}${g.go && g.go !== 'today' ? `<button class="btn small ${i === firstOpen || g.attention ? 'primary' : ''}" type="button" data-go="${g.go}">${g.attention ? '去处理' : '去做'}</button>` : ''}</div>
      </li>`).join('')}</ol>`;
    $$('[data-go]', el).forEach((b) => (b.onclick = () => go(b.dataset.go)));
    $$('[data-manual]', el).forEach((box) => (box.onchange = async () => {
      try {
        await api('/api/today/checks', { method: 'PUT', body: { day: p.day, key: 'video_shot', checked: box.checked } });
        await loadPlan(true);
        renderView();
      } catch (err) { toast(err.message); }
    }));
  },
});
