/* 定位页：我是谁 / 怎么找到客户 / 卖什么。
 * 内容是 Park 自己的 positioning.md（和 principles.md 放一起），这里只读、只渲染。
 * 工作台唯一会写的地方是文件末尾「待拍板」：Anna 提一句，Park 点了才进去。 */
window.VIEWS = window.VIEWS || {};

const POS = { data: null, loading: false };

async function loadPositioning() {
  POS.loading = true;
  try { POS.data = await api('/api/positioning'); } finally { POS.loading = false; }
}
window.reloadPositioning = async () => { try { await loadPositioning(); } catch (_) { /* shown on next render */ } if (S.view === 'positioning') renderView(); };

function posUpdated(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

window.VIEWS.positioning = {
  async render() {
    const body = $('#positioningBody');
    if (!POS.data && !POS.loading) {
      body.innerHTML = '<div class="panel empty"><span class="spin"></span><span>正在读定位…</span></div>';
      try { await loadPositioning(); } catch (err) { body.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`; return; }
    }
    const d = POS.data;
    if (!d) return;
    if (!d.exists) {
      body.innerHTML = `<div class="panel empty"><b>还没有定位文件。</b><span>在编辑器里新建 <code>${esc(d.path)}</code>，写下三问：我是谁、怎么找到客户、卖什么。</span></div>`;
      return;
    }
    const pend = d.proposals || [];
    if (d.page) {
      // Park's designed one pager, exactly as published: the frame is the page.
      const theme = document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
      body.innerHTML = `
        <iframe class="pos-frame" id="posFrame" src="/api/positioning/page?theme=${theme}&t=${Date.now()}" title="帕克动手"></iframe>
        <div class="pos-bar">
          <button class="btn small primary" type="button" id="posAsk">叫 Anna 过来</button>
          <span class="pos-bar-pend">${pend.length ? `待拍板 ${pend.length} 条：` + pend.map((p) => `<span class="pos-chip">${esc(p.text)} <button class="linklike" type="button" data-pos-drop="${esc(p.id)}">不采纳</button></span>`).join('') : ''}</span>
          <span class="pos-bar-meta"><code>${esc(d.path.replace(/positioning\.md$/, 'positioning.html'))}</code> <button class="linklike" type="button" id="posReload">重新读</button></span>
        </div>`;
      $('#posAsk').onclick = () => { if (window.openAnna) window.openAnna('先帮我看这一页：我的三问里，哪一问答得最不像细分定位？只追问一个问题。'); };
      $('#posReload').onclick = () => window.reloadPositioning();
      $$('[data-pos-drop]', body).forEach((b) => (b.onclick = async () => {
        if (!confirm('把这一条从待拍板里删掉？')) return;
        try { await api(`/api/positioning/${b.dataset.posDrop}`, { method: 'DELETE' }); toast('已删掉'); await window.reloadPositioning(); } catch (err) { toast(err.message); }
      }));
      return;
    }
    body.innerHTML = `
      <div class="pos-grid">
        <article class="panel pos-doc"><div class="md">${renderMarkdown(d.markdown)}</div></article>
        <aside class="pos-side">
          <div class="panel pos-ask">
            <div class="panel-h"><h2>和 Anna 聊定位</h2></div>
            <div class="pos-ask-body">
              <p>说不清「我是谁、找谁、卖什么」的时候，叫她过来。她会看着这一页和你最近的视频标题追问，答得更窄、更具体。</p>
              <p>她提的句子会出现在下面「待拍板」，你点了才写进文件；采纳的自己挪进正文。</p>
              <button class="btn primary" type="button" id="posAsk">叫 Anna 过来</button>
            </div>
          </div>
          <div class="panel">
            <div class="panel-h"><h2>待拍板</h2><small>${pend.length ? `${pend.length} 条` : '没有'}</small></div>
            <div class="pos-pend">${pend.length ? pend.map((p) => `<div class="pos-pend-row"><span>${esc(p.text)}</span><small>${esc(p.at)}${p.source ? ' · ' + esc(p.source) : ''}</small><button class="linklike" type="button" data-pos-drop="${esc(p.id)}">不采纳</button></div>`).join('') : '<div class="pos-empty">Anna 还没提过。</div>'}</div>
          </div>
          <div class="pos-meta"><span>文件</span><code>${esc(d.path)}</code><span>改于 ${posUpdated(d.updated)}</span><button class="linklike" type="button" id="posReload">重新读</button></div>
        </aside>
      </div>`;
    $('#posAsk').onclick = () => { if (window.openAnna) window.openAnna('先帮我看这一页：我的三问里，哪一问答得最不像细分定位？只追问一个问题。'); };
    $('#posReload').onclick = () => window.reloadPositioning();
    $$('[data-pos-drop]', body).forEach((b) => (b.onclick = async () => {
      if (!confirm('把这一条从待拍板里删掉？')) return;
      try { await api(`/api/positioning/${b.dataset.posDrop}`, { method: 'DELETE' }); toast('已删掉'); await window.reloadPositioning(); } catch (err) { toast(err.message); }
    }));
  },
};
