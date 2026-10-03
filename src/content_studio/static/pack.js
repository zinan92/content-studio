'use strict';
/* 03 打包：发之前把一条内容要的东西全备好，发布台那边就只剩一个个平台点出去。

   10/2 Park：「真正需要我 input 的就是标题……封面、插图、排版我都不需要审核。」
   「把它当成一个成熟的 SaaS：用户一看就知道点哪里，思考负担降到最低，而且要有视觉焦点。」

   所以这一页只有三段，任何时候只有一个主按钮：
     ① 定标题 —— 机器先出一批候选，点一条或自己写，点「用这个标题，开始准备」。
     ② 自动准备 —— 封面、X 图文、插图、公众号排版（小红书选了图文还有小红书图文）一步接一步做完、
        自动定稿（服务端 pack_auto.py，关了页面也接着做）。每一行能展开看、能改；失败了只给一个「重试」。
     ③ 发出去 —— 全好了才亮：还没发抖音就先发抖音、对上作品；发了就直接打开补发工作台挑其余平台。
   描述和话题已经自动填好，收在最下面，想改再打开。
   不再列别的视频（9/29 版顶上那排《为什么AI重度用户全体考公》这类，10/2 Park：分心）。 */
window.VIEWS = window.VIEWS || {};

const PK = { data: null, topic: null, view: null, at: 0, timer: null, editTitle: false, douyinNow: false, titlesAsked: new Set(), open: new Set() };

async function loadPack(force) {
  if (!force && PK.data && (!S.packId || (PK.data.topic && PK.data.topic.id === S.packId)) && Date.now() - PK.at < 15000) return PK.data;
  const d = await api('/api/publish/desk' + (S.packId ? `?topic_id=${S.packId}` : ''));
  PK.data = d; PK.at = Date.now();
  if (d.topic) {
    S.packId = d.topic.id;
    const [view, topics] = await Promise.all([api(`/api/topics/${d.topic.id}/pack`), api('/api/topics')]);
    PK.view = view;
    PK.topic = topics.find((x) => x.id === d.topic.id) || null;
  } else { PK.view = null; PK.topic = null; }
  paintPackNav(d);
  return d;
}
window.invalidatePack = () => { PK.data = null; PK.at = 0; const b = $('#packBody'); if (b) b.dataset.sig = ''; };

/* 导轨上的数：有成片、还没打包好的条数 */
function paintPackNav(d) {
  const el = $('#navPack');
  if (!el) return;
  const n = d.topic && packMissing(d).length && !(d.platforms || []).some((p) => p.shipped) ? 1 : 0;
  el.textContent = n ? String(n) : '';
}
window.refreshPackNav = async () => { try { paintPackNav(await api('/api/publish/desk')); } catch (_) { /* rail count only */ } };

const locked = (d, key) => { const a = ((d && d.approvals) || {})[key]; return Boolean(a && a.approved && a.valid); };
window.packLocked = locked;

/* 子块（配图、排版、小红书）自己在轮询：它们一变，这里重新问一次自动档 */
window.prepTick = () => { if (S.view === 'pack' && PK.view && PK.view.busy) schedule(1500); };
window.rerenderPackRow = (key) => { const box = $(`#pkd-${key}`); if (box && S.view === 'pack') { delete box.dataset.done; renderDetail(key, box); } };

function schedule(ms) {
  clearTimeout(PK.timer);
  PK.timer = setTimeout(tick, ms);
}

/* 自动档往下走一步（POST：会启动下一步），再画进度 */
async function tick() {
  const d = PK.data;
  if (!d || !d.topic || S.view !== 'pack') return;
  let v;
  try { v = await api(`/api/topics/${d.topic.id}/pack/advance`, { method: 'POST' }); } catch (_) { schedule(8000); return; }
  const changed = JSON.stringify(v.steps) !== JSON.stringify((PK.view || {}).steps);
  PK.view = v;
  if (changed) {
    // 有一步做好了：交付包（封面地址、定稿状态）也变了
    try { const fresh = await api(`/api/publish/desk?topic_id=${d.topic.id}`); Object.assign(d, { approvals: fresh.approvals, release: fresh.release, has_article: fresh.has_article, article: fresh.article }); } catch (_) { /* 下次 */ }
    paintSteps();
    paintCta();
    if (window.invalidatePublish) window.invalidatePublish();
  }
  if (v.busy) schedule(6000);
}

/* ---------- ① 定标题 ---------- */
function titleCard(d, v) {
  const done = v.armed && !PK.editTitle;
  if (done) {
    return `<section class="pk2-card pk2-done" id="pkTitle">
      <div class="pk2-step"><i>✓</i><span>标题</span></div>
      <div class="pk2-title-show"><b>${esc(v.title)}</b><button class="linklike" type="button" id="pkEditTitle">改标题</button></div>
    </section>`;
  }
  const current = v.title || (d.entry && d.entry.title) || '';
  return `<section class="pk2-card pk2-focus" id="pkTitle">
    <div class="pk2-step"><i>1</i><span>定标题</span><small>封面上的字也是它。下面是机器按你的「标题」工作流出的候选，点一条，或者直接写。</small></div>
    <input class="pk2-input" id="pkTitleInput" value="${esc(current)}" placeholder="${esc(d.topic.title)}" autocomplete="off" maxlength="100">
    <div class="pk2-go">
      <button class="btn primary big" type="button" id="pkGo">用这个标题，开始准备</button>
      <small>${v.armed ? '换了标题，封面会按新标题重出；文章、插图不受影响。' : '封面、X 图文、插图、公众号排版会自动做好，不用你一步步定稿。大约 15–20 分钟，可以先去做别的。'}</small>
    </div>
    <div class="pk2-cands" id="pkCands"><p class="pk2-muted"><span class="spin"></span> 正在出候选标题，半分钟左右…</p></div>
  </section>`;
}

async function paintCands(topicId) {
  const box = $('#pkCands');
  if (!box) return;
  let t;
  try { t = await api(`/api/topics/${topicId}/titles`); } catch (_) { box.innerHTML = ''; return; }
  // 打开页面没有候选就出一批（便宜，半分钟；是他唯一要填的那一格）。同一条只自动出一次。
  if (!t.result && !t.running && !t.error && !PK.titlesAsked.has(topicId)) {
    PK.titlesAsked.add(topicId);
    try { await api(`/api/topics/${topicId}/titles`, { method: 'POST' }); t = { running: true }; } catch (_) { /* 退回手写 */ }
  }
  if (!document.body.contains(box)) return;
  if (t.running) { box.innerHTML = '<p class="pk2-muted"><span class="spin"></span> 正在出候选标题，半分钟左右…</p>'; setTimeout(() => paintCands(topicId), 3000); return; }
  if (t.error || !t.result) { box.innerHTML = t.error ? `<p class="pk2-muted bad">候选没出来：${esc(t.error)}。直接在上面写也行。</p>` : ''; return; }
  const input = $('#pkTitleInput');
  const SHOW = 5;
  const cands = t.result.candidates;
  box.innerHTML = `<div class="pk2-cands-h">或者从候选里挑一条<small>点一下就填进上面</small></div>
    ${cands.map((c, i) => `<button type="button" class="pk2-cand ${input && input.value === c.title ? 'on' : ''}" data-cand="${i}" ${i >= SHOW ? 'hidden' : ''}>
      <b>${esc(c.title)}</b><small>${esc(c.pattern)}${c.over ? ` · ${c.title.length} 字，抖音会裁` : ''}</small></button>`).join('')}
    <div class="pk2-cands-f">${cands.length > SHOW ? `<button type="button" class="linklike" id="pkAll">再看 ${cands.length - SHOW} 条</button>` : ''}<button type="button" class="linklike" id="pkMore">换一批</button></div>`;
  const all = $('#pkAll', box);
  if (all) all.onclick = () => { $$('[data-cand][hidden]', box).forEach((b) => { b.hidden = false; }); all.remove(); };
  $$('[data-cand]', box).forEach((b) => (b.onclick = () => {
    input.value = t.result.candidates[Number(b.dataset.cand)].title;
    $$('[data-cand]', box).forEach((x) => x.classList.toggle('on', x === b));
    input.focus();
    input.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }));
  $('#pkMore', box).onclick = async () => {
    try { await api(`/api/topics/${topicId}/titles`, { method: 'POST' }); } catch (err) { toast(err.message); return; }
    box.innerHTML = '<p class="pk2-muted"><span class="spin"></span> 正在出新一批…</p>';
    setTimeout(() => paintCands(topicId), 3000);
  };
}

async function packGo(topicId) {
  const input = $('#pkTitleInput');
  const title = input ? input.value.trim() : '';
  if (!title) { toast('先写标题'); if (input) input.focus(); return; }
  const btn = $('#pkGo'); if (btn) { btn.disabled = true; btn.textContent = '开始了…'; }
  try {
    PK.view = await api(`/api/topics/${topicId}/pack/go`, { method: 'POST', body: { title } });
  } catch (err) { toast(err.message); if (btn) { btn.disabled = false; btn.textContent = '用这个标题，开始准备'; } return; }
  PK.editTitle = false;
  if (input) input.blur();  // 输入框有焦点时页面不重画（防打字被冲掉），这里要让它画
  toast('开始准备了：封面、文章、插图、排版会一步接一步做完');
  refreshPack();
}

/* ---------- ② 自动准备 ---------- */
const STEP_ICON = { done: '✓', running: '', waiting: '·', error: '!', idle: '○' };

function stepsCard(v) {
  const rows = v.steps || [];
  const n = rows.filter((r) => r.state === 'done').length;
  return `<section class="pk2-card ${v.armed && !v.ready ? 'pk2-focus soft' : ''} ${v.armed ? '' : 'pk2-dim'}" id="pkSteps">
    <div class="pk2-step"><i>${v.ready ? '✓' : '2'}</i><span>自动准备</span><small id="pkCount">${v.armed ? `${n} / ${rows.length} 好了` : '定了标题就开始'}</small></div>
    <div class="pk2-list" id="pkList">${rows.map(stepRow).join('')}</div>
  </section>`;
}

function stepRow(r) {
  const icon = r.state === 'running' ? '<span class="spin"></span>' : STEP_ICON[r.state];
  const canOpen = r.state === 'done' || r.state === 'error';
  return `<details class="pk2-row s-${r.state}" data-row="${r.key}" ${PK.open.has(r.key) ? 'open' : ''}>
    <summary><i class="pk2-dot">${icon}</i><b>${esc(r.label)}</b><span class="pk2-note">${esc(r.note)}</span>
      ${r.state === 'error' ? `<button class="btn small" type="button" data-retry="${r.key}">重试</button>` : canOpen ? '<span class="pk2-open">查看 / 改</span>' : ''}</summary>
    <div class="pk2-detail" id="pkd-${r.key}"></div>
  </details>`;
}

function paintSteps() {
  const v = PK.view;
  const list = $('#pkList');
  if (!v || !list) return;
  const rows = v.steps || [];
  rows.forEach((r) => {
    const det = $(`.pk2-row[data-row="${r.key}"]`, list);
    if (!det) return;
    if (det.className !== `pk2-row s-${r.state}` || $('.pk2-note', det).textContent !== r.note) {
      const fresh = document.createElement('div');
      fresh.innerHTML = stepRow(r);
      const row = fresh.firstElementChild;
      det.replaceWith(row);
      wireRow(row);
    }
  });
  const count = $('#pkCount');
  if (count) count.textContent = v.armed ? `${rows.filter((r) => r.state === 'done').length} / ${rows.length} 好了` : '定了标题就开始';
  const card = $('#pkSteps');
  if (card) card.classList.toggle('pk2-focus', v.armed && !v.ready);
}

function wireRow(det) {
  const key = det.dataset.row;
  const retry = $('[data-retry]', det);
  if (retry) retry.onclick = async (e) => {
    e.preventDefault();
    retry.disabled = true;
    try { PK.view = await api(`/api/topics/${PK.data.topic.id}/pack/retry`, { method: 'POST', body: { key } }); } catch (err) { toast(err.message); }
    paintSteps(); paintCta(); schedule(4000);
  };
  det.addEventListener('toggle', () => {
    if (det.open) { PK.open.add(key); renderDetail(key, $('.pk2-detail', det)); } else PK.open.delete(key);
  });
  if (det.open) renderDetail(key, $('.pk2-detail', det));
}

/* 每一行展开后：看产物、想改就改（改了自动档会重新定稿） */
function renderDetail(key, box) {
  const d = PK.data;
  if (!d || !d.topic || !box || box.dataset.done) return;
  const t = { ...d.topic, ...(PK.topic || {}) };
  box.dataset.done = '1';
  const id = d.topic.id;
  if (key === 'cover') {
    const urls = (d.release && d.release.cover_urls) || {};
    const shots = [['portrait', '竖版 3:4'], ['landscape', '横版 4:3'], ['wide', '16:9']].filter(([k]) => urls[k]);
    const stamp = Date.now();
    // 10/3：重出时这里还是上一版（旧标题）的封面，Park 以为已经出好了——要说清楚
    const redoing = ((PK.view && PK.view.steps) || []).some((r) => r.key === 'cover' && r.state === 'running');
    box.innerHTML = shots.length
      ? `${redoing ? '<p class="pk2-muted">正在按新标题重出，下面是上一版，出好会自动换上。</p>' : ''}<div class="pk2-covers${redoing ? ' old' : ''}">${shots.map(([k, l]) => `<a href="${urls[k]}" target="_blank" rel="noopener"><img class="${k}" src="${urls[k]}?t=${stamp}" alt="${l}"><small>${l}</small></a>`).join('')}</div>
         <p class="pk2-muted">封面上的字就是标题，想换字就改上面的标题。</p>`
      : '<p class="pk2-muted">还没出好。</p>';
  } else if (key === 'article') {
    const tab = (window.VIDEO_TABS || []).find((x) => x.key === 'article');
    if (!tab) { box.innerHTML = '<p class="pk2-muted">文章在「加工中」里。</p>'; return; }
    Promise.resolve(tab.render(t, box)).then(() => {
      if (!d.has_article || !document.body.contains(box)) return;
      // 10/2 Park：口述整理出来的文字可能散了，「润色」按付息稿的逻辑（发债 → 付息 → 兑付本金）重新跑一遍
      box.insertAdjacentHTML('afterbegin', `<div class="pk2-polish"><button class="btn small" type="button" id="pkPolish">润色</button>
        <small>按付息稿的逻辑重新整理：开头说清读完能拿到什么，每段都给点东西，结尾兑现。只改表达，不加新事实；插图跟着段落走；原文会先备份。</small></div>`);
      $('#pkPolish', box).onclick = async () => {
        const b = $('#pkPolish', box); b.disabled = true;
        try { toast((await api(`/api/topics/${id}/polish`, { method: 'POST' })).message); } catch (err) { toast(err.message); b.disabled = false; return; }
        const row = box.closest('.pk2-row'); if (row) { row.open = false; PK.open.delete('article'); }
        schedule(1500);
      };
    });
  } else if (key === 'figs') {
    box.innerHTML = '<div id="pdlFigs"></div><div id="pdlEvid" class="ev"></div>';
    renderFigs(box, id); renderEvidence(box, id);
  } else if (key === 'wx') {
    box.innerHTML = '<div class="pdl-wx" id="pdlWx"></div>';
    renderWx(box, id);
  } else if (key === 'xhs') {
    box.innerHTML = '<div id="pdlXhs" class="xhs"></div>';
    renderXhs(box, id);
  }
}

/* ---------- ③ 去发布 ---------- */
function ctaCard(v) {
  return `<section class="pk2-cta" id="pkCta">${ctaInner(v)}</section>`;
}
/* ③ 发出去（10/3 Park：打包好了直接进补发工作台挑格子，不再经过那张「这一条发到哪」）。
   补发工作台的表一行是一条抖音作品，所以先发抖音、对上是哪条作品，再去挑其余平台。 */
function ctaInner(v) {
  const vid = PK.data && PK.data.topic && PK.data.topic.published_video_id;
  if (!v.armed) return '<span class="pk2-muted">定了标题，剩下的自动做；全好了这里会亮。</span>';
  if ((v.ready || PK.douyinNow) && !vid) return douyinStep();
  if (v.ready) return '<button class="btn primary big" type="button" id="pkDesk">全部好了，去发其他平台 →</button>';
  const err = (v.steps || []).some((r) => r.state === 'error');
  return `<button class="btn big" type="button" disabled>${err ? '有一步没做成，点上面的「重试」' : '还在准备 · 好了这里会亮'}</button>
    <button class="linklike" type="button" id="pkEarly">${vid ? '先发已经好的平台' : '封面好了，先发抖音'}</button>`;
}
function douyinStep() {
  const admin = 'https://creator.douyin.com/creator-micro/content/upload';
  return `<div class="pk2-dy">
    <div class="pk2-dy-h"><b>先发抖音</b><small>视频、竖封面、横封面在文件夹里，标题和描述在文案.txt。发完点「发了」，对一下是哪条，就去发其他平台。</small></div>
    <div class="pk2-dy-b"><button class="btn primary big" type="button" id="pkDyFolder">打开抖音上传文件夹</button>
      <a class="btn big" href="${admin}" target="_blank" rel="noopener">去抖音上传 ↗</a>
      <button class="btn big" type="button" id="pkDyDone">发了</button></div>
    <div id="pkDyLink"></div>
  </div>`;
}
function paintCta() {
  const el = $('#pkCta');
  if (el && PK.view) { el.innerHTML = ctaInner(PK.view); wireCta(); }
}
function openDesk() {
  const t = PK.data.topic;
  if (window.openBackfillDesk) window.openBackfillDesk(t.published_video_id, { preselect: true });
}
function wireCta() {
  const desk = $('#pkDesk'); if (desk) desk.onclick = openDesk;
  const early = $('#pkEarly');
  if (early) early.onclick = () => { if (PK.data.topic.published_video_id) openDesk(); else { PK.douyinNow = true; paintCta(); } };
  const folder = $('#pkDyFolder');
  if (folder) folder.onclick = async () => {
    try { await api(`/api/topics/${PK.data.topic.id}/upload-folder`, { method: 'POST', body: { platform: 'douyin', open: true } }); toast('文件夹打开了：视频、封面、文案.txt 都在里面'); } catch (err) { toast(err.message); }
  };
  const done = $('#pkDyDone'); if (done) done.onclick = () => douyinLink($('#pkDyLink'));
}

/* 抖音发了：对一下是哪条作品（数据、评论、补发表都靠它） */
async function douyinLink(box) {
  if (!box) return;
  const id = PK.data.topic.id;
  box.innerHTML = '<p class="pk2-muted"><span class="spin"></span> 正在找你刚发的那条…</p>';
  let d;
  try { d = await api(`/api/topics/${id}/publish`); } catch (err) { box.innerHTML = `<p class="pk2-muted bad">${esc(err.message)}</p>`; return; }
  if (!d.account) { box.innerHTML = '<p class="pk2-muted">还没设置自己的抖音号，先去设置里加。</p>'; return; }
  const row = (v, primary) => `<div class="pk2-dy-v"><div><b>${esc(cleanTitle(v.title))}</b><small>${day(v.published_at)} · ${fmt(v.likes)} 赞</small></div>
    <button class="btn small ${primary ? 'primary' : ''}" type="button" data-dy="${esc(v.video_id)}">就是这条</button></div>`;
  const list = d.suggestions.length ? d.suggestions.map((v) => row(v, true)).join('') : d.recent.slice(0, 5).map((v) => row(v, false)).join('');
  box.innerHTML = `<p class="pk2-muted">${d.suggestions.length ? '是这条吗？' : '还没找到标题相近的新作品。刚发的话等一两分钟，或者'}${d.suggestions.length ? '' : ' <button class="linklike" type="button" id="pkDySync">同步一下我的抖音</button>；也可以在下面直接点。'}</p>${list}`;
  $$('[data-dy]', box).forEach((b) => (b.onclick = async () => {
    try { await api(`/api/topics/${id}/publish`, { method: 'PUT', body: { video_id: b.dataset.dy } }); } catch (err) { toast(err.message); return; }
    PK.data.topic.published_video_id = b.dataset.dy;
    PK.douyinNow = false;
    toast('对上了');
    if (window.invalidatePublish) window.invalidatePublish();
    paintCta();
  }));
  const sync = $('#pkDySync', box);
  if (sync) sync.onclick = async () => {
    try { toast((await api('/api/sync', { method: 'POST' })).message); } catch (err) { toast(err.message); }
    setTimeout(() => douyinLink(box), 20000);
  };
}

/* 描述和话题：自动填好了，收在最下面 */
function copyFold() {
  return `<details class="pk2-fold" id="pkCopy"><summary>描述和话题<small>已经自动填好，想改再打开</small></summary><div id="pkCopyBody"></div></details>`;
}

function refreshPack() {
  PK.data = null;
  const b = $('#packBody'); if (b) b.dataset.sig = '';
  if (window.invalidatePublish) window.invalidatePublish();
  if (S.view === 'pack') renderView();
}

function paintHead(d) {
  const figs = $('#packFigs');
  if (!figs) return;
  figs.innerHTML = d && d.topic && d.video ? `<div class="pub-figs"><span>成片 <b>${d.video.mb}</b> MB</span></div>` : '';
}

window.VIEWS.pack = {
  async render() {
    const body = $('#packBody');
    // 正在打字（文案、文章）就不重画，免得冲掉没保存的内容
    if ((typeof CP !== 'undefined' && CP.dirty) || (typeof AR !== 'undefined' && AR.dirty && body.querySelector('#artText'))) return;
    if (document.activeElement && document.activeElement.id === 'pkTitleInput') return;
    let d;
    try { d = await loadPack(false); } catch (err) {
      if (!PK.data) body.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`;
      return;
    }
    if (S.view !== 'pack') return;
    paintHead(d);
    if (!d.topic) {
      const w = d.waiting;
      body.dataset.sig = 'empty';
      body.innerHTML = `<div class="pub-empty"><b>还没有能打包的成片</b>
        ${w ? `<span>最近的一条是《${esc(w.title)}》，还在<b>${esc(w.stage_label || w.stage)}</b>。成片出现在项目 final/ 里，它就会出现在这儿。</span>
          <button class="btn small" type="button" data-pk-work="${w.id}">去看这一条 →</button>` : '<span>手上的都发完了。「加工中」里的下一条剪完，就会出现在这里。</span><button class="btn small" type="button" onclick="go(\'backfill\')">看全平台追踪 →</button>'}</div>`;
      $$('[data-pk-work]', body).forEach((b) => (b.onclick = () => openWork(Number(b.dataset.pkWork))));
      return;
    }
    const v = PK.view || { armed: false, steps: [] };
    const sig = JSON.stringify([d.topic.id, v.armed, v.title, PK.editTitle]);
    if (body.dataset.sig === sig) { paintSteps(); paintCta(); if (v.busy) schedule(6000); return; }
    body.dataset.sig = sig;
    body.innerHTML = `<div class="pk2">
      <div class="pk2-topic"><small>正在打包</small><h2>${esc(d.topic.title)}</h2></div>
      ${titleCard(d, v)}
      ${stepsCard(v)}
      ${ctaCard(v)}
      ${v.armed ? copyFold() : ''}
    </div>`;
    if (!v.armed || PK.editTitle) {
      paintCands(d.topic.id);
      const input = $('#pkTitleInput');
      $('#pkGo').onclick = () => packGo(d.topic.id);
      input.onkeydown = (e) => { if (e.key === 'Enter') packGo(d.topic.id); };
      input.oninput = () => $$('[data-cand]').forEach((x) => x.classList.toggle('on', $('b', x).textContent === input.value));
    }
    const edit = $('#pkEditTitle');
    if (edit) edit.onclick = () => { PK.editTitle = true; body.dataset.sig = ''; renderView(); };
    $$('.pk2-row', body).forEach(wireRow);
    wireCta();
    const fold = $('#pkCopy');
    if (fold) fold.addEventListener('toggle', () => {
      const box = $('#pkCopyBody');
      if (!fold.open || box.dataset.done) return;
      box.dataset.done = '1';
      renderCopyForm({ ...(PK.topic || {}), ...d.topic }, box, { release: d.release, onSaved: async () => {
        // 描述、话题改了：文字重新定稿。标题也在这里改了的话，按新标题重新走一遍（封面跟着重出）
        try {
          const c = await api(`/api/topics/${d.topic.id}/copy`);
          const title = ((c.copy && c.copy.platforms && (c.copy.platforms.douyin || Object.values(c.copy.platforms)[0])) || {}).title || '';
          if (title && title !== (PK.view || {}).title) PK.view = await api(`/api/topics/${d.topic.id}/pack/go`, { method: 'POST', body: { title } });
          else await api(`/api/topics/${d.topic.id}/approve`, { method: 'PUT', body: { key: 'copy', approved: true } });
        } catch (err) { toast(err.message); }
        refreshPack();
      } });
    });
    if (v.busy) schedule(3000);
  },
};
