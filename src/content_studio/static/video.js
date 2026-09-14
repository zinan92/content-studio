'use strict';
/* 加工 · 视频：拍摄提纲 → 剪辑进度 → 发出与数据 → 文案包（各页签由模块注册） */
window.VIEWS = window.VIEWS || {};
window.TOPIC_ACTIONS = window.TOPIC_ACTIONS || [];
window.VIDEO_TABS = window.VIDEO_TABS || [];

const VD = { topicId: null, tab: 'outline', outline: null, dirty: false, mode: 'preview' };

async function startOutline(topicId) {
  try {
    const res = await api(`/api/topics/${topicId}/outline`, { method: 'POST' });
    toast(res.message);
    if (window.refreshTopics) await window.refreshTopics();
    const body = $('#videoBody');
    if (body) body.dataset.sig = '';
    renderView();
  } catch (err) { toast(err.message); }
}

window.TOPIC_ACTIONS.push((t) => {
  if (t.formats === 'article') return '';
  if (t.outline_state === 'running') return '<span class="stage-pill running">提纲生成中…</span>';
  return `<button class="btn small ${t.outline_path ? '' : 'primary'}" type="button" data-open-video="${t.id}">${t.outline_path ? '看视频' : '写提纲'}</button>`;
});

document.addEventListener('click', (e) => {
  const open = e.target.closest('[data-open-video]');
  if (open) { e.preventDefault(); VD.topicId = Number(open.dataset.openVideo); VD.outline = null; VD.tab = 'outline'; go('video'); }
  const gen = e.target.closest('[data-outline]');
  if (gen) { e.preventDefault(); startOutline(Number(gen.dataset.outline)); }
});

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
        <span>按你账号的数据写：前 15 秒直接讲主线（近期平均只被看 14–26 秒），每段都要为主线服务。不写逐字稿。</span>
        ${topic.memo ? `<pre class="memo">${esc(topic.memo)}</pre>` : ''}
        <button class="btn primary" type="button" data-outline="${topic.id}">写拍摄提纲</button></div>`;
      return;
    }
    if (!VD.outline || VD.outline.topic_id !== topic.id) {
      try { VD.outline = { ...(await api(`/api/topics/${topic.id}/outline`)), topic_id: topic.id }; } catch (err) { el.innerHTML = `<div class="empty"><b>${esc(err.message)}</b></div>`; return; }
    }
    const o = VD.outline;
    el.innerHTML = `<div class="art-head"><div><small>${o.generated_at ? `生成于 ${day(o.generated_at)} · ` : ''}最后修改 ${day(o.updated_at)}</small></div>
        <div class="seg-toggle" role="group"><button type="button" class="${VD.mode === 'preview' ? 'on' : ''}" data-vmode="preview">预览</button><button type="button" class="${VD.mode === 'edit' ? 'on' : ''}" data-vmode="edit">编辑</button></div></div>
      ${VD.mode === 'edit' ? `<textarea id="outlineText" class="big-text" spellcheck="false">${esc(o.markdown)}</textarea>` : `<article class="md art-md">${renderMarkdown(o.markdown)}</article>`}
      <div class="art-foot">${VD.mode === 'edit' ? '<button class="btn primary" type="button" id="outlineSave">保存</button>' : ''}
        <button class="btn" type="button" id="outlineCopy">复制提纲</button>
        <button class="btn" type="button" data-outline="${topic.id}" title="重新生成，会覆盖当前提纲">重写</button></div>`;
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
    $('#outlineCopy').onclick = () => navigator.clipboard.writeText(text ? text.value : o.markdown).then(() => toast('已复制提纲'), () => toast('复制失败'));
  },
});

window.VIEWS.video = {
  async render() {
    const body = $('#videoBody');
    if (VD.dirty) return;
    let topics;
    try { topics = await api('/api/topics'); } catch (err) { body.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`; return; }
    const candidates = topics.filter((t) => t.formats !== 'article');
    if (!VD.topicId || !candidates.some((t) => t.id === VD.topicId)) VD.topicId = candidates.length ? candidates[0].id : null;
    const topic = candidates.find((t) => t.id === VD.topicId);
    const tabs = window.VIDEO_TABS;
    const sig = JSON.stringify([VD.topicId, VD.tab, VD.mode, VD.outline && VD.outline.updated_at, candidates.map((t) => [t.id, t.outline_state, Boolean(t.outline_path), t.video_project, t.status, t.published_video_id])]);
    if (body.dataset.sig === sig && !VD.forceRender) return;
    body.dataset.sig = sig;
    VD.forceRender = false;
    const list = candidates.length ? candidates.map((t) => `<button type="button" class="art-item ${t.id === VD.topicId ? 'on' : ''}" data-vtopic="${t.id}"><b class="clamp">${esc(t.title)}</b><small>${tabs.map((tab) => tab.badge(t)).filter(Boolean).join(' · ') || '还没开始'}</small></button>`).join('')
      : '<div class="empty"><span>还没有视频选题。去「每日统筹」挑一条，或在「选题」里加。</span></div>';
    body.innerHTML = `<div class="art-grid"><div class="panel art-list">${list}</div><div class="panel art-main">${topic ? `
      <div class="video-head"><h2>${esc(topic.title)}</h2><div class="video-tabs" role="tablist">${tabs.map((tab) => `<button type="button" role="tab" class="${VD.tab === tab.key ? 'on' : ''}" data-vtab="${tab.key}">${tab.label}${tab.badge(topic) ? `<small>${esc(tab.badge(topic))}</small>` : ''}</button>`).join('')}</div></div>
      <div id="videoTab"></div>` : '<div class="empty"><span>左边选一个视频选题。</span></div>'}</div></div>`;
    $$('[data-vtopic]', body).forEach((b) => (b.onclick = () => { VD.topicId = Number(b.dataset.vtopic); VD.outline = null; VD.mode = 'preview'; renderView(); }));
    $$('[data-vtab]', body).forEach((b) => (b.onclick = () => { VD.tab = b.dataset.vtab; body.dataset.sig = ''; renderView(); }));
    if (topic) {
      const tab = tabs.find((x) => x.key === VD.tab) || tabs[0];
      await tab.render(topic, $('#videoTab'));
    }
  },
};
