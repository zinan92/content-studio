'use strict';
/* 今天：最上面是周历（9/30 Park：「plan not just for one day, I can plan for the whole week」「每天扣了多少分，
 * I'm not even keeping count」），下面是 ABC 几件事（逻辑在 driver.py）。
 * 周历：过去的日子看四项做没做到、减几分、发了哪条；今天和以后排哪天拍哪条、加不算分的事。排哪条只由他定。
 * 做完的行收成一行，补发默认收起；每行原来那串 7 天小圆点拿掉了，周历里有。
 * A 读日报（9/30）；B 出摊：抖音、视频号、小红书发视频，X、公众号发文字；C 回私信；D X 互动，回 20 条；E 补发。
 * 没做到当天各减 1 分，左边栏一直显示。触达是结果，不在这一页看（在「已发出」）。
 * 9/29 Park：「你只需要告诉我，我今天要做的 ABC 三件事就好了……感觉今天这个页面太散了。」
 * 拍什么他定：「接下来要拍的」收在 A 里面；只有他点「我今天不知道拍什么」才建议。 */
window.VIEWS = window.VIEWS || {};

const TD = { data: null, poll: null, skipOpen: false, bfOpen: null, prev: null, bfAll: false, week: null, weekStart: null, sel: null, openRows: new Set(), wendy: null, wdOlder: false };

async function loadToday() { TD.data = await api('/api/today'); return TD.data; }
window.refreshTodayBadge = async () => { try { await loadToday(); } catch (_) { /* ignore */ } paintTodayBadge(); };

function paintTodayBadge() {
  const b = $('#navToday');
  if (!b || !TD.data) return;
  const n = TD.data.week.demerits;  // 本周（周一到周日）减的分
  b.textContent = n ? `减 ${n}` : '';
  b.classList.toggle('bad', !!n);
}

const DOW = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
function dayTitle(key) {
  const d = new Date(key + 'T00:00:00');
  return `${d.getMonth() + 1}月${d.getDate()}日 ${DOW[d.getDay()]}`;
}

/* ---- Wendy：最上面那张卡片。「现在做这一件」是工作台直接算的；她说的话是微信那边定时写的，
 *      加上你在这里回她、她在这里答你的。三小时没动静她去微信找你（规则在 wendy.py）。 ---- */
function wdWhen(iso) {
  const d = new Date(iso), now = new Date();
  const day = (x) => `${x.getFullYear()}-${x.getMonth()}-${x.getDate()}`;
  const y = new Date(now); y.setDate(now.getDate() - 1);
  const hm = d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false });
  return `${day(d) === day(now) ? '今天' : day(d) === day(y) ? '昨天' : `${d.getMonth() + 1}/${d.getDate()}`} ${hm}`;
}

function wdMsg(m, clip) {
  const where = m.who === 'park' ? '你' : m.source === 'desk' ? 'Wendy' : `Wendy · 微信${m.label ? ' · ' + esc(m.label) : ''}`;
  return `<div class="wd-m ${m.who === 'park' ? 'me' : ''} ${clip ? 'clip' : ''}"><small>${where} · ${wdWhen(m.at)}</small><p>${esc(m.text)}</p></div>`;
}

function wendyCard(w) {
  if (!w) return '';
  const n = w.now;
  let act = '';
  if (n) act = ['rd', 'dm', 'xr'].includes(n.row) ? `<div class="btns"><button class="btn go" type="button" data-wd-row="${n.row}">去做 ↓</button></div>` : actionButtons(n);
  const msgs = w.messages, shown = TD.wdOlder ? msgs : msgs.slice(-2);  // 平时只看最近两条，最新那条完整显示
  return `<section class="wd">
    <div class="wd-h"><span class="wd-av">W</span><b>Wendy</b><small>你的老板 · 盯你做没做到</small>${w.nudges.length ? `<span class="wd-nudged">今天在微信催过你 ${w.nudges.length} 次</span>` : ''}</div>
    <div class="wd-now"><span class="k">现在做这一件</span>${n ? `<b>${esc(n.text)}</b>${n.why ? `<small>${esc(n.why)}</small>` : ''}${act}` : '<b>今天算分的事都做完了。</b><small>明天拍哪条，在下面的周历里排上。</small>'}</div>
    <div class="wd-thread">${msgs.length > 2 ? `<button type="button" class="linklike wd-older" data-wd-older>${TD.wdOlder ? '只看最近两条' : `看之前的 ${msgs.length - 2} 条`}</button>` : ''}
      ${shown.map((m, i) => wdMsg(m, !TD.wdOlder && i < shown.length - 1)).join('') || '<p class="td-note">她还没说过话。早上 9:45 和晚上 22:30 她会来；你也可以现在让她看一眼。</p>'}
      ${w.busy ? '<p class="td-note"><span class="spin"></span> Wendy 在看工作台…不到一分钟</p>' : ''}${w.error ? `<p class="td-note warn">${esc(w.error)}</p>` : ''}</div>
    <form class="wd-form" id="wdForm"><input id="wdText" maxlength="2000" placeholder="回她一句：几点做、为什么没做、做完了…" autocomplete="off" ${w.busy ? 'disabled' : ''}>
      <button class="btn go" type="submit" ${w.busy ? 'disabled' : ''}>回她</button><button class="btn quiet" type="button" id="wdLook" ${w.busy ? 'disabled' : ''}>让她看一眼现在</button></form>
  </section>`;
}

/* ---- 周历 ---- */
const KPI_MARK = [['rd', '读', '读日报'], ['ship', '摊', '出摊'], ['dm', '私', '回私信'], ['xr', 'X', 'X 互动']];
const MARK_TIP = { ok: '做到了', miss: '没做到，减 1 分', pending: '今天还没做', 'n/a': '那天还不算分', future: '还没到' };
const md = (key) => `${Number(key.slice(5, 7))}/${Number(key.slice(8))}`;
const dow = (key) => DOW[new Date(key + 'T00:00:00').getDay()];

function streakText(s) {
  if (!s || !s.days) return '';
  return s.kind === 'ok' ? `连续出摊 <b class="ok">${s.days}</b> 天` : `连续 <b>${s.days}</b> 天没出摊`;
}

function weekCell(c) {
  const marks = c.state === 'future' ? '' : `<span class="wk-marks">${KPI_MARK.map(([f, ch, name]) => `<i class="${c[f] === 'n/a' ? 'na' : c[f]}" title="${name}：${MARK_TIP[c[f]]}">${ch}</i>`).join('')}</span>`;
  const score = c.state === 'today' ? '<span class="wk-score now">今天</span>' : c.demerits ? `<span class="wk-score bad">−${c.demerits}</span>` : c.state === 'past' && KPI_MARK.some(([f]) => c[f] === 'ok') ? '<span class="wk-score ok">✓</span>' : '';
  const lines = [
    ...c.shipped.map((t) => `<span class="wk-l out" title="${esc(t)}">发了：${esc(t)}</span>`),
    ...c.planned.filter((n) => !n.done).map((n) => `<span class="wk-l ${c.state === 'past' ? 'late' : 'plan'}" title="${esc(n.text)}">${c.state === 'past' ? '排了没拍' : '拍'}：${esc(n.text)}</span>`),
    ...c.items.map((it) => `<span class="wk-l item ${it.done ? 'done' : ''}" title="${esc(it.text)}">${it.done ? '✓' : '·'} ${esc(it.text)}</span>`),
  ];
  if (!lines.length && c.state !== 'past') lines.push('<span class="wk-l none">还没排拍哪条</span>');
  return `<button type="button" class="wk-day ${c.state} ${TD.sel === c.day ? 'sel' : ''}" data-wk-day="${c.day}" aria-pressed="${TD.sel === c.day}">
    <span class="wk-d"><small>${dow(c.day)}</small><b>${Number(c.day.slice(8))}</b>${score}</span>${marks}${lines.join('')}</button>`;
}

/* 点开某一天：过去的日子看那天的账；今天和以后排拍哪条、加不算分的事 */
function dayPanel(c, notes) {
  const title = `<b>${dow(c.day)} ${md(c.day)}</b>`;
  const chk = (it) => `<label class="wk-item ${it.done ? 'done' : ''}"><input type="checkbox" data-wk-done="${it.id}" ${it.done ? 'checked' : ''}><span>${esc(it.text)}</span><button type="button" class="linklike" data-wk-del="${it.id}" aria-label="删掉">×</button></label>`;
  const items = `<div class="wk-col"><h4>别的事 <small>不算分</small></h4>${c.items.map(chk).join('')}
      <form class="td-add" data-wk-item="${c.day}"><input maxlength="200" placeholder="这天还要做什么，回车加上（比如：约两个博主诊断）" autocomplete="off"></form></div>`;
  if (c.state === 'past') {
    const RES = { ok: '做到', miss: '没做到，减 1 分', 'n/a': '那天还不算分' };
    const det = { rd: '', ship: c.shipped.length ? `：${c.shipped.map((t) => `《${esc(t)}》`).join('、')}` : '',
      dm: c.dm_entry ? `：收到 ${c.dm_entry.received}，回了 ${c.dm_entry.replied}` : c.dm === 'miss' ? '（没填数）' : '',
      xr: c.xr_count != null ? `：${c.xr_count} 条` : c.xr === 'miss' ? '（没填数）' : '' };
    return `<div class="wk-panel"><div class="wk-ph">${title}<span class="wk-score ${c.demerits ? 'bad' : 'ok'}">${c.demerits ? `这天减 ${c.demerits} 分` : '这天没减分'}</span></div>
      <div class="wk-cols"><div class="wk-col"><h4>那天的账</h4>${KPI_MARK.map(([f, , name]) => `<p class="wk-res ${c[f] === 'n/a' ? 'na' : c[f]}"><b>${name}</b>${RES[c[f]]}${det[f]}</p>`).join('')}
        ${c.planned.filter((n) => !n.done).map((n) => `<p class="wk-res miss"><b>排了没拍</b>${esc(n.text)}</p>`).join('')}
        ${c.skips.map((k) => `<p class="wk-res na"><b>跳过</b>${esc(k.what)}：${esc(k.reason || '')}</p>`).join('')}</div>${items}</div></div>`;
  }
  const free = notes.filter((n) => !n.planned_day);
  const planned = c.planned.map((n) => `<span class="wk-chip ${n.done ? 'done' : ''}">${esc(n.text)}${n.done ? '' : `<button type="button" class="linklike" data-wk-unplan="${n.id}" aria-label="不排在这天">×</button>`}</span>`).join('');
  return `<div class="wk-panel"><div class="wk-ph">${title}<span class="td-note">${c.state === 'today' ? '今天' : '排这一天'}</span></div>
    <div class="wk-cols"><div class="wk-col"><h4>这天拍哪条 <small>你定</small></h4>${planned || '<p class="td-note">还没排。</p>'}
      <form class="td-add" data-wk-plan="${c.day}"><input list="wkNotes" maxlength="200" placeholder="从「接下来要拍的」里挑一条，或者直接写一条新的，回车" autocomplete="off">
        <datalist id="wkNotes">${free.map((n) => `<option value="${esc(n.text)}"></option>`).join('')}</datalist></form></div>${items}</div></div>`;
}

function weekBlock(w, streak, notes) {
  const sel = w.days.find((c) => c.day === TD.sel);
  const sum = [w.ship_days ? `出摊 <b class="${w.shipped === w.ship_days ? 'ok' : ''}">${w.shipped}/${w.ship_days}</b> 天` : '', w.demerits ? `减 <b>${w.demerits}</b> 分` : w.ship_days ? '<b class="ok">没减分</b>' : '', w.current ? streakText(streak) : ''].filter(Boolean).join(' · ');
  return `<section class="wk">
    <div class="wk-h"><span class="wk-nav"><button type="button" class="btn small" data-wk-go="${w.prev}" aria-label="上一周">‹</button><b>${w.current ? '本周' : ''} ${md(w.start)} – ${md(w.end)}</b><button type="button" class="btn small" data-wk-go="${w.next}" aria-label="下一周">›</button>${w.current ? '' : '<button type="button" class="btn small quiet" data-wk-go="">回到本周</button>'}</span>
      <span class="wk-sum">${sum || '这一周还没开始'}</span></div>
    <div class="wk-grid">${w.days.map(weekCell).join('')}</div>
    ${sel ? dayPanel(sel, notes) : '<p class="td-note wk-hint">点某一天：过去的看那天的账，今天和以后的排拍哪条、加别的事。</p>'}
  </section>`;
}

/* 每一行右上角的状态：做到了（带一句怎么做到的）/ 今天还没 */
function rowState(doneToday, detail) {
  return `<span class="td-state ${doneToday ? 'ok' : ''}">${doneToday ? `✓ 今天做到了${detail ? ` · ${detail}` : ''}` : '今天还没'}</span>`;
}

/* 一行：做完的收成一行，点标题展开；没做完的一直开着 */
function tdRow(key, letter, title, done, state, body, forceOpen) {
  const open = forceOpen != null ? forceOpen || TD.openRows.has(key) : !done || TD.openRows.has(key);
  const can = forceOpen != null ? !forceOpen : done;
  return `<section class="td-row ${done ? 'done' : ''} ${open ? '' : 'shut'}" data-row="${key}">
    <div class="td-h" ${can ? `data-row-toggle="${key}" role="button" tabindex="0"` : ''}><span class="td-letter">${letter}</span><h2>${title}</h2>${state}${can ? `<span class="td-tog">${open ? '收起' : '展开'}</span>` : ''}</div>
    ${open ? body : ''}
  </section>`;
}

function actionButtons(it) {
  let action = '';
  if (it.inputs === 'start_note') action = `<button class="btn go" type="button" data-td-start="${esc(it.key.split(':')[1])}">开始做</button>`;
  else if (it.inputs === 'focus_notes') action = '<button class="btn go" type="button" data-td-focusnotes>写一条</button>';
  else if (it.url) action = `<a class="btn go" href="${esc(it.url)}" target="_blank" rel="noopener">${esc(it.button)} ↗</a>`;
  else if (it.go) action = `<button class="btn go" type="button" data-td-go="${esc(it.go)}">${esc(it.button)} →</button>`;
  const manual = it.manual ? `<button class="btn" type="button" data-td-done="${esc(it.key)}">${it.rung === 'client' ? '发了' : '做完了'}</button>` : '';
  const skip = TD.skipOpen === it.key
    ? `<form class="td-skip" data-skip-form="${esc(it.key)}"><input maxlength="200" placeholder="为什么今天不做？一句话" autocomplete="off"><button class="btn" type="submit">跳过</button><button class="btn quiet" type="button" data-td-skipcancel>算了，去做</button></form>`
    : `<button class="btn quiet" type="button" data-td-skip="${esc(it.key)}">跳过（写一句为什么）</button>`;
  return `<div class="btns">${action}${manual}${skip}</div>`;
}

const nextLine = (it) => it ? `<div class="td-next"><b>${esc(it.text)}</b>${it.why ? `<small>${esc(it.why)}</small>` : ''}${actionButtons(it)}</div>` : '';

function firstBlock(list) {
  if (!list.length) return '';
  return `<section class="td-first"><h3>先处理</h3>${list.map((it) => `<div class="td-next"><span class="k">${esc(it.rung_label)}</span><b>${esc(it.text)}</b>${it.why ? `<small>${esc(it.why)}</small>` : ''}${actionButtons(it)}</div>`).join('')}</section>`;
}

function shipRow(d) {
  const s = d.ship;
  const plat = (p) => `<span class="td-plat ${p.shipped ? 'on' : ''} ${p.core ? '' : 'rest'}" title="${esc(p.label)}${p.shipped ? '：发了' : p.skipped ? '：这条不发' : '：还没发'}">${p.shipped ? '✓' : p.skipped ? '–' : '○'} ${esc(p.label)}</span>`;
  const FORM = { video: '发视频', text: '发文字', cards: '发图文', audio: '发音频' };
  const groups = ['video', 'text', 'cards', 'audio'].map((f) => [f, s.platforms.filter((p) => p.form === f)]).filter(([, ps]) => ps.length);
  const notes = s.notes.map((n, i) => `<li class="${i === 0 ? 'top' : ''}"><span>${esc(n.text)}${n.topic_id ? ' <small class="tag">在做</small>' : ''}${n.planned_day ? ` <small class="tag day">${dow(n.planned_day)} ${md(n.planned_day)}</small>` : ''}</span>
    <span class="acts"><button type="button" class="linklike" data-note-up="${n.id}" ${i === 0 ? 'disabled' : ''} aria-label="上移">↑</button><button type="button" class="linklike" data-note-down="${n.id}" ${i === s.notes.length - 1 ? 'disabled' : ''} aria-label="下移">↓</button><button type="button" class="linklike" data-note-del="${n.id}" aria-label="删掉">×</button></span></li>`).join('');
  const sg = s.suggest;
  let sug = '<button class="btn small" type="button" id="tdSuggest">我今天不知道拍什么</button>';
  if (sg && sg.running) sug = '<span class="td-note"><span class="spin"></span> 在你的选题池里挑一条…</span>';
  else if (sg && sg.error) sug = `<span class="td-note warn">${esc(sg.error)}</span> <button class="btn small" type="button" id="tdSuggest">再挑一次</button>`;
  else if (sg && sg.topic_id) sug = `<div class="td-sug"><b>建议拍：${esc(sg.title)}</b><span>${esc(sg.why)}</span><div class="btns"><button class="btn go" type="button" id="tdTake">就拍这条</button><button class="btn quiet" type="button" id="tdSuggest">换一条</button></div></div>`;
  return tdRow('ship', 'B', '出摊', s.done, rowState(s.done, s.topic ? `《${esc(s.topic.title.slice(0, 18))}》` : ''), `
    <div class="td-plats">${s.topic ? `<span class="td-topic">《${esc(s.topic.title)}》</span>` : ''}${groups.map(([f, ps]) => `<span class="td-form">${FORM[f]}</span>${ps.map(plat).join('')}`).join('')}</div>
    ${nextLine(s.next)}
    <details class="td-notes" ${s.notes.length ? '' : 'open'}><summary>接下来要拍的 · 你定${s.notes.length ? ` <span class="num">${s.notes.length}</span>` : ''}</summary>
      ${notes ? `<ol>${notes}</ol>` : '<p class="td-note">还没写。想好要拍什么就写在这里。排了日子的那天拍；没排的，最上面那条就是下一次出摊要拍的。</p>'}
      <form class="td-add" id="tdAdd"><input id="tdAddText" maxlength="200" placeholder="写一条要拍的，回车加到最后" autocomplete="off"></form>
      ${sug}</details>`);
}

/* A 读日报（9/30 Park：「每天最重要的事就是我要去读每日的日报，要不然日报存在的意义就没了」）。
   出了的才要读；打开 → 进项里那一份；读完点一下。 */
function readRow(d) {
  const items = d.rd.items;
  const due = items.filter((i) => i.exists);
  const done = due.length > 0 && due.every((i) => i.read_at);
  const one = (i) => `<div class="td-read ${i.read_at ? 'on' : ''}">
      <b>${esc(i.label)}</b>
      ${!i.exists ? '<small>今天的还没出</small>'
        : i.read_at ? `<small>✓ ${new Date(i.read_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })} 读完</small><button class="btn quiet" type="button" data-rd-undo="${i.key}">撤回</button>`
        : `<button class="btn" type="button" data-rd-open="${i.tab}">打开 →</button><button class="btn go" type="button" data-rd-done="${i.key}">读完了</button>`}
    </div>`;
  return tdRow('rd', 'A', '读日报', done, rowState(done, `${due.length} 份都读完了`), `
    <p class="td-why">每天第一件事。日报不读，就白出了。</p>
    <div class="td-reads">${items.map(one).join('')}</div>`);
}

function dmRow(d) {
  const e = d.dm.entry || {};
  const done = d.dm.entry && e.replied >= e.received;
  return tdRow('dm', 'C', '回私信', done, rowState(done, `收到 ${e.received}，回了 ${e.replied}`), `
    <p class="td-why">当天收到的当天回完，每条都往「动手」引。${d.dm.target ? `目标每天收到 ${d.dm.target} 条。` : `收到多少先记到 ${esc(d.dm.baseline_until.slice(5).replace('-', '/'))} 摸底，再定目标。`}</p>
    <form class="td-dm" id="tdDm"><label>收到 <input id="tdDmRecv" type="number" min="0" inputmode="numeric" value="${e.received ?? ''}"></label>
      <label>回了 <input id="tdDmRep" type="number" min="0" inputmode="numeric" value="${e.replied ?? ''}"></label>
      <button class="btn ${done ? '' : 'go'}" type="submit">${d.dm.entry ? '改' : '记下'}</button>${done ? '' : d.dm.entry ? `<small class="td-note">还差 ${e.received - e.replied} 条</small>` : ''}</form>`);
}

function xrRow(d) {
  const n = d.xr.count, t = d.xr.target;
  const done = n != null && n >= t;
  return tdRow('xr', 'D', `X 互动 · 回 ${t} 条`, done, rowState(done, `${n}/${t}`), `
    <p class="td-why">在你这个领域的中文大号帖子下面回一句有立场的话，不带链接。你在 X 上被看到过的，全是回复。</p>
    <form class="td-dm" id="tdXr"><a class="btn" href="https://x.com/home" target="_blank" rel="noopener">打开 X ↗</a>
      <label>今天回了 <input id="tdXrN" type="number" min="0" inputmode="numeric" value="${n ?? ''}"> / ${t}</label>
      <button class="btn ${done ? '' : 'go'}" type="submit">${n != null ? '改' : '记下'}</button>${n != null && !done ? `<small class="td-note">还差 ${t - n} 条</small>` : ''}</form>`);
}

/* D 补发：提前打好的包，今天挑一条发到剩下的平台。数据还是记在全平台追踪。
 * 看 → 就地展开（封面、文案、文章开头、插图、完整排版另开一页）；改 → 去打包页；发 → 一声令下。 */
const PF = { channels: '视频号', xiaohongshu: '小红书', bilibili: 'B 站', youtube: 'YouTube', x: 'X', wechat_mp: '公众号' };
const AUTO = ['bilibili', 'youtube', 'x'];
const STEP_LABEL = { copy: '文案', cover: '封面', article: '文章', figs: '插图', wx: '排版' };

function packRow(p) {
  const open = TD.bfOpen === p.topic_id;
  const steps = Object.entries(p.steps).map(([k, v]) => `<span class="td-step ${v}">${STEP_LABEL[k]}</span>`).join('');
  return `<div class="td-pack ${open ? 'open' : ''}">
    <button type="button" class="td-pack-h" data-bf-open="${p.topic_id}">
      ${p.cover ? `<img src="${esc(p.cover)}" alt="" loading="lazy">` : '<span class="td-nocover"></span>'}
      <span class="t"><b>${esc(p.title)}</b><small>${p.multiple != null ? `${p.multiple}× · ` : ''}${esc((p.published_at || '').slice(0, 10))} · 差 ${p.missing_labels.join('、')}</small>
        <span class="td-steps">${steps}${p.machine ? '<i>机器定稿，你没看过</i>' : ''}</span></span>
      <span class="chev">${open ? '收起' : '看一眼'}</span>
    </button>
    ${open ? `<div class="td-preview" id="tdPrev">${TD.prev && TD.prev.topic_id === p.topic_id ? previewHtml(TD.prev, p) : '<p class="td-note"><span class="spin"></span> 读包里的东西…</p>'}</div>` : ''}
  </div>`;
}

function previewHtml(v, p) {
  const auto = p.missing.filter((k) => AUTO.includes(k)).map((k) => PF[k]);
  const hand = p.missing.filter((k) => !AUTO.includes(k)).map((k) => PF[k]);
  return `<div class="td-pv-covers">${['portrait', 'landscape', 'wide'].filter((k) => v.covers[k]).map((k) => `<a href="${esc(v.covers[k])}" target="_blank" rel="noopener"><img class="${k}" src="${esc(v.covers[k])}" alt=""></a>`).join('')}</div>
    <div class="td-pv-copy"><b>${esc(v.title)}</b>${v.body ? `<p>${esc(v.body)}</p>` : ''}${v.tags.length ? `<small>${v.tags.map((t) => '#' + esc(t)).join(' ')}</small>` : ''}</div>
    ${v.article_title ? `<div class="td-pv-art"><h4>${esc(v.article_title)}</h4>${v.article_head.map((x) => `<p>${esc(x)}</p>`).join('')}
      ${v.figs.length ? `<div class="td-pv-figs">${v.figs.map((u) => `<a href="${esc(u)}" target="_blank" rel="noopener"><img src="${esc(u)}" alt="" loading="lazy"></a>`).join('')}</div>` : ''}
      ${v.layout_url ? `<a class="btn" href="${esc(v.layout_url)}" target="_blank" rel="noopener">看完整公众号排版 ↗</a>` : ''}</div>` : ''}
    <div class="td-pv-go">
      <p class="td-note">点「发这条」就是你的确认：${auto.length ? `<b>${auto.join('、')}</b> 自己发出去` : ''}${auto.length && hand.length ? '；' : ''}${hand.length ? `<b>${hand.join('、')}</b> 备好，你来点（公众号群发、视频号和小红书扫码上传）` : ''}。</p>
      <div class="btns"><button class="btn go" type="button" data-bf-go="${p.topic_id}">发这条</button><button class="btn" type="button" data-td-go="pack/${p.topic_id}">去改 →</button></div>
    </div>`;
}

function todayPack(t) {
  const JOB = { running: '发送中…', done: '已发出', failed: '失败了', awaiting_confirm: '等确认' };
  const cells = t.missing.concat(Object.keys(PF).filter((k) => !t.missing.includes(k) && k in PF)).filter((k, i, a) => a.indexOf(k) === i);
  const cell = (k) => {
    const shipped = !t.missing.includes(k);
    const j = (t.jobs || {})[k];
    const state = shipped ? '✓ 发了' : j ? (j.draft ? '草稿好了，去点发布' : JOB[j.state] || j.state) : AUTO.includes(k) ? '—' : '等你';
    return `<span class="td-plat ${shipped ? 'on' : j && j.state === 'failed' ? 'bad' : ''}" title="${esc((j && j.message) || '')}">${PF[k]} · ${state}</span>`;
  };
  return `<div class="td-next"><b>今天补发《${esc(t.title)}》：${t.done_count}/${t.total}</b>
      <div class="td-plats">${cells.map(cell).join('')}</div>
      <small>剩下的去发布台：公众号群发，视频号、小红书的上传文件夹里视频、封面、文案都齐了。</small>
      <div class="btns"><button class="btn go" type="button" data-td-go="publish/${t.topic_id}">去发布台 →</button><button class="btn quiet" type="button" data-bf-unpick>换一条</button></div></div>`;
}

function backfillRow(d) {
  const b = d.backfill;
  const done = b.today && b.today.missing.length === 0;
  const list = b.ready.slice(0, TD.bfAll ? 50 : 3).map(packRow).join('');
  const state = `<span class="td-state ${done ? 'ok' : ''}">${done ? '✓ 今天补完了' : b.today ? '今天在补' : `不算分 · 包打好 ${b.ready_count} 条${b.waiting_count ? ` · 还在打 ${b.waiting_count} 条` : ''}`}</span>`;
  return tdRow('bf', 'E', '补发', done, state, `
    <p class="td-why">没拍新视频的日子，挑一条旧的发到剩下的平台。B 站、YouTube、X 自己发出去；公众号、视频号、小红书你来点，十几分钟。</p>
    ${b.today ? todayPack(b.today) : ''}
    ${!b.today || done ? `<div class="td-packs">${list || '<p class="td-note">还没有打好的包。</p>'}</div>
      ${b.ready.length > 3 ? `<button class="btn quiet" type="button" data-bf-all>${TD.bfAll ? '只看前三条' : `看全部 ${b.ready.length} 条`}</button>` : ''}` : ''}`, !!(b.today && !done) || TD.bfOpen != null);
}

function wrapBlock(d) {
  const rows = d.wrap.map((it) => `<div class="td-next small"><b>${esc(it.text)}</b>${actionButtons(it)}</div>`).join('');
  const skipped = d.skipped.map((s) => `<div class="td-q skip"><span class="n">跳</span><b>${esc(s.key)}</b><small>${esc(s.reason || '')}</small></div>`).join('');
  if (!rows && !skipped) return '';
  return `<section class="td-wrap"><h3>杂事</h3>${rows}${skipped}</section>`;
}

async function tdAct(fn) {
  try { await fn(); } catch (err) { toast(err.message); }
  TD.skipOpen = false;
  $('#todayBody').dataset.sig = '';
  window.VIEWS.today.render();
}

function goHash(h) { location.hash = '#' + h; go(readHash(), { push: false }); }

window.VIEWS.today = {
  async render() {
    const body = $('#todayBody');
    let d;
    try { [d, TD.wendy] = await Promise.all([loadToday(), api('/api/wendy').catch(() => null)]); } catch (err) { body.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`; return; }
    paintTodayBadge();
    $('#todayDay').textContent = `今天 · ${dayTitle(d.day)}`;
    const wd = d.week;
    $('#todayScore').textContent = '';  // 本周出摊几天、减几分、连续几天：都在周历右上角，这里不再重复
    if (document.activeElement && body.contains(document.activeElement) && document.activeElement.matches('input:not([type=checkbox])')) return;
    // 周历翻到了别的周：那一周单独取；本周就用「今天」带回来的那份
    if (TD.weekStart && TD.weekStart !== wd.start) {
      try { TD.week = await api(`/api/today/week?start=${TD.weekStart}`); } catch (err) { toast(err.message); TD.weekStart = null; TD.week = wd; }
    } else { TD.weekStart = null; TD.week = wd; }
    const sig = JSON.stringify([d, TD.wendy, TD.wdOlder, TD.week, TD.sel, [...TD.openRows], TD.skipOpen, TD.bfOpen, TD.prev && TD.prev.topic_id, TD.bfAll]);
    if (body.dataset.sig === sig) return;
    body.dataset.sig = sig;
    body.innerHTML = `${wendyCard(TD.wendy)}${weekBlock(TD.week, d.streak, d.ship.notes)}${firstBlock(d.first)}${readRow(d)}${shipRow(d)}${dmRow(d)}${xrRow(d)}${backfillRow(d)}${wrapBlock(d)}
      <p class="td-note td-foot">触达是结果，不算你的分，在「已发出」里看：7 天平均 ${fmt(d.reach.avg7 || 0)} / 目标 ${fmt(d.reach.target)}（${esc(d.reach.by.slice(5).replace('-', '/'))} 前）。</p>`;

    $$('[data-td-go]', body).forEach((b) => (b.onclick = () => goHash(b.dataset.tdGo)));
    $$('[data-td-done]', body).forEach((b) => (b.onclick = () => tdAct(() => api('/api/today/done', { method: 'POST', body: { key: b.dataset.tdDone } }))));
    $$('[data-td-start]', body).forEach((b) => (b.onclick = () => tdAct(async () => { const r = await api(`/api/today/notes/${b.dataset.tdStart}/start`, { method: 'POST' }); goHash(`work/${r.topic.id}`); })));
    $$('[data-td-focusnotes]', body).forEach((b) => (b.onclick = () => { const dt = $('.td-notes', body); if (dt) dt.open = true; $('#tdAddText').focus(); }));
    $$('[data-td-skip]', body).forEach((b) => (b.onclick = () => { TD.skipOpen = b.dataset.tdSkip; body.dataset.sig = ''; this.render().then(() => { const i = $('[data-skip-form] input', body); if (i) i.focus(); }); }));
    $$('[data-td-skipcancel]', body).forEach((b) => (b.onclick = () => { TD.skipOpen = false; body.dataset.sig = ''; this.render(); }));
    $$('[data-skip-form]', body).forEach((f) => (f.onsubmit = (e) => { e.preventDefault(); tdAct(() => api('/api/today/skip', { method: 'POST', body: { key: f.dataset.skipForm, reason: $('input', f).value } })); }));
    const again = () => { body.dataset.sig = ''; this.render(); };
    $$('[data-row-toggle]', body).forEach((h) => {
      const flip = (e) => { if (e.target.closest('button, a, input, form')) return; const k = h.dataset.rowToggle; if (TD.openRows.has(k)) TD.openRows.delete(k); else TD.openRows.add(k); if (k === 'bf') TD.bfOpen = null; again(); };
      h.onclick = flip;
      h.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); flip(e); } };
    });
    const say = (message) => tdAct(async () => { const r = await api('/api/wendy', { method: 'POST', body: { message } }); if (!r.started) toast(r.message); });
    const wdForm = $('#wdForm');
    if (wdForm) {
      wdForm.onsubmit = (e) => { e.preventDefault(); const i = $('#wdText'); const text = i.value.trim(); if (!text) return; i.value = ''; i.blur(); say(text); };
      $('#wdLook').onclick = () => say('');
    }
    $$('[data-wd-older]', body).forEach((b) => (b.onclick = () => { TD.wdOlder = !TD.wdOlder; again(); }));
    $$('[data-wd-row]', body).forEach((b) => (b.onclick = () => { const r = $(`[data-row="${b.dataset.wdRow}"]`, body); if (r) { r.scrollIntoView({ behavior: 'smooth', block: 'center' }); const f = $('input, button.go', r); if (f) f.focus({ preventScroll: true }); } }));
    $$('[data-wk-go]', body).forEach((b) => (b.onclick = () => { TD.weekStart = b.dataset.wkGo || null; TD.sel = null; again(); }));
    $$('[data-wk-day]', body).forEach((b) => (b.onclick = () => { TD.sel = TD.sel === b.dataset.wkDay ? null : b.dataset.wkDay; again(); }));
    $$('[data-wk-plan]', body).forEach((f) => (f.onsubmit = (e) => {
      e.preventDefault();
      const text = $('input', f).value.trim();
      if (!text) return;
      $('input', f).value = '';
      const hit = d.ship.notes.find((n) => !n.planned_day && n.text === text);  // 清单里已经有这条：排上日子；没有：新写一条
      tdAct(() => (hit ? api(`/api/today/notes/${hit.id}`, { method: 'PATCH', body: { planned_day: f.dataset.wkPlan } })
        : api('/api/today/notes', { method: 'POST', body: { text, planned_day: f.dataset.wkPlan } })));
    }));
    $$('[data-wk-unplan]', body).forEach((b) => (b.onclick = () => tdAct(() => api(`/api/today/notes/${b.dataset.wkUnplan}`, { method: 'PATCH', body: { planned_day: '' } }))));
    $$('[data-wk-item]', body).forEach((f) => (f.onsubmit = (e) => {
      e.preventDefault();
      const text = $('input', f).value.trim();
      if (!text) return;
      $('input', f).value = '';
      tdAct(() => api('/api/today/plan', { method: 'POST', body: { day: f.dataset.wkItem, text } }));
    }));
    $$('[data-wk-done]', body).forEach((c) => (c.onchange = () => tdAct(() => api(`/api/today/plan/${c.dataset.wkDone}`, { method: 'PATCH', body: { done: c.checked } }))));
    $$('[data-wk-del]', body).forEach((b) => (b.onclick = () => tdAct(() => api(`/api/today/plan/${b.dataset.wkDel}`, { method: 'DELETE' }))));
    const dmForm = $('#tdDm'), xrForm = $('#tdXr'), addForm = $('#tdAdd');  // 做完的行收起来以后，这几个表单不在页面上
    if (dmForm) dmForm.onsubmit = (e) => {
      e.preventDefault();
      if ($('#tdDmRecv').value === '' || $('#tdDmRep').value === '') { toast('两个数都填上，0 也算'); return; }
      tdAct(() => api('/api/today/dm', { method: 'PUT', body: { received: Number($('#tdDmRecv').value), replied: Number($('#tdDmRep').value) } }));
    };
    if (xrForm) xrForm.onsubmit = (e) => {
      e.preventDefault();
      if ($('#tdXrN').value === '') { toast('填今天回了几条，0 也算'); return; }
      tdAct(() => api('/api/today/x-replies', { method: 'PUT', body: { value: Number($('#tdXrN').value) } }));
    };
    if (addForm) addForm.onsubmit = (e) => { e.preventDefault(); const text = $('#tdAddText').value.trim(); if (!text) return; $('#tdAddText').value = ''; tdAct(() => api('/api/today/notes', { method: 'POST', body: { text } })); };
    $$('[data-note-up]', body).forEach((b) => (b.onclick = () => tdAct(() => api(`/api/today/notes/${b.dataset.noteUp}`, { method: 'PATCH', body: { move: -1 } }))));
    $$('[data-note-down]', body).forEach((b) => (b.onclick = () => tdAct(() => api(`/api/today/notes/${b.dataset.noteDown}`, { method: 'PATCH', body: { move: 1 } }))));
    $$('[data-note-del]', body).forEach((b) => (b.onclick = () => tdAct(() => api(`/api/today/notes/${b.dataset.noteDel}`, { method: 'DELETE' }))));
    $$('[data-rd-open]', body).forEach((b) => (b.onclick = () => { if (window.openInputTab) window.openInputTab(b.dataset.rdOpen); else go('input'); }));
    const check = (key, checked) => api('/api/today/checks', { method: 'PUT', body: { day: d.day, key, checked } });
    $$('[data-rd-done]', body).forEach((b) => (b.onclick = () => tdAct(() => check(b.dataset.rdDone, true))));
    $$('[data-rd-undo]', body).forEach((b) => (b.onclick = () => tdAct(() => check(b.dataset.rdUndo, false))));
    $$('[data-bf-open]', body).forEach((b) => (b.onclick = async () => {
      const id = Number(b.dataset.bfOpen);
      TD.bfOpen = TD.bfOpen === id ? null : id;
      body.dataset.sig = '';
      this.render();
      if (TD.bfOpen && !(TD.prev && TD.prev.topic_id === id)) {
        try { TD.prev = await api(`/api/today/backfill/${id}/preview`); } catch (err) { toast(err.message); }
        body.dataset.sig = '';
        this.render();
      }
    }));
    $$('[data-bf-go]', body).forEach((b) => (b.onclick = () => tdAct(async () => {
      b.disabled = true;
      const r = await api(`/api/today/backfill/${b.dataset.bfGo}/go`, { method: 'POST' });
      TD.bfOpen = null;
      toast(r.errors.length ? `有 ${r.errors.length} 个没起来：${r.errors[0]}` : '发出去了的在发，剩下的备好了');
    })));
    const unpick = $('[data-bf-unpick]', body);
    if (unpick) unpick.onclick = () => tdAct(() => api('/api/today/backfill', { method: 'DELETE' }));
    const all = $('[data-bf-all]', body);
    if (all) all.onclick = () => { TD.bfAll = !TD.bfAll; body.dataset.sig = ''; this.render(); };
    const sugBtn = $('#tdSuggest');
    if (sugBtn) sugBtn.onclick = () => tdAct(() => api('/api/today/suggest', { method: 'POST' }));
    const take = $('#tdTake');
    if (take) take.onclick = () => tdAct(() => api('/api/today/suggest/take', { method: 'POST' }));

    clearTimeout(TD.poll);
    const sending = d.backfill.today && Object.values(d.backfill.today.jobs || {}).some((j) => j.state === 'running');
    const thinking = TD.wendy && TD.wendy.busy;
    if ((d.ship.suggest && d.ship.suggest.running) || sending || thinking) TD.poll = setTimeout(() => { if (S.view === 'today') this.render(); }, sending && !thinking ? 8000 : 3000);
  },
};
