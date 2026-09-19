'use strict';
/* Anna · 常驻右栏的内容主编：Park 在哪一页，她就看着哪一页的资料；只动嘴，动作变成按钮 */

// Open by default on a desk; on a phone the panel covers the page, so it waits for a tap.
const AN = { open: (() => { try { const saved = localStorage.getItem('cs-anna'); return saved ? saved === 'open' : window.innerWidth > 900; } catch (_) { return window.innerWidth > 900; } })(), scope: null, data: null, poll: null, draft: {} };

const ANNA_PROMPTS = {
  input: ['今天有什么值得拿来做的？', '这篇讲的是什么，能不能拍？', '最近进来的东西里哪条最有反差？'],
  board: ['今天先拍哪条？', '看板上哪条卡最久，为什么？', '推荐的这两条，三点各差在哪？'],
  work: ['这个提纲第一句够不够狠？', '交付这一点怎么补？', '按三点看，这条能不能拍？'],
  output: ['这周哪条最好，为什么？', '下一条只改一件事，改什么？', '来的人对不对？'],
  settings: ['你现在读的是哪些文件？'],
};

function annaScope() {
  if (S.view === 'work' && S.workId) return `work:${S.workId}`;
  if (OUTPUT_FAMILY.includes(S.view)) return 'output';
  if (['input', 'board', 'settings'].includes(S.view)) return S.view;
  return 'board';
}

function annaKind(scope) { return scope.split(':')[0]; }

function annaTime(iso) {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

async function loadAnna(scope) {
  AN.data = await api(`/api/anna?scope=${encodeURIComponent(scope)}`);
  AN.scope = scope;
}

function annaActionButton(a, scope) {
  const kind = annaKind(scope);
  if ((a.kind === 'outline' || a.kind === 'qa' || a.kind === 'memo') && kind !== 'work') return '';
  if (a.kind === 'take' && !['input', 'board'].includes(kind)) return '';
  const text = a.kind === 'memo' ? `存进备注：${a.arg}` : a.kind === 'take' ? `拿来做：${a.arg}` : a.label;
  return `<button class="btn small an-act" type="button" data-an-kind="${a.kind}" data-an-arg="${esc(a.arg || '')}">${esc(text)}</button>`;
}

async function runAnnaAction(kind, arg, scope) {
  const id = annaKind(scope) === 'work' ? Number(scope.split(':')[1]) : null;
  try {
    if (kind === 'memo' && id) {
      const topics = await api('/api/topics?archived=true');
      const t = topics.find((x) => x.id === id);
      const memo = `${t && t.memo ? t.memo.trimEnd() + '\n' : ''}Anna：${arg}`;
      await api(`/api/topics/${id}`, { method: 'PATCH', body: { memo } });
      toast('已存进备注');
    } else if (kind === 'outline' && id) {
      const r = await api(`/api/topics/${id}/outline`, { method: 'POST' });
      toast(r.message);
    } else if (kind === 'qa' && id) {
      const r = await api(`/api/topics/${id}/qa`, { method: 'POST' });
      toast(r.message);
    } else if (kind === 'take') {
      await api('/api/topics', { method: 'POST', body: { title: arg, formats: 'both', account_id: S.mine && S.mine.account ? S.mine.account.id : null } });
      toast('已放进看板');
    }
    if (window.refreshTopics) await window.refreshTopics();
  } catch (err) { toast(err.message); }
}

function annaMessage(m, scope) {
  if (m.role === 'park') return `<div class="an-msg from-park"><div class="an-bubble">${esc(m.text)}</div><small>${annaTime(m.at)}</small></div>`;
  const acts = (m.actions || []).map((a) => annaActionButton(a, scope)).join('');
  return `<div class="an-msg from-anna"><div class="an-bubble md">${renderMarkdown(m.text || '')}</div>${acts ? `<div class="an-acts">${acts}</div>` : ''}<small>Anna · ${annaTime(m.at)}</small></div>`;
}

async function renderAnna() {
  const box = $('#anna');
  if (!box) return;
  document.body.classList.toggle('anna-open', AN.open);
  $('#railAnna').classList.toggle('on', AN.open);
  box.hidden = !AN.open;
  if (!AN.open) { clearTimeout(AN.poll); return; }
  const scope = annaScope();
  if (AN.scope !== scope || !AN.data) {
    if (AN.scope && $('#anIn')) AN.draft[AN.scope] = $('#anIn').value;
    try { await loadAnna(scope); } catch (err) { box.innerHTML = `<div class="an-h"><b>Anna</b></div><div class="an-empty bad">${esc(err.message)}</div>`; return; }
  }
  const d = AN.data;
  const kind = annaKind(scope);
  const where = d.title ? `正在看《${d.title}》` : `正在看「${d.label}」`;
  const list = d.messages.length
    ? d.messages.map((m) => annaMessage(m, scope)).join('')
    : `<div class="an-empty"><p>我是 Anna，内容主编。我能看到你${d.title ? '这条视频' : '这一页'}的全部资料，说什么都行。</p><div class="an-chips">${(ANNA_PROMPTS[kind] || []).map((p) => `<button type="button" class="an-chip" data-an-prompt="${esc(p)}">${esc(p)}</button>`).join('')}</div></div>`;
  const wasScrolled = $('#anList') && $('#anList').scrollTop + $('#anList').clientHeight >= $('#anList').scrollHeight - 40;
  const draft = $('#anIn') && AN.scope === scope ? $('#anIn').value : (AN.draft[scope] || '');
  box.innerHTML = `<div class="an-h"><div><b>Anna</b><span class="an-role">内容主编</span></div><small class="an-where">${esc(where)}</small>
      <div class="an-tools"><button class="linklike" type="button" id="anClear" title="清掉这一页的对话，下次从头聊">清空</button><button class="btn small" type="button" id="anClose" title="收起窗口，需要时再叫她">去忙吧</button></div></div>
    <div class="an-list" id="anList">${list}${d.busy ? '<div class="an-msg from-anna"><div class="an-bubble an-wait"><span class="spin"></span>Anna 在看资料…</div></div>' : ''}${d.error && !d.busy ? `<div class="an-msg from-anna"><div class="an-bubble bad">${esc(d.error)}</div></div>` : ''}</div>
    <form class="an-form" id="anForm"><textarea id="anIn" rows="2" placeholder="问 Anna…（回车发送，Shift+回车换行）">${esc(draft)}</textarea><button class="btn primary" type="submit" ${d.busy ? 'disabled' : ''}>发送</button></form>`;
  const listEl = $('#anList');
  if (wasScrolled || !AN.rendered) listEl.scrollTop = listEl.scrollHeight;
  AN.rendered = true;
  $('#anClose').onclick = () => { AN.open = false; try { localStorage.setItem('cs-anna', 'closed'); } catch (_) { /* ignore */ } renderAnna(); };
  $('#anClear').onclick = async () => {
    if (!d.messages.length || !confirm('清掉这一页和 Anna 的对话？')) return;
    try { await api(`/api/anna?scope=${encodeURIComponent(scope)}`, { method: 'DELETE' }); AN.data = null; renderAnna(); } catch (err) { toast(err.message); }
  };
  $$('[data-an-prompt]', box).forEach((b) => (b.onclick = () => { $('#anIn').value = b.dataset.anPrompt; $('#anIn').focus(); }));
  $$('[data-an-kind]', box).forEach((b) => (b.onclick = () => { b.disabled = true; runAnnaAction(b.dataset.anKind, b.dataset.anArg, scope); }));
  const input = $('#anIn');
  input.onkeydown = (e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); $('#anForm').requestSubmit(); } };
  $('#anForm').onsubmit = async (e) => {
    e.preventDefault();
    const message = input.value.trim();
    if (!message || d.busy) return;
    const body = { scope, message };
    if (kind === 'input' && typeof C !== 'undefined' && C.open) body.note_path = C.open;
    try {
      const r = await api('/api/anna', { method: 'POST', body });
      if (!r.started) { toast(r.message); return; }
      input.value = '';
      AN.draft[scope] = '';
      await loadAnna(scope);
      renderAnna();
    } catch (err) { toast(err.message); }
  };
  clearTimeout(AN.poll);
  if (d.busy) AN.poll = setTimeout(async () => { if (AN.open && annaScope() === scope) { try { await loadAnna(scope); } catch (_) { /* retry next tick */ } renderAnna(); } }, 2000);
}
window.renderAnna = renderAnna;

document.addEventListener('DOMContentLoaded', () => {
  const btn = $('#railAnna');
  if (btn) btn.onclick = () => { AN.open = !AN.open; try { localStorage.setItem('cs-anna', AN.open ? 'open' : 'closed'); } catch (_) { /* ignore */ } renderAnna(); if (AN.open) setTimeout(() => { const i = $('#anIn'); if (i) i.focus(); }, 50); };
});
