#!/usr/bin/env python3
"""PriorStates cockpit -- a pure-Python (stdlib only) web server that maps the
journal and memory in a browser. Read-only by default; writes / open-in-editor /
the embedded terminal are opt-in via PS_ALLOW_WRITE / PS_ALLOW_OPEN /
PS_ALLOW_TERMINAL, exactly like the JS edition it replaces.

This is a faithful port of the former Node `server.js`, so PriorStates no longer
needs Node.js for anything -- the whole product is now pure Python.

Roots come from PRIORSTATES_HOME / PRIORSTATES_PROJECT_ROOT (set by
`priorstates cockpit`). Run directly: `python3 server.py` (honours PS_PORT/PS_HOST).
"""
from __future__ import annotations

import base64
import json
import os
import queue
import re
import secrets
import shutil
import struct
import subprocess
_CNW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # hide console flashes on Windows (pythonw)
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
PUBLIC = os.path.join(HERE, "public")
PTY_BRIDGE = os.path.join(HERE, "ptybridge.py")

# Opt-in side effects -- same env contract as the Node server.
ALLOW_OPEN = os.environ.get("PS_ALLOW_OPEN") == "1"
ALLOW_WRITE = os.environ.get("PS_ALLOW_WRITE") == "1"
ALLOW_TERMINAL = os.environ.get("PS_ALLOW_TERMINAL") == "1"
PS_PYTHON = os.environ.get("PS_PYTHON") or sys.executable or "python3"
SSH_HOST = os.environ.get("PS_SSH_HOST", "")
OPENER_PORT = os.environ.get("PS_OPENER_PORT", "")

HOME = os.environ.get("PRIORSTATES_HOME") or os.path.join(os.path.expanduser("~"), ".priorstates")


def detect_project_root() -> str:
    if os.environ.get("PRIORSTATES_PROJECT_ROOT"):
        return os.environ["PRIORSTATES_PROJECT_ROOT"]
    d = os.getcwd()
    while True:
        if os.path.isdir(os.path.join(d, ".priorstates")):
            return d
        up = os.path.dirname(d)
        if up == d:
            return ""
        d = up


PROJECT_ROOT = detect_project_root()
PROJECT_DIR = os.path.join(PROJECT_ROOT, ".priorstates") if PROJECT_ROOT else ""
JOURNAL_DIR = os.path.join(PROJECT_DIR, "journal") if PROJECT_DIR else ""
MEMORY_DIRS = [p for p in (
    os.path.join(PROJECT_DIR, "memory") if PROJECT_DIR else "",
    os.path.join(HOME, "memory"),
) if p]
ROOTS = [os.path.abspath(p) for p in (HOME, PROJECT_ROOT) if p]

EDITOR_CANDIDATES = [("code", "VSCode"), ("antigravity", "Antigravity"),
                     ("cursor", "Cursor"), ("windsurf", "Windsurf"),
                     ("code-insiders", "VSCode Insiders")]
# For a REMOTE cockpit (served via `priorstates connect`), open-in-editor runs on
# the CLIENT via `code --remote …`, so the buttons must reflect the CLIENT's
# editors (passed in as PS_OPENER_EDITORS), NOT this remote host's. Otherwise a
# button shows for an editor the client can't launch (e.g. a stray `antigravity`
# binary here) and the open fails.
_OPENER_EDITORS = os.environ.get("PS_OPENER_EDITORS")
if OPENER_PORT and _OPENER_EDITORS is not None:
    _avail = set(filter(None, _OPENER_EDITORS.split(",")))
    EDITORS = [{"bin": b, "label": lbl} for b, lbl in EDITOR_CANDIDATES if b in _avail]
else:
    EDITORS = [{"bin": b, "label": lbl} for b, lbl in EDITOR_CANDIDATES if shutil.which(b)]


def under_root(p: str) -> bool:
    r = os.path.abspath(p)
    return any(r == root or r.startswith(root + os.sep) for root in ROOTS)


def _read(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


# ---- frontmatter / journal / memory / docs --------------------------------
def parse_frontmatter(txt: str) -> dict:
    out: dict = {}
    if not txt.startswith("---"):
        return out
    end = txt.find("\n---", 3)
    if end < 0:
        return out
    for ln in txt[3:end].split("\n"):
        m = re.match(r"^([a-z_]+):\s*(.*)$", ln, re.I)
        if m:
            out[m.group(1)] = re.sub(r'^["\']|["\']$', "", m.group(2)).strip()
    return out


_JOURNAL_RE = re.compile(
    r"^- (\d{4}-\d{2}-\d{2}) \[([^\]]+)\]\s*((?:\[[^\]]*\]\s*)*)\*\*([^*]+)\*\*:"
    r"\s*\[([^\]]+)\]\(([^)]+)\)(?:\s+[—-]\s+(.*))?$")


def load_journal() -> list:
    entries: list = []
    if not JOURNAL_DIR:
        return entries
    text = ""
    try:
        text = _read(os.path.join(JOURNAL_DIR, "INDEX.md"))
    except OSError:
        pass
    s = text.find("<!-- priorstates:journal-index-start -->")
    e = text.find("<!-- priorstates:journal-index-end -->")
    if s >= 0 and e > s:
        for ln in text[s:e].split("\n"):
            m = _JOURNAL_RE.match(ln)
            if m:
                entries.append({
                    "date": m.group(1), "outcome": m.group(2).strip(),
                    "topic": m.group(4).strip(), "title": m.group(5).strip(),
                    "file": os.path.abspath(os.path.join(JOURNAL_DIR, m.group(6))),
                    "tldr": (m.group(7) or "").strip(),
                    "superseded": bool(re.search(r"superseded", m.group(3) or "", re.I)),
                })
    # Resilience: no INDEX markers -> scan entries/*.md frontmatter directly.
    if not entries:
        files = []
        try:
            files = [f for f in os.listdir(os.path.join(JOURNAL_DIR, "entries")) if f.endswith(".md")]
        except OSError:
            pass
        for f in sorted(files, reverse=True):
            p = os.path.join(JOURNAL_DIR, "entries", f)
            try:
                fm = parse_frontmatter(_read(p))
            except OSError:
                continue
            if not fm.get("topic") and not fm.get("strategy"):
                continue
            entries.append({
                "date": fm.get("date", ""), "outcome": fm.get("outcome", ""),
                "topic": fm.get("topic") or fm.get("strategy", ""),
                "title": fm.get("title", f), "file": os.path.abspath(p),
                "tldr": fm.get("tldr", ""), "superseded": bool(fm.get("superseded_by")),
            })
    return entries


def load_memory() -> list:
    out: list = []
    seen = set()
    for i, mdir in enumerate(MEMORY_DIRS):
        scope = "project" if (i == 0 and PROJECT_DIR) else "global"
        files = []
        try:
            files = [f for f in os.listdir(mdir) if f.endswith(".md")]
        except OSError:
            pass
        for f in files:
            if f in ("MEMORY.md", "INDEX.md", "README.md"):
                continue
            p = os.path.join(mdir, f)
            try:
                txt = _read(p)
            except OSError:
                continue
            fm = parse_frontmatter(txt)
            name = fm.get("name") or re.sub(r"\.md$", "", f)
            if name in seen:
                continue
            seen.add(name)
            out.append({
                "name": name, "description": fm.get("description", ""),
                "type": fm.get("type", "note"),
                "pinned": bool(re.match(r"^(true|yes|1|on)$", fm.get("pinned", ""), re.I)),
                "scope": scope, "file": os.path.abspath(p),
            })
    out.sort(key=lambda a: (not a["pinned"], a["name"]))
    return out


SKIP_DIRS = {".priorstates", ".git", "node_modules", "__pycache__",
             "build", "out", "dist", ".mdlab_assets", ".venv", "venv"}
SKIP_FILES = {"CLAUDE.md", "AGENTS.md", "GEMINI.md", "GEMINI.MD"}


def walk_docs(d: str, acc: list, depth: int):
    if depth > 8:
        return
    try:
        ents = list(os.scandir(d))
    except OSError:
        return
    for ent in ents:
        p = os.path.join(d, ent.name)
        if ent.is_dir():
            if ent.name not in SKIP_DIRS and not ent.name.startswith("."):
                walk_docs(p, acc, depth + 1)
        elif re.search(r"\.md$", ent.name, re.I) and ent.name not in SKIP_FILES:
            acc.append(p)


def load_docs() -> dict:
    if not PROJECT_ROOT:
        return {"groups": {}, "count": 0}
    files: list = []
    walk_docs(PROJECT_ROOT, files, 0)
    docs = []
    for f in files:
        rel = os.path.relpath(f, PROJECT_ROOT)
        dname = os.path.dirname(rel) or "."
        dname = "(top level)" if dname == "." else dname
        title = os.path.basename(f)
        has_journal = False
        try:
            t = _read(f)
            has_journal = bool(re.search(r"```journal\b", t))
            for line in t.split("\n"):
                if line.startswith("# "):
                    title = re.sub(r"^#\s*", "", line).strip()
                    break
        except OSError:
            pass
        docs.append({"file": os.path.abspath(f), "rel": rel, "dir": dname,
                     "name": os.path.basename(f), "title": title,
                     "mdlab": bool(re.search(r"\.mdlab\.md$", f, re.I)),
                     "hasJournal": has_journal})
    docs.sort(key=lambda d: d["rel"])
    groups: dict = {}
    for d in docs:
        groups.setdefault(d["dir"], []).append(d)
    return {"groups": groups, "count": len(docs)}


# ---- tiny markdown -> html ------------------------------------------------
def esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def inline_md(s: str, base: str) -> str:
    s = esc(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)

    def link(m):
        t, href = m.group(1), m.group(2)
        if re.match(r"^[a-z]+://", href, re.I) or href.startswith("#"):
            return f'<a href="{esc(href)}" target="_blank" rel="noopener">{t}</a>'
        abs_ = os.path.abspath(os.path.join(base, href.split("#")[0]))
        return f'<a href="#" data-open="{esc(abs_)}">{t}</a>' if under_root(abs_) else esc(t)

    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", link, s)


def md_to_html(md: str, base: str) -> str:
    L = md.split("\n")
    out: list = []
    i, n = 0, len(L)
    while i < n:
        line = L[i]
        f = re.match(r"^```(\w*)", line)
        if f:
            c = []
            i += 1
            while i < n and not L[i].startswith("```"):
                c.append(L[i]); i += 1
            i += 1
            out.append(f'<pre data-lang="{esc(f.group(1) or "")}"><code>{esc(chr(10).join(c))}</code></pre>')
            continue
        if "|" in line and i + 1 < n and re.match(r"^\s*\|?[\s:|-]+\|", L[i + 1]):
            head = [x.strip() for x in line.split("|") if x.strip()]
            i += 2
            rows = []
            while i < n and "|" in L[i]:
                rows.append([x.strip() for x in L[i].split("|") if x.strip()]); i += 1
            thead = "".join(f"<th>{inline_md(h, base)}</th>" for h in head)
            tbody = "".join("<tr>" + "".join(f"<td>{inline_md(c, base)}</td>" for c in r) + "</tr>"
                            for r in rows)
            out.append(f"<table><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table>")
            continue
        h = re.match(r"^(#{1,6})\s+(.*)$", line)
        if h:
            lvl = len(h.group(1))
            out.append(f"<h{lvl}>{inline_md(h.group(2), base)}</h{lvl}>"); i += 1; continue
        if line.startswith("> "):
            q = []
            while i < n and L[i].startswith("> "):
                q.append(L[i][2:]); i += 1
            out.append(f"<blockquote>{inline_md(' '.join(q), base)}</blockquote>"); continue
        if re.match(r"^\s*[-*]\s+", line):
            it = []
            while i < n and re.match(r"^\s*[-*]\s+", L[i]):
                item = re.sub(r"^\s*[-*]\s+", "", L[i])
                it.append(f"<li>{inline_md(item, base)}</li>")
                i += 1
            out.append(f"<ul>{''.join(it)}</ul>"); continue
        if line.strip() == "":
            i += 1; continue
        p = [line]; i += 1
        while (i < n and L[i].strip() != "" and not re.match(r"^(#|```|>|\s*[-*]\s)", L[i])
               and "|" not in L[i]):
            p.append(L[i]); i += 1
        out.append(f"<p>{inline_md(' '.join(p), base)}</p>")
    return "\n".join(out)


# ---- terminal state -------------------------------------------------------
MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".png": "image/png", ".jpg": "image/jpeg",
        ".svg": "image/svg+xml"}
TERMS: dict = {}
TERMS_LOCK = threading.Lock()


def term_frame(proc, typ: bytes, payload: bytes):
    body = typ + (payload if isinstance(payload, (bytes, bytearray)) else str(payload).encode())
    try:
        proc.stdin.write(struct.pack(">I", len(body)) + body)
        proc.stdin.flush()
    except Exception:
        pass


def _engine(*args, cwd=None, timeout=60000):
    """Run `priorstates <args>` on this host (reuse the Python heuristics)."""
    return subprocess.run([PS_PYTHON, "-m", "priorstates", *args],
                          cwd=cwd or (PROJECT_ROOT or HOME),
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout / 1000.0, creationflags=_CNW)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "PriorStatesCockpit/1.0"

    def log_message(self, *a):  # quiet; cmd_cockpit prints the URL
        pass

    # -- response helpers --
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionError):
            pass

    def _json(self, obj):
        self._send(200, json.dumps(obj))

    def _err(self, code, msg):
        self._send(code, json.dumps({"error": msg}))

    def _read_body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            return json.loads(raw or b"{}")
        except Exception:
            return {}

    def _read_raw(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    # -- static --
    def _serve_static(self, rel):
        file = os.path.join(PUBLIC, rel)
        if not os.path.abspath(file).startswith(PUBLIC):
            return self._send(403, "forbidden", "text/plain")
        try:
            with open(file, "rb") as f:
                buf = f.read()
        except OSError:
            return self._send(404, "not found", "text/plain")
        ctype = MIME.get(os.path.splitext(file)[1], "application/octet-stream")
        self._send(200, buf, ctype)

    # -- file view --
    def _api_file(self, abs_):
        if not abs_ or not under_root(abs_):
            return self._err(403, "outside root")
        try:
            txt = _read(abs_)
        except OSError:
            return self._err(404, "not found")
        fm_title = ""
        if txt.startswith("---"):
            end = txt.find("\n---", 3)
            if end != -1:
                m = re.search(r"^\s*title:\s*(.+)$", txt[3:end], re.M)
                if m:
                    fm_title = m.group(1).strip()
                nl = txt.find("\n", end + 1)
                txt = "" if nl == -1 else txt[nl + 1:]
        body = re.sub(r"^\s+", "", txt)
        h1 = next((l for l in body.split("\n") if l.startswith("# ")), None)
        title = (re.sub(r"^#\s*", "", h1) if h1 else (fm_title or os.path.basename(abs_))).strip()
        if not h1 and title:
            body = "# " + title + "\n\n" + body
        rel = sorted((os.path.relpath(abs_, r) for r in ROOTS), key=len)[0] if ROOTS else abs_
        self._json({"file": abs_, "rel": rel, "title": title,
                    "html": md_to_html(body, os.path.dirname(abs_))})

    # -- writes (opt-in) --
    def _api_mdlab_run(self, target):
        if not ALLOW_WRITE:
            return self._err(403, "writes/run disabled -- start the cockpit with --allow-write")
        t = os.path.abspath(target) if target else ""
        if not t or not under_root(t) or not re.search(r"\.md$", t, re.I):
            return self._err(403, "invalid path")
        try:
            r = _engine("mdlab", "run", t, cwd=PROJECT_ROOT or os.path.dirname(t), timeout=600000)
        except subprocess.TimeoutExpired:
            return self._err(500, "mdlab run timed out")
        if r.returncode != 0:
            return self._err(500, (r.stderr or "mdlab run failed")[:4000])
        self._json({"ok": True, "output": (r.stdout or r.stderr)[:4000]})

    def _api_capture(self, kind, text):
        if not ALLOW_WRITE:
            return self._err(403, "writes disabled -- start the cockpit with --allow-write")
        text = (text or "").strip()
        if not text:
            return self._err(400, "empty")
        if kind == "journal" and not JOURNAL_DIR:
            return self._err(400, "no project journal -- open the cockpit from your project dir")
        try:
            r = _engine(kind, "capture", text, timeout=60000)
        except subprocess.TimeoutExpired:
            return self._err(500, "capture timed out")
        if r.returncode != 0:
            return self._err(500, (r.stderr or "capture failed")[:2000])
        self._json({"ok": True, "result": (r.stdout or "").strip()})

    def _api_mem_op(self, op, name, unpin=False):
        if not ALLOW_WRITE:
            return self._err(403, "writes disabled -- start the cockpit with --allow-write")
        name = (name or "").strip()
        if not name:
            return self._err(400, "no name")
        args = (["memory", "delete", name] if op == "delete"
                else ["memory", "pin", name] + (["--unpin"] if unpin else []))
        try:
            r = _engine(*args, timeout=60000)
        except subprocess.TimeoutExpired:
            return self._err(500, "memory op timed out")
        if r.returncode != 0:
            return self._err(500, (r.stderr or "memory op failed")[:2000])
        self._json({"ok": True})

    def _api_export(self):
        tmp = os.path.join(tempfile.gettempdir(),
                           f"ps-export-{os.getpid()}-{secrets.token_hex(4)}.pspack")
        try:
            r = _engine("pack", "export", "--out", tmp, timeout=60000)
        except subprocess.TimeoutExpired:
            return self._err(500, "export timed out")
        if r.returncode != 0:
            return self._err(500, (r.stderr or "export failed")[:2000])
        try:
            with open(tmp, "rb") as f:
                buf = f.read()
        except OSError:
            return self._err(500, "export produced no file")
        try:
            os.unlink(tmp)
        except OSError:
            pass
        name = (os.path.basename(PROJECT_ROOT) if PROJECT_ROOT else "pack") + ".pspack"
        self.send_response(200)
        self.send_header("Content-Type", "application/gzip")
        self.send_header("Content-Disposition", f'attachment; filename="{name}"')
        self.send_header("Content-Length", str(len(buf)))
        self.end_headers()
        try:
            self.wfile.write(buf)
        except (BrokenPipeError, ConnectionError):
            pass

    def _api_import(self, url_arg, body_buf):
        if not ALLOW_WRITE:
            return self._err(403, "writes disabled -- start the cockpit with --allow-write")

        def run(src, cleanup=None):
            try:
                r = _engine("pack", "import", src, "--yes", timeout=120000)
            except subprocess.TimeoutExpired:
                if cleanup:
                    cleanup()
                return self._err(500, "import timed out")
            if cleanup:
                cleanup()
            if r.returncode != 0:
                return self._err(500, (r.stderr or "import failed")[:2000])
            self._json({"ok": True, "result": (r.stdout or "").strip()})

        if url_arg:
            if not re.match(r"^https?://", url_arg):
                return self._err(400, "url must be http(s)")
            return run(url_arg)
        if not body_buf or len(body_buf) < 2 or body_buf[0] != 0x1F or body_buf[1] != 0x8B:
            return self._err(400, "not a .pspack (gzip) upload")
        tmp = os.path.join(tempfile.gettempdir(),
                           f"ps-import-{os.getpid()}-{secrets.token_hex(4)}.pspack")
        with open(tmp, "wb") as f:
            f.write(body_buf)
        run(tmp, lambda: (os.unlink(tmp) if os.path.exists(tmp) else None))

    def _api_import_demo(self):
        if not ALLOW_WRITE:
            return self._err(403, "writes disabled -- start the cockpit with --allow-write")
        try:
            r = _engine("pack", "import", "--demo", "--yes", timeout=120000)
        except subprocess.TimeoutExpired:
            return self._err(500, "import timed out")
        if r.returncode != 0:
            return self._err(500, (r.stderr or "import failed")[:2000])
        self._json({"ok": True, "result": (r.stdout or "").strip()})

    def _api_open(self, app, target):
        if not ALLOW_OPEN:
            return self._err(403, "open is disabled -- start the cockpit with --allow-open")
        ed = next((e for e in EDITORS if e["bin"] == app), None)
        if not ed:
            return self._err(400, f"editor '{app}' not available")
        t = os.path.abspath(target) if target else PROJECT_ROOT
        if not t or not under_root(t):
            return self._err(403, "path outside workspace")
        argv = [ed["bin"], t]
        kw = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
              "stdin": subprocess.DEVNULL}
        if os.name == "nt":
            # code/cursor/etc. are .cmd shims that CreateProcess can't launch
            # directly -- run them through cmd, same as the desktop GUI does.
            argv = ["cmd", "/c"] + argv
            kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        else:
            kw["start_new_session"] = True
        try:
            subprocess.Popen(argv, **kw)
        except Exception as e:
            return self._err(500, str(e))
        self._json({"ok": True, "app": app, "path": t})

    # -- terminal --
    def _api_term_new(self):
        if not ALLOW_TERMINAL:
            return self._err(403, "terminal disabled -- start the cockpit with PS_ALLOW_TERMINAL=1")
        sid = secrets.token_hex(12)
        if os.name == "nt":
            bridge = os.path.join(HERE, "ptybridge_win.py")
            shell = (os.environ.get("PS_SHELL") or shutil.which("pwsh")
                     or shutil.which("powershell") or os.environ.get("COMSPEC") or "cmd.exe")
        else:
            bridge = PTY_BRIDGE
            shell = os.environ.get("SHELL", "/bin/bash")
        env = dict(os.environ, TERM="xterm-256color")
        try:
            proc = subprocess.Popen([PS_PYTHON, bridge, shell],
                                    cwd=PROJECT_ROOT or HOME, env=env,
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0, creationflags=_CNW)
        except Exception as e:
            return self._err(500, str(e))
        with TERMS_LOCK:
            TERMS[sid] = {"proc": proc}
        self._json({"sid": sid})

    def _api_term_stream(self, sid):
        with TERMS_LOCK:
            s = TERMS.get(sid)
        if not s:
            return self._send(404, "no such terminal", "text/plain")
        proc = s["proc"]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        self.close_connection = True  # SSE has no Content-Length; close when it ends
        # Pump the child's PTY output on a thread (works on Windows too -- you
        # can't select() on a pipe fd there). The SSE loop drains the queue and
        # uses the queue timeout to emit heartbeats; a write failure means the
        # browser hung up, so we stop and kill the shell.
        q: "queue.Queue" = queue.Queue(maxsize=2048)
        out_fd = proc.stdout.fileno()

        def pump():
            while True:
                try:
                    data = os.read(out_fd, 65536)
                except OSError:
                    data = b""
                q.put(data)
                if not data:
                    break

        threading.Thread(target=pump, daemon=True).start()
        try:
            self.wfile.write(b":ok\n\n"); self.wfile.flush()
            while True:
                try:
                    data = q.get(timeout=25)
                except queue.Empty:
                    self.wfile.write(b":hb\n\n"); self.wfile.flush()  # keep proxies alive
                    continue
                if not data:                        # child exited / pipe closed
                    break
                self.wfile.write(b"data: " + base64.b64encode(data) + b"\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionError, OSError):
            pass
        finally:
            try:
                proc.kill()
            except Exception:
                pass
            with TERMS_LOCK:
                TERMS.pop(sid, None)

    def _api_term_input(self, sid, buf):
        with TERMS_LOCK:
            s = TERMS.get(sid)
        if not s:
            return self._err(404, "no such terminal")
        term_frame(s["proc"], b"i", buf or b"")
        self._json({"ok": True})

    def _api_term_resize(self, sid, body):
        with TERMS_LOCK:
            s = TERMS.get(sid)
        if not s:
            return self._err(404, "no such terminal")
        try:
            cols = int(body.get("cols")) or 80
        except (TypeError, ValueError):
            cols = 80
        try:
            rows = int(body.get("rows")) or 24
        except (TypeError, ValueError):
            rows = 24
        term_frame(s["proc"], b"r", f"{cols},{rows}".encode())
        self._json({"ok": True})

    # -- routing --
    def do_POST(self):
        u = urlparse(self.path)
        p, q = u.path, parse_qs(u.query)
        try:
            if p == "/api/memory/capture":
                return self._api_capture("memory", self._read_body().get("text"))
            if p == "/api/journal/capture":
                return self._api_capture("journal", self._read_body().get("text"))
            if p == "/api/memory/pin":
                b = self._read_body()
                return self._api_mem_op("pin", b.get("name"), b.get("unpin"))
            if p == "/api/memory/delete":
                return self._api_mem_op("delete", self._read_body().get("name"))
            if p == "/api/workspace/import-demo":
                self._read_body()
                return self._api_import_demo()
            if p == "/api/workspace/import":
                if q.get("url"):
                    return self._api_import(q["url"][0], None)
                return self._api_import(None, self._read_raw())
            if p == "/api/term/new":
                return self._api_term_new()
            m = re.match(r"^/api/term/([a-f0-9]+)/input$", p)
            if m:
                return self._api_term_input(m.group(1), self._read_raw())
            m = re.match(r"^/api/term/([a-f0-9]+)/resize$", p)
            if m:
                return self._api_term_resize(m.group(1), self._read_body())
            return self._send(404, "not found", "text/plain")
        except Exception as e:
            return self._err(500, str(e))

    def do_GET(self):
        u = urlparse(self.path)
        p, q = u.path, parse_qs(u.query)
        try:
            if p == "/":
                return self._serve_static("index.html")
            if p == "/api/meta":
                return self._json({"home": HOME, "project_root": PROJECT_ROOT,
                                   "has_journal": bool(JOURNAL_DIR), "allow_open": ALLOW_OPEN,
                                   "allow_write": ALLOW_WRITE, "allow_terminal": ALLOW_TERMINAL,
                                   "editors": EDITORS, "ssh_host": SSH_HOST,
                                   "opener_port": OPENER_PORT})
            if p == "/api/journal":
                return self._json(load_journal())
            if p == "/api/memory":
                return self._json(load_memory())
            if p == "/api/docs":
                return self._json(load_docs())
            if p == "/api/file":
                return self._api_file((q.get("path") or [""])[0])
            if p == "/api/open":
                return self._api_open((q.get("app") or [""])[0], (q.get("path") or [""])[0])
            if p == "/api/mdlab/run":
                return self._api_mdlab_run((q.get("path") or [""])[0])
            if p == "/api/workspace/export":
                return self._api_export()
            m = re.match(r"^/api/term/([a-f0-9]+)/stream$", p)
            if m:
                return self._api_term_stream(m.group(1))
            if re.match(r"^/[\w./-]+$", p) and ".." not in p:
                return self._serve_static(p[1:])
            return self._send(404, "not found", "text/plain")
        except Exception as e:
            return self._err(500, str(e))


def main():
    port = int(os.environ.get("PS_PORT") or "7700")
    host = os.environ.get("PS_HOST") or "127.0.0.1"
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    n_journal = len(load_journal())
    print(f"[priorstates cockpit] home={HOME} project={PROJECT_ROOT or '(none)'}")
    if not PROJECT_ROOT:
        print("[priorstates cockpit] WARNING: no project detected -- Journal tab will be empty.")
        print("[priorstates cockpit] Launch `priorstates cockpit` from your project dir, or pass --project PATH.")
    else:
        print(f"[priorstates cockpit] journal={JOURNAL_DIR} ({n_journal} entries)")
    print(f"[priorstates cockpit] http://{host}:{port}/")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
