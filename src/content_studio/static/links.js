'use strict';
/* 05 已发出 · 链接：每条内容在每个平台上的链接。9/29 Park：「每一条内容在每一个平台上都有一个独特的链接，
   这个我们要好好保存下来。」存在工作台数据库一处（publish_records），这一页看、改、下载。 */
window.VIEWS = window.VIEWS || {};

const LB = { data: null };

function linkCell(row, p) {
  const r = row.links[p.key];
  if (!r) return `<td class="lb-none">—</td>`;
  const edit = `<button class="lb-edit" type="button" title="改链接" data-lb-edit="${row.id}|${p.key}">✎</button>`;
  if (!r.url) return `<td class="lb-warn" title="${esc(r.issue || '')}">已发 · 缺链接${edit}</td>`;
  return `<td class="${r.issue ? 'lb-warn' : ''}" title="${esc(r.issue || r.url)}"><a href="${esc(r.url)}" target="_blank" rel="noopener">↗ ${day(r.published_at)}</a>${r.issue ? ' <b>!</b>' : ''}${edit}</td>`;
}

function csv(d) {
  const q = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
  const head = ['内容', ...d.platforms.map((p) => p.label)];
  const lines = d.rows.map((r) => [r.title, ...d.platforms.map((p) => (r.links[p.key] || {}).url || '')]);
  return [head, ...lines].map((l) => l.map(q).join(',')).join('\n');
}

window.VIEWS.links = {
  async render() {
    const body = $('#linksBody');
    try { LB.data = await api('/api/links'); } catch (err) { body.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`; return; }
    const d = LB.data;
    const gaps = d.rows.reduce((n, r) => n + Object.values(r.links).filter((x) => x.issue).length, 0);
    body.innerHTML = d.rows.length ? `
      ${gaps ? `<p class="lb-note">有 ${gaps} 条链接要补或要换（标黄的），鼠标放上去看为什么，点 ✎ 改。</p>` : ''}
      <div class="lb-wrap"><table class="lb">
        <thead><tr><th>内容</th>${d.platforms.map((p) => `<th>${esc(p.label)}</th>`).join('')}</tr></thead>
        <tbody>${d.rows.map((r) => `<tr><th><button class="linklike" type="button" data-lb-open="${r.id}">${esc(r.title)}</button></th>${d.platforms.map((p) => linkCell(r, p)).join('')}</tr>`).join('')}</tbody>
      </table></div>`
      : '<div class="panel empty"><b>还没有发出去的内容</b><span>在发布台发完、或者存草稿后点「发出去了」，链接就会出现在这里。</span></div>';
    $$('[data-lb-open]', body).forEach((b) => (b.onclick = () => { S.publishId = Number(b.dataset.lbOpen); if (window.resetDesk) window.resetDesk(); go('publish'); }));
    $$('[data-lb-edit]', body).forEach((b) => (b.onclick = async () => {
      const [id, platform] = b.dataset.lbEdit.split('|');
      const row = d.rows.find((r) => r.id === Number(id));
      const cur = ((row && row.links[platform]) || {}).url || '';
      const url = prompt('这个平台上的链接', cur);
      if (url === null) return;
      if (url.trim() && !/^https?:\/\//.test(url.trim())) { toast('链接要以 https:// 开头'); return; }
      try { await api(`/api/topics/${id}/platforms`, { method: 'PUT', body: { platform, published: true, url: url.trim() || null } }); toast('存好了'); renderView(); } catch (err) { toast(err.message); }
    }));
    const dl = $('#linksCsv');
    if (dl) dl.onclick = () => {
      const blob = new Blob(['﻿' + csv(d)], { type: 'text/csv;charset=utf-8' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `内容链接-${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(a.href);
    };
  },
};
