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

/** 抖音没有自动发布通道（只有视频号 / B 站 / YouTube 有），所以这一页是「在这里写好，
 *  到抖音粘贴」。样子照着 creator.douyin.com 的发布页做，手感一致；但凡不能真正带过去的
 *  开关（谁可以看、允许他人保存、定时发布）一律不放假控件，只在确认框里提醒去抖音那边设。 */
function dyPreview(title, body, tags) {
  const text = [title, body].filter(Boolean).join('\n');
  const tagLine = tags.map((t) => `<span class="dy-tag">#${esc(t)}</span>`).join(' ');
  return `<div class="dy-phone"><div class="dy-screen">
      <div class="dy-cover">封面</div>
      <div class="dy-cap">${text ? esc(text).replace(/\n/g, '<br>') : '<span class="dy-ph">作品描述会显示在这里</span>'}${tagLine ? `<div class="dy-tags">${tagLine}</div>` : ''}</div>
    </div><small>手机上大概长这样</small></div>`;
}

async function renderCopyBox(topic, el) {
  let d;
  try { d = await loadCopy(topic.id, false); } catch (err) { el.innerHTML = `<div class="bad">${esc(err.message)}</div>`; return; }
  const specs = d.platforms_spec;
  const e = sharedEntry(d.copy);
  const records = d.records || {};
  const tagsOf = (raw) => raw.split(/[，,\s]+/).map((t) => t.replace(/^#/, '').trim()).filter(Boolean);
  el.innerHTML = `<section class="cb dy">
    <div class="dy-bar"><span class="dy-logo">抖音</span><b>发布视频</b><small>在这里写好，到抖音粘贴</small><span class="spacer"></span>
      ${topic.outline_path ? '<button class="btn small ghost" type="button" id="cbFill">用提纲填</button>' : ''}</div>
    <div class="dy-grid">
      <div class="dy-form">
        <label class="dy-field"><span>标题</span><input id="cbTitle" value="${esc(e.title)}" placeholder="${esc(topic.title)}" autocomplete="off" maxlength="60"></label>
        <div class="len-row" id="cbLens">${lengthChips(e.title, specs)}</div>
        <label class="dy-field"><span>作品描述<i class="dy-count" id="cbCount">0/1000</i></span><textarea id="cbBody" rows="5" placeholder="好的开头能留住人。把第一句写在这里。">${esc(e.body)}</textarea></label>
        <label class="dy-field"><span>添加话题<i class="dy-hint">逗号分隔，抖音最多 5 个</i></span><input id="cbTags" value="${esc((e.tags || []).join('，'))}" placeholder="AI，投资，副业" autocomplete="off"></label>
        <div class="dy-foot">
          <button class="btn dy-publish" type="button" id="cbPublish">发布</button>
          <button class="btn" type="button" id="cbSave">存草稿</button>
          <button class="btn ghost" type="button" id="cbCopy">复制</button>
        </div>
        <div class="dy-note">抖音这一步要你自己在抖音里传视频、粘贴描述。「谁可以看」「允许他人保存」「定时发布」也在抖音那边设。<br>视频号 / B 站 / YouTube 可以从下面「一键发布」直接走。</div>
        <span class="cb-rec">${[...new Set([...SHARED_KEYS.filter((k) => k !== 'douyin'), ...Object.keys(records)])].filter((k) => specs[k]).map((k) => records[k]
          ? `<button class="chip-state shipped" type="button" data-cb-unmark="${k}" title="点一下撤销">${esc(specs[k].label)} 已发</button>`
          : `<button class="chip-state" type="button" data-cb-mark="${k}">${esc(specs[k].label)} 标为已发</button>`).join('')}</span>
      </div>
      <div class="dy-side" id="cbPreview">${dyPreview(e.title, e.body, e.tags || [])}</div>
    </div>
  </section>`;
  const title = $('#cbTitle', el);
  const read = () => ({ title: title.value.trim(), body: $('#cbBody', el).value.trim(), tags: $('#cbTags', el).value.split(/[，,\s]+/).map((t) => t.replace(/^#/, '').trim()).filter(Boolean) });
  const repaint = () => {
    const entry = read();
    $('#cbLens', el).innerHTML = lengthChips(entry.title, specs);
    $('#cbCount', el).textContent = `${entry.body.length}/1000`;
    $('#cbPreview', el).innerHTML = dyPreview(entry.title, entry.body, entry.tags);
  };
  $$('input, textarea', el).forEach((input) => (input.oninput = () => { CP.dirty = true; repaint(); }));
  repaint();
  const fill = $('#cbFill', el);
  if (fill) fill.onclick = async () => {
    try {
      const o = await api(`/api/topics/${topic.id}/outline`);
      const heading = /^#\s+(.+)$/m.exec(o.markdown || '');
      title.value = heading ? heading[1].trim() : topic.title;
      const thesis = thesisFromOutline(o.markdown);
      if (thesis) $('#cbBody', el).value = thesis;
      CP.dirty = true;
      repaint();
    } catch (err) { toast(err.message); }
  };
  const refresh = () => { CP.dirty = false; delete CP.data[topic.id]; const body = $('#videoBody'); if (body) body.dataset.sig = ''; renderView(); };
  $('#cbSave', el).onclick = async () => {
    const entry = read();
    if (!entry.title) { toast('先写标题'); return; }
    const platforms = Object.fromEntries(SHARED_KEYS.map((k) => [k, entry]));
    try { await api(`/api/topics/${topic.id}/copy`, { method: 'PUT', body: { platforms } }); toast('已保存'); refresh(); } catch (err) { toast(err.message); }
  };
  const copyText = () => {
    const entry = read();
    const text = [entry.title, entry.body, entry.tags.map((t) => '#' + t).join(' ')].filter(Boolean).join('\n\n');
    return navigator.clipboard.writeText(text).then(() => text, () => text);
  };
  $('#cbCopy', el).onclick = () => copyText().then(() => toast('已复制'));
  $('#cbPublish', el).onclick = async () => {
    if (!read().title) { toast('先写标题'); return; }
    // 抖音没有自动通道：这个按钮只是把描述复制走、打开抖音的发布页，不会替 Park 发布。
    if (!confirm('抖音不能自动发。点「确定」会复制描述、打开抖音发布页，你在那边传视频、粘贴描述，并设置「谁可以看」。')) return;
    await copyText();
    window.open(specs.douyin.admin, '_blank', 'noopener');
    toast('描述已复制，抖音发布页已打开');
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
