# PriorStates — native install packages

Native packages so end users don't touch `pip`:

| OS | Artifact | Build on | Build command |
|---|---|---|---|
| **Ubuntu / Debian** | `priorstates_<ver>_all.deb` | Linux (needs `dpkg-deb`) | `packaging/deb/build-deb.sh` |
| **macOS** | `PriorStates-<ver>.pkg` | macOS (needs `pkgbuild`) | `packaging/macos/build-pkg.sh` |
| **macOS (alt)** | Homebrew formula | macOS (needs `brew`) | `brew install --build-from-source packaging/macos/priorstates.rb` |
| **Windows** | `PriorStates-<ver>-Setup.exe` | Windows (needs Inno Setup 6) | `packaging\windows\build-installer.ps1` |
| **Windows (no toolchain)** | pip + shortcuts | Windows (needs Python) | `packaging\windows\install.ps1` |

The cross-platform [`install.sh`](../install.sh) (pip-based) remains available for
any OS with Python; on Windows use [`install.ps1`](windows/install.ps1).

---

## Ubuntu / Debian — `.deb`

```bash
packaging/deb/build-deb.sh            # → build/deb/priorstates_0.1.0_all.deb
sudo apt install ./build/deb/priorstates_0.1.0_all.deb     # resolves deps
# or:  sudo dpkg -i ...deb && sudo apt-get -f install
```

- **Architecture:** `all` (pure Python). Installs into the system
  `dist-packages`, so `priorstates`, `priorstates-gui`, and `python3 -m priorstates` all
  work with the system `python3`.
- **Depends:** `python3 (>= 3.10)`, `python3-numpy`.
  **Recommends:** `python3-tk` (GUI), `nodejs` (cockpit).
- Ships a desktop launcher (**PriorStates** in your app menu), an icon, and man
  pages. Build is **lintian-clean**.
- Memory, journal, mdlab and the cockpit work immediately. For agent (MCP)
  integration and semantic recall, also run:
  ```bash
  pip3 install --user mcp onnxruntime tokenizers
  ```
- **Uninstall:** `sudo apt remove priorstates`.

## macOS — `.pkg`

Run on a Mac (Xcode Command Line Tools provide `pkgbuild`):

```bash
packaging/macos/build-pkg.sh          # → build/macos/PriorStates-0.1.0.pkg
# optionally sign:
packaging/macos/build-pkg.sh --sign "Developer ID Installer: NAME (TEAMID)"
```

Then double-click the `.pkg` (or `sudo installer -pkg PriorStates-0.1.0.pkg -target /`).
It installs:

- `/usr/local/priorstates/venv` — a self-contained virtualenv (built by the
  package's postinstall using the Mac's `python3`; pulls PriorStates + numpy from
  PyPI, so a network connection is needed during install).
- `/usr/local/bin/priorstates` and `/usr/local/bin/priorstates-gui` — CLI wrappers.
- `/Applications/PriorStates.app` — double-click launcher for the desktop GUI.

Extras: `/usr/local/priorstates/venv/bin/pip install mcp onnxruntime tokenizers`.
The GUI needs a working Tk; the system `python3` Tk is limited — if the GUI
won't open, `brew install python-tk` or use python.org's Python.
**Unsigned** packages require right-click → *Open* the first time (or sign with
a Developer ID as above).

## macOS — Homebrew (no `.pkg`)

```bash
brew install --build-from-source ./packaging/macos/priorstates.rb   # this checkout
# or, once published to a tap / tag:
brew install --HEAD priorstates
```

Installs PriorStates into a Homebrew-managed virtualenv and links `priorstates` /
`priorstates-gui` onto your PATH. `brew uninstall priorstates` to remove.

## Windows — `.exe` (Inno Setup)

Build on Windows (needs Python 3.10+ and [Inno Setup 6](https://jrsoftware.org/isdl.php)):

```powershell
packaging\windows\build-installer.ps1     # → build\windows\PriorStates-0.1.0-Setup.exe
```

It builds the wheel, then compiles [`priorstates.iss`](windows/priorstates.iss) into a
per-user installer (no admin). Double-clicking the `.exe`:

- checks for Python 3.10+ on PATH (offers the download page if missing),
- pip-installs the bundled wheel into the user's Python and runs `priorstates init`,
- adds **PriorStates** (desktop GUI, launched via `PriorStates.vbs` → `pyw -m priorstates
  gui`, no console window) and **PriorStates Cockpit** to the Start Menu, plus an
  optional Desktop shortcut.

Node.js is optional (only the cockpit web UI needs it). Extras for MCP + semantic
recall: `py -3 -m pip install --user mcp onnxruntime tokenizers`.
**Uninstall** via *Apps & features* → PriorStates.

## Windows — no toolchain (`install.ps1`)

If you don't want to build an `.exe`, run the pip-based installer from a checkout:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\windows\install.ps1
# options: -Extras (onnx+mcp+pandas)  -Model (download embedder)  -Wire (agents)  -NoShortcuts
```

It installs PriorStates into your Python (prefers `pipx`, else `pip --user`), runs
`priorstates init`, and creates the same Start Menu + Desktop shortcuts. Needs
Python 3.10+ on PATH; `python3-tk`-equivalent is bundled with the python.org
installer, so the GUI works out of the box.

---

## After install (any package)

```bash
priorstates init               # ~/.priorstates + ./.priorstates for the current project
priorstates agents install     # wire Claude / Codex / Gemini (needs the `mcp` extra)
priorstates gui                # desktop control panel
priorstates cockpit            # web cockpit → http://127.0.0.1:7700
```

See [`docs/QUICKSTART.md`](../docs/QUICKSTART.md) for everyday use.
