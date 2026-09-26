/* 定位页 = 工作台首页：公司 one pager，原生画在这一页里。
 * 内容来自 Park 自己的 positioning.json（和 principles.md 放一起，不进仓库）；
 * 没有 json 时退回渲染 positioning.md。工作台唯一会写的地方是「待拍板」。 */
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

/* ---------- 飞轮：五个节点一个环，博主线从右边并进来 ---------- */
function posFlywheel(f) {
  const CX = 330, CY = 300, R = 200, W = 150, H = 64;
  const ang = [-90, -18, 54, 126, 198];               // 五边形，从正上方顺时针
  const rad = (a) => (a * Math.PI) / 180;
  const at = (a, r) => [CX + r * Math.cos(rad(a)), CY + r * Math.sin(rad(a))];
  const P = (a, r) => at(a, r).map((v) => v.toFixed(1)).join(' ');
  const gap = 14;                                     // 箭头离节点的角度余量
  const arcs = ang.map((a, i) => {
    const b = ang[(i + 1) % 5];
    const cls = i === 2 ? 'arc money' : 'arc';
    return `<path class="${cls}" d="M${P(a + gap, R)} A${R} ${R} 0 0 1 ${P(b - gap, R)}" marker-end="url(#posArrow)"/>`;
  }).join('');
  // 环外的标签：两节点中间的角度、半径之外；左右两个手动往里收一点免得出画
  const labelPos = [[-54, 268, 0, 0], [8, 255, 0, 0], [90, 262, 0, 0], [162, 268, 22, 0], [234, 268, -18, 0]];
  const labels = f.edges.map((txt, i) => {
    const [a, r, dx, dy] = labelPos[i];
    const [x, y] = at(a, r);
    const cls = i === 2 ? 'lbl money' : 'lbl hot';
    return `<text class="${cls}" x="${(x + dx).toFixed(1)}" y="${(y + dy).toFixed(1)}">${esc(txt)}</text>`;
  }).join('');
  const nodes = f.nodes.map((n, i) => {
    const [x, y] = at(ang[i], R);
    return `<g><rect class="node ${n.tone || ''}" x="${(x - W / 2).toFixed(1)}" y="${(y - H / 2).toFixed(1)}" width="${W}" height="${H}" rx="12"/><text class="t" x="${x.toFixed(1)}" y="${(y - 4).toFixed(1)}">${esc(n.t)}</text><text class="s" x="${x.toFixed(1)}" y="${(y + 18).toFixed(1)}">${esc(n.s)}</text></g>`;
  }).join('');
  const s = f.side;
  const side = `
    <g><rect class="node gold" x="735" y="128" width="170" height="64" rx="12"/><text class="t" x="820" y="156">${esc(s.a.t)}</text><text class="s" x="820" y="178">${esc(s.a.s)}</text></g>
    <g><rect class="node gold" x="735" y="392" width="170" height="64" rx="12"/><text class="t" x="820" y="420">${esc(s.b.t)}</text><text class="s" x="820" y="442">${esc(s.b.s)}</text></g>
    <path class="arc gold" d="M405 74 C 540 18, 700 18, 770 128" marker-end="url(#posArrow)"/>
    <text class="lbl gold" x="600" y="30">${esc(s.in)}</text>
    <path class="arc gold" d="M820 192 L820 392" marker-end="url(#posArrow)"/>
    <text class="lbl gold" x="862" y="296">${esc(s.down)}</text>
    <path class="arc gold" d="M735 438 C 660 470, 600 475, 530 466" marker-end="url(#posArrow)"/>
    <text class="lbl gold" x="640" y="500">${esc(s.to)}</text>
    <path class="arc gold" d="M525 455 C 640 455, 700 300, 745 192" marker-end="url(#posArrow)"/>
    <text class="lbl gold" x="684" y="312" style="text-anchor:start">${esc(s.back)}</text>`;
  return `<svg class="pos-fw" viewBox="0 0 960 590" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="增长飞轮">
    <defs><marker id="posArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="context-stroke"/></marker></defs>
    <circle class="ring" cx="${CX}" cy="${CY}" r="${R}"/>
    ${arcs}${labels}${nodes}${side}
    <text class="c1" x="${CX}" y="${CY - 6}">${esc(f.center)}</text>
    <text class="s" x="${CX}" y="${CY + 18}">${esc(f.center_sub)}</text>
  </svg>`;
}

function posPage(d) {
  const p = d.data;
  const c = p.company;
  const pend = d.proposals || [];
  return `
  <div class="pos">
    <header class="pos-brand">
      <div>
        <div class="pos-eyebrow">Company one pager · ${esc(c.date)}</div>
        <h1>${esc(c.name)}</h1>
        <div class="pos-en">${esc(c.en)}</div>
        <p class="pos-vp"><b>${esc(c.tagline_lead)}</b>${esc(c.tagline)}</p>
      </div>
      <div class="pos-kw"><span>私信关键词</span><b>「${esc(c.keyword)}」</b><p>${esc(c.keyword_note)}</p></div>
    </header>

    <section class="pos-sec">
      <div class="pos-h"><h2>定位</h2><p>三问，每问一句话</p></div>
      <div class="pos-q3">${p.questions.map((q) => `<div class="pos-q"><div class="k">${esc(q.k)}</div><h3>${esc(q.title)}</h3><p>${esc(q.body)}${q.bold ? ` <b>${esc(q.bold)}</b>` : ''}</p><div class="st">${esc(q.status)}</div></div>`).join('')}</div>
    </section>

    <section class="pos-sec">
      <div class="pos-h"><h2>增长飞轮</h2><p>橙色主环是自己的号，金色是博主线，两条线在“客户”汇合</p></div>
      <div class="panel pos-fw-box">${posFlywheel(p.flywheel)}</div>
      <div class="pos-creed">${p.creed.map((x) => `<div><b>${esc(x.h)}<i>${esc(x.hi)}</i></b>${esc(x.p)}</div>`).join('')}</div>
      <div class="pos-boot">${p.bootstrap.map((x, i) => `<div class="c"><div class="n">${i}</div><b>${esc(x.b)}</b><span>${esc(x.s)}</span></div>`).join('')}</div>
    </section>

    <section class="pos-sec">
      <div class="pos-h"><h2>差异化</h2><p>三个对手，各一句</p></div>
      <div class="pos-diff">${p.diff.map((x) => `<div class="d"><div class="vs">${esc(x.vs)}</div><h3>${esc(x.h)}</h3><p>${esc(x.p)}</p></div>`).join('')}</div>
    </section>

    <section class="pos-sec">
      <div class="pos-h"><h2>定价</h2><p>${esc(p.pricing.sub)}</p></div>
      <div class="panel pos-tbl"><table>
        <thead><tr><th>档</th><th>价格</th><th>是什么</th><th>为什么这个价</th></tr></thead>
        <tbody>${p.pricing.rows.map((r) => `<tr><td class="role">${esc(r.role)}</td><td class="pr">${esc(r.price)}${r.unit ? `<small>${esc(r.unit)}</small>` : ''}</td><td>${esc(r.what)}</td><td>${esc(r.why)}</td></tr>`).join('')}</tbody>
      </table></div>
      <p class="pos-note">${esc(p.pricing.note)}</p>
    </section>

    <section class="pos-sec">
      <div class="pos-h"><h2>产品线</h2><p>全是作品集，每一个都是“我给谁做过什么”的证据，也是下一单的模板</p></div>
      <div class="pos-prods">${p.products.map((x) => `<div class="p ${x.first ? 'first' : ''}">${x.first ? `<em>${esc(x.em)}</em>` : ''}<b>${esc(x.b)}</b><span>${esc(x.s)}</span></div>`).join('')}</div>
    </section>

    <section class="pos-sec">
      <div class="pos-h"><h2>通用原则</h2><p>换个人也成立</p></div>
      <ol class="pos-pr">${p.principles.map((x) => `<li><b>${esc(x.b)}</b>${esc(x.s)}</li>`).join('')}</ol>
    </section>

    <section class="pos-sec">
      <div class="pos-h"><h2>每周自测</h2><p>翻最近 10 条视频标题，站在陌生人的角度答</p></div>
      <div class="panel pos-self">
        <ol>${p.selftest.items.map((x) => `<li>${esc(x)}</li>`).join('')}</ol>
        <div class="ans"><b>${esc(p.selftest.answer_date)} 的答案</b>${esc(p.selftest.answer)}</div>
      </div>
    </section>

    <section class="pos-sec pos-foot">
      <div class="pos-h"><h2>待拍板</h2><p>${pend.length ? `Anna 提了 ${pend.length} 条，采纳的自己挪进上面正文` : 'Anna 还没提过。说不清三问的时候，叫她过来。'}</p></div>
      <div class="pos-pend">${pend.map((x) => `<div class="pos-chip"><span>${esc(x.text)}</span><small>${esc(x.at)}${x.source ? ' · ' + esc(x.source) : ''}</small><button class="linklike" type="button" data-pos-drop="${esc(x.id)}">不采纳</button></div>`).join('')}</div>
      <div class="pos-bar"><button class="btn small primary" type="button" id="posAsk">叫 Anna 过来</button><span class="pos-bar-meta"><code>${esc(d.path.replace(/positioning\.md$/, 'positioning.json'))}</code><button class="linklike" type="button" id="posReload">重新读</button></span></div>
    </section>
  </div>`;
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
    if (d.data) {
      body.innerHTML = posPage(d);
    } else if (d.exists) {
      // 没有 json：退回渲染 Markdown（老形态）
      body.innerHTML = `<div class="pos"><article class="panel pos-doc"><div class="md">${renderMarkdown(d.markdown)}</div></article>
        <div class="pos-bar"><button class="btn small primary" type="button" id="posAsk">叫 Anna 过来</button><span class="pos-bar-meta"><code>${esc(d.path)}</code> 改于 ${posUpdated(d.updated)} <button class="linklike" type="button" id="posReload">重新读</button></span></div></div>`;
    } else {
      body.innerHTML = `<div class="panel empty"><b>还没有定位文件。</b><span>在编辑器里新建 <code>${esc(d.path)}</code>，写下三问：我是谁、怎么找到客户、卖什么。</span></div>`;
      return;
    }
    $('#posAsk').onclick = () => { if (window.openAnna) window.openAnna('先帮我看这一页：我的三问里，哪一问答得最不像细分定位？只追问一个问题。'); };
    $('#posReload').onclick = () => window.reloadPositioning();
    $$('[data-pos-drop]', body).forEach((b) => (b.onclick = async () => {
      if (!confirm('把这一条从待拍板里删掉？')) return;
      try { await api(`/api/positioning/${b.dataset.posDrop}`, { method: 'DELETE' }); toast('已删掉'); await window.reloadPositioning(); } catch (err) { toast(err.message); }
    }));
  },
};
