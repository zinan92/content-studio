'use strict';
/* 对外简介：Park 对外只有一份 profile（profiles.py），正本是 Obsidian 里的 park profile.md。
 * 放在「定位」页最下面：在这里改就写回 Obsidian，在 Obsidian 里改这里也跟着变。
 * 各平台不各写一份，只记「哪天改成了哪一版」；X 能直接改上去（点两次才改），别的平台复制过去贴。 */
const PFX = { data: null, live: null };
const PF_STATE = { synced: ['已同步', 'hot'], stale: ['简介改过了，要更新', 'mid'], never: ['还没改过', 'low'] };

function profilePlatform(p) {
  const [word, tone] = PF_STATE[p.state];
  const action = p.state === 'synced' ? ''
    : p.can_push ? `<button class="btn small primary" type="button" data-pf-push="${p.key}">改到 ${esc(p.label)} 上</button>`
      : `<button class="btn small" type="button" data-pf-applied="${p.key}">我贴好了</button>`;
  return `<div class="pf-plat ${p.core ? '' : 'rest'}"><b>${esc(p.label)}</b><span class="pill ${tone}">${word}${p.state !== 'never' && p.applied_at ? ' · ' + day(p.applied_at) : ''}</span>
    <small>${esc(p.where)}</small>
    <span class="acts">${p.edit_url ? `<a class="btn small ghost" href="${esc(p.edit_url)}" target="_blank" rel="noopener">打开 ↗</a>` : ''}${action}</span></div>`;
}

window.renderProfiles = async () => {
  const box = $('#profilesBody');
  if (!box) return;
  try { PFX.data = await api('/api/profile'); } catch (err) { box.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`; return; }
  if (document.activeElement && box.contains(document.activeElement) && document.activeElement.matches('input, textarea')) return;
  const d = PFX.data, p = d.profile, L = d.limits;
  const live = PFX.live ? `<div class="pf-live"><small>X 上现在是</small><b>${esc(PFX.live.name || '')}</b><span>${esc(PFX.live.description || '（没有简介）')}</span></div>` : '';
  const sug = d.suggestion ? `<div class="pf-sug"><small>按现在的定位，我写了一版，你看要不要换：</small><b>${esc(d.suggestion.name)}</b><span>${esc(d.suggestion.bio)}</span>
      <div class="acts"><button class="btn small primary" type="button" id="pfTake">换成这一版</button><button class="btn small ghost" type="button" id="pfDrop">不用</button></div></div>` : '';
  box.innerHTML = `<section class="pos-sec pf-sec">
      <div class="pos-h"><h2>对外简介</h2><p>别人点进你任何一个平台的主页，看到的都是这一份。正本在 Obsidian，在这里改会写回去。</p></div>
      <div class="pf-one">
        <div class="pf-edit">
          <label><span class="pf-lab">名字 <i class="${p.name.length > L.name ? 'over' : ''}"><b data-pf-count="name">${p.name.length}</b> / ${L.name}</i></span>
            <input id="pfName" value="${esc(p.name)}" placeholder="主页上显示的名字" autocomplete="off"></label>
          <label><span class="pf-lab">简介 <i class="${p.bio.length > L.bio ? 'over' : ''}"><b data-pf-count="bio">${p.bio.length}</b> / ${L.bio}</i></span>
            <textarea id="pfBio" rows="7" placeholder="我是谁、帮谁、做成什么、怎么找我">${esc(p.bio)}</textarea></label>
          <small class="pf-hint">${p.exists ? `<code>${esc(p.path.replace(/^.*\/(000_park-os\/)/, '$1'))}</code>${p.embeds ? ` · 文件里还有 ${p.embeds} 张图，原样留着` : ''}` : '这份文件还不存在，存一次就会建出来'} · 一份简介到处用，所以按最紧的 X 来：名字 ${L.name}、简介 ${L.bio} 个字以内。</small>
          <div class="pf-acts">
            <button class="btn small primary" type="button" id="pfSave">存进 Obsidian</button>
            <button class="btn small" type="button" id="pfCopy">复制简介</button>
            ${p.obsidian ? `<a class="btn small" href="${esc(p.obsidian)}">在 Obsidian 里打开</a>` : ''}
            <button class="btn small ghost" type="button" id="pfReload">重新读</button>
          </div>
          ${sug}
        </div>
        <div class="pf-side">
          ${live}
          <h3>各平台改了没有</h3>
          ${d.platforms.map(profilePlatform).join('')}
        </div>
      </div>
    </section>`;
  const again = () => window.renderProfiles();
  const save = async (extra) => {
    try { await api('/api/profile', { method: 'PUT', body: { name: $('#pfName').value, bio: $('#pfBio').value, mtime: p.mtime, ...extra } }); toast('存进 Obsidian 了'); } catch (err) { toast(err.message); }
    document.activeElement.blur();
    again();
  };
  [['pfName', 'name'], ['pfBio', 'bio']].forEach(([id, f]) => { $('#' + id).oninput = (e) => { const c = $(`[data-pf-count="${f}"]`, box); c.textContent = e.target.value.length; c.parentElement.classList.toggle('over', e.target.value.length > L[f]); }; });
  $('#pfSave').onclick = () => save({});
  $('#pfReload').onclick = () => { document.activeElement.blur(); again(); };
  $('#pfCopy').onclick = async () => { try { await navigator.clipboard.writeText($('#pfBio').value); toast('简介复制好了'); } catch (_) { toast('没复制上，手动选中复制'); } };
  const take = $('#pfTake');
  if (take) take.onclick = async () => { $('#pfName').value = d.suggestion.name; $('#pfBio').value = d.suggestion.bio; await save({ drop_suggestion: true }); };
  const drop = $('#pfDrop');
  if (drop) drop.onclick = async () => { try { await api('/api/profile/suggestion', { method: 'DELETE' }); } catch (err) { toast(err.message); } again(); };
  $$('[data-pf-applied]', box).forEach((b) => (b.onclick = async () => { try { await api(`/api/profile/applied/${b.dataset.pfApplied}`, { method: 'POST' }); toast('记下了'); } catch (err) { toast(err.message); } again(); }));
  $$('[data-pf-push]', box).forEach((b) => (b.onclick = async () => {
    if (!b.dataset.armed) { b.dataset.armed = '1'; b.textContent = '再点一次：真的改到 X 上'; setTimeout(() => { if (document.body.contains(b)) { delete b.dataset.armed; b.textContent = '改到 X 上'; } }, 4000); return; }
    b.disabled = true;
    try { const r = await api('/api/profile/x/push', { method: 'POST' }); PFX.live = r.live; toast('X 主页改好了'); } catch (err) { toast(err.message); }
    again();
  }));
  // X 上现在是什么：读一次，读不到就不显示
  if (PFX.live === null && d.platforms.some((x) => x.key === 'x')) {
    PFX.live = false;
    api('/api/profile/x/live').then((r) => { PFX.live = r.live; again(); }).catch(() => {});
  }
};
