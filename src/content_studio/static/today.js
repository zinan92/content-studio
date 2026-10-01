'use strict';
/* 今天：最上面是月历（10/1 起，原来是周历）（9/30 Park：「plan not just for one day, I can plan for the whole week」「每天扣了多少分，
 * I'm not even keeping count」），下面是 ABC 几件事（逻辑在 driver.py）。
 * 周历：过去的日子看算分的几项做没做到、减几分、发了哪条；今天和以后排哪天拍哪条、加不算分的事。排哪条只由他定。
 * 做完的行收成一行；每行原来那串 7 天小圆点拿掉了，周历里有。
 * A 读日报（9/30）；B 出摊：抖音、视频号、小红书发视频，X、公众号发文字；C 回私信；D X 互动，回 20 条。
 * E「整条补发」10/1 拿掉了：补发全走补发工作台（backfilldesk.js），他看当天的情绪自己挑格子。
 * 没做到当天各减 1 分，左边栏一直显示。触达是结果，不在这一页看（在「已发出」）。
 * 9/29 Park：「你只需要告诉我，我今天要做的 ABC 三件事就好了……感觉今天这个页面太散了。」
 * 拍什么他定：「接下来要拍的」收在 A 里面；只有他点「我今天不知道拍什么」才建议。 */
window.VIEWS = window.VIEWS || {};

const TD = { data: null, poll: null, skipOpen: false, month: null, monthStart: null, sel: null, openRows: new Set(), wendy: null, wdOlder: false };

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

/* 卡片上的回复框、「让她看一眼」、「看之前的」：今天页和定位页共用。page 告诉她你在哪一页回的她。 */
function bindWendy(root, page, redraw) {
  const say = async (message) => {
    try { const r = await api('/api/wendy', { method: 'POST', body: { message, page } }); if (!r.started) toast(r.message); } catch (err) { toast(err.message); }
    redraw();
  };
  const form = $('[data-wd-form]', root);
  if (form) {
    form.onsubmit = (e) => { e.preventDefault(); const i = $('input', form); const text = i.value.trim(); if (!text) return; i.value = ''; i.blur(); say(text); };
    $('[data-wd-look]', root).onclick = () => say('');
  }
  $$('[data-wd-older]', root).forEach((b) => (b.onclick = () => { TD.wdOlder = !TD.wdOlder; redraw(); }));
}

/* 定位页最上面也放她（10/1 Park：Wendy 在「今天」和「我是谁、找到谁、卖什么」；Anna 在进项到发布那几页） */
window.mountWendy = async (el, page) => {
  if (!el) return;
  const draw = async () => {
    if (document.activeElement && el.contains(document.activeElement) && document.activeElement.matches('input')) return;
    let w;
    try { w = await api('/api/wendy'); } catch (err) { el.innerHTML = ''; return; }
    el.innerHTML = wendyCard(w, page);
    bindWendy(el, page, draw);
    if (w.busy) setTimeout(() => { if (document.body.contains(el)) draw(); }, 3000);
  };
  draw();
};

/* 现在在哪个阶段（9/30 Park：追平——发送连贯起来，过去没发的都发出去） */
function stageLine(st) {
  if (!st) return '';
  return `<span class="wd-stage ${st.done ? 'done' : ''}" title="出关：旧内容清完，并且连续出摊 ${st.streak_target} 天。下一阶段：${esc(st.next)}">${esc(st.label)}阶段 · 旧内容还剩 <b>${st.backlog}</b> 格 · 连续出摊 <b>${st.streak}</b>/${st.streak_target} 天${st.done ? ' · 可以出关了' : ''}</span>`;
}

function wendyCard(w, page = 'today') {
  if (!w) return '';
  const pos = page === 'positioning';  // 定位页：聊方向，不放「现在做这一件」
  const n = w.now;
  let act = '';
  if (n) act = ['rd', 'dm', 'xr'].includes(n.row) ? `<div class="btns"><button class="btn go" type="button" data-wd-row="${n.row}">去做 ↓</button></div>` : actionButtons(n);
  const msgs = w.messages, shown = TD.wdOlder ? msgs : msgs.slice(-2);  // 平时只看最近两条，最新那条完整显示
  return `<section class="wd">
    <div class="wd-h"><span class="wd-av">W</span><b>Wendy</b><small>${pos ? '你的老板 · 方向你拍板，她提案、守住' : '你的老板 · 盯你做没做到'}</small>${pos ? '' : stageLine(TD.data && TD.data.stage)}${!pos && w.nudges.length ? `<span class="wd-nudged">今天在微信催过你 ${w.nudges.length} 次</span>` : ''}</div>
    ${pos ? '' : `<div class="wd-now"><span class="k">现在做这一件</span>${n ? `<b>${esc(n.text)}</b>${n.why ? `<small>${esc(n.why)}</small>` : ''}${act}` : '<b>今天算分的事都做完了。</b><small>明天拍哪条，在上面的月历里排上。</small>'}</div>`}
    <div class="wd-thread">${msgs.length > 2 ? `<button type="button" class="linklike wd-older" data-wd-older>${TD.wdOlder ? '只看最近两条' : `看之前的 ${msgs.length - 2} 条`}</button>` : ''}
      ${shown.map((m, i) => wdMsg(m, !TD.wdOlder && i < shown.length - 1)).join('') || '<p class="td-note">她还没说过话。早上 9:45 和晚上 22:30 她会来；你也可以现在让她看一眼。</p>'}
      ${w.busy ? '<p class="td-note"><span class="spin"></span> Wendy 在看工作台…不到一分钟</p>' : ''}${w.error ? `<p class="td-note warn">${esc(w.error)}</p>` : ''}</div>
    <form class="wd-form" data-wd-form><input maxlength="2000" placeholder="${pos ? '跟她聊方向：三问里哪一问还不够窄、我到底该做什么…' : '回她一句：几点做、为什么没做、做完了…'}" autocomplete="off" ${w.busy ? 'disabled' : ''}>
      <button class="btn go" type="submit" ${w.busy ? 'disabled' : ''}>${pos ? '问她' : '回她'}</button><button class="btn quiet" type="button" data-wd-look ${w.busy ? 'disabled' : ''}>${pos ? '让她看一眼这一页' : '让她看一眼现在'}</button></form>
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

const PF_SHORT = { channels: '视', xiaohongshu: '红', x: 'X', bilibili: 'B', youtube: 'Y', wechat_mp: '公', miniprogram: '程', xiaoyuzhou: '宙' };

/* 平台的小图标：和左下角那排同一套（字和品牌色从 S.platforms 来） */
function platIcon(key, size = 'sm') {
  const p = ((typeof S !== 'undefined' && S.platforms) || []).find((x) => x.key === key) || {};
  return `<span class="plat ${size}" style="--plat:${esc(p.hue || '#3A3F47')}" title="${esc(p.label || key)}"><i>${esc(p.mark || PF_SHORT[key] || key.slice(0, 1))}</i></span>`;
}

/* 那天发出去的：同一条内容只写一次标题，后面跟发到的平台图标（10/1 Park：「不要占这么大的 space」） */
function sentByTitle(sent) {
  const groups = [];
  for (const x of sent || []) {
    let g = groups.find((y) => y.title === x.title);
    if (!g) groups.push((g = { title: x.title, keys: [] }));
    if (!g.keys.includes(x.platform)) g.keys.push(x.platform);
  }
  return groups.map((g) => `<p class="wk-sent"><span class="t" title="${esc(g.title)}">《${esc(g.title)}》</span><span class="ic">${g.keys.map((k) => platIcon(k)).join('')}</span></p>`).join('');
}
const headline = (t) => String(t || '').split(/\s+/)[0].slice(0, 28);

/* 月历的一格：过去的日子——四项做没做到、减几分、发了什么、发到了哪些平台；以后的日子——排了拍哪条 */
function monthCell(c) {
  const marks = c.state === 'future' ? '' : `<span class="mo-marks">${KPI_MARK.map(([f, ch, name]) => `<i class="${c[f] === 'n/a' ? 'na' : c[f]}" title="${name}：${MARK_TIP[c[f]]}">${ch}</i>`).join('')}</span>`;
  const score = c.state === 'today' ? '<span class="wk-score now">今天</span>' : c.demerits ? `<span class="wk-score bad">−${c.demerits}</span>` : c.state === 'past' && KPI_MARK.some(([f]) => c[f] === 'ok') ? '<span class="wk-score ok">✓</span>' : '';
  const where = [...new Set(c.sent.map((x) => x.platform))];
  const lines = [
    ...c.shipped.slice(0, 1).map((t) => `<span class="wk-l out" title="${esc(c.shipped.join('；'))}">新：${esc(headline(t))}</span>`),
    ...(where.length ? [`<span class="mo-sent" title="${esc(c.sent.map((x) => `${x.label}：${x.title}`).join('\n'))}">${where.map((k) => platIcon(k, 'xs')).join('')}</span>`] : c.backfilled ? ['<span class="wk-l out">补发完成</span>'] : []),
    ...c.planned.filter((n) => !n.done).slice(0, 1).map((n) => `<span class="wk-l ${c.state === 'past' ? 'late' : 'plan'}" title="${esc(n.text)}">${c.state === 'past' ? '没拍' : '拍'}：${esc(n.text)}</span>`),
    ...(c.items.some((it) => !it.done) ? [`<span class="wk-l item">· ${c.items.filter((it) => !it.done).length} 件别的事</span>`] : []),
  ];
  // 10/1 Park：过去的一天整格上色——没减分或只减 1 分算合格（绿），减 2 分及以上不合格（红）。还没开始算分的日子不上色。
  const scored = c.state === 'past' && KPI_MARK.some(([f]) => c[f] === 'ok' || c[f] === 'miss');
  const verdict = scored ? (c.demerits >= 2 ? 'mo-fail' : 'mo-pass') : '';
  return `<button type="button" class="mo-day ${c.state} ${verdict} ${c.in_month ? '' : 'out'} ${TD.sel === c.day ? 'sel' : ''}" data-wk-day="${c.day}" aria-pressed="${TD.sel === c.day}">
    <span class="wk-d"><b>${Number(c.day.slice(8))}</b>${score}</span>${marks}${lines.join('')}</button>`;
}

/* 点开某一天：过去的日子看那天的账；今天和以后排拍哪条、加不算分的事 */
function dayPanel(c, notes) {
  const title = `<b>${dow(c.day)} ${md(c.day)}</b>`;
  const chk = (it) => `<label class="wk-item ${it.done ? 'done' : ''}"><input type="checkbox" data-wk-done="${it.id}" ${it.done ? 'checked' : ''}><span>${esc(it.text)}</span><button type="button" class="linklike" data-wk-del="${it.id}" aria-label="删掉">×</button></label>`;
  const items = `<div class="wk-col"><h4>别的事 <small>不算分</small></h4>${c.items.map(chk).join('')}
      <form class="td-add" data-wk-item="${c.day}"><input maxlength="200" placeholder="这天还要做什么，回车加上（比如：约两个博主诊断）" autocomplete="off"></form></div>`;
  if (c.state === 'past') {
    const RES = { ok: '做到', miss: '没做到，减 1 分', 'n/a': '那天还不算分' };
    const det = { rd: '', ship: c.backfilled ? '：没发新的，补发的格子都发完了' : c.shipped.length ? `：${c.shipped.map((t) => `《${esc(headline(t))}》`).join('、')}` : '',
      dm: c.dm_entry ? `：收到 ${c.dm_entry.received}，回了 ${c.dm_entry.replied}` : c.dm === 'miss' ? '（没填数）' : '',
      xr: c.xr_count != null ? `：${c.xr_count} 条` : c.xr === 'miss' ? '（没填数）' : '' };
    return `<div class="wk-panel"><div class="wk-ph">${title}<span class="wk-score ${c.demerits ? 'bad' : 'ok'}">${c.demerits ? `这天减 ${c.demerits} 分` : '这天没减分'}</span></div>
      <div class="wk-cols"><div class="wk-col"><h4>那天的账</h4>${KPI_MARK.map(([f, , name]) => `<p class="wk-res ${c[f] === 'n/a' ? 'na' : c[f]}"><b>${name}</b>${RES[c[f]]}${det[f]}</p>`).join('')}
        ${(c.sent || []).length ? `<h4 class="wk-sub">发到了</h4>${sentByTitle(c.sent)}` : ''}
        ${c.planned.filter((n) => !n.done).map((n) => `<p class="wk-res miss"><b>排了没拍</b>${esc(n.text)}</p>`).join('')}
        ${c.skips.map((k) => `<p class="wk-res na"><b>跳过</b>${esc(k.what)}：${esc(k.reason || '')}</p>`).join('')}</div>${items}</div></div>`;
  }
  const free = notes.filter((n) => !n.planned_day);
  const planned = c.planned.map((n) => `<span class="wk-chip ${n.done ? 'done' : ''}">${esc(n.text)}${n.done ? '' : `<button type="button" class="linklike" data-wk-unplan="${n.id}" aria-label="不排在这天">×</button>`}</span>`).join('');
  return `<div class="wk-panel"><div class="wk-ph">${title}<span class="td-note">${c.state === 'today' ? '今天' : '排这一天'}</span></div>
    <div class="wk-cols"><div class="wk-col"><h4>这天拍哪条 <small>你定</small></h4>${planned || '<p class="td-note">还没排。</p>'}${(c.sent || []).length ? `<h4 class="wk-sub">这天已经发出去</h4>${sentByTitle(c.sent)}` : ''}
      <form class="td-add" data-wk-plan="${c.day}"><input list="wkNotes" maxlength="200" placeholder="从「接下来要拍的」里挑一条，或者直接写一条新的，回车" autocomplete="off">
        <datalist id="wkNotes">${free.map((n) => `<option value="${esc(n.text)}"></option>`).join('')}</datalist></form></div>${items}</div></div>`;
}

function monthBlock(m, w, streak, notes) {
  const days = m.weeks.flatMap((x) => x.days);
  const sel = days.find((c) => c.day === TD.sel);
  // 右上角是这一周的账（周一到周日）：出摊几天、减几分、新视频几条、连续几天
  const sum = [w.ship_days ? `本周出摊 <b class="${w.shipped === w.ship_days ? 'ok' : ''}">${w.shipped}/${w.ship_days}</b> 天` : '', w.demerits ? `减 <b>${w.demerits}</b> 分` : w.ship_days ? '<b class="ok">没减分</b>' : '',
    w.new_target ? `新视频 <b class="${w.new_videos >= w.new_target ? 'ok' : ''}">${w.new_videos}/${w.new_target}</b> 条` : '', streakText(streak)].filter(Boolean).join(' · ');
  const [y, mo] = m.month.split('-').map(Number);
  return `<section class="wk">
    <div class="wk-h"><span class="wk-nav"><button type="button" class="btn small" data-mo-go="${m.prev}" aria-label="上个月">‹</button><b>${y} 年 ${mo} 月</b><button type="button" class="btn small" data-mo-go="${m.next}" aria-label="下个月">›</button>${m.current ? '' : '<button type="button" class="btn small quiet" data-mo-go="">回到这个月</button>'}</span>
      <span class="wk-sum">${sum}</span></div>
    <div class="mo-grid">${['周一', '周二', '周三', '周四', '周五', '周六', '周日'].map((x) => `<span class="mo-dow">${x}</span>`).join('')}${days.map(monthCell).join('')}</div>
    ${sel ? dayPanel(sel, notes) : '<p class="td-note wk-hint">绿色是合格（没减分或只减 1 分），红色是减了 2 分以上。点某一天：过去的看那天的账和发到了哪些平台，今天和以后的排拍哪条、加别的事。格子里的字母是平台：视频号、红（小红书）、X、B 站、Y（YouTube）、公众号。</p>'}
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
  // 早上那个问题：今天发不发新视频。两条路都算今天出摊。
  if (it.inputs === 'mode') return '<div class="btns"><button class="btn go" type="button" data-out-mode="new">今天发新视频</button><button class="btn go" type="button" data-out-mode="backfill">今天不发，补发旧内容</button></div>';
  // 补发：挑格子、看发到哪了、传完点「发了」，都在补发工作台
  if (it.inputs === 'bw') return '<div class="btns"><button class="btn go" type="button" data-bw-open>打开补发工作台</button></div>';
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
  /* 9/30 Park：每天要么发一条新视频，要么补发几格旧内容，两条路都算出摊。早上先选（随时能改）；算分只看结果。
     10/1 Park：补哪几格不再随机抽，他在补发工作台看当天的情绪自己挑，确认后现场按顺序发。 */
  const o = d.out, done = d.days[d.days.length - 1].ship === 'ok';
  const mode = s.done ? 'new' : o.mode;
  const pick = (o.cells.length || o.left) && !s.done ? `<div class="td-mode" role="group" aria-label="今天怎么出摊">
      <button type="button" class="${mode === 'new' ? 'on' : ''}" data-out-mode="new">今天发新视频</button>
      <button type="button" class="${mode === 'backfill' ? 'on' : ''}" data-out-mode="backfill">今天不发，补发旧内容</button>
      ${mode ? '' : '<small>先选一条路。两条都算今天出摊。</small>'}</div>` : '';
  const cells = o.cells.map((c) => `<div class="td-cell ${c.sent ? 'sent' : ''}">
      <span class="tier ${c.tier}">${c.tier === 'major' ? '重要' : '次要'}</span><b>${esc(c.label)}</b><span class="t">《${esc(c.title)}》</span>
      ${c.sent ? '<span class="ok">✓ 发了</span>' : '<span class="td-note">还没发出去</span>'}
    </div>`).join('');
  const short = Math.max(0, o.need - o.cells.length);
  const fill = `<div class="td-cells"><p class="td-note">${o.cells.length ? `今天挑了 ${o.cells.length} 格，已发 ${o.sent} 格${short ? `，还要再挑 ${short} 格才算出摊` : ''}。` : `看今天大家的情绪，在补发工作台挑 ${o.need} 格，确认后现场发。`}全平台追踪里一共还剩 ${o.left} 格。</p>${cells}
    <div class="btns"><button class="btn go" type="button" data-bw-open>打开补发工作台</button>${o.running ? '<span class="td-note"><span class="spin"></span> 正在一格一格发</span>' : ''}</div></div>`;
  const state = done ? rowState(true, s.done ? (s.topic ? `《${esc(s.topic.title.slice(0, 18))}》` : '发了新视频') : `补发的 ${o.cells.length} 格都发完了`) : rowState(false);
  return tdRow('ship', 'B', '出摊', done, state, `
    ${pick}
    ${mode === 'backfill' ? fill : `<div class="td-plats">${s.topic ? `<span class="td-topic">《${esc(s.topic.title)}》</span>` : ''}${groups.map(([f, ps]) => `<span class="td-form">${FORM[f]}</span>${ps.map(plat).join('')}`).join('')}</div>
    ${nextLine(s.next)}`}
    <details class="td-notes" ${s.notes.length || mode === 'backfill' ? '' : 'open'}><summary>接下来要拍的 · 你定${s.notes.length ? ` <span class="num">${s.notes.length}</span>` : ''}</summary>
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
    let month;
    try { [d, TD.wendy, month] = await Promise.all([loadToday(), api('/api/wendy').catch(() => null), api(`/api/today/month${TD.monthStart ? `?start=${TD.monthStart}` : ''}`).catch(() => null)]); } catch (err) { body.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`; return; }
    paintTodayBadge();
    $('#todayDay').textContent = `今天 · ${dayTitle(d.day)}`;
    const wd = d.week;
    $('#todayScore').textContent = '';  // 本周出摊几天、减几分、连续几天：都在周历右上角，这里不再重复
    if (document.activeElement && body.contains(document.activeElement) && document.activeElement.matches('input:not([type=checkbox])')) return;
    if (month) TD.month = month;
    const sig = JSON.stringify([d, TD.wendy, TD.wdOlder, TD.month, TD.sel, [...TD.openRows], TD.skipOpen]);
    if (body.dataset.sig === sig) return;
    body.dataset.sig = sig;
    body.innerHTML = `${TD.month ? monthBlock(TD.month, d.week, d.streak, d.ship.notes) : ''}${wendyCard(TD.wendy)}${firstBlock(d.first)}${readRow(d)}${shipRow(d)}${dmRow(d)}${xrRow(d)}${wrapBlock(d)}
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
      const flip = (e) => { if (e.target.closest('button, a, input, form')) return; const k = h.dataset.rowToggle; if (TD.openRows.has(k)) TD.openRows.delete(k); else TD.openRows.add(k); again(); };
      h.onclick = flip;
      h.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); flip(e); } };
    });
    bindWendy(body, 'today', again);
    $$('[data-wd-row]', body).forEach((b) => (b.onclick = () => { const r = $(`[data-row="${b.dataset.wdRow}"]`, body); if (r) { r.scrollIntoView({ behavior: 'smooth', block: 'center' }); const f = $('input, button.go', r); if (f) f.focus({ preventScroll: true }); } }));
    $$('[data-mo-go]', body).forEach((b) => (b.onclick = () => { TD.monthStart = b.dataset.moGo || null; TD.sel = null; again(); }));
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
    // 早上那个问题（卡片上和「出摊」行里都有）：今天发新视频还是补发。#347 搬月历时把这两行弄丢了，10/1 补回来。
    $$('[data-out-mode]', body).forEach((b) => (b.onclick = () => tdAct(async () => {
      await api('/api/today/mode', { method: 'POST', body: { mode: b.dataset.outMode } });
      if (b.dataset.outMode === 'backfill' && window.openBackfillDesk && confirm('今天补发。现在打开补发工作台，挑今天发哪几格？')) window.openBackfillDesk();
    })));
    $$('[data-bw-open]', body).forEach((b) => (b.onclick = () => { if (window.openBackfillDesk) window.openBackfillDesk(); }));
    const sugBtn = $('#tdSuggest');
    if (sugBtn) sugBtn.onclick = () => tdAct(() => api('/api/today/suggest', { method: 'POST' }));
    const take = $('#tdTake');
    if (take) take.onclick = () => tdAct(() => api('/api/today/suggest/take', { method: 'POST' }));

    clearTimeout(TD.poll);
    const sending = d.out.running;  // 补发工作台在一格一格发：隔一会儿看一眼
    const thinking = TD.wendy && TD.wendy.busy;
    if ((d.ship.suggest && d.ship.suggest.running) || sending || thinking) TD.poll = setTimeout(() => { if (S.view === 'today') this.render(); }, sending && !thinking ? 8000 : 3000);
  },
};
