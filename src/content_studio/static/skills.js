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

window.renderSkills = {
  async render() {
    const body = $('#skillsBody');
    if (body.dataset.done) return;
    let data;
    try { data = await loadSkills(); } catch (err) { body.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`; return; }
    body.dataset.done = '1';
    const own = data.skills.filter((s) => s.own).length;
    body.innerHTML = `<p class="sync-note">${data.skills.length} 个 skill · ${own} 个是你自己写的 · ${data.skills.filter((s) => s.installed).length} 个已装在本机。别人写的只列作者和原仓库，代码不复制进你的仓库。</p>
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
  },
};
