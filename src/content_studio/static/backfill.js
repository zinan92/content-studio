/* 03 发布 · 补发队列：抖音发过、别的平台还没发的旧视频。
 * 这里只排队和接管；真正发布走发布台，每个平台照旧要 Park 点确认。 */
window.VIEWS = window.VIEWS || {};

const BF = { data: null, busy: {}, poll: null };

async function loadBackfill() { [BF.data, BF.archive] = await Promise.all([api('/api/backfill'), api('/api/archive')]); }
window.refreshBackfillCount = async () => { try { await loadBackfill(); } catch (_) { /* ignore */ } paintPubSubnav(); };

function paintPubSubnav() {
  const n = BF.data ? BF.data.videos.filter((v) => v.missing.length).length : null;
  $$('[data-pubnav]').forEach((nav) => {
    nav.innerHTML = [['publish', '这一条'], ['backfill', `补发队列${n ? ` <span class="num">${n}</span>` : ''}`]]
      .map(([k, l]) => `<button type="button" class="${S.view === k ? 'on' : ''}" data-pubgo="${k}">${l}</button>`).join('');
    $$('[data-pubgo]', nav).forEach((b) => (b.onclick = () => go(b.dataset.pubgo)));
  });
}
window.paintPubSubnav = paintPubSubnav;

function bfCell(v, p) {
  const st = v.done[p.key];
  if (st === 'record') return `<span class="bf-dot on" title="${esc(p.label)}：发布台记过已发">✓</span>`;
  if (st === 'mark') return `<button class="bf-dot on mark" type="button" data-bfunmark="${esc(v.video_id)}" data-p="${p.key}" title="${esc(p.label)}：你标过已经发过，点一下撤回">✓</button>`;
  return `<button class="bf-dot" type="button" data-bfmark="${esc(v.video_id)}" data-p="${p.key}" title="${esc(p.label)}：还没发。在工作台外面发过的，点一下标成已发">·</button>`;
}

/* 每条只有一个按钮，永远是下一步：没有成片 → 先下成片；正在下 → 等；有了 → 拿去补发。 */
function bfNext(v) {
  if (!v.missing.length) return v.topic_id ? `<button class="linklike" type="button" data-bfopen="${v.topic_id}">看发布台 →</button>` : '';
  const has = v.video === 'master' || v.video === 'download';
  const d = v.download;
  if (!has && d && d.state === 'downloading') return '<span class="bf-file"><span class="spin"></span> 正在下成片…</span>';
  if (!has && BF.archive && BF.archive.progress && BF.archive.progress.state === 'downloading') return '<span class="bf-file">排队存档中</span>';
  // 没有成片：原片在另一台电脑上。拷进作品库里这条的「1 成片」（或 SSD 视频目录的任何地方），点顶上「在本机再找一遍」。
  if (!has) return '<span class="bf-file" title="原片在另一台电脑上：拷进作品库这条的「1 成片」，再点顶上「在本机再找一遍」">作品库缺成片 · 在另一台电脑上</span>';
  const note = v.video === 'master' ? '有成片' : '作品库里有成片';
  return `<span class="bf-file ok">${note}</span><button class="btn small primary" type="button" data-bftake="${esc(v.video_id)}" ${BF.busy[v.video_id] ? 'disabled' : ''}>拿去补发</button>`;
}

window.VIEWS.backfill = {
  async render() {
    paintPubSubnav();
    const body = $('#backfillBody');
    if (!BF.data) body.innerHTML = '<div class="panel empty"><span class="spin"></span><span>正在对账…</span></div>';
    try { await loadBackfill(); } catch (err) { body.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`; return; }
    paintPubSubnav();
    const d = BF.data;
    const cols = d.platforms;
    const todo = d.videos.filter((v) => v.missing.length);
    const done = d.videos.filter((v) => !v.missing.length);
    $('#backfillFigs').innerHTML = `<div class="pub-figs">${cols.map((p) => `<span>${esc(p.label)} 缺 <b>${p.missing}</b></span>`).join('')}</div>`;
    const row = (v) => `<tr>
      <td class="bf-title"><b>${esc(v.headline || v.title.slice(0, 30))}</b><small>${esc((v.published_at || '').slice(0, 10))} · 点赞 ${fmt(v.likes)}${v.multiple !== null ? ` · ${v.multiple}×` : ''}</small>
        <div class="bf-acts">${bfNext(v)}</div></td>
      ${cols.map((p) => `<td class="c">${bfCell(v, p)}</td>`).join('')}
    </tr>`;
    const head = `<tr><th>抖音发过的</th>${cols.map((p) => `<th class="c">${esc(p.label)}</th>`).join('')}</tr>`;
    const a = BF.archive || {};
    const p = a.progress || {};
    const running = p.state === 'downloading';
    let strip;
    if (!a.path) strip = '<span>还没设作品库目录。去「设置」填一个（建议放在外接硬盘上）。</span>';
    else if (!a.available) strip = `<span class="bad">作品库所在的硬盘没插：${esc(a.path)}</span>`;
    else strip = `<span>作品库有成片 <b>${a.archived}</b> / ${a.total} 条（本机原片 ${a.local}，其余是抖音下载版） · <code>${esc(a.path)}</code></span>
      ${running ? `<span><span class="spin"></span> 正在存：这一轮 ${p.total || '…'} 条，已存 ${p.done || 0} 条（每条之间停 20 秒）</span>`
        : a.pending ? `<button class="btn small" type="button" id="bfArchiveAll">在本机再找一遍（缺 ${a.pending} 条）</button>` : '<span class="bf-file ok">都有成片了</span>'}
      ${p.state === 'failed' && p.failed ? `<span class="bad" title="${esc(p.failed.error || '')}">上一轮停在一条下载失败上，可能是抖音风控；过一会儿再点</span>` : ''}
      <small>按时长和日期在本机找原片，不从抖音下。以后每次同步发现新视频，也只在本机找。</small>`;
    body.innerHTML = `
      <div class="panel bf-archive">${strip}</div>
      <p class="in-note">没东西拍的那天，从上往下挑一条，点它唯一的那个按钮：没有成片就「先下成片」（从抖音下回来，一次一条），下好了按钮变成「拿去补发」，它会种好文案、打开发布台，每个平台照旧你点确认才发。${esc(d.order)}。圆点可以点：在工作台外面已经发过的，点一下标成已发。公众号、研习室、X 要另写文字版，不算缺口。</p>
      <div class="panel bf-tbl"><table><thead>${head}</thead><tbody>${todo.map(row).join('') || `<tr><td colspan="${cols.length + 1}" class="empty">都补齐了。</td></tr>`}</tbody></table></div>
      ${done.length ? `<details class="panel bf-done"><summary>已经补齐 <span class="num">${done.length}</span></summary><table><tbody>${done.map(row).join('')}</tbody></table></details>` : ''}`;
    const mark = async (vid, p, doneFlag) => { try { await api(`/api/backfill/${vid}/mark`, { method: 'POST', body: { platform: p, done: doneFlag } }); await loadBackfill(); renderView(); } catch (err) { toast(err.message); } };
    $$('[data-bfmark]', body).forEach((b) => (b.onclick = () => mark(b.dataset.bfmark, b.dataset.p, true)));
    $$('[data-bfunmark]', body).forEach((b) => (b.onclick = () => mark(b.dataset.bfunmark, b.dataset.p, false)));
    $$('[data-bfopen]', body).forEach((b) => (b.onclick = () => { S.publishId = Number(b.dataset.bfopen); go('publish'); }));
    $$('[data-bftake]', body).forEach((b) => (b.onclick = async () => {
      const vid = b.dataset.bftake;
      BF.busy[vid] = true; renderView();
      try {
        const r = await api(`/api/backfill/${vid}/take`, { method: 'POST' });
        toast(r.has_video ? '接上了，去发布台' : '接上了。还没有成片，先在这里点「从抖音下成片」');
        if (r.has_video) { S.publishId = r.topic_id; if (window.resetDesk) window.resetDesk(); go('publish'); return; }
      } catch (err) { toast(err.message); }
      BF.busy[vid] = false; await loadBackfill(); renderView();
    }));
    $$('[data-bfdl]', body).forEach((b) => (b.onclick = async () => {
      if (!confirm('从抖音把这条视频下回来？一次只下一条，大概一两分钟。')) return;
      try { await api(`/api/backfill/${b.dataset.bfdl}/download`, { method: 'POST' }); toast('开始下了'); } catch (err) { toast(err.message); }
      await loadBackfill(); renderView();
    }));
    const all = $('#bfArchiveAll');
    if (all) all.onclick = async () => {
      if (!confirm(`按时长和日期在本机再找一遍这 ${a.pending} 条的原片？不会从抖音下。`)) return;
      try { await api('/api/archive/run', { method: 'POST' }); toast('开始存了'); } catch (err) { toast(err.message); }
      await loadBackfill(); renderView();
    };
    clearTimeout(BF.poll);
    if (running || d.videos.some((v) => v.download && v.download.state === 'downloading')) BF.poll = setTimeout(() => { if (S.view === 'backfill') renderView(); }, 3000);
  },
};
