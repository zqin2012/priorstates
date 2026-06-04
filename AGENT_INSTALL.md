# PriorStates — install instructions for an AI agent

> **You are an AI coding agent** (Claude, Codex, Gemini, or similar) and a human
> asked you to install **PriorStates**. Follow these steps in order using your
> shell/terminal tool. Everything here is **local to this machine** — no secrets,
> no cloud calls, nothing destructive. If any step fails, **stop and report the
> exact error** to the human instead of guessing.

## What you are installing

PriorStates gives AI agents a shared **local memory**, a durable **research
journal**, and a **web cockpit**, wired into Claude / Codex / Gemini over the MCP
protocol. It runs entirely on the user's machine, CPU-only.
Repository: <https://github.com/zqin2012/priorstates>

## Preconditions — check these first

| Need | Check (Linux/macOS) | Check (Windows) |
|---|---|---|
| Python ≥ 3.10 | `python3 --version` | `py --version` |
| pip | `python3 -m pip --version` | `py -m pip --version` |
| git *(Method B only)* | `git --version` | `git --version` |

If Python ≥ 3.10 is missing, tell the human and stop — don't silently install a
system Python. On the commands below, use `python3` on Linux/macOS and `py` on
Windows.

## Step 1 — install the package (choose ONE method)

### Method A — recommended, installs straight from the repo (no clone)

Linux / macOS:
```bash
python3 -m pip install --user --upgrade pip setuptools wheel
python3 -m pip install --user "priorstates @ git+https://github.com/zqin2012/priorstates.git"
```
Windows (PowerShell):
```powershell
py -m pip install --user --upgrade pip setuptools wheel
py -m pip install --user "priorstates @ git+https://github.com/zqin2012/priorstates.git"
```
Then continue to **Step 2**.

### Method B — clone the repo + run the installer (keeps the source; supports extras)

```bash
git clone https://github.com/zqin2012/priorstates.git
cd priorstates
./install.sh --wire          # Linux/macOS: install + init + wire agents
# Windows instead:
#   powershell -ExecutionPolicy Bypass -File packaging\windows\install.ps1 -Wire
# Optional "the works" (semantic model + all extras):
#   ./install.sh --extras --model --wire
```
Method B with `--wire` **already does Step 2** — skip straight to **Step 3**.

## Step 2 — initialize and wire the user's agents

```bash
python3 -m priorstates init             # create ~/.priorstates/ + project .priorstates/
python3 -m priorstates agents install   # register the MCP server + pinned block
```
`python3 -m priorstates …` always works regardless of PATH (Windows: `py -m priorstates …`).

## Step 3 — verify the install

```bash
python3 -m priorstates doctor
```
Expect config, backend, and agent status to report OK. If you see
`priorstates: command not found`, that's only a PATH issue — keep using
`python3 -m priorstates …` and the install is still fine.

## Step 4 — report back to the human

Tell them, concisely:
1. PriorStates is installed and `doctor` passed (paste the key lines).
2. MCP is wired for their agents — **they must restart their agent**
   (Claude / Codex / Gemini) so it loads the new MCP server.
3. Next things they can run:
   ```bash
   python3 -m priorstates cockpit    # → http://127.0.0.1:7700
   python3 -m priorstates gui
   ```

## Notes

- **Idempotent** — safe to re-run; it force-reinstalls and re-wires cleanly.
- **Optional semantic recall** (≈127 MB model download):
  `python3 -m priorstates init --download-model`. Not required — a built-in
  hashing embedder works out of the box.
- **Optional extras** (onnx, mcp, pandas, jupyter): Method A → install
  `"priorstates[full] @ git+…"`; Method B → `./install.sh --extras`.

## Troubleshooting

- **`import priorstates` fails / wheel named `UNKNOWN-0.0.0`** → the Python build
  tooling is too old to read `pyproject` metadata. Fix and retry:
  `python3 -m pip install --user --upgrade pip setuptools wheel`, then reinstall.
- **`priorstates: command not found`** → use `python3 -m priorstates …`, or add
  the user scripts dir (e.g. `~/.local/bin`, or the path `pip` prints) to `PATH`.
- **Anything else** → stop and show the human the exact command and error output.
