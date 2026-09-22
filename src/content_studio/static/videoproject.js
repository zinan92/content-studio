'use strict';
/* 视频 · 剪辑进度：关联口播 workflow（ask-park-video）项目目录，按产物读出 14 步进度 */
window.VIDEO_TABS = window.VIDEO_TABS || [];

const VP = { cache: {}, list: null, listAt: 0, media: {}, wt: false };

async function loadProjectList(force) {
  if (!force && VP.list && Date.now() - VP.listAt < 30000) return VP.list;
  VP.list = await api('/api/video-projects');
  VP.listAt = Date.now();
  return VP.list;
}

const fileUrl = (name, rel) => `/api/video-projects/${encodeURIComponent(name)}/file?path=${encodeURIComponent(rel)}`;


/* Step 3–4：成片 → 字幕 → 可以标 Hook 的工作台。以前这三步要开终端，
   标完还要把导出的 JSON 从下载文件夹拷回项目。 */
async function renderMedia(topic, box) {
  if (!box) return;
  let m;
  try { m = await api(`/api/topics/${topic.id}/video-project/media`); } catch (err) { box.innerHTML = ''; return; }
  const busy = (await api(`/api/topics/${topic.id}/video-project/transcribe`).catch(() => ({}))).running;
  VP.media[topic.id] = m;
  if (!m.video) {
    let ex = {};
    try { ex = await api(`/api/topics/${topic.id}/video-project/latest-export`); } catch (err) { /* 目录不在就当没有 */ }
    const e = ex.latest;
    const mmss = (n) => (n ? `${Math.floor(n / 60)} 分 ${String(Math.round(n % 60)).padStart(2, '0')} 秒` : '—');
    box.innerHTML = e
      // 名字全是日期，认不出内容，所以摆出时长和大小给他核对一眼。
      ? `<div class="vp-media"><span class="muted">剪映最新导出的是</span>
          <b>${esc(e.name)}</b><span class="num">${mmss(e.seconds)}</span><span class="num">${e.mb} MB</span>
          <small class="muted">${day(e.modified_at)}</small>${e.srt ? '<span class="pill hot">带字幕</span>' : ''}
          <button class="btn small primary" type="button" data-adopt="${esc(e.path)}">就是它，放进项目</button></div>`
      : `<div class="vp-media"><span class="muted">项目目录里还没有成片，${esc(ex.root || '剪映导出目录')} 里也没找到。把粗剪放进项目文件夹，回来刷新。</span></div>`;
    const b = $('[data-adopt]', box);
    if (b) b.onclick = async () => {
      b.disabled = true;
      try { toast((await api(`/api/topics/${topic.id}/video-project/adopt`, { method: 'POST', body: { path: b.dataset.adopt } })).message); renderMedia(topic, box); }
      catch (err) { toast(err.message); b.disabled = false; }
    };
    return;
  }
  const head = `<span class="pill mid">${esc(m.video.name)} · ${m.video.mb} MB</span>`;
  if (busy) {
    box.innerHTML = `<div class="vp-media">${head}<span><span class="spin"></span> 正在本机转写，15 分钟的片子大概 2–3 分钟</span></div>`;
    setTimeout(() => { if (S.view === 'work' && VD.tab === 'edit') renderMedia(topic, $('#vpMedia')); }, 15000);
    return;
  }
  if (!m.srt) {
    box.innerHTML = `<div class="vp-media">${head}<span class="muted">没找到字幕</span>
      <button class="btn small primary" type="button" id="vpTranscribe">用本机 whisper 跑一遍</button></div>`;
  } else if (!m.worktable) {
    box.innerHTML = `<div class="vp-media">${head}<span class="pill mid">${esc(m.srt.name)}</span>
      <button class="btn small primary" type="button" id="vpBuild">生成标 Hook 的工作台</button></div>`;
  } else {
    box.innerHTML = `<div class="vp-media">${head}<span class="pill mid">${esc(m.srt.name)}</span>
        ${m.exported ? '<span class="pill hot">已标完并存回项目</span>' : ''}
        <button class="btn small ${VP.wt ? '' : 'primary'}" type="button" id="vpToggleWt">${VP.wt ? '收起工作台' : '在这里标 Hook'}</button>
        <button class="btn small ghost" type="button" id="vpBuild" title="字幕改过之后重建">重建</button></div>
      ${VP.wt ? `<iframe class="vp-wt" src="/api/topics/${topic.id}/video-project/worktable.html" title="标 Hook 的工作台"></iframe>
        <p class="muted vp-wt-note">标完点表里的「保存到项目」，直接写回 analysis/worktable.json，不用再下载再拷回来。</p>` : ''}`;
  }
  const t = $('#vpTranscribe', box);
  if (t) t.onclick = async () => {
    if (!confirm(`项目里没有字幕。现在用本机 whisper 转写《${m.video.name}》？大概要 2–3 分钟，期间机器会比较忙。`)) return;
    t.disabled = true;
    try { toast((await api(`/api/topics/${topic.id}/video-project/transcribe`, { method: 'POST' })).message); renderMedia(topic, box); }
    catch (err) { toast(err.message); t.disabled = false; }
  };
  const b = $('#vpBuild', box);
  if (b) b.onclick = async () => {
    b.disabled = true;
    try { toast((await api(`/api/topics/${topic.id}/video-project/build-worktable`, { method: 'POST' })).message); renderMedia(topic, box); }
    catch (err) { toast(err.message); b.disabled = false; }
  };
  const tw = $('#vpToggleWt', box);
  if (tw) tw.onclick = () => { VP.wt = !VP.wt; renderMedia(topic, box); };
}

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
      <div id="vpMedia"></div>
      ${info.gate ? `<div class="banner warn vp-gate"><div><b>${esc(info.gate.key)} · ${esc(info.gate.title)}</b><br>${esc(info.gate.action)}
        ${info.gate.key === 'H1' && a['analysis/worktable.html'] && !a['analysis/worktable.json'] ? `<div class="vp-import"><a class="btn small primary" href="${fileUrl(info.name, 'analysis/worktable.html')}" target="_blank" rel="noopener">打开 worktable ↗</a><label class="btn small">选完了：选择导出的 worktable.json<input type="file" accept=".json,application/json" id="wtFile" hidden></label><button class="btn small ghost" type="button" id="wtPaste">粘贴 JSON 导入</button></div>` : ''}</div></div>` : ''}
      ${info.blocked_reason ? `<div class="banner warn"><div><b>卡住了：</b>${esc(info.blocked_reason)}</div></div>` : ''}
      ${info.layout !== 'v2.6' ? `<div class="banner warn"><div><b>还没按 14 步初始化</b><br>补一份 project.json，进度才算得出来，「开始跑」才能用。</div>
        <button class="btn small primary" type="button" id="vpInit">初始化</button></div>` : ''}
      <div id="vpRunner"></div>
      <div id="vpOpening"></div>
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
      ${info.log.length ? `<div class="vp-log"><h3>最近的过程记录</h3><ul>${info.log.map((l) => `<li><span class="pill ${['pass', 'approved'].includes(l.status) ? 'hot' : 'low'}">${esc(l.status || '—')}</span>${esc(l.title)}</li>`).join('')}</ul></div>` : ''}
      <div class="vp-cmd"><span>在 Claude 或 Codex 里继续：</span><button class="invoke" type="button" id="vpCmd">${esc(info.continue_command)}</button></div>
    </div>`;
    renderMedia(topic, $('#vpMedia', el));
    const init = $('#vpInit', el);
    if (init) init.onclick = async () => {
      init.disabled = true;
      try { toast((await api(`/api/topics/${topic.id}/video-project/init`, { method: 'POST' })).message); await refreshVideoTab(); }
      catch (err) { toast(err.message); init.disabled = false; }
    };
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
    renderRunner(topic, info);
    renderOpening(topic);
    $('#vpRefresh').onclick = async () => { delete VP.cache[topic.id]; $('#videoBody').dataset.sig = ''; renderView(); };
    $('#vpUnlink').onclick = async () => { try { await api(`/api/topics/${topic.id}/video-project`, { method: 'PUT', body: { name: null } }); toast('已取消关联'); await refreshVideoTab(); } catch (err) { toast(err.message); } };
    $('#vpCmd').onclick = () => navigator.clipboard.writeText(info.continue_command).then(() => toast('已复制，贴到 Claude 或 Codex'), () => toast(info.continue_command));
  },
});


const mins = (iso) => Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));

async function renderRunner(topic, info) {
  const box = $('#vpRunner');
  if (!box) return;
  let data;
  try { data = await api(`/api/topics/${topic.id}/video-project/run`); } catch (err) { box.innerHTML = ''; return; }
  const run = data.run;
  const running = run && run.state === 'running';
  let html = '';
  if (running) {
    html = `<div class="vp-run running"><div class="vp-run-h"><span class="spin"></span><b>Claude 正在后台跑口播 workflow</b><span class="muted">已跑 ${mins(run.started_at)} 分钟</span><span class="spacer"></span><button class="btn small ghost" type="button" id="runCancel">中止</button></div>
      <pre class="vp-log-tail">${esc(run.log_tail || '（还没有输出，长任务一般跑完才汇报）')}</pre></div>`;
    clearTimeout(VP.poll);
    VP.poll = setTimeout(() => { if (S.view === 'work' && VD.tab === 'edit' && VD.topicId === topic.id) { delete VP.cache[topic.id]; $('#videoBody').dataset.sig = ''; renderView(); } }, 8000);
  } else if (info.gate && info.layout === 'v2.6') {
    html = '<div class="vp-run" id="gateBox"><span class="spin"></span> 正在读取审批材料…</div>';
  } else if (info.layout === 'v2.6' && !info.delivered) {
    html = `<div class="vp-run"><div class="vp-run-h"><b>下一步：Step ${info.current_step}</b><span class="spacer"></span>
      ${data.busy_elsewhere ? '<span class="muted">另一个项目正在跑</span>' : '<button class="btn small primary" type="button" id="runStart">让 Claude 继续跑到下一个审批门</button>'}</div>
      <p class="muted">在这台 Mac 上后台执行 ask-park-video，跑到需要你拍板的地方、遇到阻塞或全部完成就停。可以随时中止。</p></div>`;
  }
  if (run && !running) {
    const label = { done: '上次运行结束', failed: '上次运行失败', cancelled: '上次运行已中止' }[run.state] || '上次运行';
    html += `<details class="vp-last"><summary>${label} · ${day(run.started_at)} · 退出码 ${run.exit_code === null ? '—' : run.exit_code}</summary><pre class="vp-log-tail">${esc(run.log_tail || '（没有输出）')}</pre></details>`;
  }
  box.innerHTML = html;
  const start = $('#runStart');
  if (start) start.onclick = async () => {
    if (!confirm('让 Claude 在后台继续跑这个口播项目？它会处理视频文件，停在下一个审批门。')) return;
    try { const r = await api(`/api/topics/${topic.id}/video-project/run`, { method: 'POST' }); toast(r.message); delete VP.cache[topic.id]; $('#videoBody').dataset.sig = ''; renderView(); } catch (err) { toast(err.message); }
  };
  const cancel = $('#runCancel');
  if (cancel) cancel.onclick = async () => {
    if (!confirm('中止后台运行？已经生成的产物会保留。')) return;
    try { await api(`/api/topics/${topic.id}/video-project/run`, { method: 'DELETE' }); toast('已中止'); delete VP.cache[topic.id]; $('#videoBody').dataset.sig = ''; renderView(); } catch (err) { toast(err.message); }
  };
  const gateBox = $('#gateBox');
  if (gateBox) renderGate(topic, info, gateBox);
}

async function renderGate(topic, info, el) {
  let data;
  try { data = await api(`/api/topics/${topic.id}/video-project/gate`); } catch (err) { el.innerHTML = `<span class="bad">${esc(err.message)}</span>`; return; }
  const r = data.review;
  const url = (rel) => fileUrl(info.name, rel);
  let body = '';
  if (r.gate === 'H1') {
    body = r.hooks.length ? `<ol class="gate-hooks">${r.hooks.map((h) => `<li>${esc(h.text || '')}${h.status && h.status !== 'ok' ? ` <span class="bad">（${esc(h.status)}，需要核对）</span>` : ''}</li>`).join('')}</ol><small class="muted">来自 ${esc(r.from)}</small>`
      : '<p class="muted">还没有 Hook。先在 worktable 里选好并导入。</p>';
  } else if (r.gate === 'H2') {
    body = `<p>视觉覆盖 ${r.coverage === null || r.coverage === undefined ? '—' : pct(r.coverage, 0)} · ${r.shots.length} 个镜头</p>
      <div class="tbl-wrap"><table class="gate-table"><thead><tr><th class="l">镜头</th><th>时间</th><th>类型</th><th class="l">目的</th><th>对你备注的处理</th></tr></thead><tbody>
      ${r.shots.map((s) => `<tr><td class="l">${esc(s.id || '')}</td><td>${s.start === undefined ? '—' : mmss(s.start)}–${s.end === undefined ? '—' : mmss(s.end)}</td><td>${esc(s.visual_type || '')}</td><td class="l">${esc(s.purpose || '')}</td><td>${esc(s.disposition || '—')}</td></tr>`).join('')}</tbody></table></div>`;
  } else if (r.gate === 'H3') {
    body = `<video class="vp-video" controls preload="metadata" src="${url('final/video.mp4')}"></video><p class="muted">QA Final：${esc(JSON.stringify(r.qa || {}).slice(0, 200))}</p>`;
  }
  const canApprove = r.gate !== 'H1' || r.hooks.length;
  el.className = 'vp-run gate';
  el.innerHTML = `<div class="vp-run-h"><b>${esc(data.gate.key)} · ${esc(data.gate.title)}</b></div>${body}
    ${canApprove ? `<textarea id="gateNote" rows="2" placeholder="备注（可选），比如「第 2 句放到最后」"></textarea>
    <div class="acts"><button class="btn primary" type="button" id="gateApprove">批准 ${esc(data.gate.key)}</button><span class="muted">批准后可以让 Claude 继续跑</span></div>` : ''}`;
  const approveBtn = $('#gateApprove');
  if (approveBtn) approveBtn.onclick = async () => {
    if (!confirm(`确认批准 ${data.gate.key}？会写进项目的 project.json 和过程日志。`)) return;
    try {
      await api(`/api/topics/${topic.id}/video-project/approve`, { method: 'POST', body: { gate: data.gate.key, note: $('#gateNote').value || null } });
      toast(`已批准 ${data.gate.key}`);
      delete VP.cache[topic.id]; $('#videoBody').dataset.sig = ''; renderView();
    } catch (err) { toast(err.message); }
  };
}

/* 开头 15 秒：主线有没有在前 15 秒说出来（读项目里已有的字幕） */
async function renderOpening(topic) {
  const el = $('#vpOpening');
  if (!el) return;
  let d;
  try { d = await api(`/api/topics/${topic.id}/opening`); } catch (err) { el.innerHTML = ''; return; }
  if (!d.subtitles && !d.result) { el.innerHTML = '<div class="op op-idle"><b>开头 15 秒</b><span>录完把粗剪和字幕放进项目文件夹，这里会检查主线有没有在前 15 秒说出来。</span></div>'; return; }
  const r = d.result;
  const btn = `<button class="btn small ${r ? '' : 'primary'}" type="button" id="opRun" ${d.state === 'running' ? 'disabled' : ''}>${d.state === 'running' ? '检查中…' : r ? '重新检查' : '检查开头 15 秒'}</button>`;
  if (d.state === 'running') setTimeout(() => { if (S.view === 'work') renderOpening(topic); }, 4000);
  el.innerHTML = `<div class="op ${r ? (r.passed ? 'op-pass' : 'op-fail') : ''}">
    <div class="op-h"><b>开头 15 秒</b>${r ? `<span class="pill ${r.passed ? 'hot' : 'low'}">${r.passed ? `过了 · ${r.stated_at.toFixed(1)} 秒说出主线` : r.stated_at === null ? '没过 · 前 60 秒没说出主线' : `没过 · 第 ${r.stated_at.toFixed(1)} 秒才说出主线`}</span>` : ''}<span class="spacer"></span>${btn}</div>
    ${d.state === 'failed' ? `<p class="bad">${esc(d.error || '检查失败')}</p>` : ''}
    ${r ? `<p class="op-line"><span>主线</span>${esc(r.thesis)}</p>
      <p class="op-line"><span>前 15 秒</span>${esc(r.first_15s)}</p>
      ${r.quote ? `<p class="op-line"><span>主线出现</span>「${esc(r.quote)}」</p>` : ''}
      ${r.before ? `<p class="op-line"><span>之前在讲</span>${esc(r.before)}</p>` : ''}
      <ol class="op-fixes">${r.fixes.map((f) => `<li>${esc(f)}</li>`).join('')}</ol>
      <small class="muted">依据：${esc(r.source_label)}字幕 ${esc(r.source)} · ${day(r.generated_at)}</small>` : `<p class="muted">会读${esc(d.subtitles.label)}字幕（${esc(d.subtitles.path)}）的前 60 秒。</p>`}
  </div>`;
  $('#opRun').onclick = async () => {
    try { const res = await api(`/api/topics/${topic.id}/opening`, { method: 'POST' }); toast(res.message); renderOpening(topic); } catch (err) { toast(err.message); }
  };
}
