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
    { key: 'copy', group: 'video', label: '标题 · 描述 · 简介 · 话题', state: d.has_copy ? 'ok' : 'no', note: d.has_copy ? (e.title || '已保存') : '先写这个：标题、描述、简介、话题。封面的字就用这个标题' },
    { key: 'cover', group: 'video', label: '封面', state: covers.length ? 'ok' : 'no', note: covers.length ? `${covers.join(' · ')}都有了` : d.has_copy ? '用标题出，画面和橙色关键词机器定，5–10 分钟' : '写好标题后自动出' },
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
/* 封面：9/29 Park——字就是标题，画面机器挑（6 选 1 也行），橙色关键词机器定。
   出图交给 Codex 的 image_gen（和他以前那些好封面一样），5–10 分钟，在后台跑；这里只选帧、点一下、等。 */
async function renderCoverMaker(topicId, box, { auto = false } = {}) {
  if (!box.dataset.polling) box.innerHTML = '<p class="pdl-note"><span class="spin"></span> 正在从视频里挑画面…</p>';
  let o;
  try { o = await api(`/api/topics/${topicId}/cover`); } catch (err) { box.innerHTML = `<p class="pdl-note bad">${esc(err.message)}</p>`; return; }
  if (!document.body.contains(box)) return;
  if (!o.from_copy) {
    box.innerHTML = '<p class="pdl-note">封面上的字就是标题。先在上面「标题 · 描述 · 简介 · 话题」里写好标题并保存，保存完封面会自己出。</p>';
    return;
  }
  const pick = o.frames.find((f) => f.pick) || o.frames[Math.floor(o.frames.length / 2)] || {};
  let at = box.dataset.at ? Number(box.dataset.at) : pick.at || 0;
  const rel = PK.data && PK.data.release;
  const current = rel && rel.cover_urls ? [['portrait', '竖版'], ['landscape', '横版']].filter(([k]) => rel.cover_urls[k]) : [];
  const stamp = Date.now();
  box.innerHTML = `<div class="cv-auto">
    <p class="cv-words">封面上的字：<span>${esc(o.title)}</span><small>就是标题；橙色关键词机器挑。想改字，改上面的标题再出一次。</small></p>
    <div class="cv-l">画面<small>从「${esc(o.source)}」里按人脸清晰、正对镜头挑了一张；想换就点另一张</small></div>
    <div class="cv-frames six">${o.frames.map((f) => `<button type="button" class="cv-frame ${f.at === at ? 'on' : ''}" data-cv-at="${f.at}" ${o.running ? 'disabled' : ''}><img src="${f.url}" alt="第 ${Math.round(f.at)} 秒"><small>${f.pick ? '机器挑的 · ' : ''}${Math.floor(f.at / 60)}:${String(Math.round(f.at % 60)).padStart(2, '0')}</small></button>`).join('')}</div>
    <div class="cv-foot">${o.running
      ? '<span class="pdl-note"><span class="spin"></span> 正在用图像生成出竖版和横版，一般 5–10 分钟。可以先去做别的，出好这里会变。</span>'
      : `<button class="btn primary" type="button" id="cvGo">${current.length ? '用这一帧重新出' : '出封面（竖 3:4、横 4:3）'}</button><span class="pdl-note">${o.error ? `<b class="bad">上次没出成：${esc(o.error)}</b>` : '图像生成，5–10 分钟'}</span>`}</div>
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
    renderCopyForm({ ...(t || {}), ...d.topic, outline_path: t && t.outline_path }, box, { release: d.release, onSaved: () => {
      // 标题一存，封面就用它自动出（还没有封面的时候）；已经有封面的不动，想换在封面那行点「重新出」
      const c = (d.release && d.release.covers) || {};
      if (d.video && !(c.landscape || c.portrait)) { PK.open.delete('copy'); PK.open.add('cover'); PK.autoCover = true; }
      refreshPack();
    } });
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
