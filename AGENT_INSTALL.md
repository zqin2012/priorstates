# PriorStates -- install instructions for an AI agent

> **You are an AI coding agent** (Claude, Codex, Gemini, or similar) and a human
> asked you to install **PriorStates**. Follow these steps in order using your
> shell/terminal tool. Everything here is **local to this machine** -- no secrets,
> no cloud calls, nothing destructive. If any step fails, **stop and report the
> exact error** to the human instead of guessing.

## What you are installing

PriorStates gives AI agents a shared **local memory**, a durable **research
journal**, and a **web cockpit**, wired into Claude / Codex / Gemini over the MCP
protocol. It runs entirely on the user's machine, CPU-only.
Repository: <https://github.com/zqin2012/priorstates>

## Preconditions -- check these first

| Need | Check (Linux/macOS) | Check (Windows) |
|---|---|---|
| Python >= 3.10 | `python3 --version` | `py --version` |
| pip | `python3 -m pip --version` | `py -m pip --version` |
| git *(Method B only)* | `git --version` | `git --version` |

If Python >= 3.10 is missing, tell the human and stop -- don't silently install a
system Python. On the commands below, use `python3` on Linux/macOS and `py` on
Windows.

## Step 1 -- install the package (choose ONE method)

### Method A -- recommended, installs straight from the repo (no clone)

Linux / macOS:
```bash
python3 -m pip install --user --upgrade pip setuptools wheel
python3 -m pip install --user --no-cache-dir "priorstates @ git+https://github.com/zqin2012/priorstates.git"
```
Windows (PowerShell):
```powershell
py -m pip install --user --upgrade pip setuptools wheel
py -m pip install --user --no-cache-dir "priorstates @ git+https://github.com/zqin2012/priorstates.git"
```
`--no-cache-dir` matters: the package version is static (`0.1.0`), so without it
pip can reuse a **stale cached wheel** from an earlier commit and silently install
old code. To **update** an existing install, add `--force-reinstall`:
```bash
python3 -m pip install --user --no-cache-dir --force-reinstall "priorstates @ git+https://github.com/zqin2012/priorstates.git"
```
Then continue to **Step 2**.

### Method B -- clone the repo + run the installer (keeps the source; supports extras)

```bash
git clone https://github.com/zqin2012/priorstates.git
cd priorstates
./install.sh --wire          # Linux/macOS: install + init + wire agents
# Windows instead:
#   powershell -ExecutionPolicy Bypass -File packaging\windows\install.ps1 -Wire
# Optional "the works" (semantic model + all extras):
#   ./install.sh --extras --model --wire
```
Method B with `--wire` **already does Steps 2 and 4** -- skip to **Step 3**.

## Step 2 -- initialize and wire the user's agents

```bash
python3 -m priorstates init             # create ~/.priorstates/ + project .priorstates/
python3 -m priorstates agents install   # register the MCP server + pinned block
```
`python3 -m priorstates ...` always works regardless of PATH (Windows: `py -m priorstates ...`).

## Step 3 -- verify the install

```bash
python3 -m priorstates doctor
```
Expect config, backend, and agent status to report OK. If you see
`priorstates: command not found`, that's only a PATH issue -- keep using
`python3 -m priorstates ...` and the install is still fine.

## Step 4 -- create the desktop launcher (so the user can click to open the GUI)

Linux / macOS:
```bash
python3 -m priorstates install-launcher --desktop
```
Windows (PowerShell):
```powershell
py -m priorstates install-launcher --desktop
```
- **Linux:** creates a **PriorStates icon on the Desktop** *and* an entry in the
  application menu. The command prints the exact paths it wrote.
- **Windows:** creates a **PriorStates shortcut in the Start menu and on the
  Desktop** (runs `pythonw -m priorstates gui`, no console window). Works after a
  plain pip install -- no native installer needed. Prints the shortcut paths.
- **macOS:** the clickable app icon comes from the native installer (`.pkg` /
  `brew install` -> *PriorStates.app*). After a bare pip install there is no icon;
  launch with `python3 -m priorstates gui`. Running the command just prints this
  guidance there; that's expected, not an error.

## Step 5 -- report back to the human

Tell them, concisely:
1. PriorStates is installed and `doctor` passed (paste the key lines).
2. MCP is wired for their agents -- **they must restart their agent**
   (Claude / Codex / Gemini) so it loads the new MCP server.
3. **How to open the GUI:**
   - **Linux:** *"Double-click the **PriorStates** icon on your Desktop (or find
     PriorStates in your application menu) to start the GUI."* If it doesn't
     appear right away, they may need to log out/in once.
   - **Windows:** *"Open **PriorStates** from the Start menu (or the Desktop
     shortcut) to start the GUI."*
   - **macOS (native installer):** *"Open **PriorStates** from Launchpad."*
     After a bare pip install with no icon: *"Start it with `priorstates gui`."*
4. They can also open the web cockpit any time (the cockpit -- and only the
   cockpit -- needs **Node.js**; memory, journal, the CLI and the GUI all work
   without it):
   ```bash
   python3 -m priorstates cockpit    # -> http://127.0.0.1:7700
   ```

## Notes

- **Node.js is optional.** It is needed *only* for the web cockpit. The core --
  memory, journal, MCP server, CLI, and the desktop GUI -- is pure Python and
  needs no Node. Don't install Node unless the user wants the cockpit; if it's
  missing, `priorstates cockpit` says so and everything else keeps working.
- **Idempotent** -- safe to re-run; it force-reinstalls and re-wires cleanly.
- **Optional semantic recall** (~127 MB model download):
  `python3 -m priorstates init --download-model`. Not required -- a built-in
  hashing embedder works out of the box.
- **Optional extras** (onnx, mcp, pandas, jupyter): Method A -> install
  `"priorstates[full] @ git+..."`; Method B -> `./install.sh --extras`.

## Troubleshooting

- **`import priorstates` fails / wheel named `UNKNOWN-0.0.0`** -> the Python build
  tooling is too old to read `pyproject` metadata. Fix and retry:
  `python3 -m pip install --user --upgrade pip setuptools wheel`, then reinstall.
- **`priorstates: command not found`** -> use `python3 -m priorstates ...`, or add
  the user scripts dir (e.g. `~/.local/bin`, or the path `pip` prints) to `PATH`.
- **Anything else** -> stop and show the human the exact command and error output.
