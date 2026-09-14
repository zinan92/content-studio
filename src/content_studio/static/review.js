'use strict';
/* 复盘 · 每周复盘 */
window.VIEWS = window.VIEWS || {};

const RV = { record: null, at: 0 };

async function loadReview(force) {
  if (!force && RV.record && Date.now() - RV.at < (RV.record.state === 'running' ? 4000 : 60000)) return RV.record;
  RV.record = await api('/api/review');
  RV.at = Date.now();
  if (RV.record.state === 'running') setTimeout(async () => { await loadReview(true); if (S.view === 'weekly') renderView(); }, 5000);
  return RV.record;
}

function reviewItems(items, cls) {
  return items.map((item) => `<li class="${cls}"><span>${esc(item.text)}</span><div class="rv-videos">${item.videos.map((v) => `<button type="button" class="linklike" data-rv-video="${esc(v.video_id)}">${esc(cleanTitle(v.title).slice(0, 24))}</button>`).join('')}</div></li>`).join('');
}

window.VIEWS.weekly = {
  async render() {
    const body = $('#weeklyBody');
    let r;
    try { r = await loadReview(false); } catch (err) { body.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`; return; }
    const sig = JSON.stringify([r.state, r.updated_at]);
    if (body.dataset.sig === sig) return;
    body.dataset.sig = sig;
    const gen = `<button class="btn ${r.data ? '' : 'primary'}" type="button" id="rvGen">${r.data ? '重新复盘' : '复盘这一周'}</button>`;
    if (r.state === 'running') { body.innerHTML = '<div class="panel empty"><span class="spin"></span><b>正在复盘这一周</b><span>一般 1–3 分钟。</span></div>'; return; }
    if (!r.data) {
      body.innerHTML = `<div class="panel empty"><b>${r.state === 'failed' ? esc(r.error || '生成失败') : '这周还没复盘'}</b><span>用这 7 天你发的视频数据、拆解报告和对标爆款，总结做对了什么、问题在哪、下周调整什么。先同步一下我的数据，结果更准。</span>${gen}</div>`;
    } else {
      const d = r.data;
      body.innerHTML = `<div class="panel">
        <div class="panel-h"><h2>${esc(d.since)} – ${esc(d.until)}</h2><small>生成于 ${day(d.generated_at)} · ${gen}</small></div>
        ${r.state === 'failed' ? `<div class="banner warn" style="margin:12px 18px 0"><div>重新复盘失败：${esc(r.error)}（下面是上一版）</div></div>` : ''}
        <p class="rv-summary">${esc(d.summary)}</p>
        <div class="rv-grid">
          <div><h3>做对了</h3><ul class="rv-list">${reviewItems(d.wins, 'win') || '<li class="muted">这周没有</li>'}</ul></div>
          <div><h3>问题</h3><ul class="rv-list">${reviewItems(d.problems, 'problem') || '<li class="muted">这周没有</li>'}</ul></div>
        </div>
        ${d.patterns.length ? `<div class="rv-block"><h3>规律</h3><ul>${d.patterns.map((p) => `<li>${esc(p)}</li>`).join('')}</ul></div>` : ''}
        <div class="rv-block"><h3>下周调整</h3><ol>${d.next_week.map((p) => `<li>${esc(p)}</li>`).join('')}</ol></div>
        <div class="rv-block rv-exp"><h3>下周小实验</h3><p><b>假设：</b>${esc(d.experiment.hypothesis)}</p><p><b>怎么做：</b>${esc(d.experiment.how)}</p><p><b>看什么：</b>${esc(d.experiment.measure)}</p></div>
        <div class="tbl-wrap"><table class="rv-table"><thead><tr><th class="l">这周的视频</th><th>点赞</th><th>倍数</th><th>收藏/赞</th><th>涨粉</th><th>均看</th><th>2s 跳出</th><th>报告</th></tr></thead>
          <tbody>${d.videos.map((v) => `<tr><td class="l"><span class="clamp">${esc(cleanTitle(v.title))}</span></td><td>${fmt(v.likes)}</td><td>${v.multiple === null ? '—' : v.multiple + '×'}</td><td>${pct(v.collect_per_like)}</td><td>${fmt(v.fans)}</td><td>${v.avg_watch_seconds === null ? '—' : v.avg_watch_seconds + '秒'}</td><td>${pct(v.bounce_2s)}</td><td>${v.report ? `<button class="btn small" type="button" data-report="${esc(v.video_id)}">看</button>` : '—'}</td></tr>`).join('')}</tbody></table></div>
      </div>`;
    }
    $('#rvGen').onclick = async () => {
      try { const res = await api('/api/review/generate', { method: 'POST' }); toast(res.message); await loadReview(true); body.dataset.sig = ''; renderView(); } catch (err) { toast(err.message); }
    };
    $$('[data-report]', body).forEach((b) => (b.onclick = () => openReport(b.dataset.report)));
    $$('[data-rv-video]', body).forEach((b) => (b.onclick = () => openReport(b.dataset.rvVideo)));
  },
};
