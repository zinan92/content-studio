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
  ['后续方案', '后续要不要出方案', ''],
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
    return `<select class="cl-in" ${data}>${CS_PLAN.map((o) => `<option value="${esc(o)}"${o === v ? ' selected' : ''}>${o || '—'}</option>`).join('')}</select>`;
  }
  if (key === '画像') return `<textarea class="cl-in" rows="3" ${data} placeholder="${esc(hint)}">${esc(v)}</textarea>`;
  return `<input class="cl-in" ${data} value="${esc(v)}" placeholder="${esc(hint)}" autocomplete="off">`;
}

function consultCell(c) {
  const day = (c.day || '').slice(5).replace('-', '/');
  if (c.stage !== 'done') {
    const retry = c.stage === 'failed' || c.stage === 'interrupted'
      ? ` <button class="btn small" type="button" data-cs-retry="${esc(c.slug)}">重试</button>` : '';
    return `<div class="cl-cs"><b>${esc(day)}</b><span class="cs-stage cs-${esc(c.stage)}">${esc(CS_STAGE[c.stage] || c.stage)}</span>${retry}${c.error ? `<small class="cs-err">${esc(c.error)}</small>` : ''}</div>`;
  }
  const sent = c.pdf || c.client
    ? `<a href="${esc(c.pdf || c.client)}" target="_blank" rel="noopener">${c.pdf ? 'PDF' : 'HTML'}</a>`
      + (c.pdf && c.client ? `<a href="${esc(c.client)}" target="_blank" rel="noopener">HTML</a>` : '')
      + `<button class="linklike" type="button" data-cs-reveal="${esc(c.slug)}" data-what="client">在 Finder 里选中</button>`
    : '<span class="cl-none">还没有</span>';
  return `<div class="cl-cs"><b>${esc(day)}</b>`
    + `<div><span class="cl-k">发给他的</span>${sent}</div>`
    + `<div><span class="cl-k">我自己看的</span><a href="${esc(c.obsidian)}">咨询记录</a><button class="linklike" type="button" data-cs-reveal="${esc(c.slug)}" data-what="folder">原件</button></div>`
    + (c.error ? `<small class="cs-err">${esc(c.error)}</small>` : '')
    + '</div>';
}

function renderClients() {
  const body = $('#clientsBody');
  if (!CS.rows) { body.innerHTML = '<div class="panel empty">正在读客户…</div>'; loadClients(); return; }
  if (CS.rows.error) { body.innerHTML = `<div class="panel empty">${esc(CS.rows.error)}</div>`; return; }
  if (!CS.rows.length) { body.innerHTML = '<div class="panel empty">还没有客户。做完一场咨询，点右上角「上传咨询录音」。</div>'; return; }
  body.innerHTML = `<div class="panel cl-wrap"><table class="cl-table">
    <thead><tr><th>客户</th>${CS_COLS.map(([, label]) => `<th>${esc(label)}</th>`).join('')}<th>Summary</th></tr></thead>
    <tbody>${CS.rows.map((r) => `<tr>
      <th scope="row"><b>${esc(r.name)}</b><small>${r.consults.length} 场咨询</small></th>
      ${CS_COLS.map((col) => `<td>${clientField(r, col)}</td>`).join('')}
      <td class="cl-sum">${r.consults.map(consultCell).join('') || '<span class="cl-none">没有录音</span>'}</td>
    </tr>`).join('')}</tbody></table></div>
    <p class="cl-foot">每个客户的信息都在 Obsidian 的 010_咨询/&lt;客户&gt;/ 里，填的这几栏存进「客户档案.md」，那边改了这里也会变。</p>`;
}

async function saveClientField(el) {
  const { client, field } = el.dataset;
  try {
    await api(`/api/clients/${encodeURIComponent(client)}`, { method: 'PUT', body: { [field]: el.value } });
    const row = CS.rows.find((r) => r.name === client);
    if (row) row.profile[field] = el.value;
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

window.VIEWS.consults = { render: renderClients };

document.addEventListener('DOMContentLoaded', () => {
  $('#consultUpload').onclick = openConsult;
  $('#csCancel').onclick = () => $('#consultDlg').close();
  $('#clientsBody').addEventListener('change', (e) => { if (e.target.matches('.cl-in')) saveClientField(e.target); });
  $('#clientsBody').addEventListener('click', async (e) => {
    const t = e.target, d = t.dataset || {};
    if (d.csReveal) {
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
