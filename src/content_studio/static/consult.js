'use strict';

/* 咨询录音：上传一场 1v1 的录音 → 本机转文字 + 分析 → vault 010_咨询/ 一篇左右对照的笔记 */
const CS = { timer: null };
const CS_STAGE = { queued: '排队中', transcribing: '转文字中', analyzing: '分析中', done: '已完成', failed: '失败', interrupted: '中断了' };

function consultToday() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function openConsult() {
  $('#csFile').value = '';
  $('#csName').value = '';
  $('#csDay').value = consultToday();
  $('#csMsg').classList.remove('err');
  $('#csMsg').textContent = '支持 m4a、mp3、wav。45 分钟的录音，转文字加分析大约 10 分钟。';
  $('#consultDlg').showModal();
  loadConsults();
}

async function loadConsults() {
  clearTimeout(CS.timer);
  let rows = [];
  try { rows = (await api('/api/consults')).consults; } catch (err) { $('#csList').innerHTML = `<p class="cs-err">${esc(err.message)}</p>`; return; }
  $('#csList').innerHTML = rows.length ? rows.map((r) => {
    const act = r.stage === 'done' && r.obsidian
      ? `<a class="btn small" href="${esc(r.obsidian)}">在 Obsidian 打开</a>`
      : (r.stage === 'failed' || r.stage === 'interrupted') ? `<button class="btn small" type="button" data-cs-retry="${esc(r.slug)}">重试</button>` : '';
    const note = r.error ? `<small class="cs-err">${esc(r.error)}</small>` : r.minutes ? `<small>${r.minutes} 分钟</small>` : '';
    return `<div class="cs-row"><div><b>${esc(r.slug)}</b>${note}</div><span class="cs-stage cs-${esc(r.stage)}">${esc(CS_STAGE[r.stage] || r.stage)}</span>${act}</div>`;
  }).join('') : '<p class="cs-empty">还没有上传过。</p>';
  if (rows.some((r) => r.running) && $('#consultDlg').open) CS.timer = setTimeout(loadConsults, 5000);
}

$('#consultBtn').onclick = openConsult;
$('#csCancel').onclick = () => { clearTimeout(CS.timer); $('#consultDlg').close(); };
$('#csList').onclick = async (e) => {
  const slug = e.target.dataset && e.target.dataset.csRetry;
  if (!slug) return;
  e.target.disabled = true;
  try { await api(`/api/consults/${encodeURIComponent(slug)}/retry`, { method: 'POST' }); } catch (err) { toast(err.message); }
  loadConsults();
};
$('#consultForm').onsubmit = async (e) => {
  e.preventDefault();
  const file = $('#csFile').files[0], msg = $('#csMsg'), btn = $('#csSubmit');
  msg.classList.remove('err');
  if (!file) { msg.classList.add('err'); msg.textContent = '先选一个录音文件'; return; }
  if (!$('#csName').value.trim()) { msg.classList.add('err'); msg.textContent = '写一下客户是谁，会用作笔记的名字'; return; }
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
    msg.textContent = '传好了，正在转文字。做完会自动在 Obsidian 里打开，这个窗口可以关掉。';
    $('#csFile').value = '';
    loadConsults();
  } catch (err) {
    msg.classList.add('err');
    msg.textContent = err.message;
  } finally {
    btn.disabled = false;
  }
};
