"""`priorstates` command-line interface."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from .core.config import (
    DEFAULT_CONFIG_TOML, PROJECT_MARKER, home_dir, load_config,
)


def _print(obj):
    print(json.dumps(obj, indent=2) if not isinstance(obj, str) else obj)


# --------------------------------------------------------------------------- #
# init
# --------------------------------------------------------------------------- #
def cmd_init(args):
    home = home_dir()
    home.mkdir(parents=True, exist_ok=True)
    cfg_path = home / "config.toml"
    if not cfg_path.exists():
        cfg_path.write_text(DEFAULT_CONFIG_TOML)
        print(f"wrote {cfg_path}")
    (home / "memory").mkdir(exist_ok=True)
    (home / "models").mkdir(exist_ok=True)

    if not args.global_only:
        proj = Path(args.path).resolve() if args.path else Path.cwd()
        pdir = proj / PROJECT_MARKER
        (pdir / "memory").mkdir(parents=True, exist_ok=True)
        (pdir / "journal" / "entries").mkdir(parents=True, exist_ok=True)
        if not (pdir / "config.toml").exists():
            (pdir / "config.toml").write_text("# Project overrides for PriorStates.\n")
        print(f"initialized project scope at {pdir}")

    if args.download_model:
        _download_model()
    print("done. Next: `priorstates agents install`  then  `priorstates cockpit`.")


MODEL_FILES = ["onnx/model.onnx", "tokenizer.json", "config.json",
               "tokenizer_config.json", "vocab.txt", "special_tokens_map.json"]


def _http_download(url: str, out: Path):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "priorstates/0.1"})
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".part")
    tty = sys.stdout.isatty()
    with urllib.request.urlopen(req, timeout=120) as r:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        with open(tmp, "wb") as f:
            while True:
                chunk = r.read(1 << 18)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if tty and total:  # live bar only on a real terminal
                    print(f"\r    {out.name}: {int(done * 100 / total):3d}%  ({done >> 20} MB)",
                          end="", flush=True)
    if tty and total:
        print()
    os.replace(tmp, out)
    mb = done / (1 << 20)
    print(f"    {out.name}: {mb:.1f} MB" if mb >= 1 else f"    {out.name}: ok")


def _download_model():
    home = home_dir()
    dest = home / "models" / "bge-small-en-v1.5"
    repo = os.environ.get("PRIORSTATES_HF_REPO", "BAAI/bge-small-en-v1.5")
    base = os.environ.get("PRIORSTATES_HF_BASE", "https://huggingface.co")
    print(f"downloading {repo} → {dest} (~127 MB)…")

    # Fast path: huggingface_hub if it happens to be installed.
    try:
        from huggingface_hub import snapshot_download
        snapshot_download(repo, local_dir=str(dest), allow_patterns=MODEL_FILES)
    except Exception:
        # Stdlib path: fetch the needed files directly (no extra dependency).
        try:
            for rel in MODEL_FILES:
                _http_download(f"{base}/{repo}/resolve/main/{rel}", dest / rel)
        except Exception as e:
            print(f"\ncould not download model ({e}).")
            print(f"  Check your network, or place the ONNX model + tokenizer under {dest}/ "
                  f"manually (files: {', '.join(MODEL_FILES)}).")
            print("  The hashing fallback keeps working meanwhile.")
            return

    onnx = dest / "onnx" / "model.onnx"
    if not onnx.exists() or onnx.stat().st_size < 1_000_000:
        print("model files look incomplete — re-run `priorstates init --download-model`.")
        return
    print("model files installed.")

    # Semantic recall also needs the inference libraries.
    missing = [m for m in ("onnxruntime", "tokenizers") if not _importable(m)]
    if missing:
        print(f"NOTE: install the inference libs to actually use it: "
              f"pip install --user {' '.join(missing)}")
        print("      then run: priorstates memory reindex")
        return
    print("semantic recall enabled (embedder: onnx).")
    # Existing .psmem indexes were built with the hashing embedder — rebuild them
    # so stored vectors live in the same space as the new query embeddings.
    try:
        from .memory.api import reindex
        reindex(load_config(), "all")
        print("re-indexed existing memories with the semantic model.")
    except Exception:
        print("run `priorstates memory reindex` to rebuild memory search with the model.")


def _importable(mod: str) -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec(mod) is not None
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# memory
# --------------------------------------------------------------------------- #
def cmd_memory(args):
    from .memory import api as mem
    cfg = load_config()
    if args.action == "add":
        body = args.body or sys.stdin.read()
        _print(mem.add_memory(cfg, name=args.name, type_str=args.type,
                              description=args.description or "", body=body,
                              pinned=args.pin, scope=args.scope, overwrite=args.overwrite))
    elif args.action == "search":
        rows = mem.search_memory(cfg, args.query, k=args.k, type_str=args.type, scope=args.scope)
        for r in rows:
            print(f"{r['score']:+.3f}  [{r['type']}]{' 📌' if r['pinned'] else ''}  {r['name']}")
            if r["description"]:
                print(f"        {r['description']}")
    elif args.action == "list":
        for r in mem.list_pinned(cfg, scope=args.scope):
            print(f"📌 {r['name']}  [{r['type']}]  {r['description']}")
    elif args.action == "pin":
        _print(mem.pin_memory(cfg, args.name, pinned=not args.unpin, scope=args.scope))
    elif args.action == "delete":
        _print(mem.delete_memory(cfg, args.name, scope=args.scope))
    elif args.action == "reindex":
        _print(mem.reindex(cfg, args.scope, verbose=True))
    elif args.action == "capture":
        from .core.capture import capture_memory
        text = args.text or sys.stdin.read()
        _print(capture_memory(cfg, text))


# --------------------------------------------------------------------------- #
# journal
# --------------------------------------------------------------------------- #
def cmd_journal(args):
    from .core import journal as J
    cfg = load_config()
    if args.action == "add":
        body = args.body or sys.stdin.read()
        e = J.add(cfg, topic=args.topic, outcome=args.outcome, title=args.title, body=body,
                  tags=args.tag, evidence=args.evidence, supersedes=args.supersedes)
        print(f"recorded {e.id}  [{e.outcome}]  → {e.path}")
    elif args.action == "search":
        rows = J.search(cfg, topic=args.topic, outcome=args.outcome, tag=args.tag,
                        since=args.since, until=args.until, query=args.query, k=args.k)
        for r in rows:
            sup = f"  (→{r['superseded_by']})" if r["superseded_by"] else ""
            print(f"{r['date']} [{r['outcome']}] {r['topic']}: {r['title']}{sup}")
        if not rows:
            print("(no matching entries)")
    elif args.action == "regen":
        J.regenerate_all(cfg)
        print("regenerated INDEX.md, by_topic/, digests/")
    elif args.action == "capture":
        from .core.capture import capture_journal
        text = args.text or sys.stdin.read()
        _print(capture_journal(cfg, text))


# --------------------------------------------------------------------------- #
# workspace share (export / import)
# --------------------------------------------------------------------------- #
def cmd_workspace(args):
    from .core import share
    cfg = load_config()
    if args.action == "export":
        out = share.export_workspace(cfg, scope=args.scope, out_path=args.out,
                                     name=args.name, author=args.author)
        print(f"exported → {out}")
        print("Share that file; the recipient runs:  priorstates workspace import <file-or-url>")
    elif args.action in ("import", "install"):
        src = share.packaged_demo() if getattr(args, "demo", False) else args.source
        if not src:
            print("give a .psworkspace file/URL, or --demo", file=sys.stderr); sys.exit(2)
        manifest, _ = share.read_bundle(src)
        print(share.summarize(manifest))
        assume_yes = args.yes or getattr(args, "demo", False)  # the bundled demo is trusted
        if not assume_yes:
            if not sys.stdin.isatty():
                print("refusing to import non-interactively without --yes "
                      "(imported memory is used by your agents).", file=sys.stderr)
                sys.exit(2)
            if input("Import into your workspace? [y/N] ").strip().lower() not in ("y", "yes"):
                print("cancelled."); return
        res = share.import_workspace(cfg, src)
        msg = f"imported '{res['name']}': +{res['memory_added']} memories"
        if res["memory_renamed"]:
            msg += f" ({res['memory_renamed']} renamed to avoid clashes)"
        msg += f", +{res['journal_added']} journal entries"
        if res["journal_needs_project"]:
            msg += "  (journal skipped — run `priorstates init` in a project to import it)"
        print(msg)
        print("Your agents can recall the new memories now (restart the agent if it caches tools).")
    elif args.action == "publish":
        import json
        import os
        import tempfile
        import urllib.error
        import urllib.request
        hub = (args.hub or os.environ.get("PRIORSTATES_HUB") or "https://priorstates.com/w").rstrip("/")
        key = os.environ.get("PRIORSTATES_HUB_KEY", "")
        fd, tmp = tempfile.mkstemp(suffix=".psworkspace"); os.close(fd)
        try:
            share.export_workspace(cfg, scope=args.scope, out_path=tmp, name=args.name, author=args.author)
            data = open(tmp, "rb").read()
        finally:
            try: os.unlink(tmp)
            except OSError: pass
        req = urllib.request.Request(hub, data=data, method="POST",
                                     headers={"Content-Type": "application/octet-stream"})
        if key:
            req.add_header("X-PriorStates-Key", key)
        if getattr(args, "list", False):
            req.add_header("X-Listed", "1")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                res = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            print(f"publish failed ({e.code}): {e.read().decode('utf-8', 'replace')}", file=sys.stderr)
            if e.code == 403:
                print("This hub requires a key — set PRIORSTATES_HUB_KEY.", file=sys.stderr)
            sys.exit(1)
        pubf = cfg.home / "published.json"
        try:
            reg = json.loads(pubf.read_text()) if pubf.exists() else {}
        except Exception:
            reg = {}
        reg[res["id"]] = {"url": res["url"], "token": res["token"], "name": args.name or ""}
        pubf.write_text(json.dumps(reg, indent=2))
        print(f"published → {res['url']}")
        print(f"install:    priorstates workspace install {res['url']}")
        if res.get("listed"):
            print("listed in the hub directory → https://priorstates.com/browse.html")
        print(f"(edit token saved to {pubf} — keep it to delete the bundle later)")


# --------------------------------------------------------------------------- #
# mdlab / agents / cockpit / gui / mcp / doctor
# --------------------------------------------------------------------------- #
def cmd_mdlab(args):
    cfg = load_config()
    from .mdlab import run_file
    for f in args.files:
        _print(run_file(f, cfg))


def _pkg_dir() -> Path:
    return Path(__file__).resolve().parent  # the `priorstates` package dir


def _warn_if_mcp_missing():
    from .agents.install import mcp_importable
    if not mcp_importable():
        print("\n⚠  The `mcp` package is NOT installed, so the PriorStates MCP server cannot")
        print("   start — agents will see no PriorStates tools (and may hand-write journal")
        print("   files in the wrong format). Fix it with:")
        print("       python3 -m pip install --user mcp")
        print("   then restart your agent (Claude / Codex / Gemini).")


def cmd_agents(args):
    from .agents.install import install, uninstall, status, protocol
    cfg = load_config()
    if args.action == "install":
        _print(install(cfg, args.agent or None, protocol=not args.no_protocol))
        _warn_if_mcp_missing()
    elif args.action == "uninstall":
        _print(uninstall(cfg, args.agent or None))
    elif args.action == "status":
        _print(status(cfg))
    elif args.action == "protocol":
        _print(protocol(cfg, args.agent or None, on=not args.off))


def cmd_cockpit(args):
    cfg = load_config(force_project=args.project) if args.project else load_config()
    server = _pkg_dir() / "cockpit" / "server.js"
    if not server.exists():
        print(f"cockpit server not found at {server}", file=sys.stderr)
        sys.exit(1)
    env = dict(os.environ)
    env["PRIORSTATES_HOME"] = str(cfg.home)
    if cfg.project_root:
        env["PRIORSTATES_PROJECT_ROOT"] = str(cfg.project_root)
        print(f"cockpit → http://{args.host}:{args.port}/   (Ctrl-C to stop)")
        print(f"  project: {cfg.project_root}")
        print(f"  journal: {cfg.journal_dir}")
    else:
        print("WARNING: no PriorStates project found from "
              f"{args.project or 'the current directory'} (no .priorstates/ here).")
        print("         The Journal tab will be EMPTY. Either:")
        print("           cd <your project> && priorstates cockpit")
        print("         or:  priorstates cockpit --project /path/to/your/project")
        print(f"cockpit → http://{args.host}:{args.port}/   (Ctrl-C to stop)")
    env["PS_PORT"] = str(args.port)
    env["PS_HOST"] = args.host
    env["PS_PYTHON"] = sys.executable  # the engine the cockpit shells out to (mdlab run, etc.)
    if args.allow_open:
        env["PS_ALLOW_OPEN"] = "1"
        print("  open-in-editor: enabled")
    if getattr(args, "allow_write", False):
        env["PS_ALLOW_WRITE"] = "1"
        print("  writes + mdlab run: enabled (code runs on THIS host)")
    import shutil
    node = shutil.which("node") or shutil.which("node.exe")
    if not node:
        print("node.js is required to run the cockpit but was not found on PATH.\n"
              "Install Node.js (https://nodejs.org) and retry.", file=sys.stderr)
        sys.exit(1)
    sys.stdout.flush()
    if os.name == "nt":
        # execvpe is unreliable on Windows consoles; run as a child and exit with it.
        try:
            sys.exit(subprocess.call([node, str(server)], env=env))
        except KeyboardInterrupt:
            sys.exit(0)
    os.execvpe(node, [node, str(server)], env)  # POSIX: replace this process


def _bootstrap_remote(host: str, ssh: list[str]) -> str | None:
    """Ship the local PriorStates package to the remote (like vscode-server) and
    return a runner command that uses it. The package is pure-Python, so we just
    copy it onto the remote's PYTHONPATH and ensure numpy is present. Returns the
    runner string, or None on failure."""
    import priorstates as _pm
    pkg = Path(_pm.__file__).resolve().parent           # .../priorstates
    remote_dir = ".priorstates-app"
    print(f"shipping PriorStates to {host}:~/{remote_dir}/ …")
    tar = subprocess.Popen(
        ["tar", "czf", "-", "-C", str(pkg.parent),
         "--exclude=__pycache__", "--exclude=*.pyc", "--exclude=*.psmem", pkg.name],
        stdout=subprocess.PIPE)
    rc = subprocess.run(ssh + [host, f"rm -rf ~/{remote_dir}/priorstates && mkdir -p ~/{remote_dir} "
                               f"&& tar xzf - -C ~/{remote_dir}"], stdin=tar.stdout).returncode
    tar.stdout.close()
    if rc != 0:
        print("  could not copy the package to the remote.", file=sys.stderr)
        return None
    # ensure numpy (the one hard dependency) on the remote
    print("ensuring numpy on the remote …")
    subprocess.run(ssh + [host, "sh -lc 'python3 -c \"import numpy\" 2>/dev/null || "
                          "python3 -m pip install --user -q numpy'"])
    runner = f"PYTHONPATH=$HOME/{remote_dir} python3 -m priorstates"
    # verify it imports there
    chk = subprocess.run(ssh + [host, f"sh -lc 'PYTHONPATH=$HOME/{remote_dir} "
                                f"python3 -c \"import priorstates\"'"]).returncode
    if chk != 0:
        print("  shipped, but it still won't import on the remote (python3/numpy issue).",
              file=sys.stderr)
        return None
    print("PriorStates bootstrapped on the remote ✓")
    return runner


def _start_local_opener(host: str) -> int:
    """Run a tiny localhost HTTP server ON THE CLIENT that opens a file/folder in
    the LOCAL editor via its CLI (``code --reuse-window --remote ssh-remote+host
    <path>``) — the proven way to open a *single remote file*, which the
    vscode:// URL handler can't do. The remote cockpit can't run the client's
    editor, so it calls this from the browser. Returns the chosen port."""
    import http.server
    import shutil
    import threading
    import urllib.parse

    BINS = {"code": "code", "code-insiders": "code-insiders", "cursor": "cursor",
            "windsurf": "windsurf", "antigravity": "antigravity"}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(u.query)
            ok = False
            if u.path == "/open":
                app = (q.get("app") or [""])[0]
                path = (q.get("path") or [""])[0]
                b = BINS.get(app)
                if b and path and shutil.which(b):
                    try:
                        subprocess.Popen([b, "--reuse-window", "--remote",
                                          f"ssh-remote+{host}", path])
                        ok = True
                    except Exception:
                        ok = False
            self.send_response(200 if ok else 400)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}' if ok else b'{"ok":false}')

    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1]


def _free_local_port(preferred: int) -> int:
    import socket
    for port in [preferred, *range(preferred + 1, preferred + 60)]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return preferred


def cmd_connect(args):
    """VSCode-style: run PriorStates on a remote host and open it locally over SSH."""
    import shlex
    import time
    import webbrowser
    import urllib.request
    import base64
    import hashlib
    import tempfile
    try:
        sys.stdout.reconfigure(line_buffering=True)  # so the GUI sees status promptly
    except Exception:
        pass
    host = args.host
    # A free LOCAL port so we never collide with a local cockpit (which would
    # make the browser open the local UI instead of the forwarded remote one).
    lport = _free_local_port(args.port)

    # SSH options: don't hang on a dead host or an unknown host key, and (on
    # POSIX) MULTIPLEX so we authenticate ONCE (the probe opens the master, the
    # tunnel reuses it — important when auth needs a password/passphrase).
    SSH = ["ssh", "-o", "ConnectTimeout=12", "-o", "StrictHostKeyChecking=accept-new"]
    if os.name != "nt":
        # ControlMaster/ControlPath multiplexing isn't supported by Windows
        # OpenSSH, and os.getuid() doesn't exist there — POSIX only.
        uid = os.getuid()
        sock = os.path.join(tempfile.gettempdir(),
                            f"pm-ssh-{uid}-{hashlib.sha1(host.encode()).hexdigest()[:8]}")
        SSH += ["-o", "ControlMaster=auto", "-o", f"ControlPath={sock}",
                "-o", "ControlPersist=120"]

    # 1) Make sure the engine exists on the remote (like vscode-server bootstrap).
    print(f"authenticating to {host} …")
    probe = subprocess.run(
        SSH + [host, "sh -lc 'command -v priorstates >/dev/null 2>&1 && echo OK || "
               "(python3 -c \"import priorstates\" >/dev/null 2>&1 && echo MOD || echo MISSING)'"],
        text=True, stdout=subprocess.PIPE)
    if probe.returncode != 0:
        print(f"cannot ssh to {host} (auth/network failed).", file=sys.stderr)
        sys.exit(1)
    state = ((probe.stdout or "").strip().splitlines()[-1:] or [""])[0]
    if state == "MISSING" or args.install:
        runner = _bootstrap_remote(host, SSH)
        if not runner:
            print(f"could not bootstrap PriorStates on {host}. Install it manually "
                  f"(needs python3 + numpy + node), then retry.", file=sys.stderr)
            sys.exit(1)
    else:
        runner = "priorstates" if state == "OK" else "python3 -m priorstates"

    # 1b) Pick a free REMOTE port (reuses the multiplexed connection — no re-auth).
    if args.remote_port:
        rport = args.remote_port
    else:
        code = "import socket;s=socket.socket();s.bind(('127.0.0.1',0));print(s.getsockname()[1]);s.close()"
        b64 = base64.b64encode(code.encode()).decode()
        rp = subprocess.run(
            SSH + [host, f"python3 -c \"import base64;exec(base64.b64decode('{b64}').decode())\""],
            capture_output=True, text=True)
        out = (rp.stdout or "").strip()
        rport = int(out) if out.isdigit() else 7765

    # 2) Build the remote command: run the cockpit on the remote, write+run enabled.
    # Local opener (on the client) so the cockpit's buttons can open a single
    # remote file in YOUR editor via `code --remote …`. PS_SSH_HOST/PS_OPENER_PORT
    # are passed through to the cockpit so the browser knows where to call.
    opener_port = _start_local_opener(host)
    proj = f" --project {shlex.quote(args.project)}" if args.project else ""
    remote_cmd = (f"sh -lc 'PATH=$HOME/.local/bin:$PATH PS_SSH_HOST={host} "
                  f"PS_OPENER_PORT={opener_port} {runner} cockpit "
                  f"--host 127.0.0.1 --port {rport} --allow-write --allow-open{proj}'")

    # 3) SSH with a port-forward; the cockpit (and any code it runs) lives on the
    #    remote; only the rendered UI comes back over the tunnel.
    url = f"http://127.0.0.1:{lport}/"
    if lport != args.port:
        print(f"(local port {args.port} busy — using {lport})")
    print(f"connecting to {host} … running PriorStates remotely; {url} → {host}:{rport}")
    print("  (research env, data, model and mdlab code all run on the server)")
    ssh = subprocess.Popen(SSH + ["-tt", "-L", f"{lport}:127.0.0.1:{rport}", host, remote_cmd])

    # 4) Wait until the REMOTE cockpit answers through the tunnel, then open it.
    ready = False
    for _ in range(40):
        if ssh.poll() is not None:
            print("ssh exited before the remote cockpit came up — check the output above.",
                  file=sys.stderr)
            sys.exit(1)
        try:
            with urllib.request.urlopen(url + "api/meta", timeout=1) as r:
                if r.status == 200:
                    ready = True
                    break
        except Exception:
            time.sleep(0.5)
    print(f"{'ready — ' if ready else ''}opening {url}   —   Ctrl-C to disconnect")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        ssh.wait()
    except KeyboardInterrupt:
        ssh.terminate()


def cmd_gui(args):
    from .gui.app import main as gui_main
    gui_main(getattr(args, "project", None))


def cmd_mcp(args):
    from .mcp.server import main as mcp_main
    mcp_main()


def cmd_doctor(args):
    cfg = load_config()
    from .core.embedder import get_embedder
    print(f"home:           {cfg.home}")
    print(f"project_root:   {cfg.project_root}")
    print(f"journal_dir:    {cfg.journal_dir}")
    emb = get_embedder(cfg)
    print(f"embedder:       {getattr(emb, 'backend', '?')} (dim={emb.dim})")
    if getattr(emb, "backend", "") == "hashing":
        print("                ↳ run `priorstates init --download-model` for semantic recall")
    print(f"node present:   {bool(_which('node'))}")
    from .agents.install import mcp_importable
    mcp_ok = mcp_importable()
    print(f"mcp server:     {'runnable' if mcp_ok else 'NOT runnable — agents get no tools'}")
    if not mcp_ok:
        print("                ↳ python3 -m pip install --user mcp   (then restart your agent)")
    from .agents import status as ag_status
    for s in ag_status(cfg):
        flag = "✓" if (s["mcp_registered"] and mcp_ok) else ("·" if s["installed"] else " ")
        print(f"agent {s['agent']:<7} installed={s['installed']} "
              f"registered={s['mcp_registered']} runnable={mcp_ok} [{flag}]")


def _which(x):
    from shutil import which
    return which(x)


# --------------------------------------------------------------------------- #
# desktop launcher
# --------------------------------------------------------------------------- #
ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">
  <rect width="128" height="128" rx="24" fill="#0d1117"/>
  <circle cx="64" cy="58" r="30" fill="none" stroke="#58a6ff" stroke-width="6"/>
  <circle cx="64" cy="58" r="12" fill="#3fb950"/>
  <line x1="86" y1="80" x2="104" y2="98" stroke="#58a6ff" stroke-width="8" stroke-linecap="round"/>
</svg>
"""


def _xdg_data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))


def _xdg_desktop_dir() -> Path:
    try:
        r = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            return Path(r.stdout.strip())
    except Exception:
        pass
    return Path.home() / "Desktop"


def _desktop_entry() -> str:
    # sys.executable -m priorstates gui works for pip/pipx/deb installs alike, and
    # uses an absolute interpreter so it runs from the desktop's minimal PATH.
    # Icon is a THEMED NAME (not an absolute path) so GNOME's dash/favorites
    # renders it — absolute-path icons go blank when added to favorites.
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Version=1.0\n"
        "Name=PriorStates\n"
        "GenericName=AI memory & journal cockpit\n"
        "Comment=Manage memory, research journal, agents and the web cockpit\n"
        f"Exec={sys.executable} -m priorstates gui\n"
        f"TryExec={sys.executable}\n"
        "Icon=priorstates\n"
        "Terminal=false\n"
        "Categories=Development;\n"
        "Keywords=AI;memory;journal;claude;codex;gemini;mcp;antigravity;\n"
        "StartupNotify=true\n"
    )


def _rasterize_svg(svg: Path, png: Path, size: int) -> bool:
    """Best-effort SVG→PNG so GNOME has a raster icon too (more reliable in the
    dash than SVG on some shell versions). No-op if no rasterizer is available."""
    png.parent.mkdir(parents=True, exist_ok=True)
    if _which("rsvg-convert"):
        subprocess.run(["rsvg-convert", "-w", str(size), "-h", str(size), str(svg), "-o", str(png)],
                       check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if png.exists():
            return True
    if _which("inkscape"):
        subprocess.run(["inkscape", str(svg), "--export-type=png", "-w", str(size),
                        "-h", str(size), "-o", str(png)],
                       check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if png.exists():
            return True
    try:
        import cairosvg
        cairosvg.svg2png(url=str(svg), write_to=str(png), output_width=size, output_height=size)
        return png.exists()
    except Exception:
        return False


def _icon_files(data: Path) -> dict:
    base = data / "icons" / "hicolor"
    return {
        "base": base,
        "svg": base / "scalable" / "apps" / "priorstates.svg",
        "png": [base / f"{s}x{s}" / "apps" / "priorstates.png" for s in (256, 128, 64, 48)],
    }


def _refresh_icon_cache(base: Path):
    # gtk-update-icon-cache needs an index.theme; reuse the system hicolor one.
    idx = base / "index.theme"
    if not idx.exists():
        sys_idx = Path("/usr/share/icons/hicolor/index.theme")
        try:
            idx.write_text(sys_idx.read_text() if sys_idx.exists()
                           else "[Icon Theme]\nName=Hicolor\nDirectories=scalable/apps\n"
                                "[scalable/apps]\nSize=256\nType=Scalable\nContext=Applications\n")
        except OSError:
            pass
    for tool in ("gtk-update-icon-cache", "gtk4-update-icon-cache"):
        if _which(tool):
            subprocess.run([tool, "-f", "-t", "-q", str(base)], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            break


def cmd_install_launcher(args):
    if sys.platform != "linux":
        where = ("packaging\\windows\\install.ps1 (or the Setup .exe)" if os.name == "nt"
                 else "the macOS .pkg / `brew install` (creates PriorStates.app)")
        print("install-launcher builds a freedesktop .desktop entry, which is Linux-only.")
        print(f"On this platform the GUI shortcut is created by {where}.")
        print("You can always run the GUI with:  priorstates gui")
        return
    data = _xdg_data_home()
    apps = data / "applications"
    icons = _icon_files(data)
    desktop_file = apps / "priorstates.desktop"
    desk_copy = _xdg_desktop_dir() / "priorstates.desktop"

    if args.uninstall:
        removed = []
        for p in (desktop_file, desk_copy, icons["svg"], *icons["png"]):
            try:
                if p.exists():
                    p.unlink()
                    removed.append(str(p))
            except OSError:
                pass
        if _which("update-desktop-database"):
            subprocess.run(["update-desktop-database", str(apps)], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _refresh_icon_cache(icons["base"])
        print("removed:", removed or "(nothing to remove)")
        return

    apps.mkdir(parents=True, exist_ok=True)
    icons["svg"].parent.mkdir(parents=True, exist_ok=True)
    icons["svg"].write_text(ICON_SVG, encoding="utf-8")
    rastered = [p for p in icons["png"]
                if _rasterize_svg(icons["svg"], p, int(p.parent.parent.name.split("x")[0]))]
    entry = _desktop_entry()
    desktop_file.write_text(entry, encoding="utf-8")
    desktop_file.chmod(0o755)
    if _which("update-desktop-database"):
        subprocess.run(["update-desktop-database", str(apps)], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _refresh_icon_cache(icons["base"])
    print(f"installed launcher → {desktop_file}")
    print(f"icon (themed 'priorstates') → {icons['svg']}"
          + (f"  (+{len(rastered)} PNG sizes)" if rastered else "  (SVG only — no rasterizer found)"))

    if args.desktop:
        desk_copy.parent.mkdir(parents=True, exist_ok=True)
        desk_copy.write_text(entry, encoding="utf-8")
        desk_copy.chmod(0o755)
        # GNOME/Nautilus require the .desktop on the Desktop to be marked trusted.
        if _which("gio"):
            subprocess.run(["gio", "set", str(desk_copy), "metadata::trusted", "true"],
                           check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"desktop icon      → {desk_copy}")

    print("\nSearch your application menu for 'PriorStates'. If it doesn't appear")
    print("immediately, log out/in (or restart the shell). Remove it later with:")
    print("  priorstates install-launcher --uninstall")


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #
def build_parser():
    p = argparse.ArgumentParser("priorstates", description="PriorStates — shared memory & research journal for your AI agents (memory + journal + cockpit + mdlab).")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init", help="initialize global + project scopes")
    pi.add_argument("path", nargs="?", help="project root (default: cwd)")
    pi.add_argument("--global-only", action="store_true")
    pi.add_argument("--download-model", action="store_true", help="fetch the ONNX embedding model")
    pi.set_defaults(func=cmd_init)

    pm = sub.add_parser("memory", help="manage memories")
    pms = pm.add_subparsers(dest="action", required=True)
    a = pms.add_parser("add"); a.add_argument("name"); a.add_argument("--type", default="note")
    a.add_argument("--description", default=""); a.add_argument("--body")
    a.add_argument("--scope", default="project"); a.add_argument("--pin", action="store_true")
    a.add_argument("--overwrite", action="store_true")
    a = pms.add_parser("search"); a.add_argument("query"); a.add_argument("-k", type=int, default=5)
    a.add_argument("--type"); a.add_argument("--scope", default="all")
    a = pms.add_parser("list"); a.add_argument("--scope", default="all")
    a = pms.add_parser("pin"); a.add_argument("name"); a.add_argument("--unpin", action="store_true")
    a.add_argument("--scope", default="all")
    a = pms.add_parser("delete"); a.add_argument("name"); a.add_argument("--scope", default="all")
    a = pms.add_parser("reindex"); a.add_argument("--scope", default="all")
    a = pms.add_parser("capture", help="add a memory from a free-text sentence")
    a.add_argument("text", nargs="?", help="plain-English memory (or piped on stdin)")
    pm.set_defaults(func=cmd_memory)

    pj = sub.add_parser("journal", help="manage the research journal")
    pjs = pj.add_subparsers(dest="action", required=True)
    a = pjs.add_parser("add"); a.add_argument("--topic", required=True); a.add_argument("--outcome", required=True)
    a.add_argument("--title", required=True); a.add_argument("--body")
    a.add_argument("--tag", action="append"); a.add_argument("--evidence", action="append")
    a.add_argument("--supersedes")
    a = pjs.add_parser("search"); a.add_argument("--topic"); a.add_argument("--outcome")
    a.add_argument("--tag"); a.add_argument("--since"); a.add_argument("--until")
    a.add_argument("--query"); a.add_argument("-k", type=int, default=20)
    pjs.add_parser("regen")
    a = pjs.add_parser("capture", help="add a journal entry from a free-text sentence")
    a.add_argument("text", nargs="?", help="plain-English note (or piped on stdin)")
    pj.set_defaults(func=cmd_journal)

    pw = sub.add_parser("workspace", help="share a workspace (memory + journal)")
    pws = pw.add_subparsers(dest="action", required=True)
    we = pws.add_parser("export", help="bundle this workspace into a .psworkspace file")
    we.add_argument("--scope", default="project", choices=["project", "global", "user", "all"])
    we.add_argument("--out"); we.add_argument("--name"); we.add_argument("--author")
    wi = pws.add_parser("import", help="import a .psworkspace file or URL (or --demo)")
    wi.add_argument("source", nargs="?", help="path or http(s) URL to a .psworkspace")
    wi.add_argument("--demo", action="store_true", help="import the bundled demo workspace")
    wi.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    wl = pws.add_parser("install", help="install a workspace from a URL (alias for import)")
    wl.add_argument("source", help="http(s) URL (or path) to a .psworkspace")
    wl.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    wpub = pws.add_parser("publish", help="export + upload to the hub; prints a shareable link")
    wpub.add_argument("--scope", default="project", choices=["project", "global", "user", "all"])
    wpub.add_argument("--name"); wpub.add_argument("--author")
    wpub.add_argument("--list", action="store_true", help="list it in the public hub directory (default: unlisted private link)")
    wpub.add_argument("--hub", help="hub base URL (default $PRIORSTATES_HUB or https://priorstates.com/w)")
    pw.set_defaults(func=cmd_workspace)

    pl = sub.add_parser("mdlab", help="run runnable-Markdown files")
    pls = pl.add_subparsers(dest="action", required=True)
    plr = pls.add_parser("run")
    plr.add_argument("files", nargs="+")
    pl.set_defaults(func=cmd_mdlab)

    pa = sub.add_parser("agents", help="wire Claude/Codex/Gemini")
    pas = pa.add_subparsers(dest="action", required=True)
    ai = pas.add_parser("install", help="register MCP + write pinned + research-protocol blocks")
    ai.add_argument("agent", nargs="*", help="claude codex gemini (default: enabled)")
    ai.add_argument("--no-protocol", action="store_true", help="don't write the research-protocol instruction block")
    au = pas.add_parser("uninstall")
    au.add_argument("agent", nargs="*")
    pas.add_parser("status")
    ap = pas.add_parser("protocol", help="add/remove just the research-protocol instruction block")
    ap.add_argument("agent", nargs="*")
    ap.add_argument("--off", action="store_true", help="remove the protocol block")
    pa.set_defaults(func=cmd_agents)

    pc = sub.add_parser("cockpit", help="launch the web cockpit")
    pc.add_argument("--port", type=int, default=7700); pc.add_argument("--host", default="127.0.0.1")
    pc.add_argument("--project", help="project root to show (default: auto-detect from cwd)")
    pc.add_argument("--allow-open", action="store_true",
                    help="enable 'Open in editor' buttons (launches VSCode/Antigravity/… on the host)")
    pc.add_argument("--allow-write", action="store_true",
                    help="enable writes + mdlab Run (code executes on the host serving the cockpit)")
    pc.set_defaults(func=cmd_cockpit)

    pcn = sub.add_parser("connect", help="run PriorStates on a remote host (VSCode-style) and open it locally")
    pcn.add_argument("host", help="ssh host (uses your ~/.ssh/config), e.g. ai2 or user@server")
    pcn.add_argument("project", nargs="?", help="remote project path (workspace on the server)")
    pcn.add_argument("--port", type=int, default=7800,
                     help="local port (default 7800, distinct from the local cockpit's 7700)")
    pcn.add_argument("--remote-port", type=int, help="remote port (default: same as --port)")
    pcn.add_argument("--install", action="store_true",
                     help="(re)ship PriorStates to the host even if already present")
    pcn.set_defaults(func=cmd_connect)

    pg = sub.add_parser("gui", help="launch the desktop control panel")
    pg.add_argument("--project", help="workspace (project folder) to open")
    pg.set_defaults(func=cmd_gui)
    sub.add_parser("mcp", help="run the MCP server (used by agents)").set_defaults(func=cmd_mcp)
    sub.add_parser("doctor", help="report config + backend + agent status").set_defaults(func=cmd_doctor)
    pdl = sub.add_parser("install-launcher", help="add a desktop/app-menu launcher for the GUI")
    pdl.add_argument("--desktop", action="store_true", help="also place an icon on your Desktop")
    pdl.add_argument("--uninstall", action="store_true", help="remove the launcher")
    pdl.set_defaults(func=cmd_install_launcher)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
