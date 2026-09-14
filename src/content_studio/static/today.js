'use strict';
/* Today page cards. Each card: { id, order, title, wide, render(el) }. Later modules push more cards. */
window.TODAY_CARDS = window.TODAY_CARDS || [];

window.TODAY_CARDS.push({
  id: 'status',
  order: 90,
  title: '账号与队列',
  render(el) {
    const st = S.state;
    const acct = S.mine.account;
    const unread = S.reports.filter((r) => !r.archived_at).length;
    const lastMine = S.mine.videos.find((v) => !v.is_image_post);
    const multiple = lastMine && S.mine.median_likes ? lastMine.likes / S.mine.median_likes : null;
    el.innerHTML = `<div class="panel-h"><h2>账号与队列</h2><small>${acct ? esc(acct.nickname || '') : '未连接账号'}</small></div>
      <div class="mini-stats">
        <button type="button" data-go="mine"><span>最新一条</span><b>${multiple === null ? '—' : multiple.toFixed(1) + '×'}</b><small class="clamp">${lastMine ? esc(cleanTitle(lastMine.title)) : '还没有作品数据'}</small></button>
        <button type="button" data-go="report"><span>没看的拆解报告</span><b>${unread}</b><small>看完点归档</small></button>
        <button type="button" data-go="queue"><span>拆解进行中</span><b>${st.active_jobs}</b><small>${S.jobs.filter((j) => j.stage === 'failed').length} 条失败</small></button>
      </div>
      ${st.vault.ok ? '' : `<div class="banner warn" style="margin:0 18px 16px"><div>${esc(st.vault.message)} <button class="btn small" type="button" data-go="settings">去设置</button></div></div>`}`;
    $$('[data-go]', el).forEach((b) => (b.onclick = () => go(b.dataset.go)));
  },
});
