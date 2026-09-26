'use strict';
/* Skills：Park 做内容在用的 skill，按生产阶段分组；放在「设置与 Skills」里 */
window.VIEWS = window.VIEWS || {};

const SK = { data: null };
async function loadSkills() {
  if (!SK.data) SK.data = await api('/api/skills');
  return SK.data;
}

function copyText(text) {
  if (navigator.clipboard) navigator.clipboard.writeText(text).then(() => toast('已复制调用方式'), () => toast(text));
  else toast(text);
}

/* Anna 的标准：拆解里学到的方法写进 park-content-qa，以后每条内容都按它评分。 */
window.reloadStandard = async function reloadStandard() {
  try { S.standard = await api('/api/standard'); } catch (_) { S.standard = null; }
  const box = $('#standardBox');
  if (box) renderStandard(box);
};

function standardRow(r) {
  return `<div class="std-row"><div><b>${esc(r.text)}</b><div class="by">${esc(r.at)}${r.source ? ' · ' + esc(r.source) : ''}</div></div>
    <button class="btn small ghost" type="button" data-std-rm="${esc(r.id)}">删掉</button></div>`;
}

function renderStandard(box) {
  const d = S.standard;
  if (!d) { box.innerHTML = ''; return; }
  box.innerHTML = `<section class="panel std">
    <div class="panel-h"><h2>从拆解里学来的 <span class="num">${d.rules.length || ''}</span></h2><small>写进三点评分标准，Anna 每轮都读它 · ${esc(d.path)}</small></div>
    ${d.rules.length ? d.rules.map(standardRow).join('')
      : '<div class="std-empty">还没有。拆一条对标的视频，问 Anna 学到什么，她会给一个「记进标准」的按钮。</div>'}
  </section>`;
  $$('[data-std-rm]', box).forEach((b) => (b.onclick = async () => {
    const r = d.rules.find((x) => x.id === b.dataset.stdRm);
    if (!confirm(`把这条从标准里删掉？\n\n${r.text}`)) return;
    try { await api(`/api/standard/${encodeURIComponent(b.dataset.stdRm)}`, { method: 'DELETE' }); toast('已删掉'); await window.reloadStandard(); } catch (err) { toast(err.message); }
  }));
}

const SKILL_FIELDS = [
  ['name', '名字', '英文，比如 khazix-writer'],
  ['title', '叫什么', '中文名，比如 卡兹克写作'],
  ['use', '用来做什么', '一句话'],
  ['repo', 'GitHub 链接', 'https://github.com/…（别人写的 skill 只放链接）'],
  ['dir', '本机 skill 目录', '装在 ~/.claude/skills 下的文件夹名，没有就空着'],
  ['path', '本机 Markdown', '~/ 开头的 .md，比如一份写作框架'],
  ['author', '作者', ''],
  ['invoke', '怎么叫它', '在 Claude 里说：…'],
];

function skillForm(stages, s) {
  s = s || {};
  return `<form class="dlg skill-form" id="skillForm">
    <h2>${s.name ? '改这个 skill' : '加一个 skill'}</h2>
    ${SKILL_FIELDS.map(([k, l, ph]) => `<label><span>${l}</span><input id="sk-${k}" value="${esc(s[k] || '')}" placeholder="${esc(ph)}" autocomplete="off"></label>`).join('')}
    <label><span>用在哪一步</span><select id="sk-stage">${stages.map((st) => `<option value="${st.key}" ${s.stage === st.key ? 'selected' : ''}>${esc(st.label)}</option>`).join('')}</select></label>
    <label class="chk"><input type="checkbox" id="sk-own" ${s.own ? 'checked' : ''}> 我自己写的</label>
    <div class="dlg-actions"><button type="button" class="btn" id="skCancel">取消</button><button class="btn primary" type="submit">保存</button></div>
  </form>`;
}

function openSkillDialog(html, bind) {
  let dlg = $('#skillDlg');
  if (!dlg) { dlg = document.createElement('dialog'); dlg.id = 'skillDlg'; dlg.className = 'skill-dlg'; document.body.appendChild(dlg); }
  dlg.innerHTML = html;
  dlg.showModal();
  bind(dlg);
  return dlg;
}

function openSkillEditor(data, s) {
  openSkillDialog(skillForm(data.stages, s), (dlg) => {
    $('#skCancel', dlg).onclick = () => dlg.close();
    $('#skillForm', dlg).onsubmit = async (e) => {
      e.preventDefault();
      const body = { previous: s ? s.name : null, stage: $('#sk-stage', dlg).value, own: $('#sk-own', dlg).checked };
      SKILL_FIELDS.forEach(([k]) => { body[k] = $(`#sk-${k}`, dlg).value.trim() || null; });
      try { await api('/api/skills', { method: 'PUT', body }); dlg.close(); toast('已保存'); await reloadSkills(); } catch (err) { toast(err.message); }
    };
  });
}

async function openDoc(url, fallbackTitle) {
  const dlg = openSkillDialog('<div class="dlg doc-dlg"><div class="empty"><span class="spin"></span></div></div>', () => {});
  try {
    const d = await api(url);
    dlg.innerHTML = `<div class="dlg doc-dlg"><div class="doc-h"><div><h2>${esc(d.name || fallbackTitle)}</h2><small>${esc(d.path)}</small></div><button class="btn small" type="button" id="docClose">关掉</button></div><article class="md">${renderMarkdown(d.body || '')}</article></div>`;
  } catch (err) { dlg.innerHTML = `<div class="dlg"><b>${esc(err.message)}</b><div class="dlg-actions"><button class="btn" type="button" id="docClose">关掉</button></div></div>`; }
  const c = $('#docClose', dlg); if (c) c.onclick = () => dlg.close();
}

async function reloadSkills() {
  SK.data = null;
  const body = $('#skillsBody'); if (body) body.dataset.done = '';
  await window.renderSkills.render();
}

function skillCard(s) {
  return `<article class="panel skill" id="skill-${esc(s.name)}">
    <div class="skill-h"><b>${esc(s.title)}</b>${s.own ? '<span class="pill hot">我的</span>' : ''}<span class="skill-state ${s.installed ? 'ok' : ''}">${s.installed ? '本机有' : '本机未装'}</span></div>
    <code class="skill-name">${esc(s.name)}</code>
    <p>${esc(s.use)}</p>
    <div class="skill-by">${s.author ? `作者：${esc(s.author)}` : '作者：来源待补'}${s.repo ? ` · <a href="${esc(s.repo)}" target="_blank" rel="noopener">GitHub ↗</a>` : ''}</div>
    <button class="invoke" type="button" data-copy="${esc(s.invoke)}" title="点击复制">${esc(s.invoke)}</button>
    <div class="skill-acts">${s.installed ? `<button class="btn small" type="button" data-sk-doc="${esc(s.name)}">看文件</button>` : ''}<button class="btn small ghost" type="button" data-sk-edit="${esc(s.name)}">改</button><button class="btn small ghost" type="button" data-sk-rm="${esc(s.name)}">删</button></div>
  </article>`;
}

window.renderSkills = {
  async render() {
    const body = $('#skillsBody');
    await window.reloadStandard();  // its own panel in 设置, not inside the collapsed Skills block
    if (body.dataset.done) return;
    let data, soul;
    try { [data, soul] = await Promise.all([loadSkills(), api('/api/anna/soul')]); } catch (err) { body.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`; return; }
    body.dataset.done = '1';
    const own = data.skills.filter((s) => s.own).length;
    body.innerHTML = `<div class="skill-top"><p class="sync-note">${data.skills.length} 个 · ${own} 个是你自己写的 · ${data.skills.filter((s) => s.installed).length} 个本机有。别人写的只放 GitHub 链接，代码不复制进仓库。清单存在 <code>${esc(data.file || '')}</code>。</p><button class="btn small primary" type="button" id="skAdd">加一个 skill</button></div>
      ${data.stages.map((stage) => {
        const list = data.skills.filter((s) => s.stage === stage.key);
        if (!list.length) return '';
        return `<section class="skill-stage" id="stage-${stage.key}"><h2>${esc(stage.label)} <small>${list.length}</small></h2><div class="skill-grid">${list.map(skillCard).join('')}</div></section>`;
      }).join('')}
      <section class="skill-stage"><h2>Anna 每轮读的文件 <small>${soul.files.length}</small></h2><p class="sync-note">角色、knowledge、原则、定位、三点评分。改这些 Markdown 就是改 Anna；这里只读。</p>
        <div class="soul-list">${soul.files.map((f) => `<button class="soul-row" type="button" data-soul="${f.i}"><b>${esc(f.name.replace(/\.(md|txt)$/, ''))}</b><small>${esc(f.path)}</small></button>`).join('')}</div></section>`;
    $$('[data-copy]', body).forEach((b) => (b.onclick = () => copyText(b.dataset.copy)));
    $('#skAdd').onclick = () => openSkillEditor(data, null);
    $$('[data-sk-edit]', body).forEach((b) => (b.onclick = () => openSkillEditor(data, data.skills.find((s) => s.name === b.dataset.skEdit))));
    $$('[data-sk-doc]', body).forEach((b) => (b.onclick = () => openDoc(`/api/skills/${encodeURIComponent(b.dataset.skDoc)}/doc`, b.dataset.skDoc)));
    $$('[data-soul]', body).forEach((b) => (b.onclick = () => openDoc(`/api/anna/soul/${b.dataset.soul}`, '')));
    $$('[data-sk-rm]', body).forEach((b) => (b.onclick = async () => {
      if (!confirm(`把「${b.dataset.skRm}」从清单里删掉？只删清单，不动本机的 skill 文件。`)) return;
      try { await api(`/api/skills/${encodeURIComponent(b.dataset.skRm)}`, { method: 'DELETE' }); toast('已删掉'); await reloadSkills(); } catch (err) { toast(err.message); }
    }));
  },
};
