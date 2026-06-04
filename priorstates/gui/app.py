"""PriorStates desktop control panel.

A stdlib-only (Tkinter) GUI that acts as the **launcher / control plane** — the
things that need a native app: manage workspaces (local + remote SSH), launch
agents (CLI) and editors/IDEs in a workspace, wire/unwire agents over MCP, and
open the web cockpit. Browsing and editing *content* (memory, journal, docs,
mdlab) lives in the cockpit, which is the better medium for it. Slow operations
(model download, cockpit) run off the UI thread. The Tk root is created only in
:func:`main`, so importing this module is safe on headless machines.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

# GitHub-dark palette — matches the web cockpit so the two surfaces feel like one product.
BG, BG2, BG3 = "#0d1117", "#161b22", "#1c2230"
FG, DIM, BORDER = "#c9d1d9", "#8b949e", "#30363d"
ACCENT, ACCENT_HOVER, ACCENT_FG = "#1f6feb", "#388bfd", "#ffffff"
HOVER = "#222b3a"
GREEN, ORANGE = "#3fb950", "#e3934d"

# A copy-paste prompt that makes an agent demonstrate PriorStates live.
STARTER_PROMPT = (
    "Use PriorStates: save a pinned 'preference' memory that I prefer "
    "hypothesis-driven parameter tuning over grid search. Then search your "
    "PriorStates memory to confirm you can recall it, and tell me what you found."
)

class _Tip:
    """Minimal hover tooltip for a Tk widget (stdlib only)."""

    def __init__(self, widget, text):
        self.widget, self.text, self.tip = widget, text, None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _show(self, _=None):
        import tkinter as tk
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 14
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry("+%d+%d" % (x, y))
        tk.Label(self.tip, text=self.text, justify="left", bg=BG3, fg=FG,
                 relief="solid", borderwidth=1, padx=8, pady=5, wraplength=320).pack()

    def _hide(self, _=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


def _load(start=None):
    from ..core.config import load_config
    return load_config(start)


def _applescript_str(s: str) -> str:
    """Quote a Python string as an AppleScript string literal."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


# macOS app-bundle names for editors that may be installed without a PATH CLI.
_MAC_APPS = {
    "code": "Visual Studio Code", "code-insiders": "Visual Studio Code - Insiders",
    "cursor": "Cursor", "windsurf": "Windsurf", "antigravity": "Antigravity",
}


def _remote_cd(proj: str) -> str:
    """A `cd` to `proj` on a remote shell that still expands a leading ~.

    The remote is always a POSIX shell (an ssh target), so this uses POSIX
    quoting regardless of the client OS.
    """
    import shlex
    if proj == "~":
        return "cd ~"
    if proj.startswith("~/"):
        return "cd ~/" + shlex.quote(proj[2:])
    return "cd " + shlex.quote(proj)


def _winq(s: str) -> str:
    """Quote an argument for a Windows cmd.exe command line."""
    return '"' + s.replace('"', '\\"') + '"'


class PriorStatesGUI:
    def __init__(self, root, project=None):
        import tkinter as tk
        from tkinter import ttk
        self.tk = tk
        self.ttk = ttk
        self.root = root
        self._explicit_project = project
        root.title("PriorStates — shared memory & research journal for your AI agents")
        root.geometry("1140x710")
        root.minsize(940, 600)
        self._cockpits = {}      # {workspace: {proc, port, allow_open}} — one cockpit each
        self._connections = []

        self._apply_theme()

        # header (brand)
        header = ttk.Frame(root, style="Header.TFrame")
        header.pack(fill="x")
        hin = ttk.Frame(header, style="Header.TFrame")
        hin.pack(fill="x", padx=18, pady=12)
        ttk.Label(hin, text="\U0001F52D  PriorStates", style="Brand.TLabel").pack(side="left")
        ttk.Label(hin, text="shared memory & research journal for your AI agents",
                  style="Dim.TLabel").pack(side="left", padx=12)

        self.status = tk.StringVar(value="ready")

        # body: LEFT workspace tabs | RIGHT notebook for the selected workspace
        body = ttk.Frame(root, style="TFrame")
        body.pack(fill="both", expand=True)
        self.sidebar = ttk.Frame(body, style="Sidebar.TFrame", width=210)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        mainf = ttk.Frame(body, style="TFrame")
        mainf.pack(side="left", fill="both", expand=True)

        # Workspaces — local OR remote — are entries in the left sidebar; the
        # right surface follows the selected one (local → notebook, remote →
        # cockpit panel). Resolve cfg BEFORE building tabs (they read self.cfg).
        self.workspaces = self._initial_workspaces()
        self.workspace = self.workspaces[0] if self.workspaces else None
        self.cfg = _load(self._ws_local_path(self.workspace))

        self._mainf = mainf
        self._remote_bins = {}        # host -> set of agent keys present (None/absent = unknown)
        self._launchbar = ttk.Frame(mainf, style="Launch.TFrame")
        self._launchbar.pack(fill="x", side="top", padx=12, pady=(8, 0))
        self._nb = ttk.Notebook(mainf)
        self._tabs = {}
        self._tab_dashboard(self._nb)
        self._tab_agents(self._nb)
        self._build_remote_panel(mainf)

        bar = ttk.Frame(root, style="Header.TFrame")
        bar.pack(fill="x", side="bottom")
        ttk.Label(bar, textvariable=self.status, style="Status.TLabel", anchor="w").pack(fill="x")

        self._rebuild_sidebar()
        self._show_for_workspace()
        if not self._ws_is_remote(self.workspace):
            self.refresh_all()

    # ----- workspace model (local path OR remote host/proj) ------------ #
    def _ws_key(self, w):
        if not w:
            return "(none)"
        if w.get("kind") == "remote":
            return "remote:" + w["host"] + ":" + (w.get("proj") or "")
        return w["path"]

    def _ws_name(self, w):
        if not w:
            return "(none)"
        if w.get("kind") == "remote":
            tail = ("/" + Path(w["proj"]).name) if w.get("proj") else ""
            return "⇆ " + w["host"] + tail
        return "\U0001F4C1 " + Path(w["path"]).name

    def _ws_is_remote(self, w):
        return bool(w) and w.get("kind") == "remote"

    def _ws_local_path(self, w):
        return w["path"] if (w and w.get("kind") == "local") else None

    def _build_remote_panel(self, parent):
        ttk = self.ttk
        f = ttk.Frame(parent, style="TFrame")
        self._remote_frame = f
        box = ttk.Frame(f, style="TFrame")
        box.pack(fill="both", expand=True, padx=34, pady=30)
        ttk.Label(box, text="⇆  Remote workspace", style="Brand.TLabel").pack(anchor="w")
        self.remote_target_var = self.tk.StringVar()
        ttk.Label(box, textvariable=self.remote_target_var,
                  style="TLabel", font=(self._pick_font(["DejaVu Sans Mono", "monospace"]), 11)).pack(
            anchor="w", pady=(4, 18))
        ttk.Label(box, text=("PriorStates runs on the server (its env, data, model and code). The\n"
                             "memory, journal, docs and mdlab Run are managed in the browser\n"
                             "cockpit, which opens locally over an SSH tunnel."),
                  style="TLabel", justify="left").pack(anchor="w", pady=(0, 18))
        row = ttk.Frame(box, style="TFrame")
        row.pack(anchor="w")
        ttk.Button(row, text="Open Cockpit", command=self.open_cockpit,
                   style="Accent.TButton").pack(side="left")
        ttk.Button(row, text="Disconnect", command=self._disconnect_current).pack(side="left", padx=8)
        self.remote_status_var = self.tk.StringVar(value="not connected")
        ttk.Label(box, textvariable=self.remote_status_var, style="Dim.TLabel").pack(anchor="w", pady=(16, 0))
        return f

    def _show_for_workspace(self):
        self._rebuild_launchbar()
        if self._ws_is_remote(self.workspace):
            self._show_remote_panel(self.workspace)
        else:
            self._show_local_notebook()

    # ----- per-workspace launch bar ------------------------------------ #
    def _launch_targets(self):
        """(key, label, bin, kind, wired_aware).

        kind        — 'cli' = terminal program; 'gui' = editor/IDE on a folder.
        wired_aware — key matches an agents.install ADAPTERS key, i.e. PriorStates's
                      MCP server is wired into it directly (so it gets a ⚠ when
                      unwired). VSCode/Cursor/Windsurf are NOT MCP clients
                      themselves (their agent *extension* is), so no ⚠.
        """
        return [
            ("claude", "Claude", "claude", "cli", True),
            ("codex", "Codex", "codex", "cli", True),
            ("gemini", "Gemini", "gemini", "cli", True),
            ("antigravity", "Antigravity", "antigravity", "gui", True),
            ("code", "VSCode", "code", "gui", False),
            ("cursor", "Cursor", "cursor", "gui", False),
            ("windsurf", "Windsurf", "windsurf", "gui", False),
            ("code-insiders", "VSCode Insiders", "code-insiders", "gui", False),
        ]

    def _bin_present_local(self, binname):
        import os
        import shutil
        if shutil.which(binname):
            return True
        if sys.platform == "darwin" and _MAC_APPS.get(binname):
            return os.path.isdir("/Applications/%s.app" % _MAC_APPS[binname])
        return False

    def _local_present_keys(self):
        return {k for k, _, b, _, _ in self._launch_targets() if self._bin_present_local(b)}

    def _cli_bins(self):
        return [(k, b) for k, _, b, kind, _ in self._launch_targets() if kind == "cli"]

    def _wired_agents(self):
        """Agent keys whose PriorStates MCP server is registered (so the launched
        agent actually sees PriorStates's tools). Local workspaces only."""
        try:
            from ..agents import status as ag_status
            return {s["agent"] for s in ag_status(self.cfg) if s.get("mcp_registered")}
        except Exception:
            return set()

    def _remote_cli_present(self, host):
        """Probe the server (key-based ssh) for which terminal-agent CLIs exist.
        None until the probe returns → show all optimistically."""
        cache = self._remote_bins
        if host in cache:
            return cache[host]
        cache[host] = None                      # pending → optimistic

        def probe():
            clibins = self._cli_bins()
            bins = " ".join(b for _, b in clibins)
            cmd = "for b in %s; do command -v $b >/dev/null 2>&1 && echo $b; done" % bins
            try:
                out = subprocess.run(
                    ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6", host, cmd],
                    capture_output=True, text=True, timeout=14)
                found = set(out.stdout.split())
            except Exception:
                cache.pop(host, None)           # couldn't probe → stay optimistic, retry later
                return
            cache[host] = {k for k, b in clibins if b in found}
            self.root.after(0, self._rebuild_launchbar)

        threading.Thread(target=probe, daemon=True).start()
        return None

    def _present_keys(self, w):
        """Target keys to show for workspace `w`. For a remote workspace, GUI
        editors connect from the LOCAL client (local presence) while terminal
        CLIs run on the server (ssh probe)."""
        local = self._local_present_keys()
        if not self._ws_is_remote(w):
            return local
        gui = {k for k, _, _, kind, _ in self._launch_targets() if kind == "gui" and k in local}
        remote = self._remote_cli_present(w["host"])
        if remote is None:                      # probe pending → optimistic
            return gui | {k for k, _, _, kind, _ in self._launch_targets() if kind == "cli"}
        return gui | set(remote)

    def _rebuild_launchbar(self):
        ttk = self.ttk
        bar = getattr(self, "_launchbar", None)
        if bar is None:
            return
        for c in bar.winfo_children():
            c.destroy()
        w = self.workspace
        if not w:
            return
        present = self._present_keys(w)
        wired = None if self._ws_is_remote(w) else self._wired_agents()
        targets = self._launch_targets()

        # Primary action — the daily driver — sits first and prominent (local
        # workspaces; remote ones have a dedicated Open Cockpit in the panel).
        if not self._ws_is_remote(w):
            ck = ttk.Button(bar, text="🛰  Open Cockpit", style="Accent.TButton",
                            command=self.open_cockpit)
            ck.pack(side="left", padx=(2, 16), pady=3)
            self._tip(ck, "Open the local web cockpit — browse and add memory, journal and docs.")

        def add_group(group, lead_gap=False):
            shown = [t for t in group if t[0] in present]
            if not shown:
                return False
            if lead_gap:                       # a little air between agents and editors
                ttk.Frame(bar, style="Launch.TFrame").pack(side="left", padx=8)
            for key, label, _b, _kind, wa in shown:
                unwired = wa and wired is not None and key not in wired
                txt = label + " ⚠" if unwired else label
                b = ttk.Button(bar, text=txt, style="Agent.TButton",
                               command=lambda k=key: self._launch_target(self.workspace, k))
                b.pack(side="left", padx=3)
                self._tip(b, ("⚠ PriorStates isn't wired into %s yet — click Install on the "
                              "Agents tab so it sees the memory + journal tools." % label)
                          if unwired else "Open %s in this workspace." % label)
            return True

        any_agent = add_group([t for t in targets if t[4]])
        add_group([t for t in targets if not t[4]], lead_gap=any_agent)
        if not present:
            ttk.Label(bar, text="no agent CLI or editor found on PATH",
                      style="LaunchHint.TLabel").pack(side="left", padx=4)
        elif not any_agent:
            ttk.Label(bar, text="(no agent CLI found — install claude / codex / gemini)",
                      style="LaunchHint.TLabel").pack(side="left", padx=8)

    def _launch_target(self, w, key):
        meta = {t[0]: t for t in self._launch_targets()}[key]
        _k, label, binname, kind, _wa = meta
        if kind == "cli":
            self._launch_cli(w, binname)
        else:
            self._launch_gui(w, binname, label)

    def _launch_cli(self, w, binname):
        """Open a terminal running a CLI agent in the workspace dir, so the
        nearest .priorstates/ resolves (local) or the remote project does (remote)."""
        import shlex
        remote = self._ws_is_remote(w)
        if remote:
            host, proj = w["host"], w.get("proj", "")
            rcmd = ((_remote_cd(proj) + " 2>/dev/null; ") if proj else "") + binname
            where = host + ((":" + proj) if proj else "")
        else:
            path = w["path"]
            where = path
        if os.name == "nt":
            if remote:
                cmdline = "ssh -t %s %s" % (_winq(host), _winq(rcmd))
            else:
                cmdline = "cd /d %s & %s" % (_winq(path), binname)
            ok = self._spawn_windows_console(cmdline)
            self.set_status(f"launched {binname} in {where}" if ok
                            else f"could not open a console for {binname}")
            return
        if remote:
            inner = "ssh -t %s %s" % (shlex.quote(host), shlex.quote(rcmd))
        else:
            inner = "cd %s && exec %s" % (shlex.quote(path), binname)
        inner += '; echo; read -p "[%s exited — press Enter to close] "' % binname
        term = self._terminal_argv(inner)
        if not term:
            self.set_status("no terminal emulator found to launch " + binname)
            return
        try:
            subprocess.Popen(term)
            self.set_status(f"launched {binname} in {where}")
        except Exception as e:
            self.set_status(f"launch failed: {e}")

    def _spawn_windows_console(self, cmdline):
        """Open a new console window running `cmdline` (cmd.exe syntax) and keep
        it open after the program exits. Prefers Windows Terminal if present."""
        import shutil
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        try:
            if shutil.which("wt"):           # Windows Terminal, if installed
                subprocess.Popen(["wt", "cmd", "/k", cmdline])
            else:
                subprocess.Popen("cmd /k " + cmdline, creationflags=flags)
            return True
        except Exception as e:
            self.set_status(f"launch failed: {e}")
            return False

    def _launch_gui(self, w, binname, label):
        """Open an editor/IDE on the workspace folder. Remote uses VSCode-style
        `--remote ssh-remote+host <path>` (the client runs locally)."""
        import os
        import shutil
        if self._ws_is_remote(w):
            host, proj = w["host"], w.get("proj", "")
            if not shutil.which(binname):
                self.set_status(f"{label}: opening a remote folder needs the '{binname}' CLI on PATH")
                return
            argv = [binname, "--remote", "ssh-remote+" + host] + ([proj] if proj else [])
            where = host + ((":" + proj) if proj else "")
        else:
            path = w["path"]
            if shutil.which(binname):
                argv = [binname, path]
            elif sys.platform == "darwin" and _MAC_APPS.get(binname):
                argv = ["open", "-a", _MAC_APPS[binname], path]
            else:
                self.set_status(f"{binname} not found on PATH")
                return
            where = path
        if os.name == "nt":
            argv = ["cmd", "/c"] + argv      # editor launchers are .cmd shims on Windows
        try:
            subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.set_status(f"opened {where} in {label}")
        except Exception as e:
            self.set_status(f"open failed: {e}")

    def _show_local_notebook(self):
        if getattr(self, "_remote_frame", None):
            self._remote_frame.pack_forget()
        self._nb.pack(fill="both", expand=True, padx=12, pady=(8, 0))

    def _show_remote_panel(self, w):
        self._nb.pack_forget()
        tail = ("  :  " + w["proj"]) if w.get("proj") else "   (server's default project)"
        self.remote_target_var.set(w["host"] + tail)
        self.remote_status_var.set(self._remote_status_text(w))
        self._remote_frame.pack(fill="both", expand=True)

    def _remote_status_text(self, w):
        e = getattr(self, "_cockpits", {}).get(self._ws_key(w))
        if e and e["proc"].poll() is None:
            return "connected — cockpit open in your browser"
        return "not connected — click Open Cockpit"

    def _disconnect_current(self):
        e = getattr(self, "_cockpits", {}).get(self._ws_key(self.workspace))
        if e:
            try:
                if e["proc"].poll() is None:
                    e["proc"].terminate()
            except Exception:
                pass
            self._cockpits.pop(self._ws_key(self.workspace), None)
        if self._ws_is_remote(self.workspace):
            self.remote_status_var.set("not connected — click Open Cockpit")
        self.set_status("disconnected")

    # ----- workspace --------------------------------------------------- #
    def _gui_state_path(self):
        from ..core.config import home_dir
        return home_dir() / "gui_state.json"

    def _gui_state(self):
        import json
        try:
            return json.loads(self._gui_state_path().read_text())
        except Exception:
            return {}

    def _initial_workspace(self):
        # 0) an explicit --project, if it's a workspace
        if self._explicit_project and (Path(self._explicit_project) / ".priorstates").is_dir():
            return Path(self._explicit_project)
        # 1) a project under the current dir (relevant when run as `priorstates gui`)
        try:
            cwd_root = _load(self._explicit_project).project_root
        except Exception:
            cwd_root = None
        if cwd_root:
            return Path(cwd_root)
        # 2) the last workspace chosen in the GUI (launcher path)
        last = self._gui_state().get("last_workspace")
        if last and (Path(last) / ".priorstates").is_dir():
            return Path(last)
        return None

    def _initial_workspaces(self):
        st = self._gui_state()
        out = []
        first = self._initial_workspace()      # explicit --project / cwd / last (local)
        if first:
            out.append({"kind": "local", "path": str(first)})
        for w in st.get("workspaces", []):
            if isinstance(w, dict):
                out.append(w)
            elif isinstance(w, str):           # migrate old format (list of paths)
                out.append({"kind": "local", "path": w})
        seen, uniq = set(), []
        for w in out:
            k = self._ws_key(w)
            if k in seen:
                continue
            if w.get("kind") == "local" and not Path(w["path"]).exists():
                continue
            seen.add(k)
            uniq.append(w)
        return uniq

    def _save_workspaces(self):
        import json
        st = self._gui_state()
        st["workspaces"] = self.workspaces
        if self.workspace and not self._ws_is_remote(self.workspace):
            st["last_workspace"] = self.workspace["path"]
        try:
            p = self._gui_state_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(st, indent=2))
        except Exception:
            pass

    def _refresh_combos(self):
        if hasattr(self, "mem_type_cb"):
            self.mem_type_cb.configure(values=self.cfg.memory_types)
        if hasattr(self, "jr_outcome_cb"):
            self.jr_outcome_cb.configure(values=self.cfg.outcomes)

    # ----- left workspace-tab sidebar ---------------------------------- #
    def _rebuild_sidebar(self):
        tk, ttk = self.tk, self.ttk
        for w in self.sidebar.winfo_children():
            w.destroy()
        ttk.Label(self.sidebar, text="WORKSPACES", style="SideHdr.TLabel").pack(
            fill="x", padx=14, pady=(14, 6))
        lst = ttk.Frame(self.sidebar, style="Sidebar.TFrame")
        lst.pack(fill="both", expand=True)
        for ws in self.workspaces:
            active = self.workspace is not None and self._ws_key(ws) == self._ws_key(self.workspace)
            row = ttk.Frame(lst, style="Sidebar.TFrame")
            row.pack(fill="x", padx=6, pady=1)
            ttk.Button(row, text=("▸ " if active else "   ") + self._ws_name(ws),
                       style=("WsActive.TButton" if active else "Ws.TButton"),
                       command=lambda p=ws: self.select_workspace(p)).pack(
                side="left", fill="x", expand=True)
            ttk.Button(row, text="✕", width=2, style="Ws.TButton",
                       command=lambda p=ws: self.close_workspace(p)).pack(side="right")
        if not self.workspaces:
            ttk.Label(lst, text="No workspace open.\nClick “+ Add workspace”.",
                      style="Dim.TLabel", justify="left").pack(padx=14, pady=10, anchor="w")
        act = ttk.Frame(self.sidebar, style="Sidebar.TFrame")
        act.pack(fill="x", side="bottom", padx=8, pady=10)
        ttk.Button(act, text="+  Add workspace", command=self.add_workspace,
                   style="Ws.TButton").pack(fill="x", pady=2)
        ttk.Button(act, text="⇆  Connect remote…", command=self.connect_remote,
                   style="Ws.TButton").pack(fill="x", pady=2)

    def select_workspace(self, w):
        if self.workspace is None or self._ws_key(w) != self._ws_key(self.workspace):
            self.set_workspace(w)

    def _add_workspace_entry(self, entry, select=True):
        if self._ws_key(entry) not in [self._ws_key(w) for w in self.workspaces]:
            self.workspaces.append(entry)
        if select:
            self.set_workspace(entry)
        else:
            self._save_workspaces()
            self._rebuild_sidebar()

    def add_workspace(self):
        from tkinter import filedialog, messagebox
        d = filedialog.askdirectory(
            title="Add a PriorStates workspace (project folder)",
            initialdir=self._ws_local_path(self.workspace) or str(Path.home()),
            mustexist=True)
        if not d:
            return
        p = Path(d)
        if not (p / ".priorstates").is_dir():
            if not messagebox.askyesno(
                    "Initialize workspace?",
                    f"{p}\n\nis not a PriorStates workspace yet. Create .priorstates/ here?"):
                return
            from ..core.config import PROJECT_MARKER
            try:
                (p / PROJECT_MARKER / "memory").mkdir(parents=True, exist_ok=True)
                (p / PROJECT_MARKER / "journal" / "entries").mkdir(parents=True, exist_ok=True)
                cfgp = p / PROJECT_MARKER / "config.toml"
                if not cfgp.exists():
                    cfgp.write_text("# Project overrides for PriorStates.\n")
            except OSError as e:
                messagebox.showerror("PriorStates", f"Could not initialize:\n{e}")
                return
        self._add_workspace_entry({"kind": "local", "path": str(p)})

    def close_workspace(self, w):
        key = self._ws_key(w)
        # stop its cockpit / connection
        e = getattr(self, "_cockpits", {}).get(key)
        if e:
            try:
                if e["proc"].poll() is None:
                    e["proc"].terminate()
            except Exception:
                pass
            self._cockpits.pop(key, None)
        self.workspaces = [x for x in self.workspaces if self._ws_key(x) != key]
        if self.workspace is not None and self._ws_key(self.workspace) == key:
            nxt = self.workspaces[0] if self.workspaces else None
            self.workspace = nxt
            self.cfg = _load(self._ws_local_path(nxt))
            self._show_for_workspace()
            if not self._ws_is_remote(nxt):
                self._refresh_combos()
                self.refresh_all()
        self._save_workspaces()
        self._rebuild_sidebar()

    def connect_remote(self):
        """Add a REMOTE workspace tab. Like a local one, it sits in the sidebar;
        clicking Open Cockpit runs PriorStates on the server and opens it locally."""
        from tkinter import simpledialog
        last = self._gui_state().get("last_remote", "")
        target = simpledialog.askstring(
            "Add a remote workspace",
            "Run PriorStates on a server (VSCode-style). Enter:\n\n"
            "host:/project/path     (e.g.  ai2:~/research)\n"
            "or just  host          (server's default project)\n",
            initialvalue=last, parent=self.root)
        if not target:
            return
        target = target.strip()
        if ":" in target and not target.startswith(("ssh://",)):
            host, _, proj = target.partition(":")
        else:
            host, proj = target, ""
        host, proj = host.strip(), proj.strip()
        if not host:
            return
        self._save_gui_kv("last_remote", target)
        self._add_workspace_entry({"kind": "remote", "host": host, "proj": proj})

    def _launch_connect(self, w):
        """Start `priorstates connect host [proj]` (in a terminal if possible).
        Returns the process or None."""
        import shlex
        host, proj = w["host"], w.get("proj", "")
        args = [sys.executable, "-m", "priorstates", "connect", host]
        if proj:
            args.append(proj)
        inner = shlex.join(args) + '; echo; read -p "Press Enter to close (disconnects)…"'
        term = self._terminal_argv(inner)
        if term:
            try:
                return subprocess.Popen(term)
            except Exception:
                pass
        try:
            p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        except Exception as e:
            self.set_status(f"connect failed: {e}")
            return None

        def reader():
            for line in iter(p.stdout.readline, ""):
                line = line.rstrip()
                if line:
                    self.root.after(0, lambda l=line: self.set_status(f"[{host}] {l}"))
            rc = p.wait()
            if rc != 0:
                self.root.after(0, lambda: self.set_status(f"[{host}] disconnected (exit {rc})"))
        threading.Thread(target=reader, daemon=True).start()
        return p

    def _terminal_argv(self, inner: str):
        """Return an argv that runs the shell command `inner` in a terminal
        emulator, or None if none is available."""
        import shutil
        import shlex
        if sys.platform == "darwin":
            # Tell Terminal.app to run the command in a new window.
            script = 'tell application "Terminal" to do script %s' % _applescript_str(
                "bash -lc " + shlex.quote(inner))
            return ["osascript", "-e", script]
        candidates = [
            ("gnome-terminal", ["gnome-terminal", "--", "bash", "-lc", inner]),
            ("konsole", ["konsole", "-e", "bash", "-lc", inner]),
            ("xfce4-terminal", ["xfce4-terminal", "--command", f"bash -lc {shlex.quote(inner)}"]),
            ("x-terminal-emulator", ["x-terminal-emulator", "-e", "bash", "-lc", inner]),
            ("xterm", ["xterm", "-e", "bash", "-lc", inner]),
            ("kitty", ["kitty", "bash", "-lc", inner]),
            ("alacritty", ["alacritty", "-e", "bash", "-lc", inner]),
        ]
        for name, argv in candidates:
            if shutil.which(name):
                return argv
        return None

    def _save_gui_kv(self, key, value):
        import json
        st = self._gui_state()
        st[key] = value
        try:
            p = self._gui_state_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(st, indent=2))
        except Exception:
            pass

    def set_workspace(self, w):
        self.workspace = w
        if self._ws_key(w) not in [self._ws_key(x) for x in self.workspaces]:
            self.workspaces.append(w)
        self.cfg = _load(self._ws_local_path(w))
        self._save_workspaces()
        self._rebuild_launchbar()
        if self._ws_is_remote(w):
            self._show_remote_panel(w)
            self.set_status(f"remote workspace: {w['host']}"
                            + (f":{w['proj']}" if w.get('proj') else ""))
        else:
            self._show_local_notebook()
            self._refresh_combos()    # project config may differ per workspace
            self.refresh_all()
            self.set_status(f"workspace: {w['path']}")
        self._rebuild_sidebar()       # update the active highlight

    # ----- theme ------------------------------------------------------- #
    def _pick_font(self, prefs):
        import tkinter.font as tkfont
        try:
            avail = set(tkfont.families(self.root))
        except Exception:
            avail = set()
        for p in prefs:
            if p in avail:
                return p
        return prefs[-1]

    def _apply_theme(self):
        tk, ttk = self.tk, self.ttk
        root = self.root
        root.configure(bg=BG)

        # fonts
        import tkinter.font as tkfont
        fam = self._pick_font(["Segoe UI", "SF Pro Text", "Helvetica Neue", "Inter",
                               "Ubuntu", "Noto Sans", "DejaVu Sans", "Arial"])
        for fn in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                tkfont.nametofont(fn).configure(family=fam, size=10)
            except Exception:
                pass
        mono = self._pick_font(["JetBrains Mono", "Cascadia Code", "Menlo", "Consolas",
                                "DejaVu Sans Mono", "monospace"])
        try:
            tkfont.nametofont("TkFixedFont").configure(family=mono, size=10)
        except Exception:
            pass

        # classic tk widgets (Text/Listbox) styled via the option DB — must run
        # BEFORE those widgets are created (i.e. before the tabs are built).
        for cls in ("Text", "Listbox"):
            root.option_add(f"*{cls}.background", BG2)
            root.option_add(f"*{cls}.foreground", FG)
            root.option_add(f"*{cls}.relief", "flat")
            root.option_add(f"*{cls}.borderWidth", "0")
            root.option_add(f"*{cls}.highlightThickness", "1")
            root.option_add(f"*{cls}.highlightBackground", BORDER)
            root.option_add(f"*{cls}.highlightColor", ACCENT)
            root.option_add(f"*{cls}.selectBackground", ACCENT)
            root.option_add(f"*{cls}.selectForeground", ACCENT_FG)
        root.option_add("*Text.insertBackground", FG)
        root.option_add("*Text.padX", "8")
        root.option_add("*Text.padY", "6")
        root.option_add("*Listbox.activeStyle", "none")
        root.option_add("*TCombobox*Listbox.background", BG2)
        root.option_add("*TCombobox*Listbox.foreground", FG)
        root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        root.option_add("*TCombobox*Listbox.selectForeground", ACCENT_FG)

        style = ttk.Style()
        # Optional Win11-style theme if the user has it; otherwise a custom dark theme.
        try:
            import sv_ttk  # noqa
            sv_ttk.set_theme("dark")
        except Exception:
            try:
                style.theme_use("clam")
            except Exception:
                pass
            self._configure_dark(style, fam)
        # header / brand / status styles (applied on top of whichever base)
        style.configure("Header.TFrame", background=BG2)
        style.configure("Brand.TLabel", background=BG2, foreground=FG, font=(fam, 16, "bold"))
        style.configure("Dim.TLabel", background=BG2, foreground=DIM, font=(fam, 10))
        style.configure("Status.TLabel", background=BG2, foreground=DIM, padding=(16, 7))
        # left workspace-tab sidebar
        style.configure("Sidebar.TFrame", background=BG2)
        style.configure("SideHdr.TLabel", background=BG2, foreground=DIM, font=(fam, 9, "bold"))
        style.configure("Ws.TButton", background=BG2, foreground=FG, bordercolor=BG2,
                        relief="flat", anchor="w", padding=(10, 8))
        style.map("Ws.TButton", background=[("active", HOVER)], bordercolor=[("active", BG2)])
        style.configure("WsActive.TButton", background=BG3, foreground=FG, bordercolor=ACCENT,
                        relief="flat", anchor="w", padding=(10, 8))
        style.map("WsActive.TButton", background=[("active", BG3)], bordercolor=[("active", ACCENT)])
        # per-workspace "Launch agent" bar
        style.configure("Launch.TFrame", background=BG)
        style.configure("LaunchHdr.TLabel", background=BG, foreground=DIM, font=(fam, 9, "bold"))
        style.configure("LaunchHint.TLabel", background=BG, foreground=DIM, font=(fam, 9))
        style.configure("Agent.TButton", background=BG3, foreground=FG, bordercolor=BORDER,
                        relief="flat", padding=(12, 5))
        style.map("Agent.TButton", background=[("active", ACCENT)], foreground=[("active", ACCENT_FG)],
                  bordercolor=[("active", ACCENT)])

    def _configure_dark(self, style, fam):
        style.configure(".", background=BG2, foreground=FG, fieldbackground=BG3,
                        bordercolor=BORDER, lightcolor=BG2, darkcolor=BG2,
                        troughcolor=BG, focuscolor=ACCENT, font=(fam, 10))
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("TButton", background=BG3, foreground=FG, bordercolor=BORDER,
                        relief="flat", padding=(12, 7), anchor="center")
        style.map("TButton",
                  background=[("pressed", "#2d3645"), ("active", HOVER), ("disabled", BG2)],
                  bordercolor=[("active", ACCENT)], foreground=[("disabled", DIM)])
        style.configure("Accent.TButton", background=ACCENT, foreground=ACCENT_FG,
                        bordercolor=ACCENT, padding=(14, 7))
        style.map("Accent.TButton",
                  background=[("pressed", "#1158c7"), ("active", ACCENT_HOVER), ("disabled", BG3)],
                  foreground=[("disabled", DIM)])
        style.configure("TCheckbutton", background=BG, foreground=FG, focuscolor=BG,
                        indicatorbackground=BG3, indicatorforeground=ACCENT)
        style.map("TCheckbutton", background=[("active", BG)], foreground=[("active", FG)],
                  indicatorbackground=[("selected", ACCENT), ("active", BG3)])
        style.configure("TEntry", fieldbackground=BG3, foreground=FG, bordercolor=BORDER,
                        insertcolor=FG, padding=6)
        style.map("TEntry", bordercolor=[("focus", ACCENT)])
        style.configure("TCombobox", fieldbackground=BG3, foreground=FG, bordercolor=BORDER,
                        arrowcolor=DIM, padding=6)
        style.map("TCombobox", fieldbackground=[("readonly", BG3)],
                  foreground=[("readonly", FG)], bordercolor=[("focus", ACCENT)],
                  arrowcolor=[("active", FG)])
        style.configure("TLabelframe", background=BG, bordercolor=BORDER, relief="solid")
        style.configure("TLabelframe.Label", background=BG, foreground=DIM, font=(fam, 9, "bold"))
        style.configure("TNotebook", background=BG, bordercolor=BG, tabmargins=(2, 6, 2, 0))
        # Drop the clam "Notebook.focus" element: it draws a dotted ring tight
        # around the selected tab's label, making it look shrunken. Rebuild the
        # tab layout without it so every tab is the same size in every state.
        try:
            style.layout("TNotebook.Tab", [
                ("Notebook.tab", {"sticky": "nswe", "children": [
                    ("Notebook.padding", {"side": "top", "sticky": "nswe", "children": [
                        ("Notebook.label", {"side": "top", "sticky": ""}),
                    ]}),
                ]}),
            ])
        except Exception:
            pass
        style.configure("TNotebook.Tab", background=BG, foreground=DIM, padding=(18, 9),
                        bordercolor=BG, font=(fam, 10), focuscolor=BG)
        style.map("TNotebook.Tab",
                  background=[("selected", BG2), ("active", HOVER)],
                  foreground=[("selected", FG), ("active", FG)],
                  padding=[("selected", (18, 9))],          # identical size when selected
                  expand=[("selected", (0, 0, 0, 0))])      # don't let clam grow it
        style.configure("Vertical.TScrollbar", background=BG3, troughcolor=BG,
                        bordercolor=BG, arrowcolor=DIM)
        style.configure("TScrollbar", background=BG3, troughcolor=BG, bordercolor=BG, arrowcolor=DIM)

    # ----- helpers ----------------------------------------------------- #
    def set_status(self, msg):
        self.status.set(msg)
        self.root.update_idletasks()

    def run_bg(self, fn, done=None):
        def worker():
            try:
                res = fn()
                if done:
                    self.root.after(0, lambda: done(res))
            except Exception as e:
                self.root.after(0, lambda: self.set_status(f"error: {e}"))
        threading.Thread(target=worker, daemon=True).start()

    # ----- dashboard --------------------------------------------------- #
    def _tab_dashboard(self, nb):
        tk, ttk = self.tk, self.ttk
        f = ttk.Frame(nb)
        nb.add(f, text="Get started")
        self._tabs["dashboard"] = f

        head = ttk.Frame(f); head.pack(fill="x", padx=16, pady=(12, 4))
        tk.Label(head, text="Get started", bg=BG, fg=FG,
                 font=(self._fam(), 13, "bold")).pack(anchor="w")
        tk.Label(head, text=("First-time setup. Your everyday actions — Open Cockpit, launch an "
                             "agent, open an editor — live in the toolbar above."),
                 bg=BG, fg=DIM, wraplength=820, justify="left",
                 font=(self._fam(), 9)).pack(anchor="w", pady=(2, 0))

        # Checklist (rebuilt by _render_dashboard on every refresh).
        self._dash_check = ttk.Frame(f); self._dash_check.pack(fill="x", padx=16, pady=8)

        self.allow_open = tk.BooleanVar(value=True)    # open-in-editor on by default (toggle in System status)

        # Footer: status toggle on the left, subtle Docs/Refresh links on the right.
        footer = ttk.Frame(f); footer.pack(fill="x", padx=16, pady=(12, 6))
        self._status_open = tk.BooleanVar(value=False)
        self._status_toggle = ttk.Button(footer, text="▸ System status & options",
                                          style="Ws.TButton", command=self._toggle_status)
        self._status_toggle.pack(side="left")
        rb = ttk.Button(footer, text="Refresh", style="Ws.TButton", command=self.refresh_all)
        rb.pack(side="right")
        self._tip(rb, "Re-check status (agents wired, memory count, model).")
        db = ttk.Button(footer, text="Docs", style="Ws.TButton", command=self.open_docs)
        db.pack(side="right", padx=6)
        self._tip(db, "Open the PriorStates documentation in your browser.")
        ub = ttk.Button(footer, text="Update", style="Ws.TButton", command=self.update_software)
        ub.pack(side="right", padx=6)
        self._tip(ub, "Reinstall the latest PriorStates from GitHub (restart the app afterward).")

        # Collapsible "System status & options" (advanced; hidden by default).
        self._status_box = ttk.Frame(f)
        cbo = ttk.Checkbutton(self._status_box, text="Cockpit: show “open in editor” buttons",
                              variable=self.allow_open)
        cbo.pack(anchor="w", padx=16, pady=(2, 6))
        self._tip(cbo, "When on, the web cockpit shows buttons that open files in your editor.")
        self.dash_text = tk.Text(self._status_box, height=9, wrap="word", relief="flat",
                                 bg=BG2, fg=DIM, insertbackground=FG, borderwidth=0)
        self.dash_text.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        # _status_box stays unpacked until toggled.

    def _toggle_status(self):
        if self._status_open.get():
            self._status_box.pack_forget()
            self._status_toggle.config(text="▸ System status & options")
            self._status_open.set(False)
        else:
            self._status_box.pack(fill="both", expand=True)
            self._status_toggle.config(text="▾ System status & options")
            self._status_open.set(True)

    def _dashboard_items(self):
        """Checklist rows from current state. kind: 'check' (done/next marker)
        or 'do' (neutral action)."""
        wired = bool(self._wired_agents())
        memn = self._memory_count()
        semantic = getattr(self, "_emb_backend", "hashing") != "hashing"
        ex = self._examples_present()
        items = [
            dict(kind="check", done=wired,
                 title="Wire your agents to PriorStates",
                 hint=("Claude / Codex / Gemini can see PriorStates' tools over MCP."
                       if wired else "No agent is wired yet — click to register the MCP server."),
                 btn=("Open Agents" if wired else "Wire agents"),
                 fn=(lambda: self.goto_tab("agents")) if wired else self.agents_install),
            dict(kind="check", done=memn > 0,
                 title="Add & browse memory + journal",
                 hint=(("%d memor%s so far — view and add more in the cockpit."
                        % (memn, "y" if memn == 1 else "ies")) if memn
                       else "Open the cockpit to add and search memory + journal (or just tell your agent)."),
                 btn="Open cockpit", fn=self.open_cockpit),
            dict(kind="do",
                 title="Try it live with an agent",
                 hint="Copies a starter prompt and opens an agent so you can watch it remember and record.",
                 btn="Try with agent", fn=self.try_with_agent),
            dict(kind="check", done=semantic,
                 title="Upgrade to semantic recall (optional)",
                 hint=("Semantic embedding model active." if semantic
                       else "Using the built-in hashing embedder; download the model for meaning-based recall (~127 MB)."),
                 btn=("Model ready" if semantic else "Download model"),
                 fn=(None if semantic else self.download_model)),
            dict(kind="do",
                 title=("Remove the example data" if ex else "Load example memories + journal"),
                 hint=("Examples are loaded — delete them when you're ready." if ex
                       else "See what a populated PriorStates looks like (clearly marked, one-click delete)."),
                 btn=("Remove examples" if ex else "Load examples"),
                 fn=(self.remove_examples if ex else self.load_examples)),
        ]
        return items

    def _render_dashboard(self):
        tk, ttk = self.tk, self.ttk
        box = getattr(self, "_dash_check", None)
        if box is None:
            return
        for c in box.winfo_children():
            c.destroy()
        for it in self._dashboard_items():
            row = ttk.Frame(box); row.pack(fill="x", pady=3)
            if it["kind"] == "check":
                mark, color = ("✓", GREEN) if it.get("done") else ("→", ACCENT_HOVER)
            else:
                mark, color = ("•", DIM)
            tk.Label(row, text=mark, bg=BG, fg=color, font=(self._fam(), 11),
                     width=2).pack(side="left", anchor="n")
            txt = ttk.Frame(row); txt.pack(side="left", fill="x", expand=True)
            tk.Label(txt, text=it["title"], bg=BG, fg=FG,
                     font=(self._fam(), 10)).pack(anchor="w")
            if it.get("hint"):
                tk.Label(txt, text=it["hint"], bg=BG, fg=DIM, wraplength=620,
                         justify="left", font=(self._fam(), 9)).pack(anchor="w")
            fn = it.get("fn")
            btn = ttk.Button(row, text=it["btn"], command=(fn or (lambda: None)),
                             style="Accent.TButton" if (it["kind"] == "check" and not it.get("done")) else "Agent.TButton")
            if fn is None:
                btn.state(["disabled"])
            btn.pack(side="right", anchor="n")

    def refresh_all(self):
        from ..core.embedder import get_embedder
        from ..agents import status as ag_status
        self.cfg = _load(self._ws_local_path(self.workspace))
        emb = get_embedder(self.cfg)
        self._emb_backend = getattr(emb, "backend", "?")
        try:
            from importlib.metadata import version as _ver
            _v = _ver("priorstates")
        except Exception:
            _v = "?"
        lines = [
            f"version:      {_v}",
            f"home:         {self.cfg.home}",
            f"project root: {self.cfg.project_root or '(none — run init in a project)'}",
            f"journal:      {self.cfg.journal_dir or '(none)'}",
            f"embedder:     {self._emb_backend} (dim={emb.dim})"
            + ("   ← hashing fallback; use 'Download model' for semantic recall"
               if self._emb_backend == 'hashing' else ""),
            "",
            "agents:",
        ]
        for s in ag_status(self.cfg):
            lines.append(f"  {s['agent']:<8} installed={s['installed']}  mcp_registered={s['mcp_registered']}")
        self.dash_text.config(state="normal")
        self.dash_text.delete("1.0", "end")
        self.dash_text.insert("1.0", "\n".join(lines))
        self.dash_text.config(state="disabled")
        self._render_dashboard()
        if hasattr(self, "_refresh_agents"):
            self._refresh_agents()

    # ----- onboarding helpers ------------------------------------------ #
    def _fam(self):
        return self._pick_font(["Inter", "Segoe UI", "Helvetica", "DejaVu Sans", "TkDefaultFont"])

    def _tip(self, widget, text):
        _Tip(widget, text)

    def goto_tab(self, name, focus=False):
        frame = self._tabs.get(name)
        if frame is not None:
            self._nb.select(frame)

    def open_docs(self):
        webbrowser.open("https://priorstates.com")

    def _memory_count(self):
        try:
            from ..memory.api import _bins_for_scope
            from ..core.store import MemoryStore
            total = 0
            for bp in _bins_for_scope(self.cfg, "all"):
                with MemoryStore(bp) as st:
                    total += st.n
            return total
        except Exception:
            return 0

    def _examples_present(self):
        try:
            from ..core import share
            return share.has_source(self.cfg, share.demo_label())
        except Exception:
            return False

    def _first_available_agent(self):
        """An agent CLI that's present and (preferably) wired, for the live demo."""
        present = self._present_keys(self.workspace)
        wired = self._wired_agents()
        order = ["claude", "codex", "gemini"]
        for k in order:
            if k in present and k in wired:
                return k
        for k in order:
            if k in present:
                return k
        return None

    def try_with_agent(self):
        key = self._first_available_agent()
        if not key:
            return self.set_status("No agent CLI found on PATH — install claude / codex / gemini first.")
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(STARTER_PROMPT)
        except Exception:
            pass
        self._launch_cli(self.workspace, {t[0]: t[2] for t in self._launch_targets()}[key])
        self.set_status(f"Starter prompt copied — paste it into {key.capitalize()} (just opened).")

    def load_examples(self):
        # The "examples" are the bundled demo workspace — same path new users get
        # from `priorstates workspace import --demo` (dogfoods the share feature).
        from ..core import share
        try:
            res = share.import_workspace(self.cfg, share.packaged_demo())
            note = "Loaded the demo workspace: +%d memories" % res["memory_added"]
            note += (", +%d journal entries." % res["journal_added"]) if res["journal_added"] \
                else " (open a project folder to also load the demo journal)."
            self.set_status(note)
        except Exception as e:
            self.set_status(f"error: {e}")
        self.refresh_all()

    def remove_examples(self):
        from ..core import share
        try:
            r = share.remove_source(self.cfg, share.demo_label())
            self.set_status("Removed demo data (%d memories, %d journal entries)."
                            % (r["memory_removed"], r["journal_removed"]))
        except Exception as e:
            self.set_status(f"error: {e}")
        self.refresh_all()


    # ----- agents ------------------------------------------------------ #
    def _tab_agents(self, nb):
        ttk = self.ttk
        f = ttk.Frame(nb)
        nb.add(f, text="Agents")
        self._tabs["agents"] = f
        self.agents_text = self.tk.Text(f, height=10, wrap="word", relief="flat")
        self.agents_text.pack(fill="both", expand=True, padx=10, pady=10)
        btns = ttk.Frame(f); btns.pack(fill="x", padx=10, pady=(0, 10))
        bi = ttk.Button(btns, text="Install (wire enabled agents)", command=self.agents_install, style="Accent.TButton")
        bi.pack(side="left")
        self._tip(bi, "Register PriorStates' MCP server + pinned context block into your agents\n"
                      "(Claude / Codex / Gemini), so they can use its memory + journal tools.")
        bu = ttk.Button(btns, text="Uninstall", command=self.agents_uninstall); bu.pack(side="left", padx=6)
        self._tip(bu, "Remove PriorStates' MCP server + pinned block from your agents.")
        ttk.Button(btns, text="Refresh", command=self._refresh_agents).pack(side="left")

    def _refresh_agents(self):
        from ..agents import status as ag_status
        lines = ["PriorStates exposes the same memory/journal/mdlab tools to each agent over MCP.",
                 "Enabled agents get MCP registered + the pinned-memory block in their context file.", ""]
        for s in ag_status(self.cfg):
            lines.append(f"  {s['agent']:<8} installed={s['installed']}  enabled={s['enabled']}  "
                         f"mcp_registered={s['mcp_registered']}\n           {s['config']}")
        self.agents_text.config(state="normal")
        self.agents_text.delete("1.0", "end")
        self.agents_text.insert("1.0", "\n".join(lines))
        self.agents_text.config(state="disabled")

    def agents_install(self):
        from ..agents.install import install
        self.set_status("wiring agents…")
        self.run_bg(lambda: install(self.cfg), lambda r: (self.set_status("agents wired"), self._refresh_agents()))

    def agents_uninstall(self):
        from ..agents.install import uninstall
        self.run_bg(lambda: uninstall(self.cfg), lambda r: (self.set_status("agents unwired"), self._refresh_agents()))


    # ----- cockpit / model -------------------------------------------- #
    def open_cockpit(self):
        # One cockpit PER workspace. Remote workspaces run via `connect` (the
        # cockpit runs on the server); local ones run a local cockpit. Each on
        # its own port so they don't collide.
        from ..cli import _free_local_port
        cks = getattr(self, "_cockpits", None)
        if cks is None:
            cks = self._cockpits = {}
        key = self._ws_key(self.workspace)

        if self._ws_is_remote(self.workspace):
            e = cks.get(key)
            if e and e["proc"].poll() is None:
                self.set_status(f"already connected to {self.workspace['host']} (see your browser)")
                if self._ws_is_remote(self.workspace):
                    self.remote_status_var.set("connected — cockpit open in your browser")
                return
            p = self._launch_connect(self.workspace)
            if p:
                cks[key] = {"proc": p, "port": None, "allow_open": False}
                self.set_status(f"connecting to {self.workspace['host']} … "
                                f"(terminal opened; browser opens when ready)")
                self.remote_status_var.set("connecting…")
            return

        want_open = bool(getattr(self, "allow_open", None) and self.allow_open.get())
        entry = cks.get(key)
        if entry and entry["proc"].poll() is None:
            if entry["allow_open"] == want_open:
                webbrowser.open(f"http://127.0.0.1:{entry['port']}/")
                self.set_status(f"cockpit for {Path(key).name} on :{entry['port']}")
                return
            entry["proc"].terminate()           # toggle changed → relaunch
            cks.pop(key, None)

        server = Path(__file__).resolve().parents[1] / "cockpit" / "server.js"
        port = _free_local_port(7700)
        env = dict(os.environ)
        env["PRIORSTATES_HOME"] = str(self.cfg.home)
        env.pop("PRIORSTATES_PROJECT_ROOT", None)
        if self.cfg.project_root:
            env["PRIORSTATES_PROJECT_ROOT"] = str(self.cfg.project_root)
        env["PS_PORT"] = str(port)
        env["PS_HOST"] = "127.0.0.1"
        env["PS_PYTHON"] = sys.executable
        env["PS_ALLOW_WRITE"] = "1"      # GUI is the trusted local control plane → enable cockpit capture
        env["PS_ALLOW_TERMINAL"] = "1"   # …and the embedded terminal (your own machine)
        if want_open:
            env["PS_ALLOW_OPEN"] = "1"
        try:
            proc = subprocess.Popen(["node", str(server)], env=env)
        except FileNotFoundError:
            self.set_status("node not found — install Node.js to use the cockpit")
            return
        cks[key] = {"proc": proc, "port": port, "allow_open": want_open}
        self.root.after(900, lambda p=port: webbrowser.open(f"http://127.0.0.1:{p}/"))
        extra = " (open-in-editor on)" if want_open else ""
        wsname = Path(key).name if self.workspace else key
        self.set_status(f"cockpit for {wsname} on :{port}{extra}")

    def reindex(self):
        from ..memory import api as mem
        self.set_status("reindexing…")
        self.run_bg(lambda: mem.reindex(_load(self._ws_local_path(self.workspace)), "all", verbose=False),
                    lambda r: self.set_status(f"reindexed: {r}"))

    def download_model(self):
        from ..cli import _download_model
        self.set_status("downloading model… (see console)")
        self.run_bg(_download_model, lambda r: (self.set_status("model step done"), self.refresh_all()))

    # Reinstall the latest PriorStates from GitHub (the pip-from-git path).
    REPO_URL = "git+https://github.com/zqin2012/priorstates.git"

    def update_software(self):
        from tkinter import messagebox
        if not messagebox.askyesno("Update PriorStates",
                                    "Reinstall the latest PriorStates from GitHub?\n\n"
                                    "You'll need to restart the app afterward to use the new version."):
            return
        in_venv = sys.prefix != sys.base_prefix          # pip --user is invalid inside a venv/pipx
        cmd = [sys.executable, "-m", "pip", "install", "--no-cache-dir", "--upgrade", "--force-reinstall"]
        if not in_venv:
            cmd.append("--user")
        cmd.append("priorstates @ " + self.REPO_URL)
        self.set_status("Updating PriorStates from GitHub… (see console)")

        def go():
            return subprocess.run(cmd, capture_output=True, text=True)

        def done(p):
            print(p.stdout or "", p.stderr or "")
            if getattr(p, "returncode", 1) == 0:
                self.set_status("Updated ✓  — restart PriorStates to use the new version.")
                try:
                    messagebox.showinfo("Update complete",
                                        "PriorStates was updated. Close and reopen the app to use the new version.")
                except Exception:
                    pass
            else:
                tail = (p.stderr or p.stdout or "").strip().splitlines()
                self.set_status("update failed: " + (tail[-1] if tail else "see console"))
        self.run_bg(go, done)

    def on_close(self):
        # stop every per-workspace cockpit
        for entry in getattr(self, "_cockpits", {}).values():
            try:
                if entry["proc"].poll() is None:
                    entry["proc"].terminate()
            except Exception:
                pass
        # close any remote connections (ssh tunnels) opened this session
        for p in getattr(self, "_connections", []):
            try:
                if p.poll() is None:
                    p.terminate()
            except Exception:
                pass
        self.root.destroy()


def main(project=None):
    try:
        import tkinter as tk
    except Exception:
        print("Tkinter is not available in this Python. Install python3-tk.", file=sys.stderr)
        sys.exit(1)
    if project is None and len(sys.argv) > 1:  # `priorstates-gui /path/to/project`
        project = sys.argv[1]
    root = tk.Tk()
    app = PriorStatesGUI(root, project=project)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
