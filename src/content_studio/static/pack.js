'use strict';
/* 03 打包：发之前把一条内容要的东西全备好，发布台那边就只剩一个个平台点出去。
   9/29 Park：「发布的时候，我希望就是纯发布；发布前准备就是 get ready for everything。」
   视频包：封面（选一帧）、标题、文案描述、简介、话题。
   文字包：X 图文文章、插图、公众号排版、小红书图文。（9/29 研习室先拿掉，要用时在设置里打开平台）
   这里不新做任何生成能力——封面、标题候选、写文章、配图、gzh 排版、小红书出图都是原来就有的，
   以前散在发布台的弹窗和「加工中」的页签里，现在收到一页。数据跟发布台共用 /api/publish/desk。 */
window.VIEWS = window.VIEWS || {};

const PK = { data: null, topic: null, st: null, at: 0, open: new Set(), timer: null };

async function loadPack(force) {
  if (!force && PK.data && (!S.packId || (PK.data.topic && PK.data.topic.id === S.packId)) && Date.now() - PK.at < 15000) return PK.data;
  const d = await api('/api/publish/desk' + (S.packId ? `?topic_id=${S.packId}` : ''));
  PK.data = d; PK.at = Date.now(); PK.topic = null; PK.st = null;
  if (d.topic) {
    S.packId = d.topic.id;
    const [topics, figs, wx] = await Promise.all([
      api('/api/topics'),
      d.has_article ? api(`/api/topics/${d.topic.id}/illustrate`).catch(() => null) : null,
      d.has_article ? api(`/api/topics/${d.topic.id}/layout`).catch(() => null) : null,
    ]);
    PK.topic = topics.find((t) => t.id === d.topic.id) || null;
    PK.st = { figs, wx };
  }
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

/* ---------- 每一项的状态 ---------- */
const PK_STATE = { lock: ['定稿'], ok: ['等你定稿'], wip: ['在做'], no: ['没做'], bad: ['要重做'] };
const PK_ICON = { lock: '✓', ok: '•', wip: '', no: '○', bad: '!' };
/* 定稿（9/29 Park：「做好一件事就 lock in，再往上搭下一块积木」）。
   每一步要等上一步定稿才开始；定稿的那一版锁住，按钮收起来，想改点「改这一步」。
   后端按指纹判断定稿那一版还是不是现在这一版（approvals.py），改过就作废。 */
// 文章这一行就是 X 图文：X 发的就是这篇文章 + 插图，定稿文章就是定稿 X（9/29 Park）；公众号排版也从它来。
// 小红书 9/29 起发视频，用封面和文案，不再有自己的一步。
const PK_DEPENDS = { cover: 'copy', figs: 'article', wx: 'figs' };
const PK_LABEL = { copy: '标题 · 描述 · 简介 · 话题', cover: '封面', article: 'X 图文文章', figs: '插图', wx: '公众号排版' };
const PK_NEXT = { copy: 'cover', cover: 'article', article: 'figs', figs: 'wx' };
const PK_APPROVE = { cover: '定稿封面', article: '定稿（X 和公众号都用这篇），下一步配图', figs: '定稿插图，下一步排版', wx: '定稿公众号排版' };
const locked = (d, key) => { const a = ((d && d.approvals) || {})[key]; return Boolean(a && a.approved && a.valid); };
window.packLocked = locked;

function packItems(d, t, st) {
  const c = (d.release && d.release.covers) || {};
  const covers = [['portrait', '竖版'], ['landscape', '横版'], ['wide', 'YouTube 16:9']].filter(([k]) => c[k]).map(([, l]) => l);
  const e = d.entry || { title: '', body: '', tags: [] };
  const art = !d.has_article
    ? (t && t.write_state === 'running' ? ['wip', '正在照视频字幕写，一般 1–5 分钟'] : t && t.write_state === 'failed' ? ['bad', t.write_error || '上次写失败了'] : ['no', '照这条视频的字幕（剪映导出的 SRT）写成文字版'])
    : ['ok', d.article && d.article.title ? `《${d.article.title}》` : '写好了'];
  const needArt = (fn) => (d.has_article ? fn() : ['no', '先写 X 图文文章']);
  // 9/29 Park：「有了文章和插图之后，才变成公众号排版、小红书图文、X 图文。」
  const needFigs = (fn) => needArt(() => (figsReady(st) ? fn() : ['no', '先配图']));
  const figs = needArt(() => {
    const s = st.figs || {};
    if (s.running) return ['wip', '小黑手绘，一张一张画，5–10 分钟'];
    if (s.error) return ['bad', s.error];
    return s.images && s.images.length ? ['ok', `${s.images.length} 张，已插进文章`] : ['no', '4–8 张，插在对应段落后面'];
  });
  const wx = needFigs(() => {
    const s = st.wx || {};
    if (s.running) return ['wip', '正在用 gzh 排版，5–10 分钟'];
    if (s.error) return ['bad', s.error];
    if (s.has_layout && s.stale) return ['bad', '文章改过了，旧排版作废'];
    return s.has_layout ? ['ok', `gzh 排好了（${s.theme || '橄榄手记'}），公众号用这份`] : ['no', '不排也能发，用的是基础排版'];
  });
  return [
    { key: 'copy', group: 'video', label: '标题 · 描述 · 简介 · 话题', state: d.has_copy ? 'ok' : 'no', note: d.has_copy ? (e.title || '已保存') : '先写这个：标题、描述、简介、话题。封面的字就用这个标题' },
    { key: 'cover', group: 'video', label: '封面', state: covers.length ? 'ok' : 'no', note: covers.length ? `${covers.join(' · ')}都有了` : d.has_copy ? '用标题出，画面和橙色关键词机器定，5–10 分钟' : '写好标题后自动出' },
    { key: 'article', group: 'text', label: 'X 图文文章', state: art[0], note: art[1] },
    { key: 'figs', group: 'text', label: '插图', state: figs[0], note: figs[1] },
    { key: 'wx', group: 'text', label: '公众号排版', state: wx[0], note: wx[1] },
  ].map((it) => {
    const a = (d.approvals || {})[it.key] || {};
    const dep = PK_DEPENDS[it.key];
    if (a.approved && a.valid) return { ...it, state: 'lock' };
    if (a.approved && a.made) return { ...it, state: 'bad', note: '定稿之后改过了（或者上一步改了），看一遍再定稿' };
    if (it.state === 'no' && dep && !locked(d, dep)) return { ...it, note: `先定稿「${PK_LABEL[dep]}」` };
    return it;
  });
}

const figsReady = (st) => Boolean(st && st.figs && !st.figs.running && st.figs.images && st.figs.images.length);

/* 配图、排版、小红书出图在各自那一块里自己轮询。它们每问一次就告诉这里一声，
   上面那一行的状态跟着变——9/29 以前只在打开页面时读一次，配图重做成功了还显示「要重做」。 */
window.prepTick = (key, st) => {
  if (S.view !== 'pack' || !PK.data || !PK.st) return;
  const was = JSON.stringify(PK.st[key] || null);
  PK.st[key] = st;
  if (was !== JSON.stringify(st)) { repaintRows(); refreshApprovals(); }
};

function repaintRows() {
  const d = PK.data;
  if (!d || !d.topic) return;
  packItems(d, PK.topic, PK.st || {}).forEach((it) => {
    const det = $(`.pk-row[data-pk="${it.key}"]`);
    if (!det) return;
    det.className = `pk-row s-${it.state}`;
    $('.pk-dot', det).innerHTML = it.state === 'wip' ? '<span class="spin"></span>' : PK_ICON[it.state];
    $('.pk-note', det).textContent = it.note;
    $('.pk-word', det).textContent = PK_STATE[it.state][0];
    paintApproval(it);
  });
  paintHead(d);
  // 上一步刚定稿：等着它的那几行解开
  Object.keys(PK_DEPENDS).forEach((k) => { const box = $(`#pki-${k}`); if (box && box.dataset.done === 'gated' && locked(d, PK_DEPENDS[k])) { delete box.dataset.done; renderRow(k, box); } });
}

/* 每一行底下的「定稿」，定了之后顶上一条「已定稿 · 改这一步」，里面的按钮收起来 */
function paintApproval(it) {
  const d = PK.data;
  const body = $(`#pkb-${it.key}`);
  if (!body || !d) return;
  const a = (d.approvals || {})[it.key] || {};
  const dep = PK_DEPENDS[it.key];
  const isLocked = it.state === 'lock';
  body.classList.toggle('pk-locked', isLocked);
  $('.pk-lock', body).innerHTML = isLocked
    ? `<div class="pk-lockbar"><b>✓ 已定稿</b><small>${a.at ? new Date(a.at).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : ''} · 锁住了，下一步照这一版做</small><span class="spacer"></span><button class="btn small" type="button" data-unlock="${it.key}">✎ 改这一步</button></div>` : '';
  const canApprove = !isLocked && a.made && PK_APPROVE[it.key] && (!dep || locked(d, dep)) && it.state !== 'wip';
  $('.pk-approve', body).innerHTML = canApprove
    ? `<button class="btn primary" type="button" data-approve="${it.key}">${PK_APPROVE[it.key]}</button><small>这一版就用它：锁住、收起来，下一步才开始。想改再点「改这一步」。</small>`
    : (!isLocked && a.made && dep && !locked(d, dep) ? `<small>先定稿「${PK_LABEL[dep]}」，这一步才能定稿。</small>` : '');
  $$('[data-approve]', body).forEach((b) => (b.onclick = () => approveStep(b.dataset.approve, true)));
  $$('[data-unlock]', body).forEach((b) => (b.onclick = () => approveStep(b.dataset.unlock, false)));
}

async function approveStep(key, approved) {
  const d = PK.data;
  if (!d || !d.topic) return;
  let res;
  try { res = await api(`/api/topics/${d.topic.id}/approve`, { method: 'PUT', body: { key, approved } }); } catch (err) { toast(err.message); return; }
  d.approvals = res.approvals;
  if (window.invalidatePublish) window.invalidatePublish();
  const inner = $(`#pki-${key}`);
  if (inner) { delete inner.dataset.done; renderRow(key, inner); }
  repaintRows();
  if (!approved) { toast(`「${PK_LABEL[key]}」解锁了，可以改`); return; }
  toast(`「${PK_LABEL[key]}」定稿了`);
  const det = $(`.pk-row[data-pk="${key}"]`);
  if (det) { det.open = false; PK.open.delete(key); }
  const next = PK_NEXT[key];
  if (next) window.packNext(next);
}
window.packApprove = approveStep;

/* 上一步做完、定稿状态可能变了（比如插图重画，旧定稿作废）：重新问一次定稿状态 */
let approvalsTimer = null;
function refreshApprovals() {
  clearTimeout(approvalsTimer);
  approvalsTimer = setTimeout(async () => {
    const d = PK.data;
    if (!d || !d.topic || S.view !== 'pack') return;
    try { const fresh = await api(`/api/publish/desk?topic_id=${d.topic.id}`); d.approvals = fresh.approvals; d.release = fresh.release; repaintRows(); } catch (_) { /* 下次 */ }
  }, 600);
}

/* 打开下一步那一行；配图还没配过就直接开始配。 */
window.packNext = async (key) => {
  const det = $(`.pk-row[data-pk="${key}"]`);
  if (!det) return;
  det.open = true; PK.open.add(key);
  det.scrollIntoView({ behavior: 'smooth', block: 'start' });
  if (key === 'figs' && PK.data && PK.data.topic && !figsReady(PK.st) && !(PK.st && PK.st.figs && PK.st.figs.running)) {
    try { toast((await api(`/api/topics/${PK.data.topic.id}/illustrate`, { method: 'POST' })).message); } catch (err) { toast(err.message); }
    const box = $('#pki-figs'); if (box) { delete box.dataset.done; renderRow('figs', box); }
  }
};

function row(it) {
  const [word] = PK_STATE[it.state];
  const icon = it.state === 'wip' ? '<span class="spin"></span>' : PK_ICON[it.state];
  return `<details class="pk-row s-${it.state}" data-pk="${it.key}" ${PK.open.has(it.key) ? 'open' : ''}>
    <summary><i class="pk-dot">${icon}</i><b>${esc(it.label)}</b><span class="pk-note">${esc(it.note)}</span><span class="pk-word">${word}</span></summary>
    <div class="pk-body" id="pkb-${it.key}"><div class="pk-lock"></div><div class="pk-inner" id="pki-${it.key}"></div><div class="pk-approve"></div></div>
  </details>`;
}

/* ---------- 每一项展开后的内容 ---------- */
/* 封面：9/29 Park——字就是标题，画面机器挑（6 选 1 也行），橙色关键词机器定。
   出图交给 Codex 的 image_gen（和他以前那些好封面一样），5–10 分钟，在后台跑；这里只选帧、点一下、等。 */
async function renderCoverMaker(topicId, box, { auto = false } = {}) {
  if (!box.dataset.polling) box.innerHTML = '<p class="pdl-note"><span class="spin"></span> 正在从视频里挑画面…</p>';
  let o;
  try { o = await api(`/api/topics/${topicId}/cover`); } catch (err) { box.innerHTML = `<p class="pdl-note bad">${esc(err.message)}</p>`; return; }
  if (!document.body.contains(box)) return;
  if (!o.from_copy || !locked(PK.data, 'copy')) {
    box.innerHTML = '<p class="pdl-note">封面上的字就是标题。先在上面「标题 · 描述 · 简介 · 话题」里写好并「保存并定稿」，定稿后封面会自己出。</p>';
    return;
  }
  const pick = o.frames.find((f) => f.pick) || o.frames[Math.floor(o.frames.length / 2)] || {};
  let at = box.dataset.at ? Number(box.dataset.at) : pick.at || 0;
  const rel = PK.data && PK.data.release;
  const current = rel && rel.cover_urls ? [['portrait', '竖版'], ['landscape', '横版'], ['wide', 'YouTube 16:9']].filter(([k]) => rel.cover_urls[k]) : [];
  const stamp = Date.now();
  box.innerHTML = `<div class="cv-auto">
    <p class="cv-words">封面上的字：<span>${esc(o.title)}</span><small>就是标题；橙色关键词机器挑。想改字，改上面的标题再出一次。</small></p>
    <div class="cv-l">画面<small>从「${esc(o.source)}」里按人脸清晰、正对镜头挑了一张；想换就点另一张</small></div>
    <div class="cv-frames six">${o.frames.map((f) => `<button type="button" class="cv-frame ${f.at === at ? 'on' : ''}" data-cv-at="${f.at}" ${o.running ? 'disabled' : ''}><img src="${f.url}" alt="第 ${Math.round(f.at)} 秒"><small>${f.pick ? '机器挑的 · ' : ''}${Math.floor(f.at / 60)}:${String(Math.round(f.at % 60)).padStart(2, '0')}</small></button>`).join('')}</div>
    <div class="cv-foot">${o.running
      ? '<span class="pdl-note"><span class="spin"></span> 正在用图像生成出竖版、横版和 YouTube 16:9，一般 5–10 分钟。可以先去做别的，出好这里会变。</span>'
      : `<button class="btn primary" type="button" id="cvGo">${current.length ? '用这一帧重新出' : '出封面（竖 3:4、横 4:3、YouTube 16:9）'}</button><span class="pdl-note">${o.error ? `<b class="bad">上次没出成：${esc(o.error)}</b>` : '图像生成，5–10 分钟'}</span>`}</div>
    <div class="cv-out">${current.map(([k, l]) => `<a href="${rel.cover_urls[k]}" target="_blank" rel="noopener"><img class="cv-shot ${k}" src="${rel.cover_urls[k]}?t=${stamp}" alt="${l}封面"></a>`).join('')}</div>
  </div>`;
  $$('[data-cv-at]', box).forEach((b) => (b.onclick = () => { at = Number(b.dataset.cvAt); box.dataset.at = String(at); $$('[data-cv-at]', box).forEach((x) => x.classList.toggle('on', x === b)); }));
  const start = async () => {
    try { await api(`/api/topics/${topicId}/cover`, { method: 'POST', body: { at } }); } catch (err) { toast(err.message); }
    renderCoverMaker(topicId, box);
  };
  const go = $('#cvGo', box);
  if (go) go.onclick = start;
  clearTimeout(box._poll);
  if (o.running) {
    box.dataset.polling = '1';
    box._poll = setTimeout(async () => {
      if (!document.body.contains(box)) return;
      const st = await api(`/api/topics/${topicId}/cover`).catch(() => null);
      if (st && !st.running) {
        // 出好了：刷新交付包（上面那行变「好了」、发布台认新封面），再画这一块
        delete box.dataset.polling;
        if (window.invalidatePublish) window.invalidatePublish();
        PK.data = null;
        try { await loadPack(true); paintHead(PK.data); } catch (_) { /* 下次刷新 */ }
      }
      renderCoverMaker(topicId, box);
    }, 8000);
  } else {
    delete box.dataset.polling;
    if (auto && !current.length && !o.error) start();
  }
}

function renderRow(key, box) {
  const d = PK.data;
  const t = PK.topic;
  if (!d || !d.topic || box.dataset.done) return;
  box.dataset.done = '1';
  const id = d.topic.id;
  if (key === 'cover') {
    if (!d.video) { box.innerHTML = '<p class="pdl-note">还没有成片，取不了帧。成片出现在项目 final/ 里就能做。</p>'; return; }
    renderCoverMaker(id, box, { auto: PK.autoCover });
    PK.autoCover = false;
  } else if (key === 'copy') {
    renderCopyForm({ ...(t || {}), ...d.topic, outline_path: t && t.outline_path }, box, { release: d.release, onSaved: async () => {
      // 保存就是定稿（文字信息这一步没有别的要看）。定稿后封面用这个标题自动出（还没有封面的时候）
      const c = (d.release && d.release.covers) || {};
      try { d.approvals = (await api(`/api/topics/${d.topic.id}/approve`, { method: 'PUT', body: { key: 'copy', approved: true } })).approvals; } catch (err) { toast(err.message); }
      if (d.video && !(c.landscape || c.portrait)) PK.autoCover = true;
      PK.open.delete('copy'); PK.open.add('cover');
      refreshPack();
    } });
  } else if (key === 'article') {
    const tab = (window.VIDEO_TABS || []).find((x) => x.key === 'article');
    if (tab && t) tab.render(t, box).then(() => {
      if (d.has_article) box.insertAdjacentHTML('afterbegin', '<p class="pdl-note pk-also">X 发的就是这一篇（连插图一起传，封面按标题出一张纯文字横幅，不用另外做）；公众号、小红书图文也都从这一篇来。</p>');
    });
  } else if (PK_DEPENDS[key] && !locked(d, PK_DEPENDS[key]) && !((d.approvals || {})[key] || {}).made) {
    box.dataset.done = 'gated';
    box.innerHTML = `<p class="pdl-note">先定稿「${PK_LABEL[PK_DEPENDS[key]]}」：一块一块往上搭，上一步定了这里自己解开。</p>`;
  } else if (key === 'figs') {
    box.innerHTML = '<div id="pdlFigs"></div>';
    if (d.has_article) renderFigs(box, id); else box.innerHTML = '<p class="pdl-note">插图插在文章里，先把上面的 X 图文文章写好。</p>';
  } else if (key === 'wx') {
    box.innerHTML = d.has_article ? '<div class="pdl-wx" id="pdlWx"></div>' : '<p class="pdl-note">公众号发的是上面那篇文章，先把它写好。</p>';
    if (d.has_article) renderWx(box, id);
  }
}

/* 文章编辑器切预览/编辑、保存之后要重画自己那一块（整页的 sig 没变，不会重画） */
window.rerenderPackRow = (key) => {
  const box = $(`#pki-${key}`);
  if (!box || S.view !== 'pack') return;
  delete box.dataset.done;
  renderRow(key, box);
};

function refreshPack() {
  PK.data = null;
  const b = $('#packBody'); if (b) b.dataset.sig = '';
  if (window.invalidatePublish) window.invalidatePublish();
  if (S.view === 'pack') renderView();
}

function paintHead(d) {
  const figs = $('#packFigs');
  if (!figs) return;
  if (!d || !d.topic) { figs.innerHTML = ''; return; }
  const items = packItems(d, PK.topic, PK.st || {});
  const n = (g) => items.filter((x) => x.group === g && x.state === 'lock').length;
  const all = (g) => items.filter((x) => x.group === g).length;
  const missing = packMissing(d);
  figs.innerHTML = `<div class="pub-figs">
    <span>成片 ${d.video ? `<b>${d.video.mb}</b> MB` : '<span class="bad">还没有</span>'}</span>
    <span>视频包定稿 <b>${n('video')}</b> / ${all('video')}</span>
    <span>文字包定稿 <b>${n('text')}</b> / ${all('text')}</span>
    <button class="btn ${missing.length ? '' : 'primary'}" type="button" data-pk-go>${missing.length ? '先去发布' : '打包好了，去发布'} →</button>
  </div>`;
  const go = $('[data-pk-go]', figs);
  if (go) go.onclick = () => {
    if (missing.length && !confirm(`还差${missing.join('、')}，现在就去发布？`)) return;
    S.publishId = d.topic.id; if (window.resetDesk) window.resetDesk(); window.go('publish');
  };
}

window.VIEWS.pack = {
  async render() {
    const body = $('#packBody');
    // 正在打字（文案、文章）就不重画，免得冲掉没保存的内容
    if ((typeof CP !== 'undefined' && CP.dirty) || (typeof AR !== 'undefined' && AR.dirty && body.querySelector('#artText'))) return;
    let d;
    try { d = await loadPack(false); } catch (err) {
      if (!PK.data) body.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`;
      return;
    }
    if (S.view !== 'pack') return;
    const st = PK.st || {};
    const t = PK.topic;
    const running = (t && t.write_state === 'running') || ['figs', 'wx'].some((k) => st[k] && st[k].running);
    clearTimeout(PK.timer);
    if (running) PK.timer = setTimeout(() => { if (S.view === 'pack') refreshPack(); }, 8000);
    const items = d.topic ? packItems(d, t, st) : [];
    const sig = JSON.stringify([d.topic && d.topic.id, d.candidates.map((c) => c.id), items.map((i) => [i.key, i.state, i.note])]);
    paintHead(d);
    if (body.dataset.sig === sig) return;
    body.dataset.sig = sig;

    if (!d.topic) {
      const w = d.waiting;
      body.innerHTML = `<div class="pub-empty"><b>还没有能打包的成片</b>
        ${w ? `<span>最近的一条是《${esc(w.title)}》，还在<b>${esc(w.stage_label || w.stage)}</b>。成片出现在项目 final/ 里，它就会出现在这儿。</span>
          <button class="btn small" type="button" data-pk-work="${w.id}">去看这一条 →</button>` : '<span>手上的都发完了。「加工中」里的下一条剪完，就会出现在这里。</span><button class="btn small" type="button" onclick="go(\'backfill\')">看全平台追踪 →</button>'}</div>`;
      $$('[data-pk-work]', body).forEach((b) => (b.onclick = () => openWork(Number(b.dataset.pkWork))));
      return;
    }
    if (!PK.open.size) PK.open = new Set(items.filter((i) => i.state !== 'lock').map((i) => i.key).slice(0, 1));
    const chip = (c) => `<button class="pub-topic ${c.id === d.topic.id ? 'on' : ''}" type="button" data-pk-topic="${c.id}"><b>${esc(c.title)}</b>${c.shipped_count ? `<span class="num">已发 ${c.shipped_count}</span>` : ''}</button>`;
    const list = d.candidates.some((c) => c.id === d.topic.id) ? d.candidates : [d.topic, ...d.candidates];
    const group = (g, title, sub) => `<section class="pk-group"><div class="pk-gh"><h2>${title}</h2><small>${sub}</small></div>
      ${items.filter((i) => i.group === g).map(row).join('')}</section>`;
    body.innerHTML = `<div class="pub-head"><div class="pub-topics"><small>打包这条</small>${list.map(chip).join('')}</div></div>
      ${d.release && d.release.copy && !d.has_copy ? '<p class="pk-hint">成片包里有一份写好的发布文案，打开「标题 · 描述 · 简介 · 话题」可以一键填进来。</p>' : ''}
      ${group('video', '视频包', '抖音、视频号、B 站、YouTube、小红书视频都用这一份')}
      ${group('text', '文字包', 'X、小红书图文、公众号用的都是这一篇文章')}`;
    $$('[data-pk-topic]', body).forEach((b) => (b.onclick = () => {
      S.packId = Number(b.dataset.pkTopic); PK.data = null; PK.open = new Set(); body.dataset.sig = '';
      history.replaceState(null, '', `#pack/${S.packId}`); renderView();
    }));
    $$('.pk-row', body).forEach((det) => {
      const key = det.dataset.pk;
      if (det.open) renderRow(key, $('.pk-inner', det));
      det.addEventListener('toggle', () => {
        if (det.open) { PK.open.add(key); renderRow(key, $('.pk-inner', det)); } else PK.open.delete(key);
      });
    });
    items.forEach(paintApproval);
  },
};
