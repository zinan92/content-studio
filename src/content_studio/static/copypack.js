'use strict';
/* 视频 · 文案与平台：各平台标题 / 正文 / 话题 + 发布状态（不自动发布） */
window.VIDEO_TABS = window.VIDEO_TABS || [];

const CP = { data: {}, dirty: false };
const PLATFORM_ORDER = ['douyin', 'channels', 'yanxishi', 'xiaohongshu', 'bilibili', 'youtube', 'x'];

function xLen(text) {
  let n = 0;
  for (const ch of text) n += /[⺀-鿿＀-￯　-〿]/.test(ch) ? 2 : 1;
  return n;
}

async function loadCopy(topicId, force) {
  if (!force && CP.data[topicId] && Date.now() - CP.data[topicId]._at < (CP.data[topicId].state === 'running' ? 4000 : 30000)) return CP.data[topicId];
  CP.data[topicId] = { ...(await api(`/api/topics/${topicId}/copy`)), _at: Date.now() };
  if (CP.data[topicId].state === 'running') setTimeout(() => { if (S.view === 'work' && !CP.dirty) { $('#videoBody').dataset.sig = ''; renderView(); } }, 5000);
  return CP.data[topicId];
}

function copyCard(key, spec, entry, record) {
  const e = entry || { title: '', body: '', tags: [] };
  const bodyLen = spec.weighted ? xLen(`${e.body} ${e.tags.map((t) => '#' + t).join(' ')}`) : e.body.length;
  return `<div class="cp-card" data-platform="${key}">
    <div class="cp-h"><b>${esc(spec.label)}</b>${record ? `<span class="pill hot">已发出</span>${record.url ? `<a href="${esc(record.url)}" target="_blank" rel="noopener">链接 ↗</a>` : ''}` : '<span class="muted">未发</span>'}
      <span class="spacer"></span>${spec.admin ? `<a class="btn small" href="${esc(spec.admin)}" target="_blank" rel="noopener">打开后台 ↗</a>` : ''}</div>
    ${spec.title ? `<label class="cp-field"><span>标题 <em class="${e.title.length > spec.title ? 'bad' : ''}">${e.title.length}/${spec.title}</em></span><input data-f="title" value="${esc(e.title)}"></label>` : ''}
    <label class="cp-field"><span>${key === 'yanxishi' ? '摘要' : '正文'} <em class="${bodyLen > spec.body ? 'bad' : ''}">${bodyLen}/${spec.body}${spec.weighted ? '（中文按 2）' : ''}</em></span><textarea data-f="body" rows="${key === 'x' || key === 'yanxishi' ? 3 : 6}">${esc(e.body)}</textarea></label>
    <label class="cp-field"><span>话题（逗号分隔，最多 ${spec.tags} 个）</span><input data-f="tags" value="${esc(e.tags.join('，'))}"></label>
    <div class="cp-foot"><button class="btn small" type="button" data-cp-copy="${key}">复制全部</button>
      ${record ? `<button class="btn small ghost" type="button" data-cp-unpublish="${key}">撤销已发</button>` : `<button class="btn small" type="button" data-cp-publish="${key}">标为已发</button>`}</div>
  </div>`;
}

function readCard(card) {
  const get = (f) => { const el = card.querySelector(`[data-f="${f}"]`); return el ? el.value : ''; };
  return { title: get('title'), body: get('body'), tags: get('tags').split(/[，,\s]+/).map((t) => t.replace(/^#/, '').trim()).filter(Boolean) };
}

window.VIDEO_TABS.push({
  key: 'copy',
  label: '文案与平台',
  badge: (t) => (t.copy_state === 'running' ? '生成中' : ''),
  async render(topic, el) {
    if (CP.dirty && el.querySelector('.cp-grid')) return;
    let d;
    try { d = await loadCopy(topic.id, false); } catch (err) { el.innerHTML = `<div class="empty"><b>${esc(err.message)}</b></div>`; return; }
    const specs = d.platforms_spec;
    const published = Object.keys(d.records).length;
    const core = d.core_platforms || ['douyin', 'channels', 'yanxishi'];
    const extra = PLATFORM_ORDER.filter((k) => !core.includes(k));
    const extraCards = (render) => {
      const cards = extra.map(render).join('');
      return cards ? `<details class="cp-more" ${extra.some((k) => d.records[k]) ? 'open' : ''}><summary>更多平台（小红书、B 站、YouTube、X）· 不自动生成，需要时自己填</summary><div class="cp-grid">${cards}</div></details>` : '';
    };
    if (d.state === 'running') {
      el.innerHTML = '<div class="empty"><span class="spin"></span><b>正在写各平台文案</b><span>一般 1 分钟。</span></div>';
      return;
    }
    const top = `<div class="cp-top"><span>${published} 个平台已发出 · 只帮你写文案和记录，不会自动发布</span>
      ${d.error && d.state === 'failed' ? `<span class="bad">${esc(d.error)}</span>` : ''}
      <span class="spacer"></span>${d.copy ? '<button class="btn small primary" type="button" id="cpSave">保存修改</button>' : ''}
      <button class="btn small ${d.copy ? '' : 'primary'}" type="button" id="cpGen">${d.copy ? '重新生成' : '生成各平台文案'}</button></div>`;
    if (!d.copy) {
      el.innerHTML = `${top}<div class="empty"><span>根据拍摄提纲${topic.article_path ? '和文章' : ''}写抖音、视频号、研习室的标题、正文和话题，长度按平台上限检查。</span></div>
        <div class="cp-grid">${PLATFORM_ORDER.map((k) => d.records[k] ? copyCard(k, specs[k], null, d.records[k]) : '').join('')}</div>`;
    } else {
      el.innerHTML = `${top}<div class="cp-grid">${core.map((k) => copyCard(k, specs[k], d.copy.platforms[k], d.records[k])).join('')}</div>${extraCards((k) => copyCard(k, specs[k], d.copy.platforms[k], d.records[k]))}`;
    }
    $$('.cp-card input, .cp-card textarea', el).forEach((input) => (input.oninput = () => { CP.dirty = true; }));
    $('#cpGen').onclick = async () => {
      if (d.copy && !confirm('重新生成会覆盖现在的文案，继续吗？')) return;
      try { const r = await api(`/api/topics/${topic.id}/copy`, { method: 'POST' }); toast(r.message); CP.dirty = false; delete CP.data[topic.id]; $('#videoBody').dataset.sig = ''; renderView(); } catch (err) { toast(err.message); }
    };
    const save = $('#cpSave');
    if (save) save.onclick = async () => {
      const platforms = {};
      $$('.cp-card', el).forEach((card) => {
        const entry = readCard(card);
        if (!core.includes(card.dataset.platform) && !entry.title && !entry.body && !entry.tags.length) return; // untouched extra platform
        platforms[card.dataset.platform] = entry;
      });
      try { await api(`/api/topics/${topic.id}/copy`, { method: 'PUT', body: { platforms } }); toast('已保存'); CP.dirty = false; delete CP.data[topic.id]; $('#videoBody').dataset.sig = ''; renderView(); } catch (err) { toast(err.message); }
    };
    $$('[data-cp-copy]', el).forEach((b) => (b.onclick = () => {
      const entry = readCard(b.closest('.cp-card'));
      const text = [entry.title, entry.body, entry.tags.map((t) => '#' + t).join(' ')].filter(Boolean).join('\n\n');
      navigator.clipboard.writeText(text).then(() => toast(`已复制${specs[b.dataset.cpCopy].label}文案`), () => toast('复制失败'));
    }));
    const mark = async (platform, publishedFlag) => {
      let url = null;
      if (publishedFlag) {
        url = prompt(`${specs[platform].label}的发布链接（可留空）`, '');
        if (url === null) return;
        url = url.trim() || null;
      }
      try { await api(`/api/topics/${topic.id}/platforms`, { method: 'PUT', body: { platform, published: publishedFlag, url } }); toast(publishedFlag ? '已标为发出' : '已撤销'); delete CP.data[topic.id]; $('#videoBody').dataset.sig = ''; renderView(); } catch (err) { toast(err.message); }
    };
    $$('[data-cp-publish]', el).forEach((b) => (b.onclick = () => mark(b.dataset.cpPublish, true)));
    $$('[data-cp-unpublish]', el).forEach((b) => (b.onclick = () => mark(b.dataset.cpUnpublish, false)));
  },
});
