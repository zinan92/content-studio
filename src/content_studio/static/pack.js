'use strict';
/* 03 打包：发之前把一条内容要的东西全备好，发布台那边就只剩一个个平台点出去。
   9/29 Park：「发布的时候，我希望就是纯发布；发布前准备就是 get ready for everything。」
   视频包：封面（选一帧）、标题、文案描述、简介、话题。
   文字包：研习室文章、插图、公众号排版、小红书图文、X 图文。
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
    const [topics, figs, wx, xhs] = await Promise.all([
      api('/api/topics'),
      d.has_article ? api(`/api/topics/${d.topic.id}/illustrate`).catch(() => null) : null,
      d.has_article ? api(`/api/topics/${d.topic.id}/layout`).catch(() => null) : null,
      d.has_article ? api(`/api/topics/${d.topic.id}/xhs`).catch(() => null) : null,
    ]);
    PK.topic = topics.find((t) => t.id === d.topic.id) || null;
    PK.st = { figs, wx, xhs };
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
const PK_STATE = { ok: ['好了'], wip: ['在做'], no: ['没做'], bad: ['要重做'] };
const PK_ICON = { ok: '✓', wip: '', no: '○', bad: '!' };

function packItems(d, t, st) {
  const c = (d.release && d.release.covers) || {};
  const covers = [['landscape', '横版'], ['portrait', '竖版'], ['wechat', '公众号']].filter(([k]) => c[k]).map(([, l]) => l);
  const e = d.entry || { title: '', body: '', tags: [] };
  const art = !d.has_article
    ? (t && t.write_state === 'running' ? ['wip', '正在写，一般 1–5 分钟'] : t && t.write_state === 'failed' ? ['bad', t.write_error || '上次写失败了'] : ['no', '用这条视频的原话写成文字版'])
    : ['ok', d.article && d.article.title ? `《${d.article.title}》` : '写好了'];
  const needArt = (fn) => (d.has_article ? fn() : ['no', '先写研习室文章']);
  const figs = needArt(() => {
    const s = st.figs || {};
    if (s.running) return ['wip', '小黑手绘，一张一张画，5–10 分钟'];
    if (s.error) return ['bad', s.error];
    return s.images && s.images.length ? ['ok', `${s.images.length} 张，已插进文章`] : ['no', '4–8 张，插在对应段落后面'];
  });
  const wx = needArt(() => {
    const s = st.wx || {};
    if (s.running) return ['wip', '正在用 gzh 排版，5–10 分钟'];
    if (s.error) return ['bad', s.error];
    if (s.has_layout && s.stale) return ['bad', '文章改过了，旧排版作废'];
    return s.has_layout ? ['ok', `gzh 排好了（${s.theme || '橄榄手记'}），公众号和研习室都用这份`] : ['no', '不排也能发，用的是基础排版'];
  });
  const xhs = needArt(() => {
    const s = st.xhs || {};
    if (s.running) return ['wip', '正在出图'];
    if (s.error) return ['bad', s.error];
    if (s.stale) return ['bad', '文章改过了，这组图是旧的'];
    return s.images && s.images.length ? ['ok', `${s.images.length} 张 3:4，一字不改`] : ['no', '文章原文排成 3:4 的图'];
  });
  return [
    { key: 'cover', group: 'video', label: '封面', state: covers.length ? 'ok' : 'no', note: covers.length ? `${covers.join(' · ')}都有了` : '从成片里选一帧，出横、竖、公众号三张' },
    { key: 'copy', group: 'video', label: '标题 · 描述 · 简介 · 话题', state: d.has_copy ? 'ok' : 'no', note: d.has_copy ? (e.title || '已保存') : '一个标题，一段描述，一段简介，几个话题' },
    { key: 'article', group: 'text', label: '研习室文章', state: art[0], note: art[1] },
    { key: 'figs', group: 'text', label: '插图', state: figs[0], note: figs[1] },
    { key: 'wx', group: 'text', label: '公众号排版', state: wx[0], note: wx[1] },
    { key: 'xhs', group: 'text', label: '小红书图文', state: xhs[0], note: xhs[1] },
    { key: 'x', group: 'text', label: 'X 图文', state: d.has_article ? 'ok' : 'no', note: d.has_article ? '发的是这篇文章，封面发的时候按标题出一张纯文字横幅' : '先写研习室文章' },
  ];
}

function row(it) {
  const [word] = PK_STATE[it.state];
  const icon = it.state === 'wip' ? '<span class="spin"></span>' : PK_ICON[it.state];
  return `<details class="pk-row s-${it.state}" data-pk="${it.key}" ${PK.open.has(it.key) ? 'open' : ''}>
    <summary><i class="pk-dot">${icon}</i><b>${esc(it.label)}</b><span class="pk-note">${esc(it.note)}</span><span class="pk-word">${word}</span></summary>
    <div class="pk-body" id="pkb-${it.key}"></div>
  </details>`;
}

/* ---------- 每一项展开后的内容 ---------- */
async function renderCoverMaker(topicId, box) {
  box.innerHTML = '<div class="cv-body"><p class="pdl-note"><span class="spin"></span> 正在从成片里取几帧…</p></div>';
  let o;
  try { o = await api(`/api/topics/${topicId}/cover`); } catch (err) { box.innerHTML = `<p class="pdl-note bad">${esc(err.message)}</p>`; return; }
  const st = { lines: o.lines, emphasis: o.emphasis, at: o.frames.length ? o.frames[Math.floor(o.frames.length / 2)].at : 0 };
  const emphasisChips = () => st.lines.map((l) => `<button type="button" class="cv-em ${l === st.emphasis ? 'on' : ''}" data-cv-em="${esc(l)}">${esc(l)}</button>`).join('');
  const rel = PK.data && PK.data.release;
  const current = rel && rel.cover_urls ? [['landscape', '横版'], ['portrait', '竖版'], ['wechat', '公众号']].filter(([k]) => rel.cover_urls[k]) : [];
  box.innerHTML = `<div class="cv-body">
    <div class="cv-col">
      <div class="cv-l">选一帧当封面<small>挑表情好、眼睛睁着的</small></div>
      <div class="cv-frames">${o.frames.map((f) => `<button type="button" class="cv-frame ${f.at === st.at ? 'on' : ''}" data-cv-at="${f.at}"><img src="${f.url}" alt="第 ${Math.round(f.at)} 秒"><small>${Math.floor(f.at / 60)}:${String(Math.round(f.at % 60)).padStart(2, '0')}</small></button>`).join('')}</div>
    </div>
    <div class="cv-col">
      <label class="cv-l" for="cvLines">封面上的字<small>一行就是封面上的一行</small></label>
      <textarea id="cvLines" rows="4">${esc(st.lines.join('\n'))}</textarea>
      <div class="cv-l">哪一行用橙色<small>放大、加下划线</small></div>
      <div class="cv-ems" id="cvEms">${emphasisChips()}</div>
    </div>
    <div class="cv-foot"><button class="btn primary" type="button" id="cvGo">${current.length ? '重新出三张' : '出横、竖、公众号三张'}</button><span class="pdl-note" id="cvMsg">抠人像要十几秒。</span></div>
    <div class="cv-out" id="cvOut">${current.map(([k, l]) => `<a href="${rel.cover_urls[k]}" target="_blank" rel="noopener"><img class="cv-shot ${k}" src="${rel.cover_urls[k]}" alt="${l}封面"></a>`).join('')}</div>
  </div>`;
  const ta = $('#cvLines', box);
  const bindEm = () => $$('[data-cv-em]', box).forEach((b) => (b.onclick = () => { st.emphasis = b.dataset.cvEm; $('#cvEms', box).innerHTML = emphasisChips(); bindEm(); }));
  bindEm();
  ta.oninput = () => {
    st.lines = ta.value.split('\n').map((l) => l.trim()).filter(Boolean);
    if (!st.lines.includes(st.emphasis)) st.emphasis = st.lines[st.lines.length - 1] || '';
    $('#cvEms', box).innerHTML = emphasisChips(); bindEm();
  };
  $$('[data-cv-at]', box).forEach((b) => (b.onclick = () => { st.at = Number(b.dataset.cvAt); $$('[data-cv-at]', box).forEach((x) => x.classList.toggle('on', x === b)); }));
  $('#cvGo', box).onclick = async () => {
    const btn = $('#cvGo', box);
    btn.disabled = true; $('#cvMsg', box).textContent = '正在抠人像、排字…';
    try {
      const r = await api(`/api/topics/${topicId}/cover`, { method: 'POST', body: st });
      const stamp = Date.now();
      $('#cvOut', box).innerHTML = Object.entries(r.urls).map(([k, url]) => `<a href="${url}?t=${stamp}" target="_blank" rel="noopener"><img class="cv-shot ${k === '竖' ? 'portrait' : k === '公众号' ? 'wechat' : 'landscape'}" src="${url}?t=${stamp}" alt="${k}版封面"></a>`).join('');
      $('#cvMsg', box).textContent = '好了，已经放进交付包。不满意就换一帧或改字再出一次。';
      if (window.invalidatePublish) window.invalidatePublish();
      PK.data = null; // 上面那一行的状态下次刷新时变成「好了」；不重画这块，免得刚出的三张被冲掉
      loadPack(true).then(paintHead).catch(() => {});
    } catch (err) { $('#cvMsg', box).textContent = err.message; }
    finally { btn.disabled = false; }
  };
}

function renderRow(key, box) {
  const d = PK.data;
  const t = PK.topic;
  if (!d || !d.topic || box.dataset.done) return;
  box.dataset.done = '1';
  const id = d.topic.id;
  if (key === 'cover') {
    if (!d.video) { box.innerHTML = '<p class="pdl-note">还没有成片，取不了帧。成片出现在项目 final/ 里就能做。</p>'; return; }
    renderCoverMaker(id, box);
  } else if (key === 'copy') {
    renderCopyForm({ ...(t || {}), ...d.topic, outline_path: t && t.outline_path }, box, { release: d.release, onSaved: () => { refreshPack(); } });
  } else if (key === 'article') {
    const tab = (window.VIDEO_TABS || []).find((x) => x.key === 'article');
    if (tab && t) tab.render(t, box);
  } else if (key === 'figs') {
    box.innerHTML = '<div id="pdlFigs"></div>';
    if (d.has_article) renderFigs(box, id); else box.innerHTML = '<p class="pdl-note">插图插在文章里，先把上面的研习室文章写好。</p>';
  } else if (key === 'wx') {
    box.innerHTML = d.has_article ? '<div class="pdl-wx" id="pdlWx"></div>' : '<p class="pdl-note">公众号发的是研习室那篇文章，先把它写好。</p>';
    if (d.has_article) renderWx(box, id);
  } else if (key === 'xhs') {
    box.innerHTML = d.has_article ? '<div id="pdlXhs" class="xhs"></div>' : '<p class="pdl-note">小红书图文是把研习室那篇文章排成图，先把它写好。</p>';
    if (d.has_article) renderXhs(box, id);
  } else if (key === 'x') {
    box.innerHTML = `<p class="pdl-note">X 发的是研习室那篇文章（图文文章，插图一起传）。封面不用做：发的时候按文章标题出一张纯文字的 5:2 横幅，不带人脸。需要 X Premium。</p>`;
  }
}

/* 文章编辑器切预览/编辑、保存之后要重画自己那一块（整页的 sig 没变，不会重画） */
window.rerenderPackRow = (key) => {
  const box = $(`#pkb-${key}`);
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
  const n = (g) => items.filter((x) => x.group === g && x.state === 'ok').length;
  const all = (g) => items.filter((x) => x.group === g).length;
  const missing = packMissing(d);
  figs.innerHTML = `<div class="pub-figs">
    <span>成片 ${d.video ? `<b>${d.video.mb}</b> MB` : '<span class="bad">还没有</span>'}</span>
    <span>视频包 <b>${n('video')}</b> / ${all('video')}</span>
    <span>文字包 <b>${n('text')}</b> / ${all('text')}</span>
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
    const running = (t && t.write_state === 'running') || ['figs', 'wx', 'xhs'].some((k) => st[k] && st[k].running);
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
          <button class="btn small" type="button" data-pk-work="${w.id}">去看这一条 →</button>` : '<span>「加工中」里的一条剪完，就会出现在这里。</span>'}</div>`;
      $$('[data-pk-work]', body).forEach((b) => (b.onclick = () => openWork(Number(b.dataset.pkWork))));
      return;
    }
    if (!PK.open.size) PK.open = new Set(items.filter((i) => i.group === 'video' && i.state !== 'ok').map((i) => i.key).slice(0, 1));
    const chip = (c) => `<button class="pub-topic ${c.id === d.topic.id ? 'on' : ''}" type="button" data-pk-topic="${c.id}"><b>${esc(c.title)}</b>${c.shipped_count ? `<span class="num">已发 ${c.shipped_count}</span>` : ''}</button>`;
    const list = d.candidates.some((c) => c.id === d.topic.id) ? d.candidates : [d.topic, ...d.candidates];
    const group = (g, title, sub) => `<section class="pk-group"><div class="pk-gh"><h2>${title}</h2><small>${sub}</small></div>
      ${items.filter((i) => i.group === g).map(row).join('')}</section>`;
    body.innerHTML = `<div class="pub-head"><div class="pub-topics"><small>打包这条</small>${list.map(chip).join('')}</div></div>
      ${d.release && d.release.copy && !d.has_copy ? '<p class="pk-hint">成片包里有一份写好的发布文案，打开「标题 · 描述 · 简介 · 话题」可以一键填进来。</p>' : ''}
      ${group('video', '视频包', '抖音、视频号、B 站、YouTube、小红书视频都用这一份')}
      ${group('text', '文字包', '公众号、研习室、X、小红书图文用的是研习室那篇文章')}`;
    $$('[data-pk-topic]', body).forEach((b) => (b.onclick = () => {
      S.packId = Number(b.dataset.pkTopic); PK.data = null; PK.open = new Set(); body.dataset.sig = '';
      history.replaceState(null, '', `#pack/${S.packId}`); renderView();
    }));
    $$('.pk-row', body).forEach((det) => {
      const key = det.dataset.pk;
      if (det.open) renderRow(key, $('.pk-body', det));
      det.addEventListener('toggle', () => {
        if (det.open) { PK.open.add(key); renderRow(key, $('.pk-body', det)); } else PK.open.delete(key);
      });
    });
  },
};
