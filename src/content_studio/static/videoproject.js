'use strict';
/* 视频 · 剪辑进度：关联口播 workflow（ask-park-video）项目目录，按产物读出 14 步进度 */
window.VIDEO_TABS = window.VIDEO_TABS || [];

const VP = { cache: {}, list: null, listAt: 0 };

async function loadProjectList(force) {
  if (!force && VP.list && Date.now() - VP.listAt < 30000) return VP.list;
  VP.list = await api('/api/video-projects');
  VP.listAt = Date.now();
  return VP.list;
}

const fileUrl = (name, rel) => `/api/video-projects/${encodeURIComponent(name)}/file?path=${encodeURIComponent(rel)}`;

async function refreshVideoTab() {
  VP.cache = {};
  VP.list = null;
  if (window.refreshTopics) await window.refreshTopics();
  const body = $('#videoBody');
  if (body) body.dataset.sig = '';
  renderView();
}

window.VIDEO_TABS.push({
  key: 'edit',
  label: '剪辑进度',
  badge: (t) => (t.video_project ? '已关联' : ''),
  async render(topic, el) {
    if (!topic.video_project) {
      let list;
      try { list = await loadProjectList(false); } catch (err) { el.innerHTML = `<div class="empty"><b>${esc(err.message)}</b></div>`; return; }
      if (list.error) {
        el.innerHTML = `<div class="empty"><b>${esc(list.error)}</b><span>视频项目放在外接硬盘上时，接上硬盘后刷新；也可以在设置里改成别的目录。</span><button class="btn" type="button" onclick="go('settings')">去设置</button></div>`;
        return;
      }
      const free = list.projects.filter((p) => !p.topic_id);
      el.innerHTML = `<div class="vp-start">
        <div class="vp-option"><h3>新建项目文件夹</h3><p>在 <code>${esc(list.root)}</code> 下建一个文件夹${topic.outline_path ? '，并放一份拍摄提纲' : ''}。录完把剪映粗剪视频和 SRT 放进去，然后在 Claude/Codex 里用口播 workflow 开始。</p><button class="btn primary" type="button" id="vpCreate">新建并关联</button></div>
        <div class="vp-option"><h3>关联已有项目</h3>${free.length ? `<select id="vpPick">${free.map((p) => `<option value="${esc(p.name)}">${esc(p.name)} · ${esc(p.summary)}</option>`).join('')}</select><button class="btn" type="button" id="vpLink">关联</button>` : '<p class="muted">没有未关联的项目</p>'}</div>
      </div>`;
      $('#vpCreate').onclick = async () => {
        try { const info = await api(`/api/topics/${topic.id}/video-project`, { method: 'POST' }); toast(`已新建 ${info.name}`); await refreshVideoTab(); } catch (err) { toast(err.message); }
      };
      const link = $('#vpLink');
      if (link) link.onclick = async () => {
        try { await api(`/api/topics/${topic.id}/video-project`, { method: 'PUT', body: { name: $('#vpPick').value } }); toast('已关联'); await refreshVideoTab(); } catch (err) { toast(err.message); }
      };
      return;
    }
    let info = VP.cache[topic.id];
    if (!info || Date.now() - info._at > 20000) {
      try { info = { ...(await api(`/api/topics/${topic.id}/video-project`)), _at: Date.now() }; VP.cache[topic.id] = info; } catch (err) {
        el.innerHTML = `<div class="empty"><b>${esc(err.message)}</b><button class="btn small ghost" type="button" id="vpUnlink">取消关联</button></div>`;
        $('#vpUnlink').onclick = async () => { await api(`/api/topics/${topic.id}/video-project`, { method: 'PUT', body: { name: null } }); await refreshVideoTab(); };
        return;
      }
    }
    const a = info.artifacts;
    const finalVideo = info.final_video;
    el.innerHTML = `<div class="vp">
      <div class="vp-head"><div><b>${esc(info.name)}</b><small>${esc(info.path)} · 更新于 ${esc(info.modified_at.replace('T', ' '))}</small></div>
        <div class="acts"><button class="btn small" type="button" id="vpRefresh">刷新</button><button class="btn small ghost" type="button" id="vpUnlink">取消关联</button></div></div>
      ${info.gate ? `<div class="banner warn vp-gate"><div><b>${esc(info.gate.key)} · ${esc(info.gate.title)}</b><br>${esc(info.gate.action)}
        ${info.gate.key === 'H1' && a['analysis/worktable.html'] && !a['analysis/worktable.json'] ? `<div class="vp-import"><a class="btn small primary" href="${fileUrl(info.name, 'analysis/worktable.html')}" target="_blank" rel="noopener">打开 worktable ↗</a><label class="btn small">选完了：选择导出的 worktable.json<input type="file" accept=".json,application/json" id="wtFile" hidden></label><button class="btn small ghost" type="button" id="wtPaste">粘贴 JSON 导入</button></div>` : ''}</div></div>` : ''}
      ${info.blocked_reason ? `<div class="banner warn"><div><b>卡住了：</b>${esc(info.blocked_reason)}</div></div>` : ''}
      <div class="vp-summary"><span class="pill ${info.delivered ? 'hot' : 'mid'}">${esc(info.summary)}</span>${info.layout !== 'v2.6' ? '<span class="muted">（按旧版目录识别）</span>' : ''}</div>
      ${info.stages.length ? `<div class="vp-stages">${info.stages.map((s) => `<div class="vp-stage ${s.state}"><b>${s.key} ${esc(s.label)}</b><span>${s.passed}/${s.total}</span></div>`).join('')}</div>
        <details class="vp-steps"><summary>14 步明细</summary><ol>${info.steps.map((s) => `<li class="${s.done ? 'done' : s.step === info.current_step ? 'now' : ''}"><b>Step ${s.step} ${esc(s.name)}</b><span>${esc(s.evidence)}</span></li>`).join('')}</ol></details>` : ''}
      <div class="vp-artifacts">
        ${a['analysis/worktable.html'] ? `<a class="btn" href="${fileUrl(info.name, 'analysis/worktable.html')}" target="_blank" rel="noopener">打开 worktable ↗</a>` : ''}
        ${a['part-a-hook/video.mp4'] ? `<a class="btn" href="${fileUrl(info.name, 'part-a-hook/video.mp4')}" target="_blank" rel="noopener">成品 A（Hook）↗</a>` : ''}
        ${a['part-b-body/video.mp4'] ? `<a class="btn" href="${fileUrl(info.name, 'part-b-body/video.mp4')}" target="_blank" rel="noopener">成品 B（正文）↗</a>` : ''}
        ${a['process-log.md'] ? `<a class="btn" href="${fileUrl(info.name, 'process-log.md')}" target="_blank" rel="noopener">过程日志 ↗</a>` : ''}
      </div>
      ${finalVideo ? `<video class="vp-video" controls preload="metadata" src="${fileUrl(info.name, finalVideo)}"></video>` : ''}
      ${info.log.length ? `<div class="vp-log"><h3>最近的过程记录</h3><ul>${info.log.map((l) => `<li><span class="pill ${l.status === 'pass' ? 'hot' : 'low'}">${esc(l.status || '—')}</span>${esc(l.title)}</li>`).join('')}</ul></div>` : ''}
      <div class="vp-cmd"><span>在 Claude 或 Codex 里继续：</span><button class="invoke" type="button" id="vpCmd">${esc(info.continue_command)}</button></div>
    </div>`;
    const importWorktable = async (body) => {
      try {
        const r = await api(`/api/topics/${topic.id}/video-project/worktable`, { method: 'POST', body });
        toast(`已导入 ${r.hooks} 个 Hook、${r.visual_notes} 条画面备注${r.needs_review ? `，${r.needs_review} 条需要核对位置` : ''}`);
        delete VP.cache[topic.id]; $('#videoBody').dataset.sig = ''; renderView();
      } catch (err) { toast(err.message); }
    };
    const wtf = $('#wtFile');
    if (wtf) wtf.onchange = async () => {
      const file = wtf.files && wtf.files[0];
      if (file) importWorktable({ text: await file.text(), filename: file.name });
    };
    const wtp = $('#wtPaste');
    if (wtp) wtp.onclick = () => {
      const text = prompt('在 worktable 里点「复制 JSON」，粘贴到这里');
      if (text && text.trim()) importWorktable({ text });
    };
    $('#vpRefresh').onclick = async () => { delete VP.cache[topic.id]; $('#videoBody').dataset.sig = ''; renderView(); };
    $('#vpUnlink').onclick = async () => { try { await api(`/api/topics/${topic.id}/video-project`, { method: 'PUT', body: { name: null } }); toast('已取消关联'); await refreshVideoTab(); } catch (err) { toast(err.message); } };
    $('#vpCmd').onclick = () => navigator.clipboard.writeText(info.continue_command).then(() => toast('已复制，贴到 Claude 或 Codex'), () => toast(info.continue_command));
  },
});
