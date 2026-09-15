'use strict';
/* 加工中 · 一条视频：拍摄提纲 → 剪辑进度 → 发布 → 研习室文章（可选）（各页签由模块注册） */
window.VIEWS = window.VIEWS || {};
window.VIDEO_TABS = window.VIDEO_TABS || [];

const VD = { topicId: null, tab: 'outline', outline: null, dirty: false, mode: 'preview' };

async function startOutline(topicId) {
  try {
    const res = await api(`/api/topics/${topicId}/outline`, { method: 'POST' });
    toast(res.message);
    if (window.refreshTopics) await window.refreshTopics();
  } catch (err) { toast(err.message); }
}

function bindOutlineButtons(root) {
  $$('[data-outline]', root).forEach((b) => (b.onclick = async () => {
    if (b.textContent.includes('重写') && !confirm('重写会覆盖现在的提纲，继续吗？')) return;
    b.disabled = true;
    await startOutline(Number(b.dataset.outline));
  }));
}

const QA_POINTS = [['pain', '痛点具象度'], ['contrast', '认知反差度'], ['delivery', '交付可行性']];
const QA_VERDICT = { go: ['可以拍', 'ok'], patch: ['先补再拍', 'warn'], thin: ['素材太薄', 'bad'] };

async function renderQA(topic, box) {
  if (!box) return;
  let d;
  try { d = await api(`/api/topics/${topic.id}/qa`); } catch (err) { box.innerHTML = ''; return; }
  const r = d.result;
  const again = `<button class="btn small ghost" type="button" data-qa-run>${r ? '重评' : '按三点评分'}</button>`;
  if (d.state === 'running') {
    box.innerHTML = '<section class="qa qa-wait"><span class="spin"></span>正在按三点评分（痛点、反差、交付），半分钟左右</section>';
    setTimeout(() => { if (S.view === 'work' && VD.tab === 'outline' && VD.topicId === topic.id) renderQA(topic, $('#qaBox')); }, 4000);
    return;
  }
  if (!r) {
    box.innerHTML = `<section class="qa qa-wait">${d.state === 'failed' ? `<span class="bad">${esc(d.error || '评分失败')}</span>` : '<span>还没按三点评过：痛点具象度、认知反差度、交付可行性。</span>'}${again}</section>`;
  } else {
    const [label, tone] = QA_VERDICT[r.verdict] || ['', ''];
    box.innerHTML = `<section class="qa">
      <div class="qa-h"><b class="qa-verdict ${tone}">${label}</b><span class="num">${r.total}/15</span><small>评于 ${day(r.generated_at)}${r.guide === 'rubric' ? ' · 没找到你的 skill 文件，用的是简版标准' : ''}</small><span class="spacer"></span>${again}</div>
      <div class="qa-grid">${QA_POINTS.map(([k, name]) => {
        const p = r[k];
        return `<div class="qa-pt ${p.score <= 2 ? 'low' : ''}">
          <div class="qa-top"><span>${name}</span><b class="num">${p.score}</b></div>
          <div class="qa-bar" aria-hidden="true">${[1, 2, 3, 4, 5].map((i) => `<i class="${i <= p.score ? 'on' : ''}"></i>`).join('')}</div>
          <p>${esc(p.reason)}</p>${p.evidence ? `<blockquote>${esc(p.evidence)}</blockquote>` : ''}
        </div>`;
      }).join('')}</div>
      <p class="qa-fix"><b>最该改的一处</b>${esc(r.fix)}</p>
      ${r.caution ? `<p class="qa-fix"><b>不要讲过头</b>${esc(r.caution)}</p>` : ''}
    </section>`;
  }
  $$('[data-qa-run]', box).forEach((b) => (b.onclick = async () => {
    b.disabled = true;
    try { const res = await api(`/api/topics/${topic.id}/qa`, { method: 'POST' }); toast(res.message); setTimeout(() => renderQA(topic, box), 400); } catch (err) { toast(err.message); b.disabled = false; }
  }));
}

window.VIDEO_TABS.push({
  key: 'outline',
  label: '拍摄提纲',
  badge: (t) => (t.outline_state === 'running' ? '生成中' : t.outline_path ? '已写' : ''),
  async render(topic, el) {
    if (topic.outline_state === 'running') {
      el.innerHTML = `<div class="empty"><span class="spin"></span><b>正在写《${esc(topic.title)}》的拍摄提纲</b><span>一般 1–2 分钟。</span></div>`;
      return;
    }
    if (!topic.outline_path) {
      el.innerHTML = `<div class="empty"><b>还没有拍摄提纲</b>${topic.outline_state === 'failed' ? `<span class="bad">${esc(topic.outline_error || '')}</span>` : ''}
        <span>一句主线 + 4–8 条要点，第一句就讲主线（近期平均只被看 14–26 秒）。不写逐字稿。</span>
        ${topic.memo ? `<pre class="memo">${esc(topic.memo)}</pre>` : ''}
        <button class="btn primary" type="button" data-outline="${topic.id}">写拍摄提纲</button></div>`;
      bindOutlineButtons(el);
      return;
    }
    if (!VD.outline || VD.outline.topic_id !== topic.id) {
      try { VD.outline = { ...(await api(`/api/topics/${topic.id}/outline`)), topic_id: topic.id }; } catch (err) { el.innerHTML = `<div class="empty"><b>${esc(err.message)}</b></div>`; return; }
    }
    const o = VD.outline;
    el.innerHTML = `<div id="qaBox"></div><div class="art-head"><div><small>${o.generated_at ? `生成于 ${day(o.generated_at)} · ` : ''}最后修改 ${day(o.updated_at)}</small></div>
        <div class="seg-toggle" role="group"><button type="button" class="${VD.mode === 'preview' ? 'on' : ''}" data-vmode="preview">预览</button><button type="button" class="${VD.mode === 'edit' ? 'on' : ''}" data-vmode="edit">编辑</button></div></div>
      ${VD.mode === 'edit' ? `<textarea id="outlineText" class="big-text" spellcheck="false">${esc(o.markdown)}</textarea>` : `<article class="md art-md">${renderMarkdown(o.markdown)}</article>`}
      <div class="art-foot">${VD.mode === 'edit' ? '<button class="btn primary" type="button" id="outlineSave">保存</button>' : ''}
        <button class="btn" type="button" id="outlineCopy">复制提纲</button>
        <button class="btn" type="button" data-outline="${topic.id}" title="重新生成，会覆盖当前提纲">重写</button></div>`;
    bindOutlineButtons(el);
    $$('[data-vmode]', el).forEach((b) => (b.onclick = () => { VD.mode = b.dataset.vmode; VD.dirty = false; $('#videoBody').dataset.sig = ''; renderView(); }));
    const text = $('#outlineText');
    if (text) text.oninput = () => { VD.dirty = true; };
    const save = $('#outlineSave');
    if (save) save.onclick = async () => {
      try {
        VD.outline = { ...(await api(`/api/topics/${topic.id}/outline`, { method: 'PUT', body: { markdown: $('#outlineText').value } })), topic_id: topic.id };
        VD.dirty = false; VD.mode = 'preview'; $('#videoBody').dataset.sig = '';
        toast('已保存'); renderView();
      } catch (err) { toast(err.message); }
    };
    renderQA(topic, $('#qaBox', el));
    $('#outlineCopy').onclick = () => navigator.clipboard.writeText(text ? text.value : o.markdown).then(() => toast('已复制提纲'), () => toast('复制失败'));
  },
});

const TAB_ORDER = ['outline', 'edit', 'publish', 'article'];
const WORK_STEPS = [['outline', '提纲'], ['record', '录制'], ['edit', '剪辑'], ['ready', '待发'], ['shipped', '已发出']];
const WK = { topics: null, at: 0 };

window.invalidateWork = () => { WK.topics = null; const body = $('#videoBody'); if (body) body.dataset.sig = ''; };

window.VIEWS.work = {
  async render() {
    const root = $('#workBody');
    if (VD.dirty || (typeof CP !== 'undefined' && CP.dirty && VD.tab === 'publish') || (typeof AR !== 'undefined' && AR.dirty && VD.tab === 'article')) return;
    if (VD.topicId !== S.workId) { VD.topicId = S.workId; VD.outline = null; VD.mode = 'preview'; VD.tab = 'outline'; }
    try {
      if (!WK.topics || Date.now() - WK.at > 5000) {
        WK.topics = await api('/api/topics?archived=true');
        WK.at = Date.now();
      }
      if (typeof BD !== 'undefined' && !BD.data) await loadBoard(false);
    } catch (err) { root.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`; return; }
    const topic = WK.topics.find((t) => t.id === VD.topicId);
    if (!topic) { root.innerHTML = '<div class="panel empty"><b>找不到这条视频</b><button class="btn" type="button" onclick="go(\'board\')">回到看板</button></div>'; return; }
    const card = BD.data && BD.data.cards.find((c) => c.id === topic.id);
    const stage = topic.published_video_id ? 'shipped' : card ? card.stage : 'outline';
    const tabs = window.VIDEO_TABS.slice().sort((a, b) => TAB_ORDER.indexOf(a.key) - TAB_ORDER.indexOf(b.key));
    let body = $('#videoBody');
    const sig = JSON.stringify([VD.topicId, VD.tab, VD.mode, VD.outline && VD.outline.updated_at, stage, card && card.next.text, topic.outline_state, Boolean(topic.outline_path), topic.video_project, topic.status, topic.published_video_id, topic.write_state, Boolean(topic.article_path), topic.archived_at]);
    if (body && body.dataset.sig === sig && !VD.forceRender) return;
    VD.forceRender = false;
    const reached = WORK_STEPS.findIndex(([k]) => k === stage);
    root.innerHTML = `<header class="work-h">
        <button class="linklike back" type="button" onclick="go('board')">← 加工中</button>
        <div class="work-title"><h1>${esc(topic.title)}</h1>
          <div class="work-acts">${topic.archived_at ? '<span class="chip-state">已归档</span>' : '<button class="btn small ghost" type="button" id="workArchive">不做了</button>'}</div></div>
        <ol class="steps-line">${WORK_STEPS.map(([k, l], i) => `<li class="${i < reached ? 'done' : i === reached ? 'now' : ''}"><i></i>${l}</li>`).join('')}</ol>
        ${card ? `<p class="work-next ${card.next.mine ? 'mine' : ''}"><i></i>${esc(card.next.text)}</p>` : ''}
      </header>
      <div class="panel work-main" id="videoBody">
        <div class="video-tabs" role="tablist">${tabs.map((tab) => `<button type="button" role="tab" class="${VD.tab === tab.key ? 'on' : ''}" data-vtab="${tab.key}">${tab.label}${tab.badge(topic) ? `<small>${esc(tab.badge(topic))}</small>` : ''}</button>`).join('')}</div>
        <div id="videoTab"></div>
      </div>`;
    body = $('#videoBody');
    body.dataset.sig = sig;
    $$('[data-vtab]', root).forEach((b) => (b.onclick = () => { if (typeof CP !== 'undefined') CP.dirty = false; VD.tab = b.dataset.vtab; body.dataset.sig = ''; renderView(); }));
    const archive = $('#workArchive');
    if (archive) archive.onclick = async () => {
      if (!confirm(`不做《${topic.title}》了？会从看板拿掉，笔记和文件都不删。`)) return;
      await window.patchTopic(topic.id, { archived: true }, '已从看板拿掉');
      go('board');
    };
    const tab = tabs.find((x) => x.key === VD.tab) || tabs[0];
    await tab.render(topic, $('#videoTab'));
  },
};
