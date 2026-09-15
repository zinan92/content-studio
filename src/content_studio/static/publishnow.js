'use strict';
/* 视频 · 发出与数据 · 一键发布：准备 → Park 确认 → 发布 */
window.VIDEO_TABS = window.VIDEO_TABS || [];

const PJ_STATE = { awaiting_confirm: '等你确认', running: '发布中', done: '已完成', failed: '失败', cancelled: '已取消', unknown: '结果不确定' };

async function renderPublishPanel(topic, el) {
  let d;
  try { d = await api(`/api/topics/${topic.id}/publish-jobs`); } catch (err) { el.innerHTML = `<div class="bad">${esc(err.message)}</div>`; return; }
  const pending = d.jobs.find((j) => j.state === 'awaiting_confirm');
  const running = d.jobs.find((j) => j.state === 'running');
  let html = '<div class="pn"><h3>一键发布</h3>';
  if (!d.video) {
    html += '<p class="muted">还没有成片：在「剪辑进度」关联视频项目并完成剪辑后，这里可以直接发到视频号、B 站、YouTube。</p>';
  } else if (!d.has_copy) {
    html += '<p class="muted">先在「文案与平台」生成各平台文案，发布会用那里的标题、正文和话题。</p>';
  } else {
    html += `<p class="muted">成片：${esc(d.video.path.split('/').slice(-3).join('/'))}（${d.video.mb} MB）。每次发布都要你看过下面的摘要并点「确认发布」。</p>`;
    if (pending) {
      const p = pending.payload;
      html += `<div class="pn-confirm"><b>确认发布到${esc(p.platform_label)}：${esc(p.mode_label)}</b>
        <dl><dt>标题</dt><dd>${esc(p.title)}</dd><dt>正文</dt><dd>${esc(p.body || '（空）')}</dd><dt>话题</dt><dd>${esc(p.tags.map((t) => '#' + t).join(' ') || '（无）')}</dd><dt>视频</dt><dd>${esc(p.video.split('/').pop())} · ${p.video_mb} MB</dd></dl>
        ${d.platforms[p.platform] && d.platforms[p.platform].likely_expired ? `<p class="bad">${esc(d.platforms[p.platform].note)}：发布大概率会失败，需要先在电脑上运行 <code>${esc(d.platforms[p.platform].login_hint)}</code></p>` : ''}
        <div class="acts"><button class="btn primary" type="button" data-pj-confirm="${pending.id}">确认发布</button><button class="btn ghost" type="button" data-pj-cancel="${pending.id}">取消</button></div></div>`;
    } else if (running) {
      html += `<div class="pn-confirm running"><span class="spin"></span> 正在发布到${esc(running.payload.platform_label)}（${esc(running.payload.mode_label)}），视频大的话要十几分钟。</div>`;
    } else {
      html += `<div class="pn-platforms">${Object.entries(d.platforms).map(([key, p]) => `<div class="pn-platform"><div><b>${esc(p.label)}</b><small class="${p.likely_expired ? 'bad' : 'muted'}">${esc(p.note)}</small></div>
        <div class="acts">${Object.entries(p.modes).map(([mode, label]) => `<button class="btn small" type="button" data-pj-prepare="${key}" data-mode="${mode}">${esc(label)}</button>`).join('')}</div></div>`).join('')}</div>`;
    }
  }
  const history = d.jobs.filter((j) => j.state !== 'awaiting_confirm').slice(0, 5);
  if (history.length) {
    html += `<ul class="pn-history">${history.map((j) => `<li><span class="pill ${j.state === 'done' ? 'hot' : j.state === 'failed' || j.state === 'unknown' ? 'low' : 'mid'}">${PJ_STATE[j.state] || j.state}</span>${esc(j.payload.platform_label)} · ${esc(j.payload.mode_label)} · ${day(j.created_at)}${j.message ? ` <span class="bad">${esc(j.message)}</span>` : ''}</li>`).join('')}</ul>`;
  }
  el.innerHTML = html + '</div>';
  const refresh = () => { const body = $('#videoBody'); if (body) body.dataset.sig = ''; renderView(); };
  $$('[data-pj-prepare]', el).forEach((b) => (b.onclick = async () => {
    try { await api(`/api/topics/${topic.id}/publish-jobs`, { method: 'POST', body: { platform: b.dataset.pjPrepare, mode: b.dataset.mode } }); refresh(); } catch (err) { toast(err.message); }
  }));
  $$('[data-pj-confirm]', el).forEach((b) => (b.onclick = async () => {
    if (!confirm('确认发布？这会把视频和文案提交到平台。')) return;
    b.disabled = true;
    try { const r = await api(`/api/publish-jobs/${b.dataset.pjConfirm}/confirm`, { method: 'POST' }); toast(r.message); refresh(); } catch (err) { toast(err.message); b.disabled = false; }
  }));
  $$('[data-pj-cancel]', el).forEach((b) => (b.onclick = async () => {
    try { await api(`/api/publish-jobs/${b.dataset.pjCancel}`, { method: 'DELETE' }); toast('已取消'); refresh(); } catch (err) { toast(err.message); }
  }));
  if (running) setTimeout(() => { if (S.view === 'work' && VD.tab === 'publish') refresh(); }, 8000);
}
window.renderPublishPanel = renderPublishPanel;
