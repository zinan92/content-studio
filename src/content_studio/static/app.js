'use strict';

/* ================= helpers ================= */
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt = (n) => {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  const v = Number(n);
  if (Math.abs(v) >= 10000) return (v / 10000).toFixed(v >= 100000 ? 0 : 1).replace(/\.0$/, '') + '万';
  return Math.round(v).toLocaleString('en-US');
};
const pct = (v, digits = 1) => (v === null || v === undefined ? '—' : (v * 100).toFixed(digits) + '%');
const mmss = (s) => {
  if (s === null || s === undefined) return '—';
  const t = Math.max(0, Math.floor(s));
  return Math.floor(t / 60) + ':' + String(t % 60).padStart(2, '0');
};
const day = (iso) => {
  if (!iso) return '—';
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()}`;
};
const cleanTitle = (t) => {
  const text = String(t || '').replace(/#[^\s#]+/g, '').replace(/\s+/g, ' ').trim();
  return text || String(t || '').trim() || '（无标题）';
};
const ago = (iso) => {
  if (!iso) return '从未同步';
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return '刚刚同步';
  if (mins < 60) return `${mins} 分钟前同步`;
  if (mins < 60 * 24) return `${Math.round(mins / 60)} 小时前同步`;
  return `${Math.round(mins / 1440)} 天前同步`;
};

function toast(message) {
  const t = $('#toast');
  t.textContent = message;
  t.classList.add('show');
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.remove('show'), 2600);
}

async function api(path, options = {}) {
  const init = { ...options, headers: { 'Content-Type': 'application/json', 'X-Content-Studio': '1', ...(options.headers || {}) } };
  if (init.body && typeof init.body !== 'string') init.body = JSON.stringify(init.body);
  let res;
  try {
    res = await fetch(path, init);
  } catch (err) {
    throw new Error('连不上本机服务：请确认终端里的 content-studio serve 还在运行');
  }
  let data = null;
  try { data = await res.json(); } catch (_) { /* empty body */ }
  if (!res.ok) {
    const detail = data && (data.error || data.detail);
    throw new Error(typeof detail === 'string' ? detail : `请求失败（${res.status}）`);
  }
  return data;
}

const STAGES = [
  ['downloading', '下载'],
  ['transcribing', '转文字'],
  ['analyzing', '结构拆解'],
  ['done', '报告'],
];
const STAGE_INDEX = { queued: -1, downloading: 0, transcribing: 1, analyzing: 2, done: 4, failed: -2 };
const STAGE_NAME = { queued: '排队中', downloading: '下载中', transcribing: '转文字中', analyzing: '拆解中', done: '已完成', failed: '失败' };

function teardownButton(item, { source } = {}) {
  if (item.has_report) return `<button class="btn small primary" type="button" data-report="${esc(item.video_id)}">看报告</button>`;
  const job = item.job;
  if (job && job.stage !== 'failed') {
    const cls = job.stage === 'queued' ? 'queued' : 'running';
    return `<span class="stage-pill ${cls}">${STAGE_NAME[job.stage] || job.stage}</span>`;
  }
  const label = job && job.stage === 'failed' ? '重新拆解' : '拆解';
  return `<button class="btn small" type="button" data-enqueue="${esc(item.video_id)}" data-source="${esc(source || '')}">${label}</button>`;
}

function bindTeardownButtons(root) {
  $$('[data-report]', root).forEach((b) => (b.onclick = () => openReport(b.dataset.report)));
  $$('[data-enqueue]', root).forEach((b) => (b.onclick = async () => {
    b.disabled = true;
    try {
      const res = await api('/api/jobs', { method: 'POST', body: { video_id: b.dataset.enqueue, source: b.dataset.source || undefined } });
      toast(res.message);
      await refreshAll();
    } catch (err) {
      toast(err.message);
      b.disabled = false;
    }
  }));
}

/* ================= state & routing ================= */
window.VIEWS = window.VIEWS || {};
const CORE_VIEWS = ['mine', 'radar', 'report', 'settings'];
const OUTPUT_FAMILY = ['output', 'mine', 'radar', 'report'];
const SUBNAV = [['output', '概览'], ['mine', '总览'], ['radar', '对标雷达'], ['report', '拆解报告']];
const S = {
  view: 'board',
  workId: null,
  publishId: null,
  accountId: (() => { try { return Number(localStorage.getItem('cs-account')) || null; } catch (_) { return null; } })(),
  state: null,
  mine: null,
  accounts: [],
  followed: { posts: [] },
  platforms: [],
  standard: null,
  outliers: [],
  jobs: [],
  reports: [],
  reportId: null,
  report: null,
  sort: 'multiple',
  radarDays: 7,
  radarAccount: null,   // 点了哪个对标账号：只看它
  radarScope: 'hot',    // hot 只看爆款 / all 全部作品
  radarQuery: '',
  radarVideos: {},      // accountId → 全部作品（切到「全部作品」时按需拉）
  mineSort: { key: 'published_at', dir: -1 },
  addMode: 'benchmark',
};

function railKey(view) {
  if (OUTPUT_FAMILY.includes(view)) return 'output';
  if (view === 'work') return 'board';
  return view;
}

function paintChrome(view) {
  const key = railKey(view);
  $$('.flow button, .rail-set').forEach((b) => b.classList.toggle('on', b.dataset.view === key));
  document.body.dataset.stage = ($(`#v-${view}`) || {}).dataset ? $(`#v-${view}`).dataset.stage : '';
  $$('.view').forEach((s) => s.classList.toggle('on', s.id === 'v-' + view));
  $$('[data-subnav]').forEach((nav) => {
    nav.innerHTML = SUBNAV.map(([k, l]) => `<button type="button" class="${k === view ? 'on' : ''}" data-sub="${k}">${l}${k === 'report' && S.reports.length ? ` <span class="num">${S.reports.filter((r) => !r.archived_at).length || ''}</span>` : ''}</button>`).join('');
    $$('[data-sub]', nav).forEach((b) => (b.onclick = () => go(b.dataset.sub)));
  });
}

function go(view, { push = true } = {}) {
  S.view = view;
  paintChrome(view);
  if (push) {
    const hash = view === 'report' && S.reportId ? `#report/${S.reportId}` : view === 'work' && S.workId ? `#work/${S.workId}` : view === 'publish' && S.publishId ? `#publish/${S.publishId}` : `#${view}`;
    if (location.hash !== hash) history.pushState(null, '', hash);
  }
  window.scrollTo(0, 0);
  renderView();
}

const OLD_ROUTES = { today: 'board', brief: 'board', topics: 'board', video: 'board', article: 'board', hot: 'board', collect: 'input', weekly: 'output', queue: 'report', skills: 'settings' };

function readHash() {
  let [view, id] = location.hash.replace(/^#/, '').split('/');
  view = OLD_ROUTES[view] || view; // old bookmarks
  if (view === 'report' && id) S.reportId = id;
  if (view === 'publish') S.publishId = id ? Number(id) : null;
  if (view === 'work') {
    if (!id) return 'board';
    S.workId = Number(id);
  }
  return [...CORE_VIEWS, ...Object.keys(window.VIEWS)].includes(view) ? view : 'board';
}

function bindNav() {
  $$('.flow button, .rail-set').forEach((b) => (b.onclick = () => go(b.dataset.view)));
}
window.addEventListener('popstate', () => go(readHash(), { push: false }));

$('#themeBtn').onclick = () => {
  const r = document.documentElement;
  const dark = r.dataset.theme ? r.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
  r.dataset.theme = dark ? 'light' : 'dark';
  try { localStorage.setItem('cs-theme', r.dataset.theme); } catch (_) { /* ignore */ }
};
try { const t = localStorage.getItem('cs-theme'); if (t) document.documentElement.dataset.theme = t; } catch (_) { /* ignore */ }

/* ================= data loading ================= */
async function refreshAll() {
  const threshold = S.state ? S.state.settings.threshold : undefined;
  const [state, mine, accounts, followed, platforms, jobs, reports] = await Promise.all([
    api('/api/state'),
    api('/api/mine' + (S.accountId ? `?account_id=${S.accountId}` : '')),
    api('/api/accounts'),
    api('/api/followed/posts'),
    api('/api/platforms'),
    api('/api/jobs'),
    api('/api/reports'),
  ]);
  S.state = state;
  S.mine = mine;
  S.accounts = accounts;
  S.followed = followed;
  S.platforms = platforms.platforms || [];
  S.jobs = jobs;
  S.reports = reports;
  S.outliers = await api('/api/outliers' + (threshold ? `?threshold=${state.settings.threshold}` : ''));
  renderChrome();
  renderView();
  if (window.refreshPublishNav) window.refreshPublishNav();
}

function renderChrome() {
  const st = S.state;
  const banner = [];
  if (!st.cookies.ok) {
    banner.push(`<div class="banner warn"><div><b>抖音登录信息不可用。</b>${esc(st.cookies.message)}。请在浏览器登录抖音网页版和创作者中心后重新导出 cookies 到 <code>~/.config/content-studio/douyin-cookies.json</code>（权限 600）。</div></div>`);
  }
  // 第一次装的人看到的第一件事：profile.yaml 缺什么。必填列出来，可选只报个数。
  if (st.setup && !st.setup.ok) {
    const req = st.setup.missing_required || [];
    const opt = st.setup.missing_optional || [];
    const lines = req.map((m) => `<li><b>${esc(m.label)}</b> <code>${esc(m.key)}</code> — ${esc(m.hint)}</li>`).join('');
    banner.push(`<div class="banner warn setup"><div><b>${st.setup.present ? `profile.yaml 还有 ${req.length} 项必填没填` : '还没有 profile.yaml'}</b>
      ${st.setup.present ? '' : `<div>${esc(st.setup.hint)}</div>`}
      ${lines ? `<ul>${lines}</ul>` : ''}
      ${opt.length ? `<small>另有 ${opt.length} 项可选没填，不影响启动。终端里 <code>python3 -m content_studio check</code> 看全部。</small>` : ''}
    </div></div>`);
  }
  const stopped = st.last_full_sync && (st.last_full_sync.stopped || st.last_full_sync.error);
  if (stopped) banner.push(`<div class="banner warn"><div><b>上次同步中断：</b>${esc(stopped)}</div></div>`);
  $('#globalBanner').innerHTML = banner.length ? `<div style="display:flex;flex-direction:column;gap:10px;margin:0 0 18px;max-width:1180px">${banner.join('')}</div>` : '';
  const weekAgo = Date.now() - 7 * 86400000;
  const shipped = S.mine.videos.filter((v) => !v.is_image_post && v.published_at && new Date(v.published_at).getTime() >= weekAgo).length;
  $('#navOut').textContent = shipped ? `${shipped} 条/周` : '';
  renderPlatformStrip();
  $('#brandSub').textContent = S.mine.account && S.mine.account.nickname ? `${S.mine.account.nickname} · 本机` : 'Park · 本机';
  const failedJobs = S.jobs.filter((j) => j.stage === 'failed').length;
  $('#qSummary').textContent = `${st.active_jobs ? `${st.active_jobs} 条进行中` : '没有进行中的'}${failedJobs ? ` · ${failedJobs} 条失败` : ''}`;
  paintChrome(S.view);
  const syncBtn = $('#syncAllBtn');
  syncBtn.disabled = st.full_sync_running;
  syncBtn.textContent = st.full_sync_running ? '同步中…' : '同步全部账号';
  $('#syncState').innerHTML = st.full_sync_running
    ? '<span class="spin"></span><span>正在同步全部账号</span>'
    : `<span class="dot"></span><span>${st.account_count} 个账号 · ${st.active_jobs} 个拆解进行中</span>`;
  const thr = $('#thr');
  if (document.activeElement !== thr) {
    thr.value = st.settings.threshold;
    $('#thrV').textContent = st.settings.threshold + '×';
  }
}


const PLAT_STATE = { linked: '已连接', ready: '凭据就绪', stale: '要重新登录', blocked: '平台限制了', setup: '差一步配置', manual: '手动发布' };

/** 左下角的平台条。三种状态，不是两种——一个永远亮不起来的灯就是骗人：
 *  已连接=彩色；要重新登录=彩色带感叹号；手动=灰色（它本来就没有通道可连）。 */
function renderPlatformStrip() {
  const box = $('#platStrip');
  if (!box) return;
  box.innerHTML = S.platforms.map((p) => {
    const title = `${p.label} · ${PLAT_STATE[p.state] || p.state}${p.note ? ' · ' + p.note : ''}`;
    const style = p.state === 'manual' || p.state === 'blocked' ? '' : ` style="--plat:${esc(p.hue)}"`;
    const warn = p.state === 'stale' || p.state === 'setup' ? '<b class="plat-warn">!</b>' : '';
    return `<span class="plat s-${p.state}"${style} title="${esc(title)}"><i>${esc(p.mark)}</i>${warn}</span>`;
  }).join('');
}

async function syncAll(btn) {
  if (btn) btn.disabled = true;
  try {
    const res = await api('/api/sync', { method: 'POST' });
    toast(res.message);
    await refreshAll();
  } catch (err) { toast(err.message); } finally { if (btn) btn.disabled = false; }
}
$('#syncAllBtn').onclick = () => syncAll($('#syncAllBtn'));
$$('[data-sync-all]').forEach((b) => (b.onclick = () => syncAll(b)));

function renderView() {
  if (!S.state) return;
  if (window.VIEWS[S.view]) window.VIEWS[S.view].render();
  if (S.view === 'settings') { renderSettings(); if (window.renderSkills) window.renderSkills.render(); }
  if (S.view === 'mine') renderMine();
  if (S.view === 'radar') renderRadar();
  if (S.view === 'report') { renderReport(); renderQueue(); }
  if (window.renderAnna) window.renderAnna();
}

/* ================= SETTINGS ================= */
function renderSettings() {
  const st = S.state;
  const input = $('#setVault');
  if (document.activeElement !== input) input.value = st.settings.obsidian_vault;
  const vr = $('#setVideoRoot');
  if (document.activeElement !== vr) vr.value = st.settings.video_projects_root || '';
  const yx = $('#setYanxishi');
  if (document.activeElement !== yx) yx.value = st.settings.yanxishi_admin_url || '';
  $('#setVaultNote').textContent = st.vault.ok ? '已找到这个库' : st.vault.message;
  $('#setVaultNote').className = st.vault.ok ? '' : 'bad';
  const mineList = st.my_accounts || [];
  $('#myAccounts').innerHTML = mineList.length
    ? `<div class="acct-list">${mineList.map((a) => `<div class="acct-row"><b>${esc(a.nickname || '同步中…')}</b><span>${esc(a.platform)} · 粉丝 ${fmt(a.follower_count)}</span></div>`).join('')}</div>`
    : '<div class="empty"><span>还没有连接自己的账号，去「已发出 → 总览」连接。</span></div>';
}

$('#settingsForm').onsubmit = async (e) => {
  e.preventDefault();
  try {
    await api('/api/settings', { method: 'PUT', body: { obsidian_vault: $('#setVault').value, yanxishi_admin_url: $('#setYanxishi').value, video_projects_root: $('#setVideoRoot').value } });
    toast('已保存');
    await refreshAll();
  } catch (err) { toast(err.message); }
};

$('#myAcctForm').onsubmit = async (e) => {
  e.preventDefault();
  try {
    const res = await api('/api/accounts', { method: 'POST', body: { url: $('#myAcctIn').value, is_self: true } });
    $('#myAcctIn').value = '';
    S.accountId = res.account.id;
    try { localStorage.setItem('cs-account', String(S.accountId)); } catch (_) { /* ignore */ }
    toast('已添加，正在同步这个账号的作品');
    await refreshAll();
  } catch (err) { toast(err.message); }
};

/* ================= MY VIDEOS ================= */
function renderMine() {
  const m = S.mine;
  const body = $('#mineBody');
  if (!m.account) {
    $('#mineActions').innerHTML = '';
    body.innerHTML = `<div class="panel onboard">
      <h2>先连上你自己的抖音号</h2>
      <p>在抖音网页版打开你的主页，把地址栏里 <b>douyin.com/user/</b> 开头的链接粘贴到下面。之后这里会显示你每条视频的数据和后台指标。</p>
      <form class="inline-form" id="selfForm"><input id="selfIn" placeholder="https://www.douyin.com/user/MS4wLjAB…" aria-label="我的主页链接"><button class="btn primary" type="submit">连接</button></form>
    </div>`;
    $('#selfForm').onsubmit = async (e) => {
      e.preventDefault();
      try {
        await api('/api/accounts', { method: 'POST', body: { url: $('#selfIn').value, is_self: true } });
        toast('已连接，正在同步你的作品');
        await refreshAll();
      } catch (err) { toast(err.message); }
    };
    return;
  }
  const acct = m.account;
  $('#mineActions').innerHTML = `<span class="sync-note">${acct.syncing ? '<span class="spin"></span> 同步中' : esc(ago(acct.last_synced_at))}</span>
    <button class="btn" type="button" id="mineSync" ${acct.syncing ? 'disabled' : ''}>同步我的数据</button>`;
  $('#mineSync').onclick = async () => {
    try { const r = await api('/api/sync', { method: 'POST' }); toast(r.message === '开始同步全部账号' ? '开始同步：作品、后台数据和对标账号' : r.message); await refreshAll(); } catch (err) { toast(err.message); }
  };
  if (acct.status === 'error' && acct.last_error) {
    body.innerHTML = `<div class="banner warn" style="margin-bottom:18px"><div><b>同步失败：</b>${esc(acct.last_error)}</div></div>`;
  } else body.innerHTML = '';
  if (!m.videos.length) {
    body.innerHTML += `<div class="panel empty"><b>还没有作品数据</b><span>${acct.syncing ? '正在同步，稍等片刻…' : '点右上角「同步我的数据」拉取作品和后台指标。'}</span></div>`;
    return;
  }

  const videos = m.videos;
  const withCreator = videos.filter((v) => v.creator);
  const recent10 = videos.filter((v) => !v.is_image_post).slice(0, 10)
    .map((v) => (v.creator ? v.creator.view_count : v.views)).filter((x) => x !== null && x !== undefined).sort((a, b) => a - b);
  const med10 = recent10.length ? (recent10.length % 2 ? recent10[(recent10.length - 1) / 2] : (recent10[recent10.length / 2 - 1] + recent10[recent10.length / 2]) / 2) : null;
  const recent5 = withCreator.filter((v) => !v.is_image_post).slice(0, 5);
  const fans5 = recent5.reduce((a, v) => a + (v.creator.fan_increment || 0), 0);
  const avgWatch = recent5.map((v) => v.creator.avg_view_second).filter((x) => x !== null && x !== undefined);
  const likes = videos.reduce((a, v) => a + (v.likes || 0), 0);
  const collects = videos.reduce((a, v) => a + (v.collects || 0), 0);
  const topFan = recent5.slice().sort((a, b) => (b.creator.fan_increment || 0) - (a.creator.fan_increment || 0))[0];

  const kpis = `<div class="kpis">
    <div class="kpi"><div class="l">粉丝</div><div class="v">${fmt(acct.follower_count)}</div><div class="s">获赞 ${fmt(acct.total_favorited)}</div></div>
    <div class="kpi"><div class="l">近 10 条播放中位数</div><div class="v">${fmt(med10)}</div><div class="s">商单预估播放的基准</div></div>
    <div class="kpi"><div class="l">近 ${recent5.length || 5} 条视频涨粉</div><div class="v">${recent5.length ? fmt(fans5) : '—'}</div><div class="s">${topFan ? '最多：' + esc(cleanTitle(topFan.title).slice(0, 12)) : '需要后台数据'}</div></div>
    <div class="kpi"><div class="l">平均观看时长</div><div class="v ${avgWatch.length ? 'bad' : ''}">${avgWatch.length ? Math.round(Math.min(...avgWatch)) + '–' + Math.round(Math.max(...avgWatch)) + ' 秒' : '—'}</div><div class="s">近 ${avgWatch.length} 条视频</div></div>
    <div class="kpi"><div class="l">收藏 / 赞</div><div class="v">${likes ? pct(collects / likes) : '—'}</div><div class="s">全部 ${videos.length} 条作品</div></div>
  </div>`;

  const note = withCreator.length ? '' : `<div class="banner info"><div>还没有创作者后台数据（涨粉、完播、跳出）。点「同步我的数据」会一并抓取最近 90 天。</div></div>`;

  body.innerHTML += `${kpis}${note}
    <div class="panel"><div class="panel-h"><h2>时长 × 播放</h2><small>圆点大小 = 点赞 · 纵轴对数刻度 · 金色 = 点赞 ≥ 账号中位数 3 倍</small></div><div class="chart" id="scatter"></div></div>
    <div class="panel"><div class="panel-h"><h2>作品明细</h2><small>点击表头排序 · 中位数 ${fmt(m.median_likes)} 赞</small></div><div class="tbl-wrap"><table id="mineTbl"></table></div></div>`;
  drawScatter(videos, m.median_likes);
  drawMineTable(videos, m.median_likes);
}

function drawScatter(videos, median) {
  const pts = videos.filter((v) => !v.is_image_post && v.duration_seconds && (v.creator ? v.creator.view_count : v.views));
  const el = $('#scatter');
  if (pts.length < 2) { el.innerHTML = '<div class="empty">视频数量不足，暂时画不出分布</div>'; return; }
  const W = 1100, H = 300, m = { l: 52, r: 16, t: 14, b: 34 };
  const plays = pts.map((v) => (v.creator ? v.creator.view_count : v.views));
  const maxDur = Math.max(...pts.map((v) => v.duration_seconds)) / 60;
  const xMax = Math.max(5, Math.ceil(maxDur / 5) * 5);
  const lo = Math.floor(Math.log10(Math.max(1, Math.min(...plays)))), hi = Math.ceil(Math.log10(Math.max(...plays) + 1));
  const xs = (d) => m.l + (d / 60) / xMax * (W - m.l - m.r);
  const ys = (p) => m.t + (1 - (Math.log10(Math.max(p, 1)) - lo) / Math.max(1, hi - lo)) * (H - m.t - m.b);
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="时长与播放散点图">`;
  for (let e = lo; e <= hi; e++) {
    const p = 10 ** e;
    s += `<line class="gridl" x1="${m.l}" x2="${W - m.r}" y1="${ys(p)}" y2="${ys(p)}"/><g class="axis"><text x="${m.l - 6}" y="${ys(p) + 3}" text-anchor="end">${fmt(p)}</text></g>`;
  }
  const step = xMax <= 10 ? 2 : 5;
  for (let x = 0; x <= xMax; x += step) s += `<g class="axis"><text x="${xs(x * 60)}" y="${H - m.b + 16}" text-anchor="middle">${x}分</text></g>`;
  pts.forEach((v, i) => {
    const hot = median && v.likes / median >= 3;
    const r = 4 + Math.sqrt(v.likes || 0) / 9;
    s += `<circle cx="${xs(v.duration_seconds)}" cy="${ys(plays[i])}" r="${Math.min(r, 26)}" fill="${hot ? 'var(--hot)' : 'var(--accent)'}" fill-opacity="${hot ? 0.8 : 0.45}" stroke="${hot ? 'var(--hot)' : 'var(--accent)'}"><title>${esc(v.title)}\n${mmss(v.duration_seconds)} · 播放 ${fmt(plays[i])} · 赞 ${fmt(v.likes)}</title></circle>`;
  });
  el.innerHTML = s + '</svg>';
}

function drawMineTable(videos, median) {
  const cols = [
    ['title', '作品', 'l'], ['published_at', '发布'], ['duration_seconds', '时长'], ['plays', '播放'], ['likes', '点赞'],
    ['save', '收藏/赞'], ['fans', '涨粉'], ['c5', '5s完播'], ['j2', '2s跳出'], ['aw', '均看'], ['multiple', '倍数'], ['act', '拆解'],
  ];
  const rows = videos.map((v) => ({
    ...v,
    plays: v.creator ? v.creator.view_count : v.views,
    save: v.likes ? (v.collects || 0) / v.likes : null,
    fans: v.creator ? v.creator.fan_increment : null,
    c5: v.creator ? v.creator.completion_rate_5s : null,
    j2: v.creator ? v.creator.bounce_rate_2s : null,
    aw: v.creator ? v.creator.avg_view_second : null,
    multiple: median && v.likes !== null ? v.likes / median : null,
  }));
  const { key, dir } = S.mineSort;
  const val = (r) => (r[key] === null || r[key] === undefined ? -Infinity : r[key]);
  rows.sort((a, b) => (typeof a[key] === 'string' ? String(a[key]).localeCompare(String(b[key])) : val(a) - val(b)) * dir);
  const maxP = Math.max(1, ...rows.map((r) => r.plays || 0));
  const na = '<td class="na" title="没有后台数据（后台只保留 90 天）">—</td>';
  const tbl = $('#mineTbl');
  tbl.innerHTML = `<thead><tr>${cols.map(([k, l, c]) => `<th class="${c || ''} ${k === key ? 'sorted' : ''}" data-k="${k}" ${k === 'act' ? 'style="cursor:default"' : ''}>${l}${k === key ? (dir > 0 ? ' ↑' : ' ↓') : ''}</th>`).join('')}</tr></thead>
  <tbody>${rows.map((v) => `<tr>
    <td class="l title">${v.is_top ? '<span class="tag pin">置顶</span>' : ''}${v.is_image_post ? '<span class="tag img">图文</span>' : ''}${v.creator && v.save > 0.6 && v.fans !== null && v.collects && v.fans / v.collects < 0.3 ? '<span class="tag warn" title="每 100 个收藏换不到 30 个粉">收藏≠关注</span>' : ''}<span class="clamp" title="${esc(v.title)}">${esc(cleanTitle(v.title))}</span></td>
    <td>${day(v.published_at)}</td><td>${v.is_image_post ? '—' : mmss(v.duration_seconds)}</td>
    <td>${fmt(v.plays)}<span class="bar" style="width:${Math.max(2, (v.plays || 0) / maxP * 60)}px"></span></td>
    <td>${fmt(v.likes)}</td><td>${pct(v.save)}</td>
    ${v.creator ? `<td>${fmt(v.fans)}</td><td>${pct(v.c5)}</td><td class="${v.j2 >= 0.35 ? 'bad' : ''}">${pct(v.j2)}</td><td>${v.aw === null ? '—' : Math.round(v.aw) + '秒'}</td>` : na + na + na + na}
    <td>${v.multiple === null ? '—' : `<span class="pill ${v.multiple >= 3 ? 'hot' : v.multiple >= 1 ? 'mid' : 'low'}">${v.multiple.toFixed(1)}×</span>`}</td>
    <td><div class="acts">${v.is_image_post ? '<span class="muted">图文</span>' : teardownButton(v, { source: '我的视频' })}</div></td>
  </tr>`).join('')}</tbody>`;
  $$('th', tbl).forEach((th) => {
    if (th.dataset.k === 'act') return;
    th.onclick = () => {
      S.mineSort = { key: th.dataset.k, dir: th.dataset.k === key ? -dir : -1 };
      drawMineTable(videos, median);
    };
  });
  bindTeardownButtons(tbl);
}

/* ================= RADAR ================= */
function spark(values, median, threshold) {
  const W = 260, H = 64, p = 4;
  if (!values.length) return `<svg class="spark" viewBox="0 0 ${W} ${H}" aria-hidden="true"></svg>`;
  const lo = Math.log10(Math.max(1, Math.min(...values))), hi = Math.log10(Math.max(...values) + 1);
  const x = (i) => p + (values.length === 1 ? 0.5 : i / (values.length - 1)) * (W - 2 * p);
  const y = (v) => p + (1 - (Math.log10(Math.max(v, 1)) - lo) / Math.max(0.01, hi - lo)) * (H - 2 * p);
  const pts = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`);
  let s = `<svg class="spark" viewBox="0 0 ${W} ${H}" role="img" aria-label="点赞走势（对数刻度）"><polygon class="area" points="${p},${H - p} ${pts.join(' ')} ${W - p},${H - p}"/><polyline class="ln" points="${pts.join(' ')}"/>`;
  if (median) s += `<line class="med" x1="${p}" x2="${W - p}" y1="${y(median)}" y2="${y(median)}"/>`;
  values.forEach((v, i) => { if (median && v / median >= threshold) s += `<circle class="hot" cx="${x(i)}" cy="${y(v)}" r="3.2"><title>${fmt(v)} 赞 · ${(v / median).toFixed(1)}×</title></circle>`; });
  return s + '</svg>';
}

function mixBar(v) {
  if (!v.likes) return '';
  const s = (v.collects || 0) / v.likes, h = (v.shares || 0) / v.likes, c = (v.comments || 0) / v.likes, tot = Math.max(0.0001, s + h + c);
  const type = h >= 0.9 ? '转发型' : s >= 0.6 && h >= 0.35 ? '收藏+转发' : s >= 0.6 ? '收藏型' : h >= 0.35 ? '转发型' : c >= 0.1 ? '评论型' : '点赞型';
  return `<div class="mix" title="收藏/赞 ${pct(s)} · 转发/赞 ${pct(h)} · 评论/赞 ${pct(c)}"><i style="width:${s / tot * 100}%;background:var(--save)"></i><i style="width:${h / tot * 100}%;background:var(--share)"></i><i style="width:${c / tot * 100}%;background:var(--talk)"></i></div><div class="mixlab">${type} · 收藏 ${pct(s)}</div>`;
}

function renderRadar() {
  const threshold = S.state.settings.threshold;
  const cards = S.accounts.map((a) => {
    const status = a.platform !== '抖音'
      ? `<div class="wait">${esc(a.pending_note)}</div>`
      : a.syncing ? '<div class="status"><span class="spin"></span>正在同步近期作品…</div>'
        : a.status === 'error' ? `<div class="status"><span class="err">同步失败：${esc(a.last_error)}</span></div>`
          : `<div class="status">${esc(ago(a.last_synced_at))}</div>`;
    const title = a.nickname || (a.platform === '抖音' ? '新账号（同步后显示昵称）' : a.external_id ? '@' + a.external_id : '新账号');
    return `<div class="panel acct pick ${S.radarAccount === a.id ? 'on' : ''}" data-pick="${a.id}" title="点一下只看这个账号，再点一下看全部">
      <div class="acct-top"><h3 title="${esc(title)}"><span class="pb">${esc(a.platform)}</span>${esc(title)}</h3><span class="fans">${a.follower_count !== null ? fmt(a.follower_count) + ' 粉' : ''} <button class="acct-x" data-rm="${a.id}" title="移出对标库" aria-label="移出对标库">×</button></span></div>
      ${a.platform === '抖音' ? spark(a.spark, a.median_likes, threshold) : `<div class="url">${esc(a.profile_url)}</div>`}
      ${a.platform === '抖音' ? `<div class="meta"><span>中位 <b>${fmt(a.median_likes)}</b></span><span>作品 <b>${a.video_count}</b></span><span style="color:var(--hot)">爆款 <b style="color:var(--hot)">${a.breakout_count}</b></span></div>` : ''}
      ${status}
      ${a.platform === '抖音' ? `<div class="row-actions"><button class="btn small ghost" type="button" data-sync="${a.id}" ${a.syncing ? 'disabled' : ''}>同步</button><a class="btn small ghost" href="${esc(a.profile_url)}" target="_blank" rel="noopener">主页 ↗</a></div>` : ''}
    </div>`;
  }).join('');
  $('#accts').innerHTML = cards + `<button class="panel acct add" id="addBtn" type="button"><span class="plus">+</span>加入对标账号<span>抖音 · 小红书 · X · 视频号</span></button>`;
  $('#addBtn').onclick = () => openAdd('benchmark');
  bindAccountActions($('#accts'), '对标库');

  $$('#accts [data-pick]').forEach((card) => (card.onclick = (e) => {
    if (e.target.closest('button, a')) return;  // 卡片上的按钮和链接照旧
    const id = Number(card.dataset.pick);
    S.radarAccount = S.radarAccount === id ? null : id;
    renderRadar();
  }));

  const cutoff = S.radarDays ? Date.now() - S.radarDays * 86400000 : 0;
  const douyinAccounts = S.accounts.filter((a) => a.platform === '抖音');
  const picked = S.radarAccount ? S.accounts.find((a) => a.id === S.radarAccount) : null;
  if (S.radarAccount && !picked) S.radarAccount = null;
  let pool;
  if (S.radarScope === 'all') {
    const ids = picked ? [picked.id] : douyinAccounts.map((a) => a.id);
    const missing = ids.filter((id) => !S.radarVideos[id]);
    if (missing.length) {
      $('#outs').innerHTML = '<div class="empty"><span class="spin"></span> 正在读全部作品…</div>';
      Promise.all(missing.map((id) => api(`/api/accounts/${id}/videos`).then((d) => { S.radarVideos[id] = d.videos; }).catch(() => { S.radarVideos[id] = []; })))
        .then(() => { if (S.view === 'radar') renderRadar(); });
      return;
    }
    pool = ids.flatMap((id) => S.radarVideos[id] || []);
  } else {
    pool = S.outliers.filter((v) => !picked || v.account_id === picked.id);
  }
  const q = S.radarQuery.trim().toLowerCase();
  const inWindow = pool.filter((v) => !cutoff || (v.published_at && new Date(v.published_at).getTime() >= cutoff));
  const list = inWindow.filter((v) => !q || String(v.title || '').toLowerCase().includes(q))
    .sort((a, b) => (S.sort === 'published_at' ? String(b.published_at).localeCompare(String(a.published_at)) : (b[S.sort] ?? -1) - (a[S.sort] ?? -1)));
  const hidden = pool.length - inWindow.length;
  $('#outsTitle').textContent = S.radarScope === 'all' ? '全部作品' : '爆款样本';
  $('#hotN').textContent = `${list.length} 条${hidden ? ` · 更早的 ${hidden} 条在「全部」里` : ''}`;
  const earliest = picked && S.radarScope === 'all' ? (S.radarVideos[picked.id] || []).reduce((m, v) => (!m || (v.published_at && v.published_at < m) ? v.published_at : m), null) : null;
  $('#radarPick').innerHTML = picked
    ? `<span class="rp-chip">只看 <b>${esc(picked.nickname || '这个账号')}</b><button type="button" id="rpClear" aria-label="看全部账号">×</button></span>
       ${S.radarScope === 'all' ? `<span class="muted">库里 ${(S.radarVideos[picked.id] || []).length} 条${earliest ? `，最早 ${day(earliest)}` : ''}。</span>
       <button class="btn small ghost" type="button" id="rpDeep" ${picked.syncing ? 'disabled' : ''} title="平时同步只拉最近约 60 条；往回翻最多 300 条，一页一页慢慢拉，遇到抖音验证就停">${picked.syncing ? '正在同步…' : '拉更早的作品'}</button>` : ''}`
    : '';
  const clear = $('#rpClear');
  if (clear) clear.onclick = () => { S.radarAccount = null; renderRadar(); };
  const deep = $('#rpDeep');
  if (deep) deep.onclick = () => syncOneAccount(picked.id, deep, { deep: true });
  const threshold2 = S.state.settings.threshold;
  $('#outs').innerHTML = list.length ? list.map((v) => {
    const hot = v.multiple !== null && v.multiple !== undefined && v.multiple >= threshold2;
    const label = `${v.account_nickname || ''} · ${v.multiple === null || v.multiple === undefined ? '' : v.multiple.toFixed(1) + '×'}`;
    return `<div class="out ${hot ? '' : 'cold'}">
      <div class="mult">${v.multiple === null || v.multiple === undefined ? '—' : v.multiple.toFixed(1) + '×'}<small>中位倍数</small></div>
      <div><div class="t clamp" title="${esc(v.title)}">${esc(cleanTitle(v.title))}</div><div class="by">${esc(v.account_nickname || '')} · ${day(v.published_at)} · ${v.is_image_post ? '图文' : mmss(v.duration_seconds)}${v.is_top ? ' · 置顶' : ''}</div></div>
      <div class="stats">赞 ${fmt(v.likes)}<br>收藏 ${fmt(v.collects)} · 转发 ${fmt(v.shares)}</div>
      <div class="mixcol">${mixBar(v)}</div>
      <div style="display:flex;gap:6px;justify-content:flex-end;align-items:center">${v.is_image_post ? '<span class="muted">图文</span>' : teardownButton(v, { source: `${hot ? '对标爆款' : '对标作品'} · ${label}` })}</div>
    </div>`;
  }).join('')
    : `<div class="empty"><b>${!douyinAccounts.length ? '还没有抖音对标账号' : q ? `没有标题里带「${esc(S.radarQuery.trim())}」的` : S.radarScope === 'all' ? (S.radarDays ? `这 ${S.radarDays} 天没有作品` : '还没有作品') : (S.radarDays ? `这 ${S.radarDays} 天没有新爆款` : '当前门槛下没有爆款')}</b><span>${!douyinAccounts.length ? '点上面的「加入对标账号」，粘贴对方主页链接。' : hidden ? `更早的 ${hidden} 条在「全部」里。` : S.radarScope === 'hot' ? '切到「全部作品」能看到没爆的。' : picked ? '点「拉更早的作品」往回翻。' : ''}</span></div>`;
  bindTeardownButtons($('#outs'));
}

/* 单个账号同步（9/20 改版时这个函数丢了，卡片上的「同步」点了没反应）。deep=true 往回翻更早的作品。 */
async function syncOneAccount(id, btn, { deep = false } = {}) {
  const before = S.accounts.find((a) => a.id === id) || {};
  const was = before.video_count || 0;
  btn.disabled = true;
  try {
    const started = await api(`/api/accounts/${id}/sync${deep ? '?deep=true' : ''}`, { method: 'POST' });
    toast(started.message);
    if (!started.started) { btn.disabled = false; return; }
    for (let i = 0; i < 150; i++) {
      await new Promise((r) => setTimeout(r, 2000));
      await refreshAll();
      const now = S.accounts.find((a) => a.id === id);
      if (!now) return;
      if (now.syncing) continue;
      delete S.radarVideos[id];
      if (S.view === 'radar') renderRadar();
      if (now.status === 'error') { toast(`同步失败：${now.last_error || '未知原因'}`); return; }
      const added = (now.video_count || 0) - was;
      toast(`${now.nickname || '账号'}：${added > 0 ? `多了 ${added} 条` : '没有新的作品'}，库里现在 ${now.video_count} 条`);
      return;
    }
    toast('还在同步，稍后看这张卡片上的时间');
  } catch (err) { toast(err.message); btn.disabled = false; }
}

/** Remove / sync — the 对标 card grid. */
function bindAccountActions(root, what) {
  $$('[data-rm]', root).forEach((b) => (b.onclick = async () => {
    const acct = S.accounts.find((a) => String(a.id) === b.dataset.rm);
    if (!confirm(`把「${acct.nickname || acct.profile_url}」移出${what}？它的作品数据会一起删除，已生成的拆解报告保留。`)) return;
    try { await api(`/api/accounts/${b.dataset.rm}`, { method: 'DELETE' }); toast(`已移出${what}`); await refreshAll(); } catch (err) { toast(err.message); }
  }));
  $$('[data-sync]', root).forEach((b) => (b.onclick = () => syncOneAccount(Number(b.dataset.sync), b)));
}

let thrTimer;
$('#thr').oninput = (e) => {
  const value = Number(e.target.value);
  $('#thrV').textContent = value + '×';
  S.state.settings.threshold = value;
  clearTimeout(thrTimer);
  thrTimer = setTimeout(async () => {
    try {
      await api('/api/settings', { method: 'PUT', body: { threshold: value } });
      $('#thrSaved').textContent = '已保存';
      setTimeout(() => ($('#thrSaved').textContent = ''), 1500);
      await refreshAll();
    } catch (err) { toast(err.message); }
  }, 350);
};
$$('#v-radar [data-days]').forEach((b) => (b.onclick = () => {
  S.radarDays = Number(b.dataset.days);
  $$('#v-radar [data-days]').forEach((x) => x.classList.toggle('on', x === b));
  renderRadar();
}));
$$('#v-radar [data-scope]').forEach((b) => (b.onclick = () => {
  S.radarScope = b.dataset.scope;
  $$('#v-radar [data-scope]').forEach((x) => x.classList.toggle('on', x === b));
  renderRadar();
}));
$('#radarQ').oninput = (e) => { S.radarQuery = e.target.value; renderRadar(); };
$$('#v-radar [data-sort]').forEach((b) => (b.onclick = () => {
  S.sort = b.dataset.sort;
  $$('#v-radar [data-sort]').forEach((x) => x.classList.toggle('on', x === b));
  renderRadar();
}));

/* add-account dialog */
function detectPlat(u) {
  if (/douyin\.com\/user\/|v\.douyin\.com\/|iesdouyin\.com/.test(u)) return '抖音';
  if (/xiaohongshu\.com\/user\/profile|xhslink\.com\//.test(u)) return '小红书';
  if (/(^|\/\/|\s)(www\.|mobile\.)?(x|twitter)\.com\/[A-Za-z0-9_]+/.test(u)) return 'X';
  if (/weixin\.qq\.com/.test(u)) return '视频号';
  return null;
}
function showDetect() {
  const u = $('#addIn').value.trim(), pl = detectPlat(u), d = $('#addDetect');
  $$('#addPlats span').forEach((x) => x.classList.toggle('on', x.textContent === pl));
  d.classList.remove('err');
  d.textContent = !u ? '支持以上四个平台的主页链接' : pl ? (pl === '抖音' ? '识别为抖音主页，加入后立即同步' : `识别为${pl}主页，先入库，抓取待接入`) : '还没认出平台，请粘贴完整的主页链接';
}
function openAdd(mode) {
  S.addMode = mode;
  $('#addIn').value = '';
  showDetect();
  $('#addDlg').showModal();
  $('#addIn').focus();
}
$('#addIn').oninput = showDetect;
$('#addCancel').onclick = () => $('#addDlg').close();
$('#addForm').onsubmit = async (e) => {
  e.preventDefault();
  const btn = $('#addSubmit');
  btn.disabled = true;
  try {
    const res = await api('/api/accounts', { method: 'POST', body: { url: $('#addIn').value } });
    $('#addDlg').close();
    toast(res.account.platform === '抖音' ? '已加入对标库，正在同步近期作品' : `已加入对标库（${res.account.platform}，抓取待接入）`);
    await refreshAll();
  } catch (err) {
    const d = $('#addDetect');
    d.classList.add('err');
    d.textContent = err.message;
  } finally {
    btn.disabled = false;
  }
};

/* ================= QUEUE ================= */
function renderQueue() {
  const jobs = S.jobs;
  const done = jobs.filter((j) => j.stage === 'done').length;
  const failed = jobs.filter((j) => j.stage === 'failed').length;
  $('#qMeta').textContent = `${done} 完成 · ${jobs.length - done - failed} 进行中 · ${failed} 失败`;
  if (!jobs.length) {
    $('#qList').innerHTML = '<div class="empty"><b>队列是空的</b><span>在上面粘贴视频链接，或去对标雷达把爆款加进来。</span></div>';
    return;
  }
  // Running first, then waiting jobs in the order they will run, then failures, then finished work.
  const rank = (j) => (['downloading', 'transcribing', 'analyzing'].includes(j.stage) ? 0 : j.stage === 'queued' ? 1 : j.stage === 'failed' ? 2 : 3);
  const ordered = jobs.slice().sort((a, b) => rank(a) - rank(b) || (rank(a) === 1 ? a.id - b.id : b.id - a.id));
  $('#qList').innerHTML = ordered.map((j) => {
    const idx = STAGE_INDEX[j.stage];
    const steps = STAGES.map(([key, label], k) => {
      let cls = '';
      if (j.stage === 'done' || idx > k) cls = 'ok';
      else if (idx === k) cls = 'run';
      return `<div class="step ${cls}"><i></i>${label}</div>`;
    }).join('');
    const action = j.stage === 'done'
      ? (j.has_report ? `<button class="btn small primary" type="button" data-report="${esc(j.video_id)}">看报告</button>` : '<span class="muted">报告缺失</span>')
      : j.stage === 'failed' ? `<button class="btn small" type="button" data-retry="${j.id}">重试</button>`
        : j.stage === 'queued' ? `<span class="stage-pill queued">排队中</span><button class="btn small ghost" type="button" data-cancel="${j.id}">取消</button>`
          : `<span class="stage-pill running">${STAGE_NAME[j.stage]}</span>`;
    return `<div class="q">
      <div><div class="src">${esc(j.source)} · ${day(j.created_at)}</div><div style="font-weight:500" class="clamp">${esc(j.title ? cleanTitle(j.title) : j.url)}</div>${j.error ? `<div class="err">${esc(j.error)}</div>` : ''}</div>
      <div class="steps">${steps}</div>
      <div style="display:flex;justify-content:flex-end;gap:6px;align-items:center">${action}</div>
    </div>`;
  }).join('');
  bindTeardownButtons($('#qList'));
  $$('[data-cancel]').forEach((b) => (b.onclick = async () => {
    try { await api(`/api/jobs/${b.dataset.cancel}`, { method: 'DELETE' }); toast('已取消'); await refreshAll(); } catch (err) { toast(err.message); }
  }));
  $$('[data-retry]').forEach((b) => (b.onclick = async () => {
    try { await api(`/api/jobs/${b.dataset.retry}/retry`, { method: 'POST' }); toast('已重新排队'); await refreshAll(); } catch (err) { toast(err.message); }
  }));
}

$('#linkForm').onsubmit = async (e) => {
  e.preventDefault();
  try {
    const res = await api('/api/jobs', { method: 'POST', body: { url: $('#linkIn').value } });
    $('#linkIn').value = '';
    toast(res.message);
    await refreshAll();
  } catch (err) { toast(err.message); }
};

/* ================= REPORT ================= */
const SEGC = { 钩子: 'var(--seg1)', 承诺: 'var(--seg6)', 论点: 'var(--seg3)', 案例: 'var(--seg2)', 跑题: 'var(--seg5)', 收束: 'var(--seg4)', 引导: 'var(--seg6)' };
const FACTS = [
  ['multiple_of_median', '账号中位数倍数', (v) => v + '×', true], ['likes', '点赞', fmt], ['collect_per_like', '收藏/赞', pct],
  ['share_per_like', '转发/赞', pct], ['comment_per_like', '评论/赞', pct], ['account_median_likes', '账号点赞中位数', fmt],
  ['views', '播放', fmt], ['creator_fan_increment', '涨粉', fmt], ['creator_avg_view_second', '平均观看', (v) => Math.round(v) + ' 秒'],
  ['creator_bounce_rate_2s', '2 秒跳出', pct], ['creator_completion_rate_5s', '5 秒完播', pct], ['creator_completion_rate', '完播率', pct],
  ['creator_homepage_visit_count', '主页访问', fmt], ['creator_cover_click_rate', '封面点击率', pct],
];

async function toggleArchive(videoId, isArchived) {
  const btn = $('#archiveBtn');
  btn.disabled = true;
  try {
    await api(`/api/reports/${videoId}/archive`, { method: isArchived ? 'DELETE' : 'POST' });
    if (isArchived) {
      toast('已取消归档');
    } else {
      const unread = S.reports.filter((x) => !x.archived_at && x.video_id !== videoId);
      toast(unread.length ? `已归档，还剩 ${unread.length} 份没看` : '已归档，报告都看完了');
      if (!S.showArchived) {
        S.reportId = unread.length ? unread[0].video_id : null;
        S.report = null;
        history.replaceState(null, '', S.reportId ? `#report/${S.reportId}` : '#report');
      }
    }
    S.reports = await api('/api/reports');
    renderChrome();
    renderReport();
  } catch (err) {
    toast(err.message);
    btn.disabled = false;
  }
}

async function openReport(videoId) {
  S.reportId = videoId;
  S.report = null;
  go('report');
}

async function loadReport(videoId) {
  try {
    S.report = await api(`/api/reports/${videoId}`);
  } catch (err) {
    S.report = { error: err.message };
  }
  if (S.view === 'report') renderReport();
}

function renderReport() {
  const pick = $('#repPick');
  const unread = S.reports.filter((r) => !r.archived_at);
  const archivedCount = S.reports.length - unread.length;
  const shown = S.showArchived ? S.reports : unread;
  // 左边一列：谁发的 / 标题 / 什么时候拆的。最新拆的排最上面（后端已按 generated_at 倒序）。
  pick.innerHTML = `<div class="panel-h"><h2>拆过的 <span class="num">${shown.length}</span></h2><small>最新在上</small></div>`
    + shown.map((r) => `<button type="button" class="rep-item ${r.video_id === S.reportId ? 'on' : ''} ${r.archived_at ? 'archived' : ''}" data-rid="${esc(r.video_id)}">
        <span class="rep-by">${r.is_self ? '我的' : esc(r.author || '对标')}</span>
        <b class="clamp2">${esc(cleanTitle(r.title))}</b>
        <small>${r.generated_at ? day(r.generated_at) : ''}${r.multiple ? ` · ${r.multiple}×` : ''}</small>
      </button>`).join('')
    + (archivedCount ? `<button type="button" class="toggle-archived" id="toggleArchived">${S.showArchived ? '收起已归档' : `已归档 ${archivedCount}`}</button>` : '');
  $$('[data-rid]', pick).forEach((b) => (b.onclick = () => openReport(b.dataset.rid)));
  if ($('#toggleArchived')) $('#toggleArchived').onclick = () => { S.showArchived = !S.showArchived; renderReport(); };
  const body = $('#repBody');
  if (!S.reports.length && !S.reportId) {
    body.innerHTML = '<div class="panel empty rep-empty"><b>还没有拆解报告</b><span>去「拆解队列」粘贴视频链接，或在对标雷达里点「拆解」。</span></div>';
    return;
  }
  if (!S.reportId && !unread.length) {
    body.innerHTML = `<div class="panel empty rep-empty"><b>报告都看完了</b><span>已归档 ${archivedCount} 份，点上面的「已归档 ${archivedCount}」可以再翻出来看。</span></div>`;
    body.dataset.rendered = '';
    return;
  }
  if (!S.reportId) { S.reportId = unread[0].video_id; history.replaceState(null, '', `#report/${S.reportId}`); }
  if (!S.report || (S.report.content_id && S.report.content_id !== S.reportId)) {
    if (!S.report || S.report.content_id !== S.reportId) {
      body.innerHTML = '<div class="panel empty rep-empty"><span class="spin"></span><span>正在读取报告…</span></div>';
      if (!S._loading || S._loading !== S.reportId) { S._loading = S.reportId; loadReport(S.reportId).finally(() => (S._loading = null)); }
      return;
    }
  }
  const r = S.report;
  if (r.error) { body.innerHTML = `<div class="panel empty rep-empty"><b>${esc(r.error)}</b></div>`; body.dataset.rendered = ''; return; }
  const entry = S.reports.find((x) => x.video_id === r.content_id);
  const isArchived = Boolean(entry && entry.archived_at);
  if (body.dataset.rendered === r.content_id + r.generated_at + isArchived) return; // keep scroll and open sections during polling
  body.dataset.rendered = r.content_id + r.generated_at + isArchived;
  const total = r.transcript.duration_seconds || (r.segments.length ? r.segments[r.segments.length - 1].end : 1);
  const facts = FACTS.filter(([k]) => r.facts[k] !== null && r.facts[k] !== undefined)
    .map(([k, l, f, hot]) => `<div><div class="l">${l}</div><div class="v ${hot && r.facts[k] >= S.state.settings.threshold ? 'hot' : ''}">${f(r.facts[k])}</div></div>`).join('');
  const cite = (ev) => (ev && ev.length ? ev.map((e) => `<span class="evidence"><button type="button" data-seek="${e.start}">${mmss(e.start)}</button> ${esc(e.quote)}</span>`).join('') : '');
  const pace = r.segments.map((s) => ({ label: s.label, cpm: s.end > s.start ? Math.round(s.text.replace(/\s/g, '').length / ((s.end - s.start) / 60)) : 0, drift: s.drift }));

  body.innerHTML = `
    <div class="panel">
      <div class="rep-head">
        <div>
          <div class="eyebrow">${r.facts.creator_avg_view_second ? '我的视频 · 主线诊断' : '对标拆解'} · ${esc(r.author || '')}</div>
          <h2 title="${esc(r.title)}">${esc(cleanTitle(r.title))}</h2>
          <div class="by">时长 ${mmss(total)} · 生成于 ${day(r.generated_at)}</div>
        </div>
        <div class="rep-actions">
          <button type="button" class="btn ${isArchived ? '' : 'primary'}" id="archiveBtn">${isArchived ? '取消归档' : '看完了，归档'}</button>
          ${r.source_url ? `<a class="btn" href="${esc(r.source_url)}" target="_blank" rel="noopener">在抖音打开 ↗</a>` : ''}
        </div>
      </div>
      <div class="facts">${facts}</div>
      ${r.facts.baseline_too_small ? `<p class="hint">这个账号近期作品太少或点赞普遍很低（${fmt(r.facts.account_post_count || 0)} 条，中位数 ${fmt(r.facts.account_median_likes || 0)}），倍数没有参考意义，所以不算。</p>` : ''}
    </div>
    ${r.opening ? `<div class="panel"><div class="panel-h"><h2>观众平均看到的前 ${Math.round(r.opening.seconds)} 秒</h2><small>来自创作者后台的平均观看时长</small></div>
      <div class="opening"><p>${esc(r.opening.analysis)}</p><blockquote>${esc(r.opening.transcript)}</blockquote></div></div>` : ''}
    <div class="rep-grid">
      <div class="panel">
        <div class="panel-h"><h2>主线结构</h2><span class="drift-sum">跑题 ${Math.round(r.drift.seconds)} 秒 · 占 ${pct(r.drift.share, 0)}</span></div>
        <div class="spine">
          <p class="thesis">${esc(r.thesis.text)}</p>
          <div class="tl" id="rTl">${r.segments.map((s, i) => `<button type="button" class="${s.drift ? 'drift' : ''}" style="flex:${Math.max(1, s.end - s.start)};background:${SEGC[s.label] || 'var(--seg6)'}" data-i="${i}" title="${esc(s.label)} ${mmss(s.start)}–${mmss(s.end)} · ${esc(s.summary)}">${(s.end - s.start) > total * 0.07 ? esc(s.label) : ''}</button>`).join('')}</div>
          <div class="tl-axis"><span>0:00</span><span>${mmss(total / 2)}</span><span>${mmss(total)}</span></div>
          <div class="legend">${[...new Set(r.segments.map((s) => s.label))].map((k) => `<span><i style="background:${SEGC[k] || 'var(--seg6)'}"></i>${k}</span>`).join('')}<span style="color:var(--warn)">斜纹 = 不服务主线</span></div>
        </div>
        <div class="transcript" id="rTx">${r.segments.map((s, i) => `<div class="line ${s.drift ? 'driftline' : ''}" data-i="${i}" id="seg-${i}">
          <div class="ts">${mmss(s.start)}</div>
          <div class="lab" style="color:${s.drift ? 'var(--warn)' : 'var(--ink-2)'}"><i style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${SEGC[s.label] || 'var(--seg6)'};margin-right:5px"></i>${esc(s.label)}</div>
          <div class="seg-body"><b>${esc(s.summary)}</b><span class="seg-reason">${s.drift ? '不服务主线：' : ''}${esc(s.reason)}</span>
          <details><summary>展开这段原文（${mmss(s.start)}–${mmss(s.end)}）</summary><p>${esc(s.text)}</p></details></div>
        </div>`).join('')}</div>
      </div>
      <div class="side">
        <div class="panel"><div class="panel-h"><h2>为什么爆</h2></div><div class="why"><ul>${r.why_boom.map((w) => `<li><span style="color:var(--ink)">${esc(w.text)}</span>${cite(w.evidence)}</li>`).join('')}</ul></div></div>
        <div class="panel"><div class="panel-h"><h2>为什么散</h2></div><div class="why"><ul>${r.why_scatter.map((w) => `<li><span style="color:var(--ink)">${esc(w.text)}</span>${cite(w.evidence)}</li>`).join('')}</ul></div></div>
        <div class="panel"><div class="panel-h"><h2>语速节奏</h2><small>字 / 分钟 · 按段（由转写计算）</small></div><div class="pace" id="rPace"></div></div>
        <div class="banner info"><div>${esc(r.hypothesis_note)}</div></div>
      </div>
    </div>`;

  drawPace(pace);
  const seek = (i) => {
    $$('#rTl button').forEach((x) => x.classList.toggle('on', x.dataset.i === String(i)));
    $$('#rTx .line').forEach((l) => l.classList.toggle('on', l.dataset.i === String(i)));
    const el = $(`#seg-${i}`);
    if (el) { el.scrollIntoView({ behavior: 'smooth', block: 'center' }); const d = $('details', el); if (d) d.open = true; }
  };
  $$('#rTl button').forEach((b) => (b.onclick = () => seek(Number(b.dataset.i))));
  $('#archiveBtn').onclick = () => toggleArchive(r.content_id, isArchived);
  $$('[data-seek]', body).forEach((b) => (b.onclick = () => {
    const t = Number(b.dataset.seek);
    let idx = 0;
    r.segments.forEach((s, i) => { if (s.start <= t + 0.5) idx = i; });
    seek(idx);
  }));
}

function drawPace(pace) {
  const el = $('#rPace');
  const vals = pace.map((p) => p.cpm).filter((v) => v > 0);
  if (!vals.length) { el.innerHTML = '<div class="empty">没有足够的转写计算语速</div>'; return; }
  const W = 320, H = 140, m = { l: 34, b: 24, t: 10 };
  const lo = Math.max(0, Math.floor((Math.min(...vals) - 20) / 50) * 50), hi = Math.ceil((Math.max(...vals) + 10) / 50) * 50;
  const bw = (W - m.l) / pace.length;
  const ys = (v) => m.t + (1 - (v - lo) / Math.max(1, hi - lo)) * (H - m.t - m.b);
  const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="各段语速">`;
  [lo, Math.round((lo + hi) / 2), hi].forEach((v) => (s += `<line class="gridl" x1="${m.l}" x2="${W}" y1="${ys(v)}" y2="${ys(v)}"/><g class="axis"><text x="${m.l - 5}" y="${ys(v) + 3}" text-anchor="end">${v}</text></g>`));
  pace.forEach((p, i) => {
    const x = m.l + i * bw + bw * 0.18;
    const fast = p.cpm > avg * 1.15;
    s += `<rect x="${x}" y="${ys(Math.max(p.cpm, lo))}" width="${bw * 0.64}" height="${Math.max(0, H - m.b - ys(Math.max(p.cpm, lo)))}" rx="2" fill="${p.drift ? 'var(--warn)' : fast ? 'var(--hot)' : 'var(--accent)'}" fill-opacity=".75"><title>第 ${i + 1} 段 ${p.label} · ${p.cpm} 字/分</title></rect>`;
    if (pace.length <= 12) s += `<g class="axis"><text x="${x + bw * 0.32}" y="${H - 8}" text-anchor="middle">${i + 1}</text></g>`;
  });
  el.innerHTML = s + '</svg>';
}

/* ================= boot & polling ================= */
async function boot() {
  bindNav();
  S.view = readHash();
  paintChrome(S.view);
  try {
    await refreshAll();
  } catch (err) {
    $('#globalBanner').innerHTML = `<div class="banner warn" style="margin-bottom:18px"><div><b>加载失败：</b>${esc(err.message)}</div></div>`;
  }
}

setInterval(async () => {
  if (!S.state || document.hidden) return;
  const syncing = (a) => a.syncing;
  const busy = S.state.full_sync_running || S.state.active_jobs > 0 || S.accounts.some(syncing)
    || (S.mine.account && S.mine.account.syncing);
  if (!busy) return;
  const focus = document.activeElement;
  if (focus && (focus.tagName === 'INPUT' || $('#addDlg').open)) return;
  try { await refreshAll(); } catch (_) { /* transient */ }
}, 3000);

boot();
