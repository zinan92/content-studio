'use strict';

/* 设置页「版本与更新」：看现在是哪个版本、有没有新版本，一点就拉下来并安全重启。
 * 只更新工作台自己；deploy.json 里的其他依赖只显示装没装。开发机（不在更新分支、或有没提交的改动）只看不动。
 * 在 app.js 之前加载，所以 $、api 只在函数里用。 */
const UP = { data: null, loading: false, busy: false };

function upDay(iso) { return iso ? iso.slice(0, 10) : ''; }

async function loadUpdate(fetchRemote) {
  UP.loading = true;
  renderUpdate();
  try { UP.data = await api(`/api/update?fetch=${fetchRemote ? 'true' : 'false'}`); } catch (err) { UP.data = { error: err.message }; }
  UP.loading = false;
  renderUpdate();
}

function renderUpdate() {
  const box = $('#updateBody');
  if (!box) return;
  const d = UP.data;
  if (!d) { box.innerHTML = '<p class="up-note">正在读版本…</p>'; loadUpdate(false); return; }
  if (d.error) { box.innerHTML = `<p class="up-note err">${esc(d.error)}</p>`; return; }
  const deps = (d.deps || []).map((x) => `<li class="${x.installed ? 'ok' : x.required ? 'miss' : 'off'}"><b>${esc(x.name)}</b><span>${esc(x.feature)}</span><em>${x.installed ? '已装' : x.required ? '没装' : '可选，没装'}</em></li>`).join('');
  const commits = (d.commits || []).map((c) => `<li><span class="num">${esc(upDay(c.date))}</span>${esc(c.subject)}</li>`).join('');
  const head = d.head || {};
  box.innerHTML = `<div class="up-now">
      <div><span class="up-k">现在的版本</span><b>${esc(upDay(head.date))} · ${esc(head.hash || '')}</b><small>${esc(head.subject || '')}</small></div>
      <div class="up-acts">
        <button class="btn" type="button" id="upCheck" ${UP.loading || UP.busy ? 'disabled' : ''}>${UP.loading ? '正在查…' : '检查更新'}</button>
        ${d.can_update ? `<button class="btn primary" type="button" id="upApply" ${UP.busy ? 'disabled' : ''}>${UP.busy ? '正在更新…' : `更新到最新（${d.behind} 个新改动）`}</button>` : ''}
      </div>
    </div>
    ${d.reason ? `<p class="up-note">${esc(d.reason)}</p>` : d.behind ? '' : '<p class="up-note">已经是最新版。</p>'}
    ${commits ? `<ul class="up-log">${commits}</ul>` : ''}
    ${deps ? `<details class="up-deps"><summary>依赖（${(d.deps || []).filter((x) => x.installed).length}/${(d.deps || []).length} 已装）</summary><ul>${deps}</ul></details>` : ''}`;
  $('#upCheck').onclick = () => loadUpdate(true);
  const apply = $('#upApply');
  if (apply) apply.onclick = async () => {
    UP.busy = true; renderUpdate();
    try {
      const r = await api('/api/update', { method: 'POST' });
      toast(r.message || '更新好了');
      UP.data = null;
    } catch (err) { toast(err.message); }
    UP.busy = false; renderUpdate();
  };
}
window.renderUpdate = renderUpdate;
