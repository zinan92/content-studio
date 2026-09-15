'use strict';
/* 统筹页下方的参考：对标爆款 48 小时 · 日报头条 · 高频话题（统筹生成时也会读对标爆款） */
window.VIEWS = window.VIEWS || {};
window.TODAY_CARDS = window.TODAY_CARDS || [];

const HOT = { data: null, at: 0 };
async function loadHot(force) {
  if (!force && HOT.data && Date.now() - HOT.at < 120000) return HOT.data;
  HOT.data = await api('/api/hot');
  HOT.at = Date.now();
  return HOT.data;
}

async function topicFrom(title, notePath) {
  try {
    await api('/api/topics', { method: 'POST', body: { title, note_paths: notePath ? [notePath] : [], account_id: S.mine.account ? S.mine.account.id : null } });
    toast('已做成选题');
    if (window.refreshTopics) await window.refreshTopics();
  } catch (err) { toast(err.message); }
}

function benchRow(v) {
  return `<div class="hot-row">
    <span class="pill hot">${v.multiple.toFixed(1)}×</span>
    <div class="hot-main"><b class="clamp">${esc(cleanTitle(v.title))}</b><small>${esc(v.account_nickname || '')} · ${fmt(v.likes)} 赞 · ${day(v.published_at)}</small></div>
    <div class="acts">${teardownButton(v, { source: `统筹参考 · ${v.account_nickname || ''} · ${v.multiple.toFixed(1)}×` })}<button class="btn small ghost" type="button" data-hot-topic="${esc(cleanTitle(v.title))}">做成选题</button></div>
  </div>`;
}

function headlineRow(h) {
  return `<div class="hot-row">
    <span class="src-tag">${esc(h.daily)}</span>
    <div class="hot-main"><b class="clamp">${h.url ? `<a href="${esc(h.url)}" target="_blank" rel="noopener">${esc(h.title)}</a>` : esc(h.title)}</b><small>${esc(h.source)}</small></div>
    <div class="acts"><button class="btn small ghost" type="button" data-hot-topic="${esc(h.title)}" data-hot-note="${esc(h.daily_path)}">做成选题</button></div>
  </div>`;
}

function bindHot(root) {
  $$('[data-hot-topic]', root).forEach((b) => (b.onclick = () => topicFrom(b.dataset.hotTopic, b.dataset.hotNote)));
  bindTeardownButtons(root);
}

const syncedNote = (b) => (b.last_synced_at ? `对标数据 ${ago(b.last_synced_at)}` : '对标账号还没同步');

window.renderBriefHot = {
  async render() {
    const body = $('#briefHot');
    if (!body) return;
    let d;
    try { d = await loadHot(false); } catch (err) { body.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`; return; }
    const sig = String(HOT.at) + S.jobs.map((j) => j.stage).join();
    if (body.dataset.sig === sig) return;
    body.dataset.sig = sig;
    const b = d.benchmarks;
    body.innerHTML = `
      <div class="panel"><div class="panel-h"><h2>参考：对标账号近 ${b.hours} 小时爆款</h2><small>门槛 ${d.threshold}× · ${syncedNote(b)} <button class="btn small" type="button" id="hotSync">同步对标</button></small></div>
        ${b.items.length ? b.items.map(benchRow).join('') : `<div class="empty"><span>近 ${b.hours} 小时没有超过门槛的新作品${b.fallback.length ? '，下面是近 7 天的' : ''}</span></div>${b.fallback.map(benchRow).join('')}`}
      </div>
      <div class="two-col">
        <div class="panel"><div class="panel-h"><h2>今天日报的头条</h2><small>来自你的 AI 日报和财经日报</small></div>
          ${d.vault_error ? `<div class="empty"><span>${esc(d.vault_error)}</span></div>` : d.headlines.length ? d.headlines.map(headlineRow).join('') : '<div class="empty"><span>今天的日报还没出</span></div>'}
        </div>
        <div class="panel"><div class="panel-h"><h2>反复出现的话题</h2><small>近 7 天剪藏 + 近 2 天日报，出现 ≥2 次</small></div>
          ${d.topics.length ? `<div class="terms">${d.topics.map((t) => `<details class="term"><summary><b>${esc(t.term)}</b><span class="num">${t.count}</span></summary>${t.examples.map((e) => `<div class="term-ex">${e.url ? `<a href="${esc(e.url)}" target="_blank" rel="noopener">${esc(e.title)}</a>` : esc(e.title)}</div>`).join('')}<button class="btn small ghost" type="button" data-hot-topic="${esc(t.term)}">用这个话题做选题</button></details>`).join('')}</div>` : '<div class="empty"><span>还没有重复出现的话题</span></div>'}
        </div>
      </div>`;
    bindHot(body);
    $('#hotSync').onclick = async () => {
      try { const r = await api('/api/sync', { method: 'POST' }); toast(r.message); } catch (err) { toast(err.message); }
    };
  },
};
