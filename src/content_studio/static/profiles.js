'use strict';
/* 各平台主页：别人点进来第一眼看到的名字、简介、链接（profiles.py）。放在「定位」页最下面——它们都从定位来。
 * 工作台是正本：在这里写、存；X 能直接改上去（点了才改），别的平台复制过去、贴完点「已经改到平台上了」。 */
const PF_STATE = { empty: ['没写', 'low'], draft: ['写了，还没改到平台', 'mid'], applied: ['平台上就是这一版', 'hot'] };
const PFX = { data: null, live: null };

function profileCard(p) {
  const [word, tone] = PF_STATE[p.state];
  const cap = (f) => (p.limits[f] ? ` / ${p.limits[f]}` : '');
  const over = (f) => (p.limits[f] && (p[f] || '').length > p.limits[f] ? 'over' : '');
  const live = p.key === 'x' && PFX.live ? `<div class="pf-live"><small>X 上现在是</small><b>${esc(PFX.live.name || '')}</b><span>${esc(PFX.live.description || '（没有简介）')}</span></div>` : '';
  return `<div class="pf-card ${p.core ? '' : 'rest'}" data-pf="${p.key}">
    <div class="pf-top"><b>${esc(p.label)}</b><span class="pill ${tone}">${word}${p.state === 'applied' && p.applied_at ? ' · ' + day(p.applied_at) : ''}</span></div>
    ${live}
    <label><span class="pf-lab">名字 <i class="${over('name')}"><b data-pf-count="name">${(p.name || '').length}</b>${cap('name')}</i></span>
      <input data-pf-f="name" value="${esc(p.name)}" placeholder="主页上显示的名字" autocomplete="off"></label>
    <label><span class="pf-lab">简介 <i class="${over('bio')}"><b data-pf-count="bio">${(p.bio || '').length}</b>${cap('bio')}</i></span>
      <textarea data-pf-f="bio" rows="4" placeholder="我是谁、帮谁、做成什么、怎么找我">${esc(p.bio)}</textarea></label>
    <label><span class="pf-lab">链接</span>
      <input data-pf-f="link" value="${esc(p.link)}" placeholder="https://（可留空）" autocomplete="off"></label>
    <small class="pf-hint">${esc(p.hint)}</small>
    <div class="pf-acts">
      <button class="btn small" type="button" data-pf-copy="${p.key}">复制简介</button>
      ${p.edit_url ? `<a class="btn small" href="${esc(p.edit_url)}" target="_blank" rel="noopener">打开编辑页 ↗</a>` : ''}
      ${p.can_push ? `<button class="btn small primary" type="button" data-pf-push="${p.key}" ${p.state === 'draft' ? '' : 'disabled'}>改到 ${esc(p.label)} 上</button>`
        : `<button class="btn small ${p.state === 'draft' ? 'primary' : ''}" type="button" data-pf-applied="${p.key}" ${p.state === 'draft' ? '' : 'disabled'}>已经改到平台上了</button>`}
    </div></div>`;
}

window.renderProfiles = async () => {
  const box = $('#profilesBody');
  if (!box) return;
  try { PFX.data = await api('/api/profiles'); } catch (err) { box.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`; return; }
  if (document.activeElement && box.contains(document.activeElement) && document.activeElement.matches('input, textarea')) return;
  const ps = PFX.data.platforms;
  box.innerHTML = `<section class="pos-sec pf-sec">
      <div class="pos-h"><h2>各平台主页</h2><p>别人点进你主页第一眼看到的：名字、简介、链接。都从上面的定位来，在这里写、存。X 可以直接改上去；别的平台复制过去，贴完回来点一下。</p></div>
      <div class="pf-grid">${ps.map(profileCard).join('')}</div>
    </section>`;
  const again = () => window.renderProfiles();
  const save = async (card) => {
    const key = card.dataset.pf;
    const body = Object.fromEntries($$('[data-pf-f]', card).map((el) => [el.dataset.pfF, el.value]));
    try { await api(`/api/profiles/${key}`, { method: 'PUT', body }); toast('存好了'); } catch (err) { toast(err.message); }
    again();
  };
  $$('.pf-card', box).forEach((card) => {
    $$('[data-pf-f]', card).forEach((el) => {
      el.onchange = () => save(card);
      el.oninput = () => { const c = $(`[data-pf-count="${el.dataset.pfF}"]`, card); if (c) c.textContent = el.value.length; };
    });
  });
  $$('[data-pf-copy]', box).forEach((b) => (b.onclick = async () => {
    const p = ps.find((x) => x.key === b.dataset.pfCopy);
    try { await navigator.clipboard.writeText(p.bio || ''); toast('简介复制好了'); } catch (_) { toast('没复制上，手动选中复制'); }
  }));
  $$('[data-pf-applied]', box).forEach((b) => (b.onclick = async () => { try { await api(`/api/profiles/${b.dataset.pfApplied}/applied`, { method: 'POST' }); toast('记下了'); } catch (err) { toast(err.message); } again(); }));
  $$('[data-pf-push]', box).forEach((b) => (b.onclick = async () => {
    if (!b.dataset.armed) { b.dataset.armed = '1'; b.textContent = '再点一次：真的改到 X 上'; setTimeout(() => { if (document.body.contains(b)) { delete b.dataset.armed; b.textContent = '改到 X 上'; } }, 4000); return; }
    b.disabled = true;
    try { const r = await api('/api/profiles/x/push', { method: 'POST' }); PFX.live = r.live; toast('X 主页改好了'); } catch (err) { toast(err.message); }
    again();
  }));
  // X 上现在是什么：读一次，读不到就不显示
  if (PFX.live === null && ps.some((p) => p.key === 'x')) {
    PFX.live = false;
    api('/api/profiles/x/live').then((r) => { PFX.live = r.live; again(); }).catch(() => {});
  }
};
