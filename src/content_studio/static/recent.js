'use strict';
/* 今天 · 我最近发的视频：近 7 天作品的数据，满 48 小时提示拆解 */
window.TODAY_CARDS = window.TODAY_CARDS || [];

window.TODAY_CARDS.push({
  id: 'recent-videos',
  order: 35,
  title: '我最近发的视频',
  render(el) {
    const m = S.mine;
    if (!m || !m.account) { el.innerHTML = ''; el.hidden = true; return; }
    el.hidden = false;
    const now = Date.now();
    const recent = m.videos.filter((v) => !v.is_image_post && v.published_at && now - new Date(v.published_at).getTime() < 7 * 86400000);
    const sig = JSON.stringify([m.account.last_synced_at, recent.map((v) => [v.video_id, v.likes, v.has_report, v.job && v.job.stage])]);
    if (el.dataset.sig === sig) return;
    el.dataset.sig = sig;
    const rows = recent.map((v) => {
      const hours = (now - new Date(v.published_at).getTime()) / 3600000;
      const multiple = m.median_likes && v.likes !== null ? v.likes / m.median_likes : null;
      const due = hours >= 48 && !v.has_report && !(v.job && v.job.stage !== 'failed');
      return `<div class="hot-row">
        <span class="pill ${multiple >= 3 ? 'hot' : multiple >= 1 ? 'mid' : 'low'}">${multiple === null ? '—' : multiple.toFixed(1) + '×'}</span>
        <div class="hot-main"><b class="clamp">${esc(cleanTitle(v.title))}</b><small>${hours < 48 ? Math.round(hours) + ' 小时前' : Math.round(hours / 24) + ' 天前'} · ${fmt(v.likes)} 赞${v.creator && v.creator.avg_view_second ? ` · 均看 ${Math.round(v.creator.avg_view_second)} 秒` : ''}</small></div>
        <div class="acts">${due ? `<button class="btn small primary" type="button" data-enqueue="${esc(v.video_id)}" data-source="复盘 · 我的视频">满 48 小时，拆解</button>` : teardownButton(v, { source: '复盘 · 我的视频' })}</div>
      </div>`;
    }).join('');
    const stale = !m.account.last_synced_at || now - new Date(m.account.last_synced_at).getTime() > 6 * 3600000;
    el.innerHTML = `<div class="panel-h"><h2>我最近发的视频</h2><small>${esc(ago(m.account.last_synced_at))}${stale ? ' · <button class="linklike" type="button" data-sync-mine>同步</button>' : ''}</small></div>
      ${rows || '<div class="empty"><span>近 7 天没有发视频</span></div>'}`;
    bindTeardownButtons(el);
    $$('[data-sync-mine]', el).forEach((b) => (b.onclick = async () => { try { const r = await api('/api/sync', { method: 'POST' }); toast(r.message); await refreshAll(); } catch (err) { toast(err.message); } }));
  },
});
