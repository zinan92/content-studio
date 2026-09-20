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
      : '<div class="std-empty">还没有。拆一条老师的视频，问 Anna 学到什么，她会给一个「记进标准」的按钮。</div>'}
  </section>`;
  $$('[data-std-rm]', box).forEach((b) => (b.onclick = async () => {
    const r = d.rules.find((x) => x.id === b.dataset.stdRm);
    if (!confirm(`把这条从标准里删掉？\n\n${r.text}`)) return;
    try { await api(`/api/standard/${encodeURIComponent(b.dataset.stdRm)}`, { method: 'DELETE' }); toast('已删掉'); await window.reloadStandard(); } catch (err) { toast(err.message); }
  }));
}

window.renderSkills = {
  async render() {
    const body = $('#skillsBody');
    await window.reloadStandard();
    if (body.dataset.done) return;
    let data;
    try { data = await loadSkills(); } catch (err) { body.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`; return; }
    body.dataset.done = '1';
    const own = data.skills.filter((s) => s.own).length;
    body.innerHTML = `<div id="standardBox"></div><p class="sync-note">${data.skills.length} 个 skill · ${own} 个是你自己写的 · ${data.skills.filter((s) => s.installed).length} 个已装在本机。别人写的只列作者和原仓库，代码不复制进你的仓库。</p>
      ${data.stages.map((stage) => {
        const list = data.skills.filter((s) => s.stage === stage.key);
        if (!list.length) return '';
        return `<section class="skill-stage" id="stage-${stage.key}"><h2>${esc(stage.label)}</h2><div class="skill-grid">${list.map((s) => `<article class="panel skill" id="skill-${esc(s.name)}">
          <div class="skill-h"><b>${esc(s.title)}</b>${s.own ? '<span class="pill hot">我的</span>' : ''}<span class="skill-state ${s.installed ? 'ok' : ''}">${s.installed ? '已安装' : '本机未装'}</span></div>
          <code class="skill-name">${esc(s.name)}</code>
          <p>${esc(s.use)}</p>
          <div class="skill-by">${s.author ? `作者：${esc(s.author)}` : '作者：来源待补'} · ${s.repo ? `<a href="${esc(s.repo)}" target="_blank" rel="noopener">原仓库 ↗</a>` : '原仓库待补'}</div>
          <button class="invoke" type="button" data-copy="${esc(s.invoke)}" title="点击复制">${esc(s.invoke)}</button>
          ${s.description ? `<details><summary>SKILL.md 说明</summary><p>${esc(s.description)}</p><small>${esc(s.local_path || '')}</small></details>` : ''}
        </article>`).join('')}</div></section>`;
      }).join('')}`;
    $$('[data-copy]', body).forEach((b) => (b.onclick = () => copyText(b.dataset.copy)));
    renderStandard($('#standardBox'));
  },
};
