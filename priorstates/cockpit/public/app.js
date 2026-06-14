// PriorStates cockpit SPA — Journal + Memory navigation with browser history.
'use strict';
const $ = (s, e) => (e || document).querySelector(s);
const el = (tag, props, kids) => {
  const e = document.createElement(tag);
  if (props) for (const k in props) {
    if (k === 'class') e.className = props[k];
    else if (k === 'html') e.innerHTML = props[k];
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), props[k]);
    else if (k === 'data') for (const d in props[k]) e.dataset[d] = props[k][d];
    else e.setAttribute(k, props[k]);
  }
  for (const c of [].concat(kids || [])) if (c != null) e.append(c.nodeType ? c : document.createTextNode(c));
  return e;
};
const api = (p) => fetch(p).then((r) => r.json());
const post = (p, body) => fetch(p, { method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body || {}) }).then((r) => r.json());

// Re-fetch all data and re-render (used after a capture and by the refresh button).
async function reload() {
  const [journal, memory, docs] = await Promise.all([api('/api/journal'), api('/api/memory'), api('/api/docs')]);
  state.journal = journal; state.memory = memory; state.docs = docs;
  $('#cnt-journal').textContent = `(${journal.length})`;
  $('#cnt-memory').textContent = `(${memory.length})`;
  $('#cnt-docs').textContent = `(${docs.count})`;
  renderWorkspaceOpen();
  render();
}

// Free-text quick-capture box (memory / journal). Only when the cockpit allows
// writes; the server reuses the local Python parsers via `… capture`.
function captureBox(kind) {
  const m = state.meta || {};
  if (!m.allow_write) return null;
  if (kind === 'journal' && !m.has_journal) {
    return el('div', { class: 'capture', style: 'padding:8px;border-bottom:1px solid #21262d;color:#8b949e;font-size:12px' },
      'Journal needs a project — open the cockpit from your project folder.');
  }
  const ph = kind === 'journal'
    ? 'Describe what happened… e.g. “grid search too noisy — loser #tuning”'
    : 'Jot a memory in plain English… add #pin to pin it';
  const inp = el('textarea', { rows: '2', placeholder: ph,
    style: 'width:100%;box-sizing:border-box;background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:6px;padding:6px;font:inherit;resize:vertical' });
  const save = async () => {
    const text = inp.value.trim(); if (!text) return;
    btn.disabled = true; const was = btn.textContent; btn.textContent = 'saving…';
    const r = await post('/api/' + kind + '/capture', { text });
    btn.disabled = false; btn.textContent = was;
    if (r && r.error) { alert('Save failed: ' + r.error); return; }
    inp.value = ''; await reload();
  };
  // Cmd/Ctrl+Enter submits.
  inp.addEventListener('keydown', (e) => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') save(); });
  const btn = el('button', { class: 'wsbtn', style: 'margin-top:4px', onclick: save },
    kind === 'journal' ? 'Record' : 'Save');
  const tip = el('div', { style: 'color:#6e7681;font-size:11px;margin-top:3px' },
    'or just tell your agent — ⌘/Ctrl+Enter to save');
  return el('div', { class: 'capture', style: 'padding:8px 8px 10px;border-bottom:1px solid #21262d' }, [inp, btn, tip]);
}
const OUT = { winner: '#3fb950', loser: '#f85149', bug: '#db6d28', gotcha: '#d29922', decision: '#d2a8ff', inconclusive: '#58a6ff', note: '#8b949e' };
const sym = (o) => ({ winner: '✓', loser: '✗', bug: '🐞', gotcha: '⚠', decision: '💡', inconclusive: 'ℹ', note: '•' }[o] || '•');

const state = { view: 'journal', journal: [], memory: [], docs: { groups: {}, count: 0 }, groupBy: 'topic',
  expanded: { journal: new Set(), memory: new Set(), docs: new Set() } };
const nav = { seq: -1, max: -1 };

async function boot() {
  // Wire the tabs + nav FIRST so the UI stays interactive even if a data endpoint
  // errors or hangs. (Previously bind() ran only after awaiting four /api/* calls,
  // so a single failing endpoint aborted boot() and left every tab dead.)
  bind();
  let meta = {}, journal = [], memory = [], docs = { count: 0 };
  [meta, journal, memory, docs] = await Promise.all([
    api('/api/meta').catch((e) => (console.error('cockpit /api/meta failed', e), {})),
    api('/api/journal').catch((e) => (console.error('cockpit /api/journal failed', e), [])),
    api('/api/memory').catch((e) => (console.error('cockpit /api/memory failed', e), [])),
    api('/api/docs').catch((e) => (console.error('cockpit /api/docs failed', e), { count: 0 })),
  ]);
  // Scope badge: make it obvious whether you're in global or a project, and
  // where new memories will save.
  const _rl = $('#rootlbl'), _proj = meta.project_root || '';
  if (_rl) {
    _rl.textContent = _proj ? ('Project: ' + _proj.replace(/[\\/]+$/, '').split(/[\\/]/).pop()) : 'Global memory';
    _rl.title = _proj ? (_proj + '\nProject memory + global; new memories save to this project.')
                      : ((meta.home || '') + '\nGlobal memory; new memories save here. (Run `priorstates init` in a repo to add a project layer.)');
  }
  state.journal = journal; state.memory = memory; state.docs = docs; state.meta = meta;
  $('#cnt-journal').textContent = `(${journal.length})`;
  $('#cnt-memory').textContent = `(${memory.length})`;
  $('#cnt-docs').textContent = `(${(docs && docs.count) || 0})`;
  if (meta.allow_terminal) { const tt = $('#tab-term'); if (tt) tt.hidden = false; }
  renderWorkspaceOpen();
  render();
  placeholder();   // dynamic empty state (incl. workspace-open buttons)
  nav.seq = 0; nav.max = 0; history.replaceState({ type: 'placeholder', seq: 0 }, ''); updateNav();
}

// Open a path (file) or, when no path is given, the whole workspace, in an editor.
// Local cockpit: ask the server to launch the editor here. Remote cockpit (served
// via `priorstates connect`): hand off to YOUR editor via a vscode-remote:// URL,
// because running the editor on the server can't reach your screen.
async function doOpen(bin, abs) {
  const meta = state.meta || {};
  const target = abs || meta.project_root;
  // Remote cockpit + a client-side opener (from `priorstates connect`): open the
  // exact file/folder in YOUR local editor via `code --remote …`. This is the
  // only reliable way to open a single REMOTE file.
  if (meta.opener_port) {
    if (!target) return;
    try {
      const r = await fetch('http://127.0.0.1:' + meta.opener_port + '/open?app='
        + encodeURIComponent(bin) + '&path=' + encodeURIComponent(target));
      const j = await r.json();
      if (!j.ok) alert(`Couldn't open in ${bin}. Is it installed locally with the Remote-SSH extension?`);
    } catch (e) {
      alert('Could not reach the local opener (is the connect session still running?).');
    }
    return;
  }
  // Remote cockpit without an opener: fall back to the vscode-remote:// URL
  // (opens a folder only).
  if (meta.ssh_host) {
    launchUri(editorRemoteUri(bin, meta.ssh_host, meta.project_root || target));
    return;
  }
  // Local cockpit: ask the server to launch the editor here.
  const q = '/api/open?app=' + encodeURIComponent(bin) + (abs ? '&path=' + encodeURIComponent(abs) : '');
  const r = await api(q);
  if (r && r.error) alert('Open failed: ' + r.error);
}
// vscode://… URL that opens a file/folder on a remote SSH host in the LOCAL editor
// (VSCode and its forks register these handlers; needs the Remote-SSH extension).
const EDITOR_SCHEME = { code: 'vscode', 'code-insiders': 'vscode-insiders',
  cursor: 'cursor', windsurf: 'windsurf', antigravity: 'antigravity' };
function editorRemoteUri(bin, host, path) {
  const scheme = EDITOR_SCHEME[bin] || 'vscode';
  return `${scheme}://vscode-remote/ssh-remote+${host}${path}`;
}
function launchUri(uri) {
  // trigger the OS protocol handler without navigating away from the page
  const a = document.createElement('a');
  a.href = uri; a.style.display = 'none';
  document.body.appendChild(a); a.click();
  setTimeout(() => a.remove(), 1500);
}
function editorsAvailable() {
  const m = state.meta || {};
  return (m.allow_open && (m.editors || []).length) ? m.editors : null;
}
// Top-bar buttons that open the whole workspace folder in an editor.
function renderWorkspaceOpen() {
  const host = $('#wsopen'); if (!host) return;
  host.innerHTML = '';
  const eds = editorsAvailable();
  if (!eds || !(state.meta || {}).project_root) return;
  for (const ed of eds) {
    host.append(el('button', { class: 'wsbtn', title: `Open the project folder in ${ed.label}`,
      onclick: () => doOpen(ed.bin) }, '📂 ' + ed.label));
  }
}
function bind() {
  $('#back').onclick = () => history.back();
  $('#fwd').onclick = () => history.forward();
  document.querySelectorAll('.tab').forEach((t) => t.onclick = () => {
    state.view = t.dataset.view;
    document.querySelectorAll('.tab').forEach((x) => x.classList.toggle('active', x === t));
    render();
  });
  $('#refresh').onclick = async () => {
    const [journal, memory, docs] = await Promise.all([api('/api/journal'), api('/api/memory'), api('/api/docs')]);
    state.journal = journal; state.memory = memory; state.docs = docs;
    $('#cnt-journal').textContent = `(${journal.length})`;
    $('#cnt-memory').textContent = `(${memory.length})`;
    $('#cnt-docs').textContent = `(${docs.count})`;
    renderWorkspaceOpen();
    render();
  };
  $('#search').oninput = render;
  // Export / Import a workspace bundle.
  const ex = $('#export');
  if (ex) ex.onclick = () => { window.location.href = '/api/workspace/export'; };
  const im = $('#import'), imf = $('#importfile');
  if (im && imf && (state.meta || {}).allow_write) {
    im.hidden = false;
    im.onclick = () => imf.click();
    imf.onchange = async () => {
      const f = imf.files && imf.files[0]; if (!f) return;
      im.disabled = true; const was = im.textContent; im.textContent = 'importing…';
      let r;
      try {
        const buf = await f.arrayBuffer();
        r = await fetch('/api/workspace/import', { method: 'POST',
          headers: { 'Content-Type': 'application/gzip' }, body: buf }).then((x) => x.json());
      } catch (e) { r = { error: String(e) }; }
      imf.value = ''; im.disabled = false; im.textContent = was;
      if (r && r.error) { alert('Import failed: ' + r.error); return; }
      alert((r && r.result) || 'Imported.'); await reload();
    };
  }
  window.addEventListener('popstate', (e) => {
    if (e.state && typeof e.state.seq === 'number') { nav.seq = e.state.seq; renderLoc(e.state); }
    else { nav.seq = -1; placeholder(); }
    updateNav();
  });
}
function updateNav() { $('#back').disabled = nav.seq <= 0; $('#fwd').disabled = nav.seq >= nav.max; }
function go(loc) { nav.seq += 1; nav.max = nav.seq; history.pushState({ ...loc, seq: nav.seq }, ''); renderLoc(loc); updateNav(); }
function renderLoc(loc) {
  if (!loc) return;
  if (loc.type === 'file') return renderFile(loc.file);
  if (loc.type === 'memory') return renderMemory(loc.name);
  if (loc.type === 'placeholder') return placeholder();
}
async function loadDemo(e) {
  const b = e && e.currentTarget;
  if (b) { b.disabled = true; b.textContent = 'loading…'; }
  const r = await post('/api/workspace/import-demo', {});
  if (r && r.error) { alert('Load failed: ' + r.error); if (b) { b.disabled = false; b.textContent = '🛰 Load the demo project'; } return; }
  await reload();
}
function placeholder() {
  setActive(null);
  const c = $('#content'); c.innerHTML = '';
  const m = state.meta || {};
  // First run: empty + writable → offer the bundled demo workspace.
  if (m.allow_write && !state.journal.length && !state.memory.length) {
    const box = el('div', { class: 'placeholder' }, ['New here? Load a sample project to see PriorStates populated.']);
    box.append(el('div', { class: 'ph-open' }, [el('button', { class: 'wsbtn', onclick: loadDemo }, '🛰 Load the demo project')]));
    c.append(box);
    return;
  }
  const box = el('div', { class: 'placeholder' }, ['Pick a journal entry, memory, or doc on the left.']);
  const eds = editorsAvailable();
  if (eds && (state.meta || {}).project_root) {
    const row = el('div', { class: 'ph-open' });
    row.append(el('span', { class: 'ph-lbl' }, 'Open the project in:'));
    for (const ed of eds) {
      row.append(el('button', { class: 'wsbtn', onclick: () => doOpen(ed.bin) }, '📂 ' + ed.label));
    }
    box.append(row);
  }
  c.append(box);
}

function render() {
  const q = $('#search').value.trim().toLowerCase();
  $('#viewctl').innerHTML = '';
  if (state.view === 'journal') {
    const c = $('#viewctl');
    c.append(el('span', { class: 'lbl' }, 'group:'));
    const sel = el('select', { onchange: (e) => { state.groupBy = e.target.value; render(); } });
    ['topic', 'outcome', 'date'].forEach((g) => sel.append(el('option', { value: g, ...(g === state.groupBy ? { selected: 'selected' } : {}) }, g)));
    c.append(sel);
    renderJournal(q);
  } else if (state.view === 'docs') {
    $('#viewctl').append(el('span', { class: 'lbl' }, 'research docs in this project, by folder'));
    renderDocs(q);
  } else if (state.view === 'term') {
    $('#viewctl').append(el('span', { class: 'lbl' }, 'a shell on this machine — run claude / codex / gemini here'));
    renderTerminal();
  } else {
    $('#viewctl').append(el('span', { class: 'lbl' }, '📌 pinned shown first'));
    renderMemoryList(q);
  }
}

// ── Embedded terminal (xterm.js ↔ SSE/POST ↔ python pty) ──
var TERM = null, TERM_SID = null, TERM_ES = null, FIT = null;
function renderTerminal() {
  $('#tree').innerHTML = '';
  var c = $('#content'); c.innerHTML = ''; c.style.position = 'relative';
  if (!window.Terminal || !window.FitAddon) { c.innerHTML = '<div class="placeholder">terminal assets unavailable</div>'; return; }
  var host = el('div', { style: 'position:absolute;inset:0;padding:8px;background:#0a0d12' });
  c.append(host);
  if (!TERM) {
    TERM = new window.Terminal({ fontSize: 13, cursorBlink: true,
      fontFamily: 'ui-monospace,SFMono-Regular,Menlo,Consolas,monospace',
      theme: { background: '#0a0d12', foreground: '#c9d1d9' } });
    FIT = new window.FitAddon.FitAddon(); TERM.loadAddon(FIT);
  }
  TERM.open(host);
  try { FIT.fit(); } catch (_) {}
  if (!TERM_SID) {
    post('/api/term/new', {}).then(function (r) {
      if (!r || r.error) { host.innerHTML = '<div class="placeholder">terminal: ' + ((r && r.error) || 'failed') + '</div>'; return; }
      TERM_SID = r.sid;
      TERM.onData(function (d) { fetch('/api/term/' + TERM_SID + '/input', { method: 'POST', body: d }); });
      TERM.onResize(function (s) { post('/api/term/' + TERM_SID + '/resize', { cols: s.cols, rows: s.rows }); });
      TERM_ES = new EventSource('/api/term/' + TERM_SID + '/stream');
      TERM_ES.onmessage = function (e) {
        try { TERM.write(Uint8Array.from(atob(e.data), function (ch) { return ch.charCodeAt(0); })); } catch (_) {}
      };
      try { FIT.fit(); } catch (_) {}
      post('/api/term/' + TERM_SID + '/resize', { cols: TERM.cols, rows: TERM.rows });
      TERM.focus();
    });
  } else {
    try { FIT.fit(); } catch (_) {}
    TERM.focus();
  }
  if (!renderTerminal._resize) {
    renderTerminal._resize = true;
    window.addEventListener('resize', function () { if (state.view === 'term' && FIT) { try { FIT.fit(); } catch (_) {} } });
  }
}
function renderDocs(q) {
  const tree = $('#tree'); tree.innerHTML = '';
  const groups = state.docs.groups || {};
  if (!Object.keys(groups).length) {
    tree.append(el('div', { class: 'placeholder', style: 'padding:20px;font-size:12px' },
      state.docs.count === 0 ? 'No project detected, or no Markdown docs found.' : ''));
    return;
  }
  for (const dir of Object.keys(groups).sort()) {
    let docs = groups[dir];
    if (q) docs = docs.filter((d) => (d.name + d.title + d.rel).toLowerCase().includes(q));
    if (!docs.length) continue;
    tree.append(groupNode('docs', dir, `${docs.length}`, () => docs.map(docLeaf)));
  }
}
function docLeaf(d) {
  const leaf = el('div', { class: 'leaf', data: { file: d.file }, title: `${d.title}\n${d.rel}`,
    onclick: () => go({ type: 'file', file: d.file }) }, [
    el('span', { class: 'sym' }, d.hasJournal ? '✎' : (d.mdlab ? '📓' : '📄')),
    el('span', { class: 'ltitle' }, d.name),
  ]);
  return leaf;
}
function renderJournal(q) {
  const tree = $('#tree'); tree.innerHTML = '';
  const cb = captureBox('journal'); if (cb) tree.append(cb);
  let es = state.journal;
  if (q) es = es.filter((e) => (e.title + e.topic + e.tldr + e.outcome).toLowerCase().includes(q));
  const keyer = state.groupBy === 'outcome' ? (e) => e.outcome : state.groupBy === 'date' ? (e) => e.date.slice(0, 7) : (e) => e.topic;
  const groups = {};
  for (const e of es) (groups[keyer(e)] = groups[keyer(e)] || []).push(e);
  const keys = Object.keys(groups).sort(state.groupBy === 'date' ? (a, b) => b.localeCompare(a) : (a, b) => groups[b].length - groups[a].length);
  for (const k of keys) tree.append(groupNode('journal', k, `${groups[k].length}`, () => groups[k].map(entryLeaf)));
}
function entryLeaf(e) {
  const color = OUT[e.outcome] || '#8b949e';
  const leaf = el('div', { class: 'leaf' + (e.superseded ? ' sup' : ''), data: { file: e.file }, title: e.tldr, onclick: () => go({ type: 'file', file: e.file }) }, [
    el('span', { class: 'sym', style: `color:${color}` }, sym(e.outcome)),
    el('span', { class: 'ltitle' }, e.title),
    el('span', { class: 'ldesc' }, e.date),
  ]);
  return leaf;
}
function renderMemoryList(q) {
  const tree = $('#tree'); tree.innerHTML = '';
  const cb = captureBox('memory'); if (cb) tree.append(cb);
  let ms = state.memory;
  if (q) ms = ms.filter((m) => (m.name + m.description + m.type).toLowerCase().includes(q));
  const groups = {};
  for (const m of ms) (groups[m.type] = groups[m.type] || []).push(m);
  for (const t of Object.keys(groups).sort()) tree.append(groupNode('memory', t, `${groups[t].length}`, () => groups[t].map(memLeaf)));
}
function memLeaf(m) {
  const leaf = el('div', { class: 'leaf', data: { memory: m.name }, title: m.description, onclick: () => go({ type: 'memory', name: m.name }) }, [
    el('span', { class: 'sym' }, m.pinned ? '📌' : '·'),
    el('span', { class: 'ltitle' }, m.name),
    el('span', { class: 'ldesc' }, m.scope),
  ]);
  return leaf;
}
function groupNode(view, key, desc, factory) {
  const open = state.expanded[view].has(key);
  const head = el('div', { class: 'group' }, [el('span', { class: 'tw' }, open ? '▾' : '▸'), el('span', { class: 'gname' }, key), el('span', { class: 'gcount' }, desc)]);
  const kids = el('div');
  const draw = () => { kids.innerHTML = ''; if (state.expanded[view].has(key)) for (const c of factory()) kids.append(c); };
  head.onclick = () => { state.expanded[view].has(key) ? state.expanded[view].delete(key) : state.expanded[view].add(key); head.firstChild.textContent = state.expanded[view].has(key) ? '▾' : '▸'; draw(); };
  draw();
  const wrap = el('div'); wrap.append(head, kids); return wrap;
}
function setActive(leaf) { document.querySelectorAll('.leaf.active').forEach((l) => l.classList.remove('active')); if (leaf) leaf.classList.add('active'); }
function hl(sel) { setActive(null); try { const m = document.querySelector(sel); if (m) m.classList.add('active'); } catch (_) {} }

async function renderFile(abs) {
  hl(`.leaf[data-file="${(window.CSS && CSS.escape) ? CSS.escape(abs) : abs}"]`);
  const content = $('#content'); content.innerHTML = '<div class="placeholder">loading…</div>';
  const d = await api('/api/file?path=' + encodeURIComponent(abs));
  if (d.error) { content.innerHTML = `<div class="placeholder">${d.error}</div>`; return; }
  content.innerHTML = '';
  const crumbs = el('div', { class: 'crumbs' }, [el('span', { class: 'rel' }, d.rel)]);
  const rb = runButton(abs); if (rb) crumbs.append(rb);
  for (const b of openButtons(abs)) crumbs.append(b);
  content.append(crumbs, el('div', { class: 'doc', html: d.html }));
  content.querySelectorAll('a[data-open]').forEach((a) => a.onclick = (e) => { e.preventDefault(); go({ type: 'file', file: a.dataset.open }); });
  content.scrollTop = 0;
}
// "Open in <editor>" buttons (only when the cockpit was started with --allow-open
// and the editor's CLI is present on the host).
// ▶ Run an mdlab doc on the server (executes code in the remote research env).
function runButton(abs) {
  const m = state.meta || {};
  if (!m.allow_write || !/\.mdlab\.md$/i.test(abs)) return null;
  return el('button', { class: 'runbtn', title: 'Run all blocks (executes on the server)',
    onclick: async (e) => {
      const b = e.currentTarget; b.disabled = true; const was = b.textContent; b.textContent = '⏳ running…';
      const r = await api('/api/mdlab/run?path=' + encodeURIComponent(abs));
      if (r && r.error) { alert('Run failed:\n' + r.error); b.disabled = false; b.textContent = was; return; }
      renderFile(abs);  // re-fetch — result regions were written into the file on the host
    } }, '▶ Run');
}
function openButtons(abs) {
  const eds = editorsAvailable();
  if (!eds) return [];
  const m = state.meta || {};
  const remote = m.ssh_host && !m.opener_port;  // folder-only fallback case
  return eds.map((ed) => el('button', { class: 'openbtn',
    title: m.ssh_host ? `Open this file in your local ${ed.label} (Remote-SSH to ${m.ssh_host})`
                      : `Open this file in ${ed.label}`,
    onclick: () => doOpen(ed.bin, abs) },
    (remote ? '↗ project in ' : '↗ ') + ed.label));
}
function renderMemory(name) {
  hl(`.leaf[data-memory="${(window.CSS && CSS.escape) ? CSS.escape(name) : name}"]`);
  const m = state.memory.find((x) => x.name === name);
  if (m) renderFile(m.file);
}
boot();
