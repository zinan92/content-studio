'use strict';

/* 咨询录音：上传一场 1v1 的录音 → 本机转文字 + 分析 → vault 010_咨询/ 一篇左右对照的笔记 */
const CS = { timer: null };
const CS_STAGE = { queued: '排队中', transcribing: '转文字中', analyzing: '分析中', client: '写客户版', done: '已完成', failed: '失败', interrupted: '中断了' };

function consultToday() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function openConsult() {
  $('#csFile').value = '';
  $('#csName').value = '';
  $('#csDay').value = consultToday();
  $('#csMsg').classList.remove('err');
  $('#csMsg').textContent = '录音、录像都行（m4a、mp3、mp4、mov…）。45 分钟大约 10–15 分钟出两份：给你的、给客户的。';
  $('#consultDlg').showModal();
  loadConsults();
}

async function loadConsults() {
  clearTimeout(CS.timer);
  let rows = [];
  try { rows = (await api('/api/consults')).consults; } catch (err) { $('#csList').innerHTML = `<p class="cs-err">${esc(err.message)}</p>`; return; }
  $('#csList').innerHTML = rows.length ? rows.map((r) => {
    const done = r.stage === 'done' && r.obsidian;
    const act = done
      ? `<span class="cs-acts"><a class="btn small" href="${esc(r.obsidian)}" title="总结 + 转写和逐段分析">我的版本</a>`
        + (r.client ? `<a class="btn small primary" href="${esc(r.client)}" target="_blank" rel="noopener" title="纪要 + takeaway，不带转写">客户版</a>`
          + `<button class="btn small" type="button" data-cs-reveal="${esc(r.slug)}" data-what="client" title="在 Finder 里找到客户版 HTML，拖进微信发给客户">发给客户</button>` : '')
        + `<button class="btn small" type="button" data-cs-reveal="${esc(r.slug)}" data-what="folder" title="本机留的原件和转写文字">原件</button></span>`
      : (r.stage === 'failed' || r.stage === 'interrupted') ? `<button class="btn small" type="button" data-cs-retry="${esc(r.slug)}">重试</button>` : '';
    const note = r.error ? `<small class="cs-err">${esc(r.error)}</small>` : r.minutes ? `<small>${r.minutes} 分钟</small>` : '';
    return `<div class="cs-row"><div><b>${esc(r.slug)}</b>${note}</div><span class="cs-stage cs-${esc(r.stage)}">${esc(CS_STAGE[r.stage] || r.stage)}</span>${act}</div>`;
  }).join('') : '<p class="cs-empty">还没有上传过。</p>';
  if (rows.some((r) => r.running) && $('#consultDlg').open) CS.timer = setTimeout(loadConsults, 5000);
}

$('#consultBtn').onclick = openConsult;
$('#csCancel').onclick = () => { clearTimeout(CS.timer); $('#consultDlg').close(); };
$('#csList').onclick = async (e) => {
  const reveal = e.target.dataset && e.target.dataset.csReveal;
  if (reveal) {
    try { await api(`/api/consults/${encodeURIComponent(reveal)}/reveal?what=${e.target.dataset.what}`, { method: 'POST' }); toast(e.target.dataset.what === 'client' ? '已在 Finder 里选中客户版，拖进微信就能发' : '已在 Finder 里打开'); } catch (err) { toast(err.message); }
    return;
  }
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
