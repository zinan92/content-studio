'use strict';
/* 03 已发出 · 概览：每条视频的倍数、开头留存、涨粉，每周复盘，满 48 小时待拆解 */
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
    if (el.classList.contains('q')) el.onclick = (e) => { e.stopPropagation(); const same = !tip.hidden && tip.textContent === el.dataset.tip; tip.textContent = el.dataset.tip; tip.hidden = same; place(e); };
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

/* Small multiple: one measure per video in publish order, with a reference line. */
function miniChart({ rows, value, format, ref, refLabel, worseHigh }) {
  const pts = rows.filter((r) => value(r) !== null && value(r) !== undefined);
  if (pts.length < 2) return '<div class="mini-empty">需要创作者后台数据（同步我的数据）</div>';
  const W = 520, H = 150, m = { l: 44, r: 12, t: 14, b: 12 };
  const vals = pts.map(value);
  const hi = Math.max(...vals, ref || 0) * 1.12, lo = 0;
  const x = (i) => m.l + (pts.length === 1 ? 0.5 : i / (pts.length - 1)) * (W - m.l - m.r);
  const y = (v) => m.t + (1 - (v - lo) / (hi - lo)) * (H - m.t - m.b);
  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(value(p)).toFixed(1)}`).join(' ');
  let s = `<svg viewBox="0 0 ${W} ${H}" class="chart-svg" role="img">`;
  s += `<line class="gridl" x1="${m.l}" x2="${W - m.r}" y1="${y(0)}" y2="${y(0)}"/>`;
  if (ref !== undefined) s += `<line class="ref" x1="${m.l}" x2="${W - m.r}" y1="${y(ref)}" y2="${y(ref)}"/><text class="axis-t" x="${m.l - 6}" y="${y(ref) + 4}" text-anchor="end">${refLabel}</text>`;
  s += `<path class="spark-area" d="${line} L${x(pts.length - 1)},${y(0)} L${x(0)},${y(0)} Z"/><path class="spark-line" d="${line}"/>`;
  pts.forEach((p, i) => {
    const v = value(p);
    const bad = ref !== undefined && (worseHigh ? v > ref : v < ref);
    const last = i === pts.length - 1;
    s += `<circle class="dot ${bad ? 'bad' : ''} ${last ? 'last' : ''}" cx="${x(i)}" cy="${y(v)}" r="${last ? 5 : 3.5}"/>`;
    s += `<rect class="hit" x="${x(i) - 14}" y="${m.t}" width="28" height="${H - m.t - m.b}" data-tip="${esc(`${day(p.published_at)} · ${p.title.slice(0, 24)}\n${format(v)}`)}"/>`;
  });
  const lastV = value(pts[pts.length - 1]);
  s += `<text class="bar-label" x="${x(pts.length - 1) - 8}" y="${y(lastV) - 10}" text-anchor="end">${format(lastV)}</text>`;
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
  return `<section class="panel review">
    <div class="panel-h"><h2>这周复盘 <small>${esc(d.since)} – ${esc(d.until)}</small></h2>${gen}</div>
    <p class="rv-snapshot">数字算于 ${day(r.updated_at)}，和现在的图表可能差一点（视频还在涨赞）</p>
    ${d.next_week && d.next_week.length ? `<div class="focus"><span>下周只改一件事</span><p>${esc(d.next_week[0])}</p></div>` : ''}
    <p class="rv-summary">${esc(d.summary)}</p>
    <div class="rv-grid">
      <div><h3>做对了</h3><ul class="rv-list">${items(d.wins, 'win') || '<li class="muted">这周没有</li>'}</ul></div>
      <div><h3>问题</h3><ul class="rv-list">${items(d.problems, 'problem') || '<li class="muted">这周没有</li>'}</ul></div>
    </div>
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

const q = (text) => `<button class="q" type="button" data-tip="${esc(text)}" aria-label="怎么算的">?</button>`;

function reachBlock(r) {
  const today = new Date().toLocaleDateString('sv-SE');
  const rows = r.platforms.map((p) => `<div class="rp-row ${p.on ? '' : 'off'}">
      <label class="rp-on"><input type="checkbox" data-rp-on="${p.key}" ${p.on ? 'checked' : ''} ${p.auto ? 'disabled' : ''}><b>${esc(p.label)}</b></label>
      <input class="rp-handle" data-rp-handle="${p.key}" value="${esc(p.handle)}" placeholder="账号名" ${p.auto ? 'disabled' : ''}>
      ${p.auto
        ? `<span class="rp-views num">${p.today === null || p.today === undefined ? '—' : fmt(p.today)}</span><small>自动 · ${esc(ago(r.douyin_synced_at))}</small>`
        : `<input class="rp-views" type="number" min="0" inputmode="numeric" data-rp-views="${p.key}" value="${p.today ?? ''}" placeholder="今天播放"><small>手填</small>`}
    </div>`).join('');
  return `<section class="reach">
    <div class="reach-hero">
      <div class="reach-big"><span>今天触达 ${q(`今天各平台播放的合计。\n抖音：今天同步的播放数 − 上次同步的播放数，逐条视频相加（老视频第一次同步只当基线，不算）。\n其他平台：你手填的今天播放。\n今天包含：${r.platforms.filter((p) => p.today).map((p) => `${p.label} ${fmt(p.today)}`).join('、') || '还没有数'}`)}</span><b class="num">${fmt(r.today)}</b><small>各平台播放合计 · ${today.slice(5)}</small></div>
      <div class="reach-side">
        <div><span>近 7 天日均 ${q('最近 7 天每天触达的平均值（没同步的日子算 0，所以偏低）。')}</span><b class="num">${fmt(r.avg7)}</b></div>
        <div><span>按这个节奏 30 天 ${q('近 7 天日均 × 30。不是预测，是照现在的节奏一个月能到多少。')}</span><b class="num">${fmt(r.pace30)}</b></div>
      </div>
      <div class="reach-chart">${reachBars(r.days)}</div>
    </div>
    <details class="reach-platforms"><summary><b>各平台</b><small>${r.platforms.filter((p) => p.on).length} 个开了 · 抖音自动，其他先手填今天的播放，接上数据后自动</small></summary>
      <div class="rp-list">${rows}</div>
    </details>
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

window.VIEWS.output = {
  async render() {
    const body = $('#outputBody');
    const m = S.mine;
    if (!m || !m.account) {
      body.innerHTML = '<div class="panel empty"><b>还没连上你的抖音号</b><span>去「我的视频」连接后，这里会画出每条视频的数据。</span><button class="btn primary" type="button" onclick="go(\'mine\')">去连接</button></div>';
      return;
    }
    let review, board, reach;
    try { [review, board, reach] = await Promise.all([loadReview(false), typeof loadBoard === 'function' ? loadBoard(false) : null, loadReach(false)]); } catch (err) { body.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`; return; }
    if (document.activeElement && body.contains(document.activeElement) && document.activeElement.matches('input')) return;
    const sig = JSON.stringify([m.account.last_synced_at, m.videos.length, review.state, review.updated_at, board && board.streak, S.jobs.map((j) => j.stage).join(), RE.at]);
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
    const last30 = rows.filter((r) => now - r.t < 30 * 86400000);
    const withCreator = rows.filter((r) => r.bounce !== null || r.watch !== null).slice(-16);
    const k = board ? board.streak : null;
    const fans30 = last30.reduce((a, r) => a + (r.fans || 0), 0);
    const medMult = median(last30.map((r) => r.multiple));
    const medWatch = median(last30.map((r) => r.watch));


    const last7 = rows.filter((r) => now - r.t < 7 * 86400000);
    const sum7 = (key) => last7.reduce((a, r) => a + (r[key] || 0), 0);
    const douyin7 = reach.days.slice(-7).reduce((a, d) => a + (d.by_platform.douyin || 0), 0);
    const fans7 = last7.reduce((a, r) => a + (r.fans || 0), 0);
    const watch7 = median(last7.map((r) => r.watch));
    const followers = m.account.follower_count;
    const wk = '只算最近 7 天发出的视频';
    body.innerHTML = `${reachBlock(reach)}
      <div class="kpi-strip week">
        <div class="kpi-big ${last7.length === 0 ? 'bad' : ''}"><span>近 7 天发了 ${q('最近 7 天发出的视频条数（图文不算）。')}</span><b class="num">${last7.length}</b><small>条 · 近 30 天 ${last30.length} 条</small></div>
        <div class="kpi-big"><span>播放 ${q('最近 7 天抖音每天涨的播放相加（同上面的触达口径，只算抖音）。没同步的日子算 0。')}</span><b class="num">${fmt(douyin7)}</b><small>7 天 · 抖音</small></div>
        <div class="kpi-big"><span>点赞 ${q(wk + '的点赞合计，取最近一次同步的数。')}</span><b class="num">${fmt(sum7('likes'))}</b><small>评论 ${fmt(sum7('comments'))} · 收藏 ${fmt(sum7('collects'))}</small></div>
        <div class="kpi-big"><span>涨粉 ${q(wk + '带来的涨粉相加，来自创作者后台；总粉丝是主页显示的粉丝数，最近一次同步。')}</span><b class="num">${fmt(fans7)}</b><small>总粉丝 ${followers === null || followers === undefined ? '—' : fmt(followers)}</small></div>
        <div class="kpi-big ${watch7 !== null && watch7 < 15 ? 'bad' : ''}"><span>平均观看 ${q(wk + '的平均观看秒数的中位数，来自创作者后台。主线要在 15 秒内说出来。')}</span><b class="num">${watch7 === null ? '—' : Math.round(watch7) + '秒'}</b><small>${k ? `连续拍摄 ${k.today_done || k.days ? k.days : 0} 天` : ''}</small></div>
      </div>
      <section class="panel chart-panel">
        <div class="panel-h"><h2>每条视频的倍数 <small>近 90 天 · 点赞 ÷ 账号中位数 ${fmt(med)}</small> ${q('每条视频的点赞除以你账号非置顶作品的点赞中位数。1× = 平时水平，≥3× 算爆。')}</h2><small class="legend"><i class="lg hot"></i>≥3× <i class="lg ok"></i>1–3× <i class="lg low"></i>&lt;1×</small></div>
        <div class="chart-box">${multipleChart(rows)}</div>
      </section>
      <div class="mini-grid">
        <section class="panel mini"><div class="panel-h"><h2>2 秒跳出</h2><small>越低越好 · 虚线 35%</small></div>${miniChart({ rows: withCreator, value: (r) => r.bounce, format: (v) => pct(v, 0), ref: 0.35, refLabel: '35%', worseHigh: true })}</section>
        <section class="panel mini"><div class="panel-h"><h2>平均观看秒数</h2><small>虚线 15 秒</small></div>${miniChart({ rows: withCreator, value: (r) => r.watch, format: (v) => Math.round(v) + '秒', ref: 15, refLabel: '15s', worseHigh: false })}</section>
        <section class="panel mini"><div class="panel-h"><h2>每条涨粉</h2><small>按发布先后</small></div>${miniChart({ rows: withCreator, value: (r) => r.fans, format: (v) => fmt(v) })}</section>
        <section class="panel mini"><div class="panel-h"><h2>收藏 / 赞</h2><small>高 = 观众想留着</small></div>${miniChart({ rows: rows.slice(-16), value: (r) => (r.likes ? (r.collects || 0) / r.likes : null), format: (v) => pct(v, 0) })}</section>
      </div>
      ${reviewBlock(review)}`;
    bindTips(body);
    bindTeardownButtons(body);
    bindReach(body, body);
    const gen = $('#rvGen');
    if (gen) gen.onclick = async () => {
      try { const res = await api('/api/review/generate', { method: 'POST' }); toast(res.message); await loadReview(true); body.dataset.sig = ''; renderView(); } catch (err) { toast(err.message); }
    };
  },
};
