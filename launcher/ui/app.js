// Mod launcher UI. Game-independent: everything game specific comes from the Python API
// (window.pywebview.api) as data: enemies, sections, models, assignments.
const S = { data: null, view: 'type', tab: null, query: '', selected: new Set(), busy: false };
const $ = (id) => document.getElementById(id);
const api = () => window.pywebview.api;

function esc(s) { return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }

// ---------- rendering ----------
function sections() {
  const d = S.data;
  if (S.view === 'type') return d.categories.map(([title, keys]) => [title, keys.filter((k) => d.enemies[k])]);
  const out = d.acts.map(([key, label]) => [label, Object.keys(d.enemies).filter((e) => d.enemies[e].acts.includes(key))]);
  out.push([d.no_campaign, Object.keys(d.enemies).filter((e) => !d.enemies[e].acts.length)]);
  const order = d.categories.flatMap(([, keys]) => keys);
  return out.filter(([, es]) => es.length).map(([t, es]) => [t, es.sort((a, b) => order.indexOf(a) - order.indexOf(b))]);
}

function where(e) {
  const acts = S.data.enemies[e].acts;
  if (!acts.length) return S.data.no_campaign;
  const labels = Object.fromEntries(S.data.acts);
  return 'Appears in: ' + acts.map((a) => labels[a]).join(', ');
}

function renderEnemies() {
  const d = S.data, box = $('enemies'), top = box.scrollTop;
  let html = '';
  for (const [title, enemies] of sections()) {
    html += `<div class="section-head"><span class="section-title">${esc(title)}</span>` +
            `<span class="drop-all" data-section="${esc(title)}">⇩ apply to all (${enemies.length})</span></div>`;
    for (const e of enemies) {
      const ms = d.assign[e] || [];
      const chips = ms.length
        ? ms.map((m) => `<span class="chip" data-enemy="${e}" data-model="${m}">${esc(d.modelNames[m] || m)}<span class="x" data-remove="${m}" title="Remove">×</span></span>`).join('')
        : '<span class="empty">Original model — drop a model here</span>';
      html += `<div class="enemy" data-enemy="${e}"><div class="enemy-row"><span class="enemy-name">${esc(d.enemies[e].name)}</span>` +
              `<span class="enemy-where">${esc(where(e))}</span></div><div class="chips">${chips}</div></div>`;
    }
  }
  box.innerHTML = html;
  box.scrollTop = top;
}

function renderTabs() {
  $('tabs').innerHTML = S.data.tabs.map((t) => `<button data-tab="${esc(t)}" class="${t === S.tab ? 'on' : ''}">${esc(t)}</button>`).join('');
}

function renderModels() {
  const q = S.query.toLowerCase(), groups = new Map();
  for (const m of S.data.models) {
    if (m.tab !== S.tab || (q && !m.name.toLowerCase().includes(q))) continue;
    if (!groups.has(m.group)) groups.set(m.group, []);
    groups.get(m.group).push(m);
  }
  let html = '';
  for (const [group, ms] of groups) {
    html += `<div class="group-title">${esc(group)}</div>`;
    html += ms.map((m) => `<div class="model ${S.selected.has(m.key) ? 'selected' : ''}" data-model="${m.key}">${esc(m.name)}</div>`).join('');
  }
  $('models').innerHTML = html || '<p class="empty">No models found</p>';
}

function renderState() {
  const pill = $('state-pill');
  pill.textContent = S.data.installed ? 'Mod installed · playing online is at your own risk' : 'Original game';
  pill.className = 'pill ' + (S.data.installed ? 'warn' : 'ok');
}

// optional on/off switches from the backend: options = [{key, label, value}]
function renderOptions() {
  $('options').innerHTML = (S.data.options || []).map((o) =>
    `<label class="toggle"><input type="checkbox" data-option="${esc(o.key)}" ${o.value ? 'checked' : ''}>` +
    `<span class="track"></span>${esc(o.label)}</label>`).join('');
}

function renderAll() { renderState(); renderEnemies(); renderTabs(); renderModels(); renderOptions(); }

// ---------- assignments ----------
function save() { api().save_assign(S.data.assign); }

function addModels(enemies, models) {
  for (const e of enemies) {
    const list = S.data.assign[e] || (S.data.assign[e] = []);
    for (const m of models) if (!list.includes(m)) list.push(m);
  }
}

// ---------- drag and drop (pointer based: works the same everywhere, with auto-scroll) ----------
let drag = null;
document.addEventListener('pointerdown', (ev) => {
  if (S.busy || ev.button !== 0 || ev.target.closest('.x')) return;
  const model = ev.target.closest('.model'), chip = ev.target.closest('.chip');
  if (model && (ev.ctrlKey || ev.metaKey)) {
    const k = model.dataset.model;
    S.selected.has(k) ? S.selected.delete(k) : S.selected.add(k);
    renderModels();
    return;
  }
  if (model) {
    const k = model.dataset.model;
    const models = S.selected.has(k) ? [...S.selected] : [k];
    drag = { models, source: null, x: ev.clientX, y: ev.clientY, started: false };
  } else if (chip) {
    drag = { models: [chip.dataset.model], source: chip.dataset.enemy, x: ev.clientX, y: ev.clientY, started: false };
  }
});

let scrollTimer = null;
document.addEventListener('pointermove', (ev) => {
  if (!drag) return;
  if (!drag.started && Math.hypot(ev.clientX - drag.x, ev.clientY - drag.y) < 5) return;
  drag.started = true;
  const g = $('drag-ghost');
  const first = S.data.modelNames[drag.models[0]] || drag.models[0];
  g.textContent = first + (drag.models.length > 1 ? `  (+${drag.models.length - 1})` : '');
  g.hidden = false;
  g.style.left = ev.clientX + 14 + 'px';
  g.style.top = ev.clientY + 10 + 'px';
  document.querySelectorAll('.hot').forEach((el) => el.classList.remove('hot'));
  const target = targetAt(ev.clientX, ev.clientY);
  if (target) target.classList.add('hot');
  const box = $('enemies').getBoundingClientRect();
  clearInterval(scrollTimer);
  if (ev.clientX >= box.left && ev.clientX <= box.right) {
    const dy = ev.clientY < box.top + 40 ? -12 : ev.clientY > box.bottom - 40 ? 12 : 0;
    if (dy) scrollTimer = setInterval(() => { $('enemies').scrollTop += dy; }, 16);
  }
});

function targetAt(x, y) {
  const el = document.elementFromPoint(x, y);
  return el ? el.closest('.enemy, .drop-all') : null;
}

document.addEventListener('pointerup', (ev) => {
  clearInterval(scrollTimer);
  if (!drag) return;
  const { models, source, started } = drag;
  drag = null;
  $('drag-ghost').hidden = true;
  document.querySelectorAll('.hot').forEach((el) => el.classList.remove('hot'));
  if (!started) return;
  const target = targetAt(ev.clientX, ev.clientY);
  if (!target) return;
  if (target.classList.contains('drop-all')) {
    const sec = sections().find(([t]) => t === target.dataset.section);
    if (!sec) return;
    addModels(sec[1], models);
    status(`${models.map((m) => S.data.modelNames[m]).join(', ')} → all ${sec[1].length} enemies of "${sec[0]}"`);
  } else {
    const e = target.dataset.enemy;
    if (e === source) return;
    addModels([e], models);
    if (source) S.data.assign[source] = S.data.assign[source].filter((m) => !models.includes(m));
  }
  S.selected.clear();
  save();
  renderEnemies();
  renderModels();
});

document.addEventListener('click', (ev) => {
  const x = ev.target.closest('.x');
  if (x && !S.busy) {
    const e = x.closest('.chip').dataset.enemy;
    S.data.assign[e] = S.data.assign[e].filter((m) => m !== x.dataset.remove);
    save();
    renderEnemies();
  }
  const tab = ev.target.closest('#tabs button');
  if (tab) { S.tab = tab.dataset.tab; $('models').scrollTop = 0; renderTabs(); renderModels(); }
  const view = ev.target.closest('#views button');
  if (view) {
    S.view = view.dataset.view;
    document.querySelectorAll('#views button').forEach((b) => b.classList.toggle('on', b === view));
    $('enemies').scrollTop = 0;
    renderEnemies();
  }
});

$('search').addEventListener('input', (ev) => { S.query = ev.target.value; renderModels(); });

document.addEventListener('change', (ev) => {
  const box = ev.target.closest('input[data-option]');
  if (!box) return;
  const o = (S.data.options || []).find((x) => x.key === box.dataset.option);
  if (o) o.value = box.checked;
  api().set_option(box.dataset.option, box.checked);
});

// ---------- dialogs ----------
function confirmBox(title, text, okLabel = 'OK') {
  return new Promise((resolve) => {
    $('modal-title').textContent = title;
    $('modal-text').textContent = text;
    $('modal-ok').textContent = okLabel;
    $('modal').hidden = false;
    const close = (v) => { $('modal').hidden = true; $('modal-ok').onclick = $('modal-cancel').onclick = null; resolve(v); };
    $('modal-ok').onclick = () => close(true);
    $('modal-cancel').onclick = () => close(false);
  });
}

function status(msg) { $('status').textContent = msg || ''; }

// ---------- actions ----------
$('apply-launch').onclick = () => api().apply(S.data.assign, true);
$('apply').onclick = () => api().apply(S.data.assign, false);
$('restore').onclick = async () => {
  if (!S.data.installed) { status('The game is already original.'); return; }
  if (await confirmBox('Restore', 'Remove the mod and bring the game back to its original files?', 'Restore')) api().restore();
};
$('uninstall').onclick = async () => {
  if (await confirmBox('Uninstall', 'Remove the mod from the game?\n\n1. The game goes back to its original files\n2. The mod launcher and its desktop shortcut are deleted', 'Uninstall')) api().uninstall();
};
$('clear').onclick = async () => {
  if (await confirmBox('Clear all', 'Remove every assigned model? Enemies go back to their original look.', 'Clear all')) {
    for (const e of Object.keys(S.data.enemies)) S.data.assign[e] = [];
    save();
    renderEnemies();
  }
};
$('random').onclick = () => {
  const pool = S.data.models.filter((m) => m.tab === S.tab).map((m) => m.key);
  const enemies = Object.keys(S.data.enemies);
  for (let i = pool.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [pool[i], pool[j]] = [pool[j], pool[i]]; }
  enemies.forEach((e, i) => { S.data.assign[e] = [pool[i % pool.length]]; });
  save();
  renderEnemies();
  status(`Random ${S.tab.toLowerCase()} models on every enemy`);
};

// ---------- called from Python ----------
window.ui = {
  busy(on) {
    S.busy = on;
    document.querySelectorAll('.actions button, #uninstall').forEach((b) => { b.disabled = on; });
    $('progress').hidden = !on;
    if (on) window.ui.progress(0);
  },
  progress(f) {
    const pct = Math.max(0, Math.min(100, Math.round(f * 100)));
    $('progress-fill').style.width = pct + '%';
    $('progress-pct').textContent = pct + '%';
  },
  status,
  async refresh() { S.data = await api().get_state(); renderAll(); },
  error(msg) { status('Error: ' + msg); confirmBox('Error', msg); },
};

// the bridge may be ready before this script runs (event already fired) or after it
let started = false;
function ready() { return window.pywebview && window.pywebview.api && window.pywebview.api.get_state; }
window.addEventListener('pywebview-ready', init);
if (ready()) init();
else { const t = setInterval(() => { if (ready()) { clearInterval(t); init(); } }, 100); }

async function init() {
  if (started || !ready()) return;
  started = true;
  S.data = await api().get_state();
  S.tab = S.data.tabs[0];
  $('title').textContent = S.data.title;
  document.title = S.data.title;
  $('uninstall').hidden = !S.data.can_uninstall;
  renderAll();
  status(S.data.message || '');
}
