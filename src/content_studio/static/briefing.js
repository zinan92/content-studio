'use strict';
/* 每日统筹：今天读什么、今天拍什么 */
window.VIEWS = window.VIEWS || {};
window.TODAY_CARDS = window.TODAY_CARDS || [];

const BR = { record: null, at: 0 };
const todayKey = () => new Date().toLocaleDateString('sv-SE');

async function loadBriefing(force) {
  const running = BR.record && BR.record.state === 'running';
  if (!force && BR.record && BR.record.day === todayKey() && Date.now() - BR.at < (running ? 4000 : 60000)) return BR.record;
  BR.record = await api(`/api/briefing?day=${todayKey()}`);
  BR.at = Date.now();
  if (BR.record.state === 'running') setTimeout(async () => { await loadBriefing(true); renderView(); }, 5000);
  return BR.record;
}

async function generateBriefing() {
  try {
    const res = await api('/api/briefing/generate', { method: 'POST', body: { day: todayKey() } });
    toast(res.message);
    await loadBriefing(true);
    renderView();
  } catch (err) { toast(err.message); }
}

function sourceLink(src, label) {
  const text = esc(label || src.title || src.path || src.url);
  if (src.url) return `<a class="src-link" href="${esc(src.url)}" target="_blank" rel="noopener">${text} ↗</a>`;
  if (src.path && src.path.endsWith('.html')) return `<a class="src-link" href="/api/vault/raw?path=${encodeURIComponent(src.path)}" target="_blank" rel="noopener">${text} ↗</a>`;
  return `<button type="button" class="linklike src-link" data-note="${esc(src.path)}">${text}</button>`;
}

function videoIdea(v, index, day, full) {
  return `<div class="idea ${v.primary ? 'primary' : ''}">
    <div class="idea-h">${v.primary ? '<span class="pill hot">首选</span>' : '<span class="pill mid">备选</span>'}<b>${esc(v.title)}</b><span class="muted">拍摄负担 ${esc(v.effort)}</span></div>
    <p class="idea-hook">「${esc(v.hook)}」</p>
    <p class="idea-claim">主张：${esc(v.claim)}</p>
    ${full || v.primary ? `<ol class="idea-outline">${v.outline.map((line) => `<li>${esc(line)}</li>`).join('')}</ol>` : ''}
    <div class="idea-meta">为什么是今天：${esc(v.why_today)}${v.caution ? `<br><span class="bad">注意：${esc(v.caution)}</span>` : ''}</div>
    <div class="idea-foot"><span class="idea-src">素材：${v.sources.map((s) => sourceLink(s)).join('、')}</span><span class="acts"><button class="btn small" type="button" data-idea="${index}" data-day="${esc(day)}">做成选题</button><button class="btn small primary" type="button" data-idea="${index}" data-day="${esc(day)}" data-outline-after="1">做成选题并写提纲</button></span></div>
  </div>`;
}

function bindBriefing(root) {
  $$('[data-note]', root).forEach((b) => (b.onclick = () => openNote(b.dataset.note)));
  $$('[data-idea]', root).forEach((b) => (b.onclick = async () => {
    b.disabled = true;
    try {
      const res = await api('/api/briefing/topic', { method: 'POST', body: { day: b.dataset.day, index: Number(b.dataset.idea) } });
      if (b.dataset.outlineAfter) {
        await api(`/api/topics/${res.topic.id}/outline`, { method: 'POST' });
        toast('已做成选题，正在写拍摄提纲，在「视频」里看');
      } else {
        toast('已做成视频选题，在「选题」里继续');
      }
      if (window.refreshTopics) await window.refreshTopics();
    } catch (err) { toast(err.message); b.disabled = false; }
  }));
  $$('[data-brief-generate]', root).forEach((b) => (b.onclick = generateBriefing));
}

function briefingBody(r, full) {
  if (r.state === 'missing') {
    return `<div class="empty"><b>今天还没有统筹</b><span>读今天的日报、近 2 天剪藏和近 7 天原始输出，告诉你先读什么、今天可以拍什么。</span><button class="btn primary" type="button" data-brief-generate>生成今日统筹</button></div>`;
  }
  if (r.state === 'running') return '<div class="empty"><span class="spin"></span><b>正在统筹今天的内容</b><span>一般 1–3 分钟，好了自动出现。</span></div>';
  if (r.state === 'failed' && !r.data) return `<div class="empty"><b class="bad">${esc(r.error || '生成失败')}</b><button class="btn" type="button" data-brief-generate>重新生成</button></div>`;
  const d = r.data;
  const videos = d.videos.map((v, i) => ({ v, i })).sort((a, b) => Number(b.v.primary) - Number(a.v.primary));
  const shownVideos = full ? videos : videos.slice(0, 1);
  return `${r.state === 'failed' ? `<div class="banner warn" style="margin:12px 18px 0"><div>重新生成失败：${esc(r.error)}（下面是上一版）</div></div>` : ''}
    <div class="brief-grid ${full ? 'full' : ''}">
      <div class="brief-reads"><h3>今天先读</h3><ol>${d.reads.map((x) => `<li>${sourceLink(x.source, x.title)}<span>${esc(x.why)}</span></li>`).join('')}</ol>
        ${full ? `<h3>已知</h3><ul class="brief-facts">${d.known.map((k) => `<li>${esc(k)}</li>`).join('')}</ul><h3>还不知道</h3><ul class="brief-facts">${d.unknown.map((k) => `<li>${esc(k)}</li>`).join('')}</ul>` : ''}
      </div>
      <div class="brief-videos"><h3>今天可以拍</h3>${shownVideos.map(({ v, i }) => videoIdea(v, i, d.day, full)).join('')}
        ${!full && videos.length > 1 ? `<button class="linklike more" type="button" data-go="brief">还有 ${videos.length - 1} 条备选 →</button>` : ''}
        ${d.prep ? `<p class="brief-prep">今日最小准备：${esc(d.prep)}</p>` : ''}
      </div>
    </div>`;
}

window.VIEWS.brief = {
  async render() {
    const body = $('#briefBody');
    let r;
    try { r = await loadBriefing(false); } catch (err) { body.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`; return; }
    const sig = JSON.stringify([r.state, r.updated_at]);
    if (body.dataset.sig === sig) return;
    body.dataset.sig = sig;
    body.innerHTML = `<div class="panel"><div class="panel-h"><h2>${esc(r.day)} 统筹</h2><small>${r.data ? `基于 ${r.data.input_counts.dailies} 份日报、${r.data.input_counts.notes} 条笔记 · 生成于 ${hmTime(r.data.generated_at)}` : ''} ${r.data && r.state !== 'running' ? '<button class="btn small" type="button" data-brief-generate>重新生成</button>' : ''}</small></div>${briefingBody(r, true)}</div>`;
    bindBriefing(body);
    $$('[data-go]', body).forEach((b) => (b.onclick = () => go(b.dataset.go)));
  },
};
const renderBriefView = window.VIEWS.brief.render;
window.VIEWS.brief.render = async function () {
  await renderBriefView();
  if (window.renderBriefHot) await window.renderBriefHot.render();
};

function hmTime(iso) {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

window.TODAY_CARDS.push({
  id: 'briefing',
  order: 2,
  wide: true,
  title: '今日统筹',
  async render(el) {
    let r;
    try { r = await loadBriefing(false); } catch (err) { el.innerHTML = `<div class="panel-h"><h2>今日统筹</h2></div><div class="empty"><span>${esc(err.message)}</span></div>`; return; }
    // Opening the page is Park's intent to plan the day: start today's briefing once if the dailies are out.
    if (r.state === 'missing' && S.state.vault.ok && !BR.autoStarted) {
      let already = false;
      try { already = localStorage.getItem('cs-brief-auto') === r.day; } catch (_) { /* ignore */ }
      BR.autoStarted = true;
      const dailies = already ? null : await api(`/api/today/dailies?day=${r.day}`).catch(() => null);
      if (dailies && dailies.items.some((i) => i.path)) {
        try { localStorage.setItem('cs-brief-auto', r.day); } catch (_) { /* ignore */ }
        await generateBriefing();
        return;
      }
    }
    const sig = JSON.stringify([r.state, r.updated_at]);
    if (el.dataset.sig === sig) return;
    el.dataset.sig = sig;
    el.innerHTML = `<div class="panel-h"><h2>今日统筹</h2><small>${r.data ? `生成于 ${hmTime(r.data.generated_at)} · <button class="linklike" type="button" data-go="brief">看完整统筹</button>` : ''}</small></div>${briefingBody(r, false)}`;
    bindBriefing(el);
    $$('[data-go]', el).forEach((b) => (b.onclick = () => go(b.dataset.go)));
  },
});
