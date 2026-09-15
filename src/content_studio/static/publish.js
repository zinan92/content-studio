'use strict';
/* 视频 · 发布：标题和简介 → 一键发布 → 关联抖音视频看数据，满 48 小时拆解 */
window.VIDEO_TABS = window.VIDEO_TABS || [];

function sparkSeries(series) {
  const pts = series.filter((s) => s.likes !== null && s.likes !== undefined);
  if (pts.length < 2) return '<div class="muted">同步两次以上才画得出变化曲线</div>';
  const W = 520, H = 120, m = { l: 44, r: 10, t: 10, b: 22 };
  const maxH = Math.max(...pts.map((p) => p.hours), 1), maxL = Math.max(...pts.map((p) => p.likes), 1);
  const x = (h) => m.l + (h / maxH) * (W - m.l - m.r);
  const y = (l) => m.t + (1 - l / maxL) * (H - m.t - m.b);
  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${x(p.hours).toFixed(1)},${y(p.likes).toFixed(1)}`).join(' ');
  const last = pts[pts.length - 1];
  return `<svg viewBox="0 0 ${W} ${H}" class="perf-chart" role="img" aria-label="点赞随时间变化">
    <line class="gridl" x1="${m.l}" x2="${W - m.r}" y1="${y(maxL)}" y2="${y(maxL)}"/><line class="gridl" x1="${m.l}" x2="${W - m.r}" y1="${y(0)}" y2="${y(0)}"/>
    <g class="axis"><text x="${m.l - 6}" y="${y(maxL) + 4}" text-anchor="end">${fmt(maxL)}</text><text x="${m.l - 6}" y="${y(0) + 4}" text-anchor="end">0</text>
    <text x="${m.l}" y="${H - 6}">发出</text><text x="${W - m.r}" y="${H - 6}" text-anchor="end">${Math.round(maxH)} 小时</text></g>
    <path d="${line}" fill="none" stroke="var(--accent)" stroke-width="2"/>
    <circle cx="${x(last.hours)}" cy="${y(last.likes)}" r="4" fill="var(--accent)"/>
  </svg>`;
}

window.VIDEO_TABS.push({
  key: 'publish',
  label: '发布',
  badge: (t) => (t.published_video_id ? '已发出' : ''),
  async render(topic, el) {
    let d;
    try { d = await api(`/api/topics/${topic.id}/publish`); } catch (err) { el.innerHTML = `<div class="empty"><b>${esc(err.message)}</b></div>`; return; }
    const publishSlot = '<div id="copyBox"></div><div id="publishNow"></div>';
    if (!d.account) {
      el.innerHTML = `<div class="pub">${publishSlot}<div class="empty"><b>还没有连接自己的抖音号</b><span>去「我的视频」连接后，这里才能关联发出的抖音视频、看数据。</span></div></div>`;
      if (window.renderCopyBox) window.renderCopyBox(topic, $('#copyBox'));
    if (window.renderPublishPanel) window.renderPublishPanel(topic, $('#publishNow'));
      return;
    }
    const syncLine = `<div class="pub-sync"><span>${esc(d.account.nickname || '')} · ${d.account.syncing ? '<span class="spin"></span> 同步中' : esc(ago(d.account.last_synced_at))}</span>${d.stale_sync && !d.account.syncing ? '<span class="bad">数据可能不是最新的</span>' : ''}<button class="btn small" type="button" id="pubSync">同步我的数据</button></div>`;
    if (!d.video) {
      el.innerHTML = `<div class="pub">${publishSlot}${syncLine}
        ${d.suggestions.length ? `<div class="pub-block"><h3>可能是这条</h3>${d.suggestions.map((v) => `<div class="hot-row"><span class="pill mid">${Math.round(v.score * 100)}%</span><div class="hot-main"><b class="clamp">${esc(cleanTitle(v.title))}</b><small>${day(v.published_at)} · ${fmt(v.likes)} 赞</small></div><div class="acts"><button class="btn small primary" type="button" data-pub="${esc(v.video_id)}">就是这条</button></div></div>`).join('')}</div>` : '<div class="empty"><span>还没找到标题相近、在选题之后发出的视频。发出后点「同步我的数据」，或从下面手动选。</span></div>'}
        <div class="pub-block"><h3>手动选择</h3><div class="linkbox"><select id="pubPick">${d.recent.map((v) => `<option value="${esc(v.video_id)}">${day(v.published_at)} · ${esc(cleanTitle(v.title).slice(0, 40))}</option>`).join('')}</select><button class="btn" type="button" id="pubLink">关联</button></div></div>
      </div>`;
      $$('[data-pub]', el).forEach((b) => (b.onclick = () => linkVideo(topic.id, b.dataset.pub)));
      const pick = $('#pubLink');
      if (pick) pick.onclick = () => linkVideo(topic.id, $('#pubPick').value);
    } else {
      const v = d.video;
      const c = v.creator;
      el.innerHTML = `<div class="pub">${publishSlot}${syncLine}
        <div class="pub-title"><a href="${esc(v.url)}" target="_blank" rel="noopener">${esc(cleanTitle(v.title))} ↗</a><small>发出 ${v.hours_since === null ? '—' : v.hours_since < 48 ? `${Math.round(v.hours_since)} 小时` : `${Math.round(v.hours_since / 24)} 天`}</small></div>
        <div class="facts pub-facts">
          <div><div class="l">账号中位数倍数</div><div class="v ${v.multiple >= S.state.settings.threshold ? 'hot' : ''}">${v.multiple === null ? '—' : v.multiple + '×'}</div></div>
          <div><div class="l">点赞</div><div class="v">${fmt(v.likes)}</div></div>
          <div><div class="l">播放</div><div class="v">${fmt(v.views)}</div></div>
          <div><div class="l">收藏/赞</div><div class="v">${pct(v.collect_per_like)}</div></div>
          ${c ? `<div><div class="l">涨粉</div><div class="v">${fmt(c.fan_increment)}</div></div><div><div class="l">平均观看</div><div class="v">${c.avg_view_second === null ? '—' : Math.round(c.avg_view_second) + ' 秒'}</div></div><div><div class="l">2 秒跳出</div><div class="v">${pct(c.bounce_rate_2s)}</div></div>` : ''}
        </div>
        <div class="pub-block"><h3>点赞变化</h3>${sparkSeries(v.series)}
          <div class="milestones">${v.milestones.map((ms) => `<div class="${ms.reached ? '' : 'muted'}"><span>${ms.label}</span><b>${ms.reached ? (ms.likes === null ? '没有这个时间点的同步' : fmt(ms.likes) + ' 赞') : '还没到'}</b></div>`).join('')}</div>
        </div>
        <div class="pub-actions">
          ${v.has_report ? `<button class="btn primary" type="button" data-report="${esc(v.video_id)}">看拆解报告</button>`
            : v.job && v.job.stage !== 'failed' ? `<span class="stage-pill running">${STAGE_NAME[v.job.stage] || v.job.stage}</span>`
              : `<button class="btn ${v.suggest_teardown ? 'primary' : ''}" type="button" data-enqueue="${esc(v.video_id)}" data-source="复盘 · ${esc(topic.title.slice(0, 20))}">${v.suggest_teardown ? '满 48 小时了，拆解这条' : '拆解这条'}</button>`}
          <button class="btn ghost" type="button" id="pubUnlink">取消关联</button>
        </div>
      </div>`;
      bindTeardownButtons(el);
      $('#pubUnlink').onclick = () => linkVideo(topic.id, null);
    }
    if (window.renderCopyBox) window.renderCopyBox(topic, $('#copyBox'));
    if (window.renderPublishPanel) window.renderPublishPanel(topic, $('#publishNow'));
    $('#pubSync').onclick = async () => {
      try { const r = await api('/api/sync', { method: 'POST' }); toast(r.message); } catch (err) { toast(err.message); }
    };
  },
});

async function linkVideo(topicId, videoId) {
  try {
    await api(`/api/topics/${topicId}/publish`, { method: 'PUT', body: { video_id: videoId } });
    toast(videoId ? '已关联，选题标为已发出' : '已取消关联');
    if (window.refreshTopics) await window.refreshTopics();
    const body = $('#videoBody');
    if (body) body.dataset.sig = '';
    renderView();
  } catch (err) { toast(err.message); }
}
