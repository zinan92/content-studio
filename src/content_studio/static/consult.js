'use strict';

/* 咨询客户页：一个客户一行（= vault 010_咨询/<客户>/ 一个文件夹）。
 * Park 填的来源、首次收费、微信名、后续方案和报价存进那个文件夹的「客户档案.md」；
 * 画像由录音分析自动填一次，之后随便改。最右边是每一场咨询的两份 summary。
 * 上传录音还是那个窗口；上传后在这张表里看进度。
 * 这个文件在 app.js 之前加载（要先登记 VIEWS），所以 $、api 只在函数里用。 */
window.VIEWS = window.VIEWS || {};

const CS = { rows: null, timer: null };
const CS_STAGE = { queued: '排队中', transcribing: '转文字中', analyzing: '分析中', client: '写客户版', done: '已完成', failed: '失败', interrupted: '中断了' };
const CS_PLAN = ['', '待定', '要出方案', '暂不需要'];
const CS_COLS = [
  ['来源', '怎么进来的', '例如：抖音私信、博主介绍'],
  ['首次咨询收费', '初始咨询收费', '例如：1000 元 / 1 小时'],
  ['画像', '一句话定位 · 体量', '做什么、多大体量'],
  ['微信名', '微信名', ''],
  ['后续方案', '后续方案', ''],
  ['报价', '怎么报价', '例如：方案 3 万，分两期'],
];

function consultToday() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

async function loadClients() {
  clearTimeout(CS.timer);
  try { CS.rows = (await api('/api/clients')).clients; } catch (err) { CS.rows = { error: err.message }; }
  if (S.view === 'consults') renderClients();
  const running = Array.isArray(CS.rows) && CS.rows.some((r) => r.consults.some((c) => c.running));
  if (running) CS.timer = setTimeout(loadClients, 5000);
}

function clientField(row, [key, , hint]) {
  const v = row.profile[key] || '';
  const data = `data-client="${esc(row.name)}" data-field="${esc(key)}"`;
  if (key === '后续方案') {
    return `<select class="cl-in" ${data} title="后续要不要出更重的方案">${CS_PLAN.map((o) => `<option value="${esc(o)}"${o === v ? ' selected' : ''}>${o || '—'}</option>`).join('')}</select>`;
  }
  if (key === '画像') return `<textarea class="cl-in" rows="${Math.min(6, Math.max(2, Math.ceil(v.length / 13)))}" ${data} placeholder="${esc(hint)}">${esc(v)}</textarea>`;
  return `<input class="cl-in" ${data} value="${esc(v)}" title="${esc(v)}" placeholder="${esc(hint)}" autocomplete="off">`;
}

function jobLine(c) {
  const day = (c.day || '').slice(5).replace('-', '/');
  const retry = c.stage === 'failed' || c.stage === 'interrupted'
    ? `<button class="btn small" type="button" data-cs-retry="${esc(c.slug)}">重试</button>` : '';
  return `<div class="cl-job"><span class="cl-day">${esc(day)}</span><span class="cs-stage cs-${esc(c.stage)}">${esc(CS_STAGE[c.stage] || c.stage)}</span>${retry}${c.error ? `<small class="cs-err">${esc(c.error)}</small>` : ''}</div>`;
}

function docChip(name, d) {
  const main = d.pdf_url || d.html_url;
  const alt = d.pdf_url && d.html_url ? `<a class="cl-alt" href="${esc(d.html_url)}" target="_blank" rel="noopener" title="网页版">HTML</a>` : '';
  return `<span class="cl-doc"><a href="${esc(main)}" target="_blank" rel="noopener" title="打开"><i>${d.pdf_url ? 'PDF' : 'HTML'}</i>${esc(d.label)}</a>${alt}`
    + `<button class="cl-find" type="button" data-cl-reveal="${esc(name)}" data-file="${esc(d.pdf || d.html)}" title="在 Finder 里选中，拖进微信发给客户">⌕</button></span>`;
}

function summaryCell(r) {
  const jobs = r.consults.filter((c) => c.stage !== 'done').map(jobLine).join('');
  const days = (r.files || []).map((f) => `<div class="cl-day-block">
      <span class="cl-day">${esc(f.day.slice(0, 2))}/${esc(f.day.slice(2))}</span>
      <div class="cl-grp"><span class="cl-k">发给他的</span>${f.sent.map((d) => docChip(r.name, d)).join('') || '<span class="cl-none">没有</span>'}</div>
      <div class="cl-grp"><span class="cl-k">我自己看的</span>${f.mine.map((d) => `<span class="cl-doc mine"><a href="${esc(d.obsidian)}" title="在 Obsidian 打开"><i>MD</i>${esc(d.label)}</a></span>`).join('') || '<span class="cl-none">没有</span>'}</div>
    </div>`).join('');
  return jobs + days || '<span class="cl-none">还没有录音</span>';
}

function renderClients() {
  const body = $('#clientsBody');
  if (!CS.rows) { body.innerHTML = '<div class="panel empty">正在读客户…</div>'; loadClients(); return; }
  if (CS.rows.error) { body.innerHTML = `<div class="panel empty">${esc(CS.rows.error)}</div>`; return; }
  if (!CS.rows.length) { body.innerHTML = '<div class="panel empty">还没有客户。做完一场咨询，点右上角「上传咨询录音」。</div>'; return; }
  const sessions = CS.rows.reduce((n, r) => n + Math.max(r.consults.length, (r.files || []).length), 0);
  const follow = CS.rows.filter((r) => r.profile['后续方案'] === '要出方案').length;
  const pending = CS.rows.filter((r) => !r.profile['后续方案'] || r.profile['后续方案'] === '待定').length;
  body.innerHTML = `<div class="cl-stats">
      <div><b>${CS.rows.length}</b><span>客户</span></div>
      <div><b>${sessions}</b><span>场咨询</span></div>
      <div><b>${follow}</b><span>要出方案</span></div>
      <div><b>${pending}</b><span>还没定下一步</span></div>
    </div>
    <div class="panel cl-wrap"><table class="cl-table">
    <colgroup><col class="c-name"><col class="c-src"><col class="c-fee"><col class="c-who"><col class="c-wx"><col class="c-plan"><col class="c-quote"><col class="c-sum"></colgroup>
    <thead><tr><th>客户</th>${CS_COLS.map(([, label]) => `<th>${esc(label)}</th>`).join('')}<th>Summary</th></tr></thead>
    <tbody>${CS.rows.map((r) => `<tr class="${r.profile['后续方案'] === '暂不需要' ? 'cl-noplan' : ''}">
      <th scope="row"><b>${esc(r.name)}</b><small>${Math.max(r.consults.length, (r.files || []).length)} 场咨询</small></th>
      ${CS_COLS.map((col) => `<td class="f-${esc(col[0])}">${clientField(r, col)}</td>`).join('')}
      <td class="cl-sum">${summaryCell(r)}</td>
    </tr>`).join('')}</tbody></table></div>
    <p class="cl-foot">每个客户一个文件夹：Obsidian 的 010_咨询/&lt;客户&gt;/。填的几栏存在那里的「客户档案.md」；「发给他的」「我自己看的」按文件夹里实际的文件列出，手动放进去的 PDF 也会出现。</p>`;
}

async function saveClientField(el) {
  const { client, field } = el.dataset;
  try {
    await api(`/api/clients/${encodeURIComponent(client)}`, { method: 'PUT', body: { [field]: el.value } });
    const row = CS.rows.find((r) => r.name === client);
    if (row) row.profile[field] = el.value;
    if (field === '后续方案') el.closest('tr').classList.toggle('cl-noplan', el.value === '暂不需要');
    toast('已保存到客户档案');
  } catch (err) { toast(err.message); }
}

function openConsult() {
  $('#csFile').value = '';
  $('#csName').value = '';
  $('#csDay').value = consultToday();
  $('#csMsg').classList.remove('err');
  $('#csMsg').textContent = '录音、录像都行（m4a、mp3、mp4、mov…）。45 分钟大约 10–15 分钟出两份：给你的、给客户的。同一个客户写同一个名字，会放进同一个文件夹。';
  $('#consultDlg').showModal();
}

/* 诊断流程：做咨询时照着过的那一页（vault 010_咨询/诊断流程.md）。每次打开重新读，Obsidian 里改了这里就变。 */
async function openPlaybook() {
  const body = $('#playbookBody');
  body.innerHTML = '<p class="cl-none">正在读…</p>';
  $('#playbookDlg').showModal();
  try {
    const d = await api('/api/consults/playbook');
    $('#playbookEdit').href = d.obsidian;
    body.innerHTML = d.markdown ? renderMarkdown(d.markdown) : `<p class="cl-none">还没有这一页。在 Obsidian 里建 ${esc(d.path)}，写好再回来点开。</p>`;
    body.scrollTop = 0;
  } catch (err) { body.innerHTML = `<p class="cl-none">${esc(err.message)}</p>`; }
}

window.VIEWS.consults = { render: renderClients };

document.addEventListener('DOMContentLoaded', () => {
  $('#consultUpload').onclick = openConsult;
  $('#playbookOpen').onclick = openPlaybook;
  $('#playbookClose').onclick = () => $('#playbookDlg').close();
  $('#csCancel').onclick = () => $('#consultDlg').close();
  $('#clientsBody').addEventListener('change', (e) => { if (e.target.matches('.cl-in')) saveClientField(e.target); });
  $('#clientsBody').addEventListener('click', async (e) => {
    const t = e.target, d = t.dataset || {};
    if (d.clReveal) {
      try { await api(`/api/clients/${encodeURIComponent(d.clReveal)}/reveal?file=${encodeURIComponent(d.file)}`, { method: 'POST' }); toast('已在 Finder 里选中，拖进微信就能发'); } catch (err) { toast(err.message); }
    } else if (d.csReveal) {
      try { await api(`/api/consults/${encodeURIComponent(d.csReveal)}/reveal?what=${d.what}`, { method: 'POST' }); toast(d.what === 'client' ? '已在 Finder 里选中客户版，拖进微信就能发' : '已在 Finder 里打开'); } catch (err) { toast(err.message); }
    } else if (d.csRetry) {
      t.disabled = true;
      try { await api(`/api/consults/${encodeURIComponent(d.csRetry)}/retry`, { method: 'POST' }); } catch (err) { toast(err.message); }
      loadClients();
    }
  });
  $('#consultForm').onsubmit = async (e) => {
    e.preventDefault();
    const file = $('#csFile').files[0], msg = $('#csMsg'), btn = $('#csSubmit');
    msg.classList.remove('err');
    if (!file) { msg.classList.add('err'); msg.textContent = '先选一个录音或录像文件'; return; }
    if (!$('#csName').value.trim()) { msg.classList.add('err'); msg.textContent = '写一下客户是谁，会用作文件夹的名字'; return; }
    const body = new FormData();
    body.append('file', file);
    body.append('name', $('#csName').value.trim());
    body.append('day', $('#csDay').value);
    btn.disabled = true;
    msg.textContent = `正在上传 ${(file.size / 1048576).toFixed(1)} MB…`;
    try {
      const res = await fetch('/api/consults', { method: 'POST', body, headers: { 'X-Content-Studio': '1' } });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || data.error || `上传失败（${res.status}）`);
      $('#consultDlg').close();
      toast('传好了，正在转文字。进度看表里这一行，做完会自动在 Obsidian 打开');
      loadClients();
    } catch (err) {
      msg.classList.add('err');
      msg.textContent = err.message;
    } finally {
      btn.disabled = false;
    }
  };
});
