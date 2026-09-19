'use strict';
/* Anna · 悬浮窗里的内容主编：一场贯穿所有页面的对话；Park 在哪一页，她就看着哪一页的资料；只动嘴，动作变成按钮 */

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

/* ---- window: drag by the title bar, resize from any edge, remembered per browser ---- */
const AN_MIN = { w: 320, h: 360 };
function annaGeom() { try { return JSON.parse(localStorage.getItem('cs-anna-geom') || 'null'); } catch (_) { return null; } }
function saveAnnaGeom(g) { try { localStorage.setItem('cs-anna-geom', JSON.stringify(g)); } catch (_) { /* ignore */ } }
function clampGeom(g) {
  const vw = window.innerWidth, vh = window.innerHeight;
  const w = Math.min(Math.max(g.w, AN_MIN.w), vw - 16);
  const h = Math.min(Math.max(g.h, AN_MIN.h), vh - 16);
  return { w, h, x: Math.min(Math.max(g.x, 8), vw - w - 8), y: Math.min(Math.max(g.y, 8), vh - h - 8) };
}
function applyAnnaGeom(box) {
  const g = annaGeom();
  if (!g || window.innerWidth <= 900) { box.removeAttribute('style'); return; }
  const c = clampGeom(g);
  Object.assign(box.style, { left: `${c.x}px`, top: `${c.y}px`, width: `${c.w}px`, height: `${c.h}px`, right: 'auto', bottom: 'auto' });
}
function startAnnaGesture(e, box, mode) {
  if (window.innerWidth <= 900 || e.button !== 0) return;
  e.preventDefault();
  const r = box.getBoundingClientRect();
  const start = { px: e.clientX, py: e.clientY, x: r.left, y: r.top, w: r.width, h: r.height };
  box.classList.add('an-dragging');
  const move = (ev) => {
    const dx = ev.clientX - start.px, dy = ev.clientY - start.py;
    let { x, y, w, h } = start;
    const edge = mode === 'move' ? '' : mode;  // 'move' must not be read as the e(ast) edge
    if (mode === 'move') { x += dx; y += dy; }
    if (edge.includes('w')) { w = start.w - dx; x = start.x + (start.w - Math.max(w, AN_MIN.w)); w = Math.max(w, AN_MIN.w); }
    if (edge.includes('e')) w = start.w + dx;
    if (edge.includes('n')) { h = start.h - dy; y = start.y + (start.h - Math.max(h, AN_MIN.h)); h = Math.max(h, AN_MIN.h); }
    if (edge.includes('s')) h = start.h + dy;
    const c = clampGeom({ x, y, w, h });
    Object.assign(box.style, { left: `${c.x}px`, top: `${c.y}px`, width: `${c.w}px`, height: `${c.h}px`, right: 'auto', bottom: 'auto' });
  };
  const up = () => {
    window.removeEventListener('pointermove', move);
    window.removeEventListener('pointerup', up);
    box.classList.remove('an-dragging');
    const r2 = box.getBoundingClientRect();
    saveAnnaGeom({ x: Math.round(r2.left), y: Math.round(r2.top), w: Math.round(r2.width), h: Math.round(r2.height) });
  };
  window.addEventListener('pointermove', move);
  window.addEventListener('pointerup', up);
}
function bindAnnaWindow(box) {
  applyAnnaGeom(box);
  const head = $('.an-h', box);
  if (head) head.onpointerdown = (e) => { if (!e.target.closest('button')) startAnnaGesture(e, box, 'move'); };
  $$('[data-an-edge]', box).forEach((h) => (h.onpointerdown = (e) => startAnnaGesture(e, box, h.dataset.anEdge)));
  const reset = $('.an-h', box);
  if (reset) reset.ondblclick = (e) => { if (e.target.closest('button')) return; try { localStorage.removeItem('cs-anna-geom'); } catch (_) { /* ignore */ } box.removeAttribute('style'); };
}
window.addEventListener('resize', () => { const box = $('#anna'); if (box && !box.hidden) applyAnnaGeom(box); });

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
  const where = m.page ? ` · 在${esc(m.page)}` : '';
  const at = m.scope || scope;  // an action applies to the page it was suggested on
  if (m.role === 'park') return `<div class="an-msg from-park"><div class="an-bubble">${esc(m.text)}</div><small>${annaTime(m.at)}${where}</small></div>`;
  const acts = (m.actions || []).map((a) => annaActionButton(a, at)).join('');
  return `<div class="an-msg from-anna"><div class="an-bubble md">${renderMarkdown(m.text || '')}</div>${acts ? `<div class="an-acts" data-an-scope="${esc(at)}">${acts}</div>` : ''}<small>Anna · ${annaTime(m.at)}${where}</small></div>`;
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
    if ($('#anIn')) AN.draft.main = $('#anIn').value;
    try { await loadAnna(scope); } catch (err) { box.innerHTML = `<div class="an-h"><b>Anna</b></div><div class="an-empty bad">${esc(err.message)}</div>`; return; }
  }
  const d = AN.data;
  const kind = annaKind(scope);
  const where = d.title ? `正在看《${d.title}》` : `正在看「${d.label}」`;
  const list = d.messages.length
    ? d.messages.map((m) => annaMessage(m, scope)).join('')
    : `<div class="an-empty"><p>我是 Anna，内容主编。我能看到你${d.title ? '这条视频' : '这一页'}的全部资料，说什么都行。</p><div class="an-chips">${(ANNA_PROMPTS[kind] || []).map((p) => `<button type="button" class="an-chip" data-an-prompt="${esc(p)}">${esc(p)}</button>`).join('')}</div></div>`;
  const wasScrolled = $('#anList') && $('#anList').scrollTop + $('#anList').clientHeight >= $('#anList').scrollHeight - 40;
  // One conversation, one draft: switching pages keeps what you were typing.
  const draft = $('#anIn') ? $('#anIn').value : (AN.draft.main || '');
  box.innerHTML = `<div class="an-h"><div><b>Anna</b><span class="an-role">内容主编</span></div><small class="an-where">${esc(where)}</small>
      <div class="an-tools"><button class="linklike" type="button" id="anClear" title="清掉和 Anna 的全部对话，从头聊">清空</button><button class="btn small" type="button" id="anClose" title="收起窗口，需要时再叫她">去忙吧</button></div></div>
    <div class="an-list" id="anList">${list}${d.busy ? '<div class="an-msg from-anna"><div class="an-bubble an-wait"><span class="spin"></span>Anna 在看资料…</div></div>' : ''}${d.error && !d.busy ? `<div class="an-msg from-anna"><div class="an-bubble bad">${esc(d.error)}</div></div>` : ''}</div>
    <form class="an-form" id="anForm"><textarea id="anIn" rows="2" placeholder="问 Anna…（回车发送，Shift+回车换行）">${esc(draft)}</textarea><button class="btn primary" type="submit" ${d.busy ? 'disabled' : ''}>发送</button></form>
    <i class="an-edge w" data-an-edge="w"></i><i class="an-edge e" data-an-edge="e"></i><i class="an-edge n" data-an-edge="n"></i><i class="an-edge s" data-an-edge="s"></i>
    <i class="an-edge nw" data-an-edge="nw"></i><i class="an-edge sw" data-an-edge="sw"></i><i class="an-edge ne" data-an-edge="ne"></i><i class="an-edge se" data-an-edge="se"></i>`;
  bindAnnaWindow(box);
  const listEl = $('#anList');
  if (wasScrolled || !AN.rendered) listEl.scrollTop = listEl.scrollHeight;
  AN.rendered = true;
  $('#anClose').onclick = () => { AN.open = false; try { localStorage.setItem('cs-anna', 'closed'); } catch (_) { /* ignore */ } renderAnna(); };
  $('#anClear').onclick = async () => {
    if (!d.messages.length || !confirm('清掉和 Anna 的全部对话？')) return;
    try { await api(`/api/anna?scope=${encodeURIComponent(scope)}`, { method: 'DELETE' }); AN.data = null; renderAnna(); } catch (err) { toast(err.message); }
  };
  $$('[data-an-prompt]', box).forEach((b) => (b.onclick = () => { $('#anIn').value = b.dataset.anPrompt; $('#anIn').focus(); }));
  $$('[data-an-kind]', box).forEach((b) => (b.onclick = () => { b.disabled = true; runAnnaAction(b.dataset.anKind, b.dataset.anArg, b.closest('[data-an-scope]').dataset.anScope); }));
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
      AN.draft.main = '';
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
