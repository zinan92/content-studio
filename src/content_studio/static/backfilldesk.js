'use strict';
/* 补发工作台（10/1 Park）：「我要每天看大家的情绪和 mood……自己想好今天最适合发什么」。
 * 一张和全平台追踪一样的表（一行一条内容、一列一个平台），点格子挑今天发什么，点的顺序就是发的顺序（1、2、3、4）。
 * 确认 → 换个样子再看一遍（每格发出去是什么样、怎么发）→ 再确认，工作台按顺序现场发。
 * B 站、YouTube、X 自己发出去；公众号进草稿箱，群发他点；视频号、小红书没有自动通道，文件夹备好他传，传完点「发了」。
 * 全平台追踪那张表还是只用来看和补记（那边点「·」是「在外面发过」），挑格子只在这里。 */

const BW = { data: null, picks: [], step: 'pick', preview: null, poll: null, busy: false };
const BW_HOW = { auto: '自动发', draft: '进草稿箱', hand: '你来传' };
const BW_STATE = { idle: '还没发出去', waiting: '排队', running: '正在发…', done: '✓ 发出去了', draft: '进了草稿箱：去后台点发布，发完点「发了」', hand: '文件夹备好了：你传，传完点「发了」', failed: '没发出去' };

window.openBackfillDesk = async () => {
  BW.picks = []; BW.step = 'pick'; BW.preview = null;
  $('#bwBody').innerHTML = '<p class="td-note"><span class="spin"></span> 读全平台追踪…</p>';
  $('#bwDlg').showModal();
  await bwLoad();
};

async function bwLoad() {
  try { BW.data = await api('/api/backfill/desk'); } catch (err) { $('#bwBody').innerHTML = `<p class="td-note warn">${esc(err.message)}</p>`; return; }
  bwDraw();
  clearTimeout(BW.poll);
  if (BW.data.run.running) BW.poll = setTimeout(() => { if ($('#bwDlg').open && BW.step === 'pick') bwLoad(); }, 3000);
}

const bwKey = (vid, p) => `${vid}|${p}`;
function bwIndex(vid, p) { return BW.picks.findIndex((x) => bwKey(x.video_id, x.platform) === bwKey(vid, p)); }

function bwCell(r, p) {
  const c = r.cells[p.key] || {};
  if (c.state === 'sent') return c.url ? `<a class="bw-c sent" href="${esc(c.url)}" target="_blank" rel="noopener" title="${esc(p.label)}：发过了">✓</a>` : `<span class="bw-c sent" title="${esc(p.label)}：发过了">✓</span>`;
  if (c.state === 'planned') return `<span class="bw-c planned" title="今天已经排上了">今天</span>`;
  if (c.state === 'blocked') return `<span class="bw-c blocked" title="${esc(c.why || '')}">–</span>`;
  const i = bwIndex(r.video_id, p.key);
  return `<button type="button" class="bw-c open ${i >= 0 ? 'on' : ''}" data-bw-cell="${esc(r.video_id)}" data-p="${p.key}" title="《${esc(r.title)}》发到${esc(p.label)}" aria-pressed="${i >= 0}">${i >= 0 ? i + 1 : '+'}</button>`;
}

function bwRunBlock(run) {
  if (!run.items.length) return '';
  const row = (it, i) => {
    const sent = it.sent || it.state === 'done';
    const hand = it.how === 'hand';
    // 还没发出去的（没起过、失败了、或者重启后没了进度）：自动发的能再点一次「现在发」；要他传的给文件夹和上传页
    const again = !hand && ['idle', 'failed'].includes(it.state) && !run.running ? `<button class="btn small" type="button" data-bw-now="${esc(it.video_id)}" data-p="${it.platform}">${it.state === 'failed' ? '再发一次' : '现在发'}</button>` : '';
    const tail = sent ? '<span class="bw-ok">✓ 发了</span>' : ['idle', 'hand', 'draft', 'failed'].includes(it.state)
      ? `${again}${hand ? `<button class="btn small" type="button" data-bw-folder="${it.topic_id}" data-p="${it.platform}">打开上传文件夹</button>` : ''}${it.upload_url ? `<a class="btn small" href="${esc(it.upload_url)}" target="_blank" rel="noopener">去${esc(it.label)}上传 ↗</a>` : ''}<button class="btn small go" type="button" data-bw-sent="${esc(it.video_id)}" data-p="${it.platform}">发了</button>${it.state === 'idle' || it.state === 'failed' ? `<button class="linklike" type="button" data-bw-drop="${esc(it.video_id)}" data-p="${it.platform}">不发这格</button>` : ''}` : '';
    return `<div class="bw-run-i ${sent ? 'sent' : it.state}"><span class="bw-n">${i + 1}</span><span class="t"><b>《${esc(it.title)}》→ ${esc(it.label)}</b>
      <small>${it.state === 'running' ? '<span class="spin"></span> ' : ''}${sent ? '' : esc(BW_STATE[it.state] || it.state)}${it.message && !sent ? ` · ${esc(it.message)}` : ''}</small></span><span class="acts">${tail}</span></div>`;
  };
  return `<section class="bw-run"><h3>今天在发的 ${run.running ? '<small><span class="spin"></span> 一格一格发，前一格发完才发下一格</small>' : ''}</h3>${run.items.map(row).join('')}</section>`;
}

function bwPickView(d) {
  const head = `<tr><th>内容</th>${d.platforms.map((p) => `<th class="c">${esc(p.label)}<small class="bw-how ${p.how}" title="${esc(p.how_text)}">${BW_HOW[p.how] || ''}</small></th>`).join('')}</tr>`;
  const rows = d.rows.map((r) => `<tr><td class="bw-t"><b>${esc(r.title)}</b><small>${esc((r.published_at || '').slice(0, 10))}${r.likes != null ? ` · 点赞 ${fmt(r.likes)}` : ''}</small></td>${d.platforms.map((p) => `<td class="c">${bwCell(r, p)}</td>`).join('')}</tr>`).join('');
  const have = d.planned + BW.picks.length;
  const note = have >= d.need ? `今天一共 ${have} 格，够 ${d.need} 格了，都发出去就算出摊。` : `今天已排 ${d.planned} 格，还要再挑 ${d.need - have} 格才算出摊。`;
  return `${bwRunBlock(d.run)}
    <p class="td-note">看今天大家的情绪，点格子挑今天发什么：点的顺序就是发的顺序，再点一下取消。✓ 是发过了，– 是现在发不了（鼠标停上去看为什么）。</p>
    ${d.rows.length ? `<div class="bw-tbl"><table><thead>${head}</thead><tbody>${rows}</tbody></table></div>` : '<p class="td-note">旧内容都发完了。</p>'}
    <div class="bw-bar"><span>已选 <b>${BW.picks.length}</b> 格 · ${note}</span>
      <span class="btns"><button class="btn quiet" type="button" data-bw-clear ${BW.picks.length ? '' : 'disabled'}>清空</button><button class="btn go" type="button" data-bw-review ${BW.picks.length && !BW.busy ? '' : 'disabled'}>确认，换个样子看一遍 →</button></span></div>`;
}

function bwPreviewView(pv) {
  const item = (x) => `<article class="bw-pv">
      <span class="bw-n">${x.n}</span>
      ${x.cover ? `<img src="${esc(x.cover)}" alt="" loading="lazy">` : '<span class="bw-nocover"></span>'}
      <div class="bw-pv-b"><h4>《${esc(x.title)}》→ ${esc(x.label)}</h4>
        <p class="bw-how-line ${x.how}">${esc(x.how_text)}</p>
        ${x.article && x.article.title ? `<p><b>文章：${esc(x.article.title)}</b></p>${x.article.head.map((h) => `<p class="bw-dim">${esc(h)}</p>`).join('')}${x.article.layout_url ? `<a class="linklike" href="${esc(x.article.layout_url)}" target="_blank" rel="noopener">看完整排版 ↗</a>` : ''}`
          : `${x.copy.title ? `<p><b>${esc(x.copy.title)}</b></p>` : ''}${x.copy.body ? `<p class="bw-dim">${esc(x.copy.body.slice(0, 160))}${x.copy.body.length > 160 ? '…' : ''}</p>` : ''}${x.copy.tags.length ? `<p class="bw-dim">${x.copy.tags.map((t) => '#' + esc(t)).join(' ')}</p>` : ''}`}
      </div></article>`;
  return `<p class="td-note">按这个顺序发。点「开始发」就是你的确认：自动发的马上发出去，公众号进草稿箱，视频号、小红书把文件夹备好。</p>
    <div class="bw-pvs">${pv.items.map(item).join('')}</div>
    ${pv.short ? `<p class="td-note warn">这批发完，今天还差 ${pv.short} 格才算出摊。可以先发这批，回来再挑。</p>` : ''}
    <div class="bw-bar"><span>${pv.items.length} 格</span><span class="btns"><button class="btn quiet" type="button" data-bw-back>← 回去改</button><button class="btn go" type="button" data-bw-go ${BW.busy ? 'disabled' : ''}>开始发</button></span></div>`;
}

function bwDraw() {
  const body = $('#bwBody');
  const d = BW.data;
  if (!d) return;
  $('#bwStep').textContent = BW.step === 'preview' ? '第 2 步 · 再看一遍' : '第 1 步 · 挑格子';
  body.innerHTML = BW.step === 'preview' && BW.preview ? bwPreviewView(BW.preview) : bwPickView(d);
  $$('[data-bw-cell]', body).forEach((b) => (b.onclick = () => {
    const i = bwIndex(b.dataset.bwCell, b.dataset.p);
    if (i >= 0) BW.picks.splice(i, 1); else BW.picks.push({ video_id: b.dataset.bwCell, platform: b.dataset.p });
    bwDraw();
  }));
  const clear = $('[data-bw-clear]', body);
  if (clear) clear.onclick = () => { BW.picks = []; bwDraw(); };
  const review = $('[data-bw-review]', body);
  if (review) review.onclick = async () => {
    BW.busy = true; bwDraw();
    try { BW.preview = await api('/api/backfill/desk/preview', { method: 'POST', body: { cells: BW.picks } }); BW.step = 'preview'; } catch (err) { toast(err.message); }
    BW.busy = false; bwDraw();
    body.scrollTop = 0;
  };
  const back = $('[data-bw-back]', body);
  if (back) back.onclick = () => { BW.step = 'pick'; bwDraw(); };
  const goBtn = $('[data-bw-go]', body);
  if (goBtn) goBtn.onclick = async () => {
    BW.busy = true; bwDraw();
    try {
      const r = await api('/api/backfill/desk/go', { method: 'POST', body: { cells: BW.picks } });
      toast(`开始发：${r.started} 格，按你点的顺序`);
      BW.picks = []; BW.step = 'pick'; BW.preview = null;
    } catch (err) { toast(err.message); }
    BW.busy = false;
    await bwLoad();
    body.scrollTop = 0;
  };
  $$('[data-bw-folder]', body).forEach((b) => (b.onclick = async () => {
    try { await api(`/api/topics/${b.dataset.bwFolder}/upload-folder`, { method: 'POST', body: { platform: b.dataset.p, open: true } }); toast('文件夹打开了：视频、封面、文案.txt 都在里面'); } catch (err) { toast(err.message); }
  }));
  $$('[data-bw-now]', body).forEach((b) => (b.onclick = async () => {
    if (!confirm('这一格现在发出去？')) return;
    try { await api('/api/backfill/desk/go', { method: 'POST', body: { cells: [{ video_id: b.dataset.bwNow, platform: b.dataset.p }] } }); toast('开始发了'); } catch (err) { toast(err.message); }
    bwLoad();
  }));
  $$('[data-bw-drop]', body).forEach((b) => (b.onclick = async () => {
    try { await api('/api/backfill/desk/drop', { method: 'POST', body: { video_id: b.dataset.bwDrop, platform: b.dataset.p } }); toast('拿掉了，可以在表里重新挑'); } catch (err) { toast(err.message); }
    bwLoad();
  }));
  $$('[data-bw-sent]', body).forEach((b) => (b.onclick = async () => {
    try { await api(`/api/backfill/${b.dataset.bwSent}/mark`, { method: 'POST', body: { platform: b.dataset.p, done: true } }); } catch (err) { toast(err.message); }
    bwLoad();
  }));
}

document.addEventListener('DOMContentLoaded', () => {
  const dlg = $('#bwDlg');
  if (!dlg) return;
  $('#bwClose').onclick = () => dlg.close();
  dlg.addEventListener('close', () => {
    clearTimeout(BW.poll);
    const tb = $('#todayBody');
    if (tb) tb.dataset.sig = '';
    if (typeof S !== 'undefined' && S.view === 'today') renderView();
  });
});
