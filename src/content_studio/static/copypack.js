'use strict';
/* 视频 · 发布：一个标题 + 一段简介，所有平台共用；各平台只提示字数，发布记录按平台记 */

const CP = { data: {}, dirty: false };
// Platforms Park publishes a video to; the shared title/简介 is saved under each of these keys.
const SHARED_KEYS = ['douyin', 'channels', 'bilibili', 'youtube'];

async function loadCopy(topicId, force) {
  if (!force && CP.data[topicId] && Date.now() - CP.data[topicId]._at < 30000) return CP.data[topicId];
  CP.data[topicId] = { ...(await api(`/api/topics/${topicId}/copy`)), _at: Date.now() };
  return CP.data[topicId];
}

function sharedEntry(copy) {
  const platforms = (copy && copy.platforms) || {};
  const key = ['douyin', 'channels', ...Object.keys(platforms)].find((k) => platforms[k] && (platforms[k].title || platforms[k].body));
  return key ? platforms[key] : { title: '', body: '', tags: [] };
}

function lengthChips(title, specs) {
  return SHARED_KEYS.map((k) => {
    const cap = specs[k].title;
    const over = title.length > cap;
    return `<span class="len-chip ${over ? 'bad' : ''}" title="${esc(specs[k].label)}标题最多 ${cap} 字">${esc(specs[k].label)} ${title.length}/${cap}</span>`;
  }).join('');
}

function thesisFromOutline(markdown) {
  const m = /^##\s*主线\s*\n([\s\S]+?)(?=^##\s|$(?![\s\S]))/m.exec(markdown || '');
  return m ? m[1].replace(/\s+/g, ' ').trim() : '';
}

async function renderCopyBox(topic, el) {
  let d;
  try { d = await loadCopy(topic.id, false); } catch (err) { el.innerHTML = `<div class="bad">${esc(err.message)}</div>`; return; }
  const specs = d.platforms_spec;
  const e = sharedEntry(d.copy);
  const records = d.records || {};
  el.innerHTML = `<section class="cb">
    <div class="cb-h"><h3>标题和简介</h3><small>所有平台共用一份，发布时用这里的内容</small><span class="spacer"></span>
      ${topic.outline_path ? '<button class="btn small ghost" type="button" id="cbFill">用提纲填</button>' : ''}</div>
    <label class="cb-field"><span>标题</span><input id="cbTitle" value="${esc(e.title)}" placeholder="${esc(topic.title)}" autocomplete="off"></label>
    <div class="len-row" id="cbLens">${lengthChips(e.title, specs)}</div>
    <label class="cb-field"><span>简介</span><textarea id="cbBody" rows="3" placeholder="一两句话说这期讲什么">${esc(e.body)}</textarea></label>
    <label class="cb-field"><span>话题（逗号分隔，可不填）</span><input id="cbTags" value="${esc((e.tags || []).join('，'))}" autocomplete="off"></label>
    <div class="cb-foot"><button class="btn small primary" type="button" id="cbSave">保存</button><button class="btn small" type="button" id="cbCopy">复制</button>
      <span class="spacer"></span>
      <span class="cb-rec">${SHARED_KEYS.filter((k) => k !== 'douyin').map((k) => records[k]
        ? `<button class="chip-state shipped" type="button" data-cb-unmark="${k}" title="点一下撤销">${esc(specs[k].label)} 已发</button>`
        : `<button class="chip-state" type="button" data-cb-mark="${k}">${esc(specs[k].label)} 标为已发</button>`).join('')}</span></div>
  </section>`;
  const title = $('#cbTitle', el);
  const read = () => ({ title: title.value.trim(), body: $('#cbBody', el).value.trim(), tags: $('#cbTags', el).value.split(/[，,\s]+/).map((t) => t.replace(/^#/, '').trim()).filter(Boolean) });
  $$('input, textarea', el).forEach((input) => (input.oninput = () => { CP.dirty = true; $('#cbLens', el).innerHTML = lengthChips(title.value.trim(), specs); }));
  const fill = $('#cbFill', el);
  if (fill) fill.onclick = async () => {
    try {
      const o = await api(`/api/topics/${topic.id}/outline`);
      const heading = /^#\s+(.+)$/m.exec(o.markdown || '');
      title.value = heading ? heading[1].trim() : topic.title;
      const thesis = thesisFromOutline(o.markdown);
      if (thesis) $('#cbBody', el).value = thesis;
      CP.dirty = true;
      $('#cbLens', el).innerHTML = lengthChips(title.value.trim(), specs);
    } catch (err) { toast(err.message); }
  };
  const refresh = () => { CP.dirty = false; delete CP.data[topic.id]; const body = $('#videoBody'); if (body) body.dataset.sig = ''; renderView(); };
  $('#cbSave', el).onclick = async () => {
    const entry = read();
    if (!entry.title) { toast('先写标题'); return; }
    const platforms = Object.fromEntries(SHARED_KEYS.map((k) => [k, entry]));
    try { await api(`/api/topics/${topic.id}/copy`, { method: 'PUT', body: { platforms } }); toast('已保存'); refresh(); } catch (err) { toast(err.message); }
  };
  $('#cbCopy', el).onclick = () => {
    const entry = read();
    const text = [entry.title, entry.body, entry.tags.map((t) => '#' + t).join(' ')].filter(Boolean).join('\n\n');
    navigator.clipboard.writeText(text).then(() => toast('已复制'), () => toast('复制失败'));
  };
  const mark = async (platform, published) => {
    let url = null;
    if (published) {
      url = prompt(`${specs[platform].label}的链接（可留空）`, '');
      if (url === null) return;
      url = url.trim() || null;
    }
    try { await api(`/api/topics/${topic.id}/platforms`, { method: 'PUT', body: { platform, published, url } }); toast(published ? '已记下' : '已撤销'); refresh(); } catch (err) { toast(err.message); }
  };
  $$('[data-cb-mark]', el).forEach((b) => (b.onclick = () => mark(b.dataset.cbMark, true)));
  $$('[data-cb-unmark]', el).forEach((b) => (b.onclick = () => mark(b.dataset.cbUnmark, false)));
}
window.renderCopyBox = renderCopyBox;
