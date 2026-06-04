#!/usr/bin/env node
// PriorStates cockpit — a dependency-free Node server that maps the journal and
// memory in a browser. Read-only. Generalized from the research-cockpit web
// edition: roots come from PRIORSTATES_HOME / PRIORSTATES_PROJECT_ROOT (set by
// `priorstates cockpit`) instead of a hardcoded workspace.
'use strict';
const http = require('http');
const fs = require('fs');
const path = require('path');
const os = require('os');
const url = require('url');
const cp = require('child_process');
const crypto = require('crypto');

// Opt-in: launch a file/folder in a local editor. Off unless --allow-open
// (PS_ALLOW_OPEN=1). Side-effecting, so it stays opt-in like the rest of the
// read-only cockpit. Only editors whose CLI is on PATH are offered.
const ALLOW_OPEN = process.env.PS_ALLOW_OPEN === '1';
// Write/run actions (mdlab run, journal/memory writes) shell out to the PriorStates
// engine ON THIS HOST — so when the cockpit runs on a remote server, code runs
// there (the research env). Opt-in, like open.
const ALLOW_WRITE = process.env.PS_ALLOW_WRITE === '1';
// Embedded terminal (a real shell in the browser) — opt-in, off by default.
const ALLOW_TERMINAL = process.env.PS_ALLOW_TERMINAL === '1';
const PS_PYTHON = process.env.PS_PYTHON || 'python3';
const PTY_BRIDGE = path.join(__dirname, 'ptybridge.py');
const TERMS = new Map();   // sid → { proc }
// Set when this cockpit is being served to a client over `priorstates connect`.
// Tells the browser to open files in the LOCAL editor via a vscode-remote:// URL
// (running `code` on this remote host can't reach the user's editor / display).
const SSH_HOST = process.env.PS_SSH_HOST || '';
// Port of the client-side opener that `priorstates connect` runs; lets the browser
// open a single remote file in the LOCAL editor (code --remote …).
const OPENER_PORT = process.env.PS_OPENER_PORT || '';
function which(bin) {
  for (const d of (process.env.PATH || '').split(path.delimiter)) {
    if (!d) continue;
    try { fs.accessSync(path.join(d, bin), fs.constants.X_OK); return path.join(d, bin); } catch (_) {}
  }
  return null;
}
const EDITOR_CANDIDATES = [['code', 'VSCode'], ['antigravity', 'Antigravity'],
  ['cursor', 'Cursor'], ['windsurf', 'Windsurf'], ['code-insiders', 'VSCode Insiders']];
const EDITORS = EDITOR_CANDIDATES.filter(([bin]) => which(bin)).map(([bin, label]) => ({ bin, label }));

const HOME = process.env.PRIORSTATES_HOME || path.join(os.homedir(), '.priorstates');

// Project root: explicit env wins; otherwise walk up from the working dir
// looking for a .priorstates/ directory (so `node server.js` from a project works).
function detectProjectRoot() {
  if (process.env.PRIORSTATES_PROJECT_ROOT) return process.env.PRIORSTATES_PROJECT_ROOT;
  let d = process.cwd();
  for (;;) {
    try { if (fs.statSync(path.join(d, '.priorstates')).isDirectory()) return d; } catch (_) {}
    const up = path.dirname(d);
    if (up === d) return '';
    d = up;
  }
}
const PROJECT_ROOT = detectProjectRoot();
const PROJECT_DIR = PROJECT_ROOT ? path.join(PROJECT_ROOT, '.priorstates') : '';
const JOURNAL_DIR = PROJECT_DIR ? path.join(PROJECT_DIR, 'journal') : '';
const MEMORY_DIRS = [
  PROJECT_DIR ? path.join(PROJECT_DIR, 'memory') : '',
  path.join(HOME, 'memory'),
].filter(Boolean);
// reads are confined to these roots
const ROOTS = [HOME, PROJECT_ROOT].filter(Boolean).map((p) => path.resolve(p));

function underRoot(p) {
  const r = path.resolve(p);
  return ROOTS.some((root) => r === root || r.startsWith(root + path.sep));
}

// ---- journal -------------------------------------------------------------
function loadJournal() {
  const entries = [];
  if (!JOURNAL_DIR) return entries;
  let text = '';
  try { text = fs.readFileSync(path.join(JOURNAL_DIR, 'INDEX.md'), 'utf8'); } catch (_) {}
  const s = text.indexOf('<!-- priorstates:journal-index-start -->');
  const e = text.indexOf('<!-- priorstates:journal-index-end -->');
  const re = /^- (\d{4}-\d{2}-\d{2}) \[([^\]]+)\]\s*((?:\[[^\]]*\]\s*)*)\*\*([^*]+)\*\*:\s*\[([^\]]+)\]\(([^)]+)\)(?:\s+[—-]\s+(.*))?$/;
  if (s >= 0 && e > s) {
    for (const ln of text.slice(s, e).split('\n')) {
      const m = ln.match(re);
      if (m) entries.push({
        date: m[1], outcome: m[2].trim(), topic: m[4].trim(), title: m[5].trim(),
        file: path.resolve(JOURNAL_DIR, m[6]), tldr: (m[7] || '').trim(),
        superseded: /superseded/i.test(m[3] || ''),
      });
    }
  }
  // Resilience: if INDEX.md is missing/has no markers, scan entries/*.md
  // frontmatter directly (only well-formed entries with id/topic/outcome).
  if (entries.length === 0) {
    let files = [];
    try { files = fs.readdirSync(path.join(JOURNAL_DIR, 'entries')).filter((f) => f.endsWith('.md')); } catch (_) {}
    for (const f of files.sort().reverse()) {
      const p = path.join(JOURNAL_DIR, 'entries', f);
      let fm = {};
      try { fm = parseFrontmatter(fs.readFileSync(p, 'utf8')); } catch (_) { continue; }
      if (!fm.topic && !fm.strategy) continue;   // skip non-PriorStates files
      entries.push({
        date: fm.date || '', outcome: fm.outcome || '', topic: fm.topic || fm.strategy || '',
        title: fm.title || f, file: path.resolve(p), tldr: fm.tldr || '',
        superseded: !!fm.superseded_by,
      });
    }
  }
  return entries;
}

// ---- memory --------------------------------------------------------------
function parseFrontmatter(txt) {
  const out = {};
  if (!txt.startsWith('---')) return out;
  const end = txt.indexOf('\n---', 3);
  if (end < 0) return out;
  for (const ln of txt.slice(3, end).split('\n')) {
    const m = ln.match(/^([a-z_]+):\s*(.*)$/i);
    if (m) out[m[1]] = m[2].replace(/^["']|["']$/g, '').trim();
  }
  return out;
}
function loadMemory() {
  const out = [];
  const seen = new Set();
  for (let i = 0; i < MEMORY_DIRS.length; i++) {
    const scope = i === 0 && PROJECT_DIR ? 'project' : 'global';
    let files = [];
    try { files = fs.readdirSync(MEMORY_DIRS[i]).filter((f) => f.endsWith('.md')); } catch (_) {}
    for (const f of files) {
      if (['MEMORY.md', 'INDEX.md', 'README.md'].includes(f)) continue;
      const p = path.join(MEMORY_DIRS[i], f);
      let txt = '';
      try { txt = fs.readFileSync(p, 'utf8'); } catch (_) { continue; }
      const fm = parseFrontmatter(txt);
      const name = fm.name || f.replace(/\.md$/, '');
      if (seen.has(name)) continue;
      seen.add(name);
      out.push({
        name, description: fm.description || '', type: fm.type || 'note',
        pinned: /^(true|yes|1|on)$/i.test(fm.pinned || ''), scope, file: path.resolve(p),
      });
    }
  }
  out.sort((a, b) => (b.pinned - a.pinned) || a.name.localeCompare(b.name));
  return out;
}

// ---- docs: research Markdown under the project, grouped by folder ---------
const SKIP_DIRS = new Set(['.priorstates', '.git', 'node_modules', '__pycache__',
  'build', 'out', 'dist', '.mdlab_assets', '.venv', 'venv']);
// PriorStates-managed agent context files — not research docs.
const SKIP_FILES = new Set(['CLAUDE.md', 'AGENTS.md', 'GEMINI.md', 'GEMINI.MD']);
function walkDocs(dir, acc, depth) {
  if (depth > 8) return;
  let ents = [];
  try { ents = fs.readdirSync(dir, { withFileTypes: true }); } catch (_) { return; }
  for (const ent of ents) {
    const p = path.join(dir, ent.name);
    if (ent.isDirectory()) {
      if (!SKIP_DIRS.has(ent.name) && !ent.name.startsWith('.')) walkDocs(p, acc, depth + 1);
    } else if (/\.md$/i.test(ent.name) && !SKIP_FILES.has(ent.name)) {
      acc.push(p);
    }
  }
}
function loadDocs() {
  if (!PROJECT_ROOT) return { groups: {}, count: 0 };
  const files = [];
  walkDocs(PROJECT_ROOT, files, 0);
  const docs = files.map((f) => {
    const rel = path.relative(PROJECT_ROOT, f);
    const dir = path.dirname(rel) === '.' ? '(top level)' : path.dirname(rel);
    let title = path.basename(f), hasJournal = false;
    try {
      const t = fs.readFileSync(f, 'utf8');
      hasJournal = /```journal\b/.test(t);
      const h = t.split('\n').find((l) => l.startsWith('# '));
      if (h) title = h.replace(/^#\s*/, '').trim();
    } catch (_) {}
    return { file: path.resolve(f), rel, dir, name: path.basename(f), title,
             mdlab: /\.mdlab\.md$/i.test(f), hasJournal };
  });
  docs.sort((a, b) => a.rel.localeCompare(b.rel));
  const groups = {};
  for (const d of docs) (groups[d.dir] = groups[d.dir] || []).push(d);
  return { groups, count: docs.length };
}

// ---- tiny markdown -> html ----------------------------------------------
function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
function inlineMd(s, base) {
  return esc(s)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, (mm, t, href) => {
      if (/^[a-z]+:\/\//i.test(href) || href.startsWith('#')) return `<a href="${esc(href)}" target="_blank" rel="noopener">${t}</a>`;
      const abs = path.resolve(base, href.split('#')[0]);
      return underRoot(abs) ? `<a href="#" data-open="${esc(abs)}">${t}</a>` : esc(t);
    });
}
function mdToHtml(md, base) {
  const L = md.split('\n'); const out = []; let i = 0;
  while (i < L.length) {
    const line = L[i];
    const f = line.match(/^```(\w*)/);
    if (f) { const c = []; i++; while (i < L.length && !L[i].startsWith('```')) c.push(L[i++]); i++; out.push(`<pre data-lang="${esc(f[1] || '')}"><code>${esc(c.join('\n'))}</code></pre>`); continue; }
    if (line.includes('|') && i + 1 < L.length && /^\s*\|?[\s:|-]+\|/.test(L[i + 1])) {
      const head = line.split('|').map((x) => x.trim()).filter(Boolean); i += 2; const rows = [];
      while (i < L.length && L[i].includes('|')) { rows.push(L[i].split('|').map((x) => x.trim()).filter(Boolean)); i++; }
      out.push('<table><thead><tr>' + head.map((h) => `<th>${inlineMd(h, base)}</th>`).join('') + '</tr></thead><tbody>'
        + rows.map((r) => '<tr>' + r.map((c) => `<td>${inlineMd(c, base)}</td>`).join('') + '</tr>').join('') + '</tbody></table>');
      continue;
    }
    const h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h) { out.push(`<h${h[1].length}>${inlineMd(h[2], base)}</h${h[1].length}>`); i++; continue; }
    if (line.startsWith('> ')) { const q = []; while (i < L.length && L[i].startsWith('> ')) q.push(L[i++].slice(2)); out.push(`<blockquote>${inlineMd(q.join(' '), base)}</blockquote>`); continue; }
    if (/^\s*[-*]\s+/.test(line)) { const it = []; while (i < L.length && /^\s*[-*]\s+/.test(L[i])) it.push(`<li>${inlineMd(L[i++].replace(/^\s*[-*]\s+/, ''), base)}</li>`); out.push(`<ul>${it.join('')}</ul>`); continue; }
    if (line.trim() === '') { i++; continue; }
    const p = [line]; i++;
    while (i < L.length && L[i].trim() !== '' && !/^(#|```|>|\s*[-*]\s)/.test(L[i]) && !L[i].includes('|')) p.push(L[i++]);
    out.push(`<p>${inlineMd(p.join(' '), base)}</p>`);
  }
  return out.join('\n');
}

// ---- http ----------------------------------------------------------------
const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.png': 'image/png', '.jpg': 'image/jpeg', '.svg': 'image/svg+xml' };
function send(res, code, body, type) { res.writeHead(code, { 'Content-Type': type || 'application/json; charset=utf-8', 'Cache-Control': 'no-store' }); res.end(body); }
function sendJson(res, o) { send(res, 200, JSON.stringify(o)); }
function serveStatic(res, rel) {
  const file = path.join(__dirname, 'public', rel);
  if (!file.startsWith(path.join(__dirname, 'public'))) return send(res, 403, 'forbidden', 'text/plain');
  fs.readFile(file, (err, buf) => err ? send(res, 404, 'not found', 'text/plain') : send(res, 200, buf, MIME[path.extname(file)] || 'application/octet-stream'));
}
function apiFile(res, abs) {
  if (!abs || !underRoot(abs)) return send(res, 403, JSON.stringify({ error: 'outside root' }));
  let txt; try { txt = fs.readFileSync(abs, 'utf8'); } catch (_) { return send(res, 404, JSON.stringify({ error: 'not found' })); }
  // Strip YAML frontmatter for display (don't show raw `--- id: … ---`); lift its title.
  let fmTitle = '';
  if (txt.startsWith('---')) {
    const end = txt.indexOf('\n---', 3);
    if (end !== -1) {
      const m = txt.slice(3, end).match(/^\s*title:\s*(.+)$/m);
      if (m) fmTitle = m[1].trim();
      const nl = txt.indexOf('\n', end + 1);
      txt = nl === -1 ? '' : txt.slice(nl + 1);
    }
  }
  let body = txt.replace(/^\s+/, '');
  const h1 = body.split('\n').find((l) => l.startsWith('# '));
  const title = (h1 ? h1.replace(/^#\s*/, '') : (fmTitle || path.basename(abs))).trim();
  if (!h1 && title) body = '# ' + title + '\n\n' + body;   // give the pane a clean heading
  sendJson(res, { file: abs, rel: ROOTS.map((r) => path.relative(r, abs)).sort((a, b) => a.length - b.length)[0], title, html: mdToHtml(body, path.dirname(abs)) });
}

// Run an mdlab file via the PriorStates engine ON THIS HOST (so on a remote server,
// the code executes there). Opt-in via --allow-write; path confined to roots.
function apiMdlabRun(res, target) {
  if (!ALLOW_WRITE) return send(res, 403, JSON.stringify({ error: 'writes/run disabled — start the cockpit with --allow-write' }));
  const t = target ? path.resolve(target) : '';
  if (!t || !underRoot(t) || !/\.md$/i.test(t)) return send(res, 403, JSON.stringify({ error: 'invalid path' }));
  cp.execFile(PS_PYTHON, ['-m', 'priorstates', 'mdlab', 'run', t],
    { cwd: PROJECT_ROOT || path.dirname(t), timeout: 600000, maxBuffer: 1 << 24 },
    (err, stdout, stderr) => {
      if (err) return send(res, 500, JSON.stringify({ error: String(stderr || err.message).slice(0, 4000) }));
      sendJson(res, { ok: true, output: String(stdout || stderr).slice(0, 4000) });
    });
}

// Read a JSON request body (small, capped) for POST writes.
function readBody(req, cb) {
  let b = '';
  req.on('data', (d) => { b += d; if (b.length > 1e6) req.destroy(); });
  req.on('end', () => { let j = {}; try { j = JSON.parse(b || '{}'); } catch (_) {} cb(j); });
}

// Free-text capture → add a memory / journal entry via the Python CLI on this
// host (so the local heuristic parsers are reused, no logic duplicated in JS).
// Opt-in via --allow-write. `text` is passed as an argv element (no shell), so
// there is no injection surface.
function apiCapture(res, kind, text) {
  if (!ALLOW_WRITE) return send(res, 403, JSON.stringify({ error: 'writes disabled — start the cockpit with --allow-write' }));
  text = (text || '').trim();
  if (!text) return send(res, 400, JSON.stringify({ error: 'empty' }));
  if (kind === 'journal' && !JOURNAL_DIR) return send(res, 400, JSON.stringify({ error: 'no project journal — open the cockpit from your project dir' }));
  cp.execFile(PS_PYTHON, ['-m', 'priorstates', kind, 'capture', text],
    { cwd: PROJECT_ROOT || HOME, timeout: 60000, maxBuffer: 1 << 22 },
    (err, stdout, stderr) => err
      ? send(res, 500, JSON.stringify({ error: String(stderr || err.message).slice(0, 2000) }))
      : sendJson(res, { ok: true, result: String(stdout).trim() }));
}

// ---- embedded terminal (xterm.js ↔ SSE/POST ↔ python pty bridge) ---------
function termFrame(proc, type, payload) {       // [len][type][payload] on the bridge's stdin
  const p = Buffer.isBuffer(payload) ? payload : Buffer.from(String(payload));
  const body = Buffer.concat([Buffer.from(type), p]);
  const len = Buffer.alloc(4); len.writeUInt32BE(body.length, 0);
  try { proc.stdin.write(Buffer.concat([len, body])); } catch (_) {}
}
function apiTermNew(res) {
  if (!ALLOW_TERMINAL) return send(res, 403, JSON.stringify({ error: 'terminal disabled — start the cockpit with PS_ALLOW_TERMINAL=1' }));
  const sid = crypto.randomBytes(12).toString('hex');
  const shell = process.env.SHELL || '/bin/bash';
  const env = Object.assign({}, process.env, { TERM: 'xterm-256color' });
  let proc;
  try {
    proc = cp.spawn(PS_PYTHON, [PTY_BRIDGE, shell], { cwd: PROJECT_ROOT || HOME, env });
  } catch (e) {
    return send(res, 500, JSON.stringify({ error: String((e && e.message) || e) }));
  }
  TERMS.set(sid, { proc });
  proc.on('exit', () => { const s = TERMS.get(sid); if (s && s.sse) { try { s.sse.end(); } catch (_) {} } TERMS.delete(sid); });
  sendJson(res, { sid });
}
function apiTermStream(res, req, sid) {
  const s = TERMS.get(sid);
  if (!s) return send(res, 404, 'no such terminal', 'text/plain');
  res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache',
    Connection: 'keep-alive', 'X-Accel-Buffering': 'no' });
  res.write(':ok\n\n');
  s.sse = res;
  const onData = (d) => { try { res.write('data: ' + d.toString('base64') + '\n\n'); } catch (_) {} };
  s.proc.stdout.on('data', onData);
  req.on('close', () => {
    s.proc.stdout.removeListener('data', onData);
    try { s.proc.kill(); } catch (_) {}
    TERMS.delete(sid);
  });
}
function apiTermInput(res, sid, buf) {
  const s = TERMS.get(sid);
  if (!s) return send(res, 404, JSON.stringify({ error: 'no such terminal' }));
  termFrame(s.proc, 'i', buf || Buffer.alloc(0));
  sendJson(res, { ok: true });
}
function apiTermResize(res, sid, body) {
  const s = TERMS.get(sid);
  if (!s) return send(res, 404, JSON.stringify({ error: 'no such terminal' }));
  const cols = parseInt(body.cols, 10) || 80, rows = parseInt(body.rows, 10) || 24;
  termFrame(s.proc, 'r', cols + ',' + rows);
  sendJson(res, { ok: true });
}

// Read a raw (binary) request body, capped — for uploading a .psworkspace.
function readRawBody(req, cb) {
  const chunks = []; let n = 0;
  req.on('data', (d) => { n += d.length; if (n > 6e6) { req.destroy(); return; } chunks.push(d); });
  req.on('end', () => cb(Buffer.concat(chunks)));
}

// Export this workspace → a .psworkspace download (read-only; no key needed).
function apiExport(res) {
  const tmp = path.join(os.tmpdir(), 'ps-export-' + process.pid + '-' + Math.abs(Date.now()) + '.psworkspace');
  cp.execFile(PS_PYTHON, ['-m', 'priorstates', 'workspace', 'export', '--out', tmp],
    { cwd: PROJECT_ROOT || HOME, timeout: 60000, maxBuffer: 1 << 22 },
    (err) => {
      if (err) return send(res, 500, JSON.stringify({ error: String(err.message).slice(0, 2000) }));
      let buf; try { buf = fs.readFileSync(tmp); } catch (_) { return send(res, 500, JSON.stringify({ error: 'export produced no file' })); }
      try { fs.unlinkSync(tmp); } catch (_) {}
      const name = (PROJECT_ROOT ? path.basename(PROJECT_ROOT) : 'workspace') + '.psworkspace';
      res.writeHead(200, { 'Content-Type': 'application/gzip',
        'Content-Disposition': 'attachment; filename="' + name + '"', 'Content-Length': buf.length });
      res.end(buf);
    });
}

// Import a .psworkspace: from `?url=` or from the raw uploaded body. Opt-in via --allow-write.
function apiImport(res, urlArg, bodyBuf) {
  if (!ALLOW_WRITE) return send(res, 403, JSON.stringify({ error: 'writes disabled — start the cockpit with --allow-write' }));
  const run = (src, cleanup) => cp.execFile(PS_PYTHON, ['-m', 'priorstates', 'workspace', 'import', src, '--yes'],
    { cwd: PROJECT_ROOT || HOME, timeout: 120000, maxBuffer: 1 << 22 },
    (err, stdout, stderr) => {
      if (cleanup) cleanup();
      if (err) return send(res, 500, JSON.stringify({ error: String(stderr || err.message).slice(0, 2000) }));
      sendJson(res, { ok: true, result: String(stdout).trim() });
    });
  if (urlArg) {
    if (!/^https?:\/\//.test(urlArg)) return send(res, 400, JSON.stringify({ error: 'url must be http(s)' }));
    return run(urlArg, null);
  }
  if (!bodyBuf || bodyBuf.length < 2 || bodyBuf[0] !== 0x1f || bodyBuf[1] !== 0x8b) {
    return send(res, 400, JSON.stringify({ error: 'not a .psworkspace (gzip) upload' }));
  }
  const tmp = path.join(os.tmpdir(), 'ps-import-' + process.pid + '-' + Math.abs(Date.now()) + '.psworkspace');
  fs.writeFileSync(tmp, bodyBuf);
  run(tmp, () => { try { fs.unlinkSync(tmp); } catch (_) {} });
}

// Import the bundled demo workspace (for the cockpit's first-run empty state).
function apiImportDemo(res) {
  if (!ALLOW_WRITE) return send(res, 403, JSON.stringify({ error: 'writes disabled — start the cockpit with --allow-write' }));
  cp.execFile(PS_PYTHON, ['-m', 'priorstates', 'workspace', 'import', '--demo', '--yes'],
    { cwd: PROJECT_ROOT || HOME, timeout: 120000, maxBuffer: 1 << 22 },
    (err, stdout, stderr) => err
      ? send(res, 500, JSON.stringify({ error: String(stderr || err.message).slice(0, 2000) }))
      : sendJson(res, { ok: true, result: String(stdout).trim() }));
}

// Pin/unpin or delete a memory by name (argv, no shell).
function apiMemOp(res, op, name, unpin) {
  if (!ALLOW_WRITE) return send(res, 403, JSON.stringify({ error: 'writes disabled — start the cockpit with --allow-write' }));
  name = (name || '').trim();
  if (!name) return send(res, 400, JSON.stringify({ error: 'no name' }));
  const args = op === 'delete' ? ['memory', 'delete', name]
    : ['memory', 'pin', name, ...(unpin ? ['--unpin'] : [])];
  cp.execFile(PS_PYTHON, ['-m', 'priorstates', ...args],
    { cwd: PROJECT_ROOT || HOME, timeout: 60000 },
    (err, stdout, stderr) => err
      ? send(res, 500, JSON.stringify({ error: String(stderr || err.message).slice(0, 2000) }))
      : sendJson(res, { ok: true }));
}

// Launch a path in a local editor (opt-in). Validates the editor against the
// detected allowlist and confines the path to the workspace roots; spawns the
// CLI directly (no shell) so there's no injection surface.
function apiOpen(res, app, target) {
  if (!ALLOW_OPEN) return send(res, 403, JSON.stringify({ error: 'open is disabled — start the cockpit with --allow-open' }));
  const ed = EDITORS.find((e) => e.bin === app);
  if (!ed) return send(res, 400, JSON.stringify({ error: `editor '${app}' not available` }));
  const t = target ? path.resolve(target) : PROJECT_ROOT;
  if (!t || !underRoot(t)) return send(res, 403, JSON.stringify({ error: 'path outside workspace' }));
  try {
    const child = cp.spawn(ed.bin, [t], { detached: true, stdio: 'ignore' });
    child.on('error', () => {});
    child.unref();
    return sendJson(res, { ok: true, app, path: t });
  } catch (e) {
    return send(res, 500, JSON.stringify({ error: String((e && e.message) || e) }));
  }
}

const server = http.createServer((req, res) => {
  const u = url.parse(req.url, true); const p = u.pathname;
  try {
    if (req.method === 'POST') {
      if (p === '/api/memory/capture') return readBody(req, (b) => apiCapture(res, 'memory', b.text));
      if (p === '/api/journal/capture') return readBody(req, (b) => apiCapture(res, 'journal', b.text));
      if (p === '/api/memory/pin') return readBody(req, (b) => apiMemOp(res, 'pin', b.name, b.unpin));
      if (p === '/api/memory/delete') return readBody(req, (b) => apiMemOp(res, 'delete', b.name));
      if (p === '/api/workspace/import-demo') return readBody(req, () => apiImportDemo(res));
      if (p === '/api/workspace/import') {
        if (u.query.url) return apiImport(res, u.query.url, null);
        return readRawBody(req, (buf) => apiImport(res, null, buf));
      }
      if (p === '/api/term/new') return apiTermNew(res);
      let mt = p.match(/^\/api\/term\/([a-f0-9]+)\/input$/);
      if (mt) return readRawBody(req, (buf) => apiTermInput(res, mt[1], buf));
      mt = p.match(/^\/api\/term\/([a-f0-9]+)\/resize$/);
      if (mt) return readBody(req, (b) => apiTermResize(res, mt[1], b));
      return send(res, 404, 'not found', 'text/plain');
    }
    if (p === '/') return serveStatic(res, 'index.html');
    if (p === '/api/meta') return sendJson(res, { home: HOME, project_root: PROJECT_ROOT,
      has_journal: !!JOURNAL_DIR, allow_open: ALLOW_OPEN, allow_write: ALLOW_WRITE, allow_terminal: ALLOW_TERMINAL,
      editors: EDITORS, ssh_host: SSH_HOST, opener_port: OPENER_PORT });
    if (p === '/api/journal') return sendJson(res, loadJournal());
    if (p === '/api/memory') return sendJson(res, loadMemory());
    if (p === '/api/docs') return sendJson(res, loadDocs());
    if (p === '/api/file') return apiFile(res, u.query.path);
    if (p === '/api/open') return apiOpen(res, u.query.app, u.query.path);
    if (p === '/api/mdlab/run') return apiMdlabRun(res, u.query.path);
    if (p === '/api/workspace/export') return apiExport(res);
    const ts = p.match(/^\/api\/term\/([a-f0-9]+)\/stream$/);
    if (ts) return apiTermStream(res, req, ts[1]);
    if (/^\/[\w./-]+$/.test(p) && !p.includes('..')) return serveStatic(res, p.slice(1));
    return send(res, 404, 'not found', 'text/plain');
  } catch (e) { return send(res, 500, JSON.stringify({ error: String(e && e.message || e) })); }
});

const PORT = parseInt(process.env.PS_PORT || '7700', 10);
const HOST = process.env.PS_HOST || '127.0.0.1';
server.listen(PORT, HOST, () => {
  const nJournal = loadJournal().length;
  console.log(`[priorstates cockpit] home=${HOME} project=${PROJECT_ROOT || '(none)'}`);
  if (!PROJECT_ROOT) {
    console.log('[priorstates cockpit] WARNING: no project detected — Journal tab will be empty.');
    console.log('[priorstates cockpit] Launch `priorstates cockpit` from your project dir, or pass --project PATH.');
  } else {
    console.log(`[priorstates cockpit] journal=${JOURNAL_DIR} (${nJournal} entries)`);
  }
  console.log(`[priorstates cockpit] http://${HOST}:${PORT}/`);
});
