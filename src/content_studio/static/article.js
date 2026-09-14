'use strict';
/* 加工 · 文章：选题 → 卡兹克写作草稿 → 编辑 → 交给研习室 */
window.VIEWS = window.VIEWS || {};
window.TOPIC_ACTIONS = window.TOPIC_ACTIONS || [];

const AR = { topicId: null, draft: null, dirty: false, mode: 'preview' };

async function startWrite(topicId) {
  try {
    const res = await api(`/api/topics/${topicId}/write`, { method: 'POST' });
    toast(res.message);
    if (window.refreshTopics) await window.refreshTopics();
  } catch (err) { toast(err.message); }
}

window.TOPIC_ACTIONS.push((t) => {
  if (t.formats === 'video') return '';
  if (t.write_state === 'running') return '<span class="stage-pill running">写作中…</span>';
  const failed = t.write_state === 'failed' ? `<span class="err" title="${esc(t.write_error || '')}">写作失败</span>` : '';
  if (t.article_path) return `${failed}<button class="btn small primary" type="button" data-open-article="${t.id}">看文章</button>`;
  return `${failed}<button class="btn small primary" type="button" data-write="${t.id}">${t.write_state === 'failed' ? '重写' : '写文章'}</button>`;
});

document.addEventListener('click', (e) => {
  const write = e.target.closest('[data-write]');
  if (write) { e.preventDefault(); startWrite(Number(write.dataset.write)); return; }
  const open = e.target.closest('[data-open-article]');
  if (open) { e.preventDefault(); AR.topicId = Number(open.dataset.openArticle); AR.draft = null; go('article'); }
});

async function loadDraft() {
  AR.draft = null;
  try { AR.draft = { ...(await api(`/api/topics/${AR.topicId}/article`)), topic_id: AR.topicId }; } catch (err) { AR.draft = { error: err.message, topic_id: AR.topicId }; }
  AR.dirty = false;
}

function copyArticle(text) {
  if (!navigator.clipboard) { toast('浏览器不允许复制，请用「下载 .md」'); return Promise.resolve(false); }
  return navigator.clipboard.writeText(text).then(() => true, () => { toast('复制失败，请用「下载 .md」'); return false; });
}

window.VIEWS.article = {
  async render() {
    const body = $('#articleBody');
    if (AR.dirty) return; // never overwrite unsaved edits during polling
    let topics;
    try { topics = await api('/api/topics'); } catch (err) { body.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`; return; }
    const candidates = topics.filter((t) => t.formats !== 'video');
    if (!AR.topicId) { const first = candidates.find((t) => t.article_path) || candidates[0]; AR.topicId = first ? first.id : null; }
    const topic = candidates.find((t) => t.id === AR.topicId);
    if (topic && topic.article_path && (!AR.draft || AR.draft.topic_id !== topic.id)) await loadDraft();
    const sig = JSON.stringify([AR.topicId, AR.mode, AR.draft && AR.draft.updated_at, candidates.map((t) => [t.id, t.write_state, t.status, Boolean(t.article_path)])]);
    if (body.dataset.sig === sig) return;
    body.dataset.sig = sig;
    const list = candidates.length ? candidates.map((t) => `<button type="button" class="art-item ${t.id === AR.topicId ? 'on' : ''}" data-art="${t.id}">
        <b class="clamp">${esc(t.title)}</b>
        <small>${t.write_state === 'running' ? '写作中…' : t.write_state === 'failed' ? '写作失败' : t.article_path ? { drafting: '草稿', ready: '待发', published: '已发出', todo: '草稿' }[t.status] : '还没写'}</small>
      </button>`).join('') : '<div class="empty"><span>还没有要写成文章的选题。去「选题」加一个。</span></div>';
    let main = '<div class="empty"><span>左边选一个选题。</span></div>';
    if (topic) {
      if (topic.write_state === 'running') {
        main = `<div class="empty"><span class="spin"></span><b>卡兹克写作正在写《${esc(topic.title)}》</b><span>一般 1–5 分钟，写完自动出现在这里。可以先去做别的。</span></div>`;
      } else if (!topic.article_path) {
        main = `<div class="empty"><b>${esc(topic.title)}</b>${topic.write_state === 'failed' ? `<span class="err">${esc(topic.write_error || '写作失败')}</span>` : ''}<span>会把选题关联的 ${topic.note_paths.length} 条 Obsidian 笔记交给卡兹克写作 skill。作者是你，不会带卡兹克的署名。</span><button class="btn primary" type="button" data-write="${topic.id}">${topic.write_state === 'failed' ? '重写' : '写文章'}</button></div>`;
      } else if (AR.draft && AR.draft.error) {
        main = `<div class="empty"><b>${esc(AR.draft.error)}</b></div>`;
      } else if (AR.draft) {
        const d = AR.draft;
        const chars = d.markdown.replace(/\s/g, '').length;
        main = `<div class="art-head">
            <div><h2>${esc(topic.title)}</h2><small>${chars} 字 · ${d.generated_at ? `生成于 ${day(d.generated_at)}` : ''} · 最后修改 ${day(d.updated_at)}${d.sources && d.sources.length ? ` · 素材 ${d.sources.length} 条` : ''}</small></div>
            <div class="acts">
              <div class="seg-toggle" role="group"><button type="button" class="${AR.mode === 'preview' ? 'on' : ''}" data-mode="preview">预览</button><button type="button" class="${AR.mode === 'edit' ? 'on' : ''}" data-mode="edit">编辑</button></div>
            </div>
          </div>
          ${AR.mode === 'edit' ? `<textarea id="artText" spellcheck="false">${esc(d.markdown)}</textarea>` : `<article class="md art-md">${renderMarkdown(d.markdown)}</article>`}
          <div class="art-foot">
            ${AR.mode === 'edit' ? '<button class="btn primary" type="button" id="artSave">保存</button>' : ''}
            <button class="btn" type="button" id="artCopy">复制正文</button>
            <a class="btn" href="/api/topics/${topic.id}/article.md" download>下载 .md</a>
            <button class="btn" type="button" data-write="${topic.id}" title="重新让卡兹克写作写一版，会覆盖当前草稿">重写</button>
            <span class="spacer"></span>
            ${topic.status === 'published' ? `<span class="stage-pill running">已发出</span>` : `<button class="btn primary" type="button" id="artHandoff">交给研习室</button><button class="btn" type="button" id="artPublished">研习室已发出</button>`}
          </div>`;
      }
    }
    body.innerHTML = `<div class="art-grid"><div class="panel art-list">${list}</div><div class="panel art-main">${main}</div></div>`;
    $$('[data-art]', body).forEach((b) => (b.onclick = () => { AR.topicId = Number(b.dataset.art); AR.draft = null; AR.mode = 'preview'; body.dataset.sig = ''; renderView(); }));
    $$('[data-mode]', body).forEach((b) => (b.onclick = () => { AR.mode = b.dataset.mode; body.dataset.sig = ''; renderView(); }));
    const text = $('#artText');
    if (text) text.oninput = () => { AR.dirty = true; };
    const save = $('#artSave');
    if (save) save.onclick = async () => {
      try {
        AR.draft = { ...(await api(`/api/topics/${topic.id}/article`, { method: 'PUT', body: { markdown: $('#artText').value } })), topic_id: topic.id };
        AR.dirty = false; AR.mode = 'preview'; body.dataset.sig = '';
        toast('已保存');
        renderView();
      } catch (err) { toast(err.message); }
    };
    const copy = $('#artCopy');
    if (copy) copy.onclick = async () => { if (await copyArticle(text ? text.value : AR.draft.markdown)) toast('已复制正文'); };
    const handoffBtn = $('#artHandoff');
    if (handoffBtn) handoffBtn.onclick = async () => {
      if (AR.dirty) { toast('先保存修改'); return; }
      const copied = await copyArticle(AR.draft.markdown);
      try {
        const res = await api(`/api/topics/${topic.id}/handoff`, { method: 'POST' });
        if (res.admin_url) window.open(res.admin_url, '_blank', 'noopener');
        toast(res.admin_url ? `${copied ? '已复制正文，' : ''}已打开研习室后台：在「内容」里导入 Markdown` : '已标为待发。在设置里填研习室后台地址，下次会直接打开');
        if (window.refreshTopics) await window.refreshTopics();
        body.dataset.sig = '';
        renderView();
      } catch (err) { toast(err.message); }
    };
    const published = $('#artPublished');
    if (published) published.onclick = async () => {
      const url = prompt('研习室文章链接（可留空）', '');
      if (url === null) return;
      await window.patchTopic(topic.id, { status: 'published', ...(url.trim() ? { published_url: url.trim() } : {}) }, '已标为发出');
      body.dataset.sig = '';
    };
  },
};
