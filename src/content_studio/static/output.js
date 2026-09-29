'use strict';
/* 05 已发出 · 概览（9/29 改版）：一切回到 KPI——触达。
   顶上：今天触达、这一周触达、这一周发了几条（目标每天一条）、30 天节奏；7 个平台今天的触达常驻不折叠；
   每条内容 × 每个平台的累计触达（看出哪条在哪起量）；做对了 / 做错了 / 下一步只改一件（来自每周复盘）；
   倍数图放最下面。2 秒跳出、平均观看、收藏赞这些小图拿掉了（Park：用处不大）。 */
const WEEK_TARGET = 7; // PARK-OS：每天一条
window.VIEWS = window.VIEWS || {};

const OUT = { review: null, reviewAt: 0 };

async function loadReview(force) {
  if (!force && OUT.review && Date.now() - OUT.reviewAt < (OUT.review.state === 'running' ? 4000 : 60000)) return OUT.review;
  OUT.review = await api('/api/review');
  OUT.reviewAt = Date.now();
  if (OUT.review.state === 'running') setTimeout(() => { if (S.view === 'output') { $('#outputBody').dataset.sig = ''; renderView(); } }, 5000);
  return OUT.review;
}

const median = (xs) => {
  const v = xs.filter((x) => x !== null && x !== undefined && !Number.isNaN(x)).sort((a, b) => a - b);
  if (!v.length) return null;
  return v.length % 2 ? v[(v.length - 1) / 2] : (v[v.length / 2 - 1] + v[v.length / 2]) / 2;
};

/* One shared floating tooltip for every chart mark carrying data-tip. */
function bindTips(root) {
  let tip = $('#chartTip');
  if (!tip) { tip = document.createElement('div'); tip.id = 'chartTip'; tip.className = 'chart-tip'; tip.hidden = true; document.body.appendChild(tip); }
  const place = (e) => { tip.style.left = `${Math.min(e.clientX + 14, window.innerWidth - 300)}px`; tip.style.top = `${e.clientY + 14}px`; };
  $$('[data-tip]', root).forEach((el) => {
    el.onmouseenter = (e) => { tip.textContent = el.dataset.tip; tip.hidden = false; place(e); };
    el.onmousemove = place;
    el.onmouseleave = () => { tip.hidden = true; };
    if (el.classList.contains('help-q')) el.onclick = (e) => { e.stopPropagation(); const same = !tip.hidden && tip.textContent === el.dataset.tip; tip.textContent = el.dataset.tip; tip.hidden = same; place(e); };
  });
  document.addEventListener('click', () => { tip.hidden = true; }, { once: true });
}

/* Bars on a time axis: one bar per video, height = multiple of the account median. */
function multipleChart(rows) {
  if (rows.length < 2) return '<div class="empty"><span>近 90 天视频少于 2 条，画不出走势</span></div>';
  const W = 1100, H = 260, m = { l: 40, r: 16, t: 18, b: 30 };
  const t1 = Date.now(), t0 = t1 - 90 * 86400000;
  const span = Math.max(1, t1 - t0);
  const top = Math.max(4, Math.ceil(Math.max(...rows.map((r) => r.multiple))));
  const x = (t) => m.l + 10 + ((t - t0) / span) * (W - m.l - m.r - 20);
  const y = (v) => m.t + (1 - Math.min(v, top) / top) * (H - m.t - m.b);
  const bw = 9;
  const ticks = top <= 6 ? [0, 1, 3, top] : [0, 1, 3, Math.round(top / 2), top];
  let s = `<svg viewBox="0 0 ${W} ${H}" class="chart-svg" role="img" aria-label="每条视频的倍数">`;
  [...new Set(ticks)].forEach((v) => {
    s += `<line class="${v === 1 ? 'ref' : 'gridl'}" x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}"/><text class="axis-t" x="${m.l - 8}" y="${y(v) + 4}" text-anchor="end">${v}×</text>`;
  });
  for (let k = 0; k <= 3; k++) { // month-ish ticks every 30 days
    const t = t0 + k * 30 * 86400000, d = new Date(t);
    s += `<text class="axis-t" x="${x(t)}" y="${H - 8}" text-anchor="${k === 3 ? 'end' : k === 0 ? 'start' : 'middle'}">${k === 3 ? '今天' : `${d.getMonth() + 1}/${d.getDate()}`}</text>`;
  }
  rows.forEach((r) => {
    const d = new Date(r.t);
    const key = `${d.getMonth() + 1}/${d.getDate()}`;
    const h = Math.max(2, y(0) - y(r.multiple));
    const cls = r.multiple >= 3 ? 'hot' : r.multiple >= 1 ? 'ok' : 'low';
    s += `<path class="bar ${cls}" d="M${x(r.t) - bw / 2},${y(0)} v${-(h - 4)} q0,-4 4,-4 h${bw - 8} q4,0 4,4 v${h - 4} z"/>`;
    s += `<rect class="hit" x="${x(r.t) - Math.max(bw, 14) / 2}" y="${m.t}" width="${Math.max(bw, 14)}" height="${H - m.t - m.b}" data-tip="${esc(`${key} · ${r.title.slice(0, 28)}\n${r.multiple.toFixed(1)}× · ${fmt(r.likes)} 赞`)}"/>`;
  });
  rows.filter((r) => r.multiple >= 3).forEach((r) => { s += `<text class="bar-label" x="${x(r.t)}" y="${y(r.multiple) - 6}" text-anchor="middle">${r.multiple.toFixed(1)}×</text>`; });
  return s + '</svg>';
}

function reviewBlock(r) {
  const gen = `<button class="btn small ${r.data ? '' : 'primary'}" type="button" id="rvGen" ${r.state === 'running' ? 'disabled' : ''}>${r.state === 'running' ? '复盘中…' : r.data ? '重新复盘' : '复盘这一周'}</button>`;
  if (!r.data) {
    return `<section class="panel review"><div class="panel-h"><h2>这周复盘</h2>${gen}</div>
      <div class="empty"><span>${r.state === 'running' ? '<span class="spin"></span> 正在看这 7 天的数据和拆解报告' : r.state === 'failed' ? esc(r.error || '生成失败') : '用这 7 天的视频数据、拆解报告和对标爆款，看做对了什么、问题在哪，定下周只改的一件事。'}</span></div></section>`;
  }
  const d = r.data;
  const items = (list, cls) => list.map((it) => `<li class="${cls}"><span>${esc(it.text)}</span>${(it.videos || []).map((v) => `<button type="button" class="linklike" data-report="${esc(v.video_id)}">${esc(cleanTitle(v.title).slice(0, 18))}</button>`).join('')}</li>`).join('');
  const first = (list) => (list && list.length ? esc(list[0].text || list[0]) : '<span class="muted">这周没有</span>');
  return `<section class="panel review">
    <div class="panel-h"><h2>这一周 <small>${esc(d.since)} – ${esc(d.until)} · 算于 ${day(r.updated_at)}</small></h2>${gen}</div>
    <div class="ov-three">
      <div class="win"><h3>做对了</h3><p>${first(d.wins)}</p></div>
      <div class="bad"><h3>做错了</h3><p>${first(d.problems)}</p></div>
      <div class="next"><h3>下一步只改一件</h3><p>${d.next_week && d.next_week.length ? esc(d.next_week[0]) : '<span class="muted">还没定</span>'}</p></div>
    </div>
    <details class="rv-full"><summary>看完整复盘</summary>
      <p class="rv-summary">${esc(d.summary)}</p>
      <div class="rv-grid">
        <div><h3>做对了</h3><ul class="rv-list">${items(d.wins, 'win') || '<li class="muted">这周没有</li>'}</ul></div>
        <div><h3>问题</h3><ul class="rv-list">${items(d.problems, 'problem') || '<li class="muted">这周没有</li>'}</ul></div>
      </div>
    </details>
  </section>`;
}

/* ---- 触达：第一 KPI，各平台合计 ---- */
const RE = { data: null, at: 0, editing: null };
async function loadReach(force) {
  if (!force && RE.data && Date.now() - RE.at < 20000) return RE.data;
  RE.data = await api('/api/reach?days=14');
  RE.at = Date.now();
  return RE.data;
}

function reachBars(days) {
  const W = 560, H = 100, pad = 4, n = days.length, bw = (W - pad * 2) / n;
  const max = Math.max(1, ...days.map((d) => d.total));
  const bars = days.map((d, i) => {
    const h = Math.round((d.total / max) * (H - 30));
    const x = pad + i * bw, cx = (x + bw / 2).toFixed(1);
    const last = i === n - 1;
    const label = `${d.day.slice(5).replace('-', '/')}`;
    const mark = d.total
      ? `<rect class="rb ${last ? 'today' : ''}" x="${(x + 3).toFixed(1)}" y="${H - 20 - h}" width="${(bw - 6).toFixed(1)}" height="${h}" rx="2"/>`
      : `<line class="rb-none" x1="${(x + 5).toFixed(1)}" x2="${(x + bw - 5).toFixed(1)}" y1="${H - 20}" y2="${H - 20}"/>`;
    return `${mark}<rect class="hit" x="${x.toFixed(1)}" y="0" width="${bw.toFixed(1)}" height="${H}" data-tip="${esc(`${d.day}\n${d.total ? fmt(d.total) + ' 播放' : '那天没同步，不是 0'}${Object.keys(d.by_platform).length > 1 ? '\n' + Object.entries(d.by_platform).map(([k, v]) => `${k} ${fmt(v)}`).join(' · ') : ''}`)}"/>
      <text class="axis" x="${cx}" y="${H - 5}" text-anchor="middle">${i % 2 === (n - 1) % 2 ? label : ''}</text>`;
  }).join('');
  return `<svg viewBox="0 0 ${W} ${H}" class="reach-svg" role="img" aria-label="近 14 天每天触达">${bars}</svg>`;
}

const q = (text) => `<button class="help-q" type="button" data-tip="${esc(text)}" aria-label="怎么算的">?</button>`;

function reachBlock(r, posts7) {
  const meta = Object.fromEntries((S.platforms || []).map((x) => [x.key, x]));
  const week = r.days.slice(-7).reduce((a, d) => a + d.total, 0);
  const prev = r.days.slice(0, 7).reduce((a, d) => a + d.total, 0);
  const vs = (now, base) => (base ? Math.round(((now - base) / base) * 100) : null);
  const dToday = vs(r.today, r.avg7);
  // 上周有没同步的日子（算成 0）就不比：比出来的百分比是假的
  const prevGaps = r.days.slice(0, 7).filter((d) => !d.total).length;
  const dWeek = prevGaps ? null : vs(week, prev);
  const on = reachPlatforms(r);
  const sumToday = on.reduce((a, p) => a + (p.today || 0), 0);
  const tile = (p) => {
    const m = meta[p.key] || {};
    const share = sumToday && p.today ? `${Math.round((p.today / sumToday) * 100)}%` : '';
    const READ = { baseline: '今天第一次读，明天起有数', not_read: p.key === 'xiaohongshu' ? '今天还没读（每天 9:25）' : '今天还没读（每天 9:30）', read: '自动' };
    const how = p.auto ? (READ[p.read] || ((r.synced_at || {})[p.key] ? '自动' : '明早第一次读')) : '手填';
    const value = p.auto
      ? `<b class="num">${p.today === null || p.today === undefined ? '—' : fmt(p.today)}</b>`
      : `<input class="ov-in num" type="number" min="0" inputmode="numeric" data-rp-views="${p.key}" value="${p.today ?? ''}" placeholder="待填">${p.stats_url ? `<a class="ov-look" href="${esc(p.stats_url)}" target="_blank" rel="noopener">去后台看今天的数 ↗</a>` : ''}`;
    return `<div class="ov-plat"><small>${m.mark ? `<i class="plat s-${m.state}"${m.state === 'manual' ? '' : ` style="--plat:${esc(m.hue)}"`}>${esc(m.mark)}</i>` : ''}${esc(p.label)}</small>${value}<i>${[share, how].filter(Boolean).join(' · ')}</i></div>`;
  };
  const rows = r.platforms.filter((p) => (meta[p.key] || {}).on !== false || !p.auto).map((p) => `<div class="rp-row ${p.on ? '' : 'off'}">
      <label class="rp-on"><input type="checkbox" data-rp-on="${p.key}" ${p.on ? 'checked' : ''} ${p.auto ? 'disabled' : ''}><b>${esc(p.label)}</b></label>
      <input class="rp-handle" data-rp-handle="${p.key}" value="${esc(p.handle)}" placeholder="账号名" ${p.auto ? 'disabled' : ''}></div>`).join('');
  return `<section class="ov-kpi">
      <div class="ov-k main"><span>今天触达 ${q(`今天 ${on.length} 个平台播放的合计。抖音、B 站、YouTube、X 每天自动读，按两次之间的差算；小红书截图读；视频号、公众号手填。`)}</span><b class="num">${fmt(r.today)}</b>
        <small class="${dToday === null ? '' : dToday < 0 ? 'bad' : 'good'}">${dToday === null ? '' : `比 7 天日均 ${fmt(r.avg7)} ${dToday < 0 ? '少' : '多'} ${Math.abs(dToday)}%`}</small></div>
      <div class="ov-k"><span>这一周触达</span><b class="num">${fmt(week)}</b><small class="${dWeek === null ? '' : dWeek < 0 ? 'bad' : 'good'}">${dWeek === null ? (prevGaps ? `上周有 ${prevGaps} 天没同步，不比` : '上周没数据') : `${dWeek < 0 ? '↓' : '↑'} ${Math.abs(dWeek)}% 比上周`}</small></div>
      <div class="ov-k"><span>这一周发了 ${q('最近 7 天发出的抖音视频条数。目标每天一条。')}</span><b class="num">${posts7} 条</b><small class="${posts7 < WEEK_TARGET ? 'bad' : 'good'}">目标 ${WEEK_TARGET} 条</small></div>
      <div class="ov-k"><span>30 天节奏 ${q('近 7 天日均 × 30。不是预测，是照现在的节奏一个月能到多少。')}</span><b class="num">${fmt(r.pace30)}</b><small>照这个速度</small></div>
      <div class="ov-k chart">${reachBars(r.days)}</div>
    </section>
    <section class="panel ov-plats-panel"><div class="panel-h"><h2>各平台今天触达</h2><small>手填的平台直接在格子里填今天的播放</small></div>
      <div class="ov-plats">${on.map(tile).join('')}</div>
      <details class="ov-manage"><summary>管理平台（开关、账号名）</summary><div class="rp-list">${rows}</div></details>
    </section>`;
}

function matrixBlock(mx) {
  if (!mx || !mx.rows.length) return '';
  const all = mx.rows.flatMap((r) => Object.values(r.cells).filter((c) => c.state === 'views' && c.views).map((c) => c.views));
  const top = Math.max(1, ...all);
  const cell = (c) => {
    if (c.state === 'none') return '<td class="mx-none">—</td>';
    if (c.state === 'sent') return `<td class="mx-sent" title="${c.no_api ? '这个平台没有接口读数' : '发了，还没读到数'}">${c.no_api ? '没接口' : '已发'}</td>`;
    const lvl = c.views >= top * 0.5 ? 3 : c.views >= top * 0.1 ? 2 : c.views ? 1 : 0;
    return `<td class="num mx-${lvl}">${fmt(c.views)}</td>`;
  };
  return `<section class="panel"><div class="panel-h"><h2>每条内容在每个平台的累计触达 <small>最近 ${mx.rows.length} 条 · 颜色越深越好</small></h2><small>倍数 = 抖音点赞 ÷ 你的中位数</small></div>
    <div class="mx-wrap"><table class="mx"><thead><tr><th>内容</th>${mx.platforms.map((p) => `<th>${esc(p.label)}</th>`).join('')}<th>合计</th><th>倍数</th></tr></thead>
      <tbody>${mx.rows.map((r) => `<tr><th title="${esc(r.title)}"><span>${esc(r.title)}</span><small>${day(r.published_at)}</small></th>${mx.platforms.map((p) => cell(r.cells[p.key] || { state: 'none' })).join('')}<td class="num"><b>${fmt(r.total)}</b></td><td class="num">${r.multiple === null ? '—' : `${r.multiple}×`}</td></tr>`).join('')}</tbody></table></div>
  </section>`;
}

function bindReach(root, body) {
  const save = async (platform, views) => {
    try { RE.data = await api('/api/reach', { method: 'PUT', body: { day: new Date().toLocaleDateString('sv-SE'), platform, views } }); RE.at = Date.now(); toast('记下了'); body.dataset.sig = ''; renderView(); } catch (err) { toast(err.message); }
  };
  $$('[data-rp-views]', root).forEach((i) => (i.onchange = () => save(i.dataset.rpViews, i.value === '' ? null : Number(i.value))));
  const saveAccounts = async () => {
    const accounts = {};
    $$('[data-rp-on]', root).forEach((box) => { if (!box.disabled) accounts[box.dataset.rpOn] = { on: box.checked, handle: ($(`[data-rp-handle="${box.dataset.rpOn}"]`, root) || {}).value || '' }; });
    try { await api('/api/settings', { method: 'PUT', body: { platform_accounts: accounts } }); RE.data = null; body.dataset.sig = ''; renderView(); } catch (err) { toast(err.message); }
  };
  $$('[data-rp-on]', root).forEach((box) => (box.onchange = saveAccounts));
  $$('[data-rp-handle]', root).forEach((i) => (i.onchange = saveAccounts));
}

/* 只列设置里开着的平台，按发布顺序（抖音 → 视频号 → B 站 → YouTube → X → 小红书 → 公众号） */
const REACH_ORDER = ['douyin', 'channels', 'bilibili', 'youtube', 'x', 'xiaohongshu', 'wechat_mp', 'miniprogram', 'xiaoyuzhou'];
function reachPlatforms(r) {
  const meta = Object.fromEntries((S.platforms || []).map((x) => [x.key, x]));
  return r.platforms.filter((p) => p.on && (meta[p.key] || {}).on !== false)
    .sort((a, b) => REACH_ORDER.indexOf(a.key) - REACH_ORDER.indexOf(b.key));
}

/* 按钮旁边写清楚：哪些平台自动同步（点按钮也会立刻同步），哪些只能手填。平台开关跟设置走。 */
function syncNote(r) {
  const box = $('#ovSyncNote');
  if (!box || !r || !r.platforms) return;
  const on = reachPlatforms(r);
  const names = (list) => list.map((p) => (p.key === 'douyin' ? '抖音（你的号）' : p.label)).join(' · ');
  const auto = on.filter((p) => p.auto), manual = on.filter((p) => !p.auto);
  box.innerHTML = `<b>自动</b> ${esc(names(auto))}<br>每天早上读一次，点按钮马上再读${auto.some((p) => p.key === 'xiaohongshu') ? '（小红书一分钟后到）' : ''}`
    + (manual.length ? `<br><b>要手填</b> ${esc(names(manual))}：在下面格子里填` : '');
}

window.VIEWS.output = {
  async render() {
    const body = $('#outputBody');
    const m = S.mine;
    if (!m || !m.account) {
      body.innerHTML = '<div class="panel empty"><b>还没连上你的抖音号</b><span>去「我的视频」连接后，这里会画出每条视频的数据。</span><button class="btn primary" type="button" onclick="go(\'mine\')">去连接</button></div>';
      return;
    }
    let review, board, reach, matrix;
    try { [review, board, reach, matrix] = await Promise.all([loadReview(false), typeof loadBoard === 'function' ? loadBoard(false) : null, loadReach(false), api('/api/outbox/matrix').catch(() => null)]); } catch (err) { body.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`; return; }
    syncNote(reach);
    if (document.activeElement && body.contains(document.activeElement) && document.activeElement.matches('input')) return;
    const sig = JSON.stringify([m.account.last_synced_at, m.videos.length, review.state, review.updated_at, board && board.streak, RE.at, matrix && matrix.rows.map((r) => r.total)]);
    if (body.dataset.sig === sig) return;
    body.dataset.sig = sig;

    const now = Date.now();
    const med = m.median_likes;
    const rows = m.videos
      .filter((v) => !v.is_image_post && v.published_at && now - new Date(v.published_at).getTime() < 90 * 86400000)
      .map((v) => ({
        ...v,
        t: new Date(v.published_at).getTime(),
        title: cleanTitle(v.title),
        multiple: med && v.likes !== null ? v.likes / med : 0,
        bounce: v.creator ? v.creator.bounce_rate_2s : null,
        watch: v.creator ? v.creator.avg_view_second : null,
        fans: v.creator ? v.creator.fan_increment : null,
      }))
      .sort((a, b) => a.t - b.t);
    const last7 = rows.filter((r) => now - r.t < 7 * 86400000);
    body.innerHTML = `${reachBlock(reach, last7.length)}
      ${matrixBlock(matrix)}
      ${reviewBlock(review)}
      <section class="panel chart-panel small">
        <div class="panel-h"><h2>每条视频的倍数 <small>近 90 天 · 点赞 ÷ 账号中位数 ${fmt(med)}</small> ${q('每条视频的点赞除以你账号非置顶作品的点赞中位数。1× = 平时水平，≥3× 算爆。')}</h2><small class="legend"><i class="lg hot"></i>≥3× <i class="lg ok"></i>1–3× <i class="lg low"></i>&lt;1×</small></div>
        <div class="chart-box">${multipleChart(rows)}</div>
      </section>`;
    bindTips(body);
    bindTeardownButtons(body);
    bindReach(body, body);
    const gen = $('#rvGen');
    if (gen) gen.onclick = async () => {
      try { const res = await api('/api/review/generate', { method: 'POST' }); toast(res.message); await loadReview(true); body.dataset.sig = ''; renderView(); } catch (err) { toast(err.message); }
    };
  },
};
