#!/usr/bin/env bash
# PriorStates installer. Installs the package, initializes data dirs, and wires
# the MCP server + pinned block into every detected AI agent (install-and-forget).
#
#   ./install.sh                     # install + wire agents + semantic recall (default)
#   ./install.sh --lite              # skip the onnx libs + 127MB model (hashing recall)
#   ./install.sh --extras            # everything incl. pandas/jupyter extras
#   ./install.sh --no-wire           # skip agent wiring
#
# Also works without a checkout (installs the released package from PyPI):
#   curl -fsSL https://priorstates.com/install.sh | sh
set -euo pipefail

# Detect whether we're running inside a checkout (./install.sh) or piped from
# curl (no source tree -> install from PyPI).
HERE="$(cd "$(dirname "$0")" 2>/dev/null && pwd || true)"
LOCAL_TREE=0
if [ -n "$HERE" ] && [ -f "$HERE/pyproject.toml" ] && \
   grep -q '^name = "priorstates"' "$HERE/pyproject.toml" 2>/dev/null; then
  LOCAL_TREE=1
  cd "$HERE"
fi

# Defaults: agents wired + MCP tools + semantic recall (install-and-forget).
# --lite drops the onnx inference libs and the 127MB model (hashing recall —
# everything still works, recall is just keyword-ish instead of by meaning).
EXTRAS=0; MODEL=1; WIRE=1; EXTRA_SPEC="[mcp,onnx]"
for a in "$@"; do
  case "$a" in
    --extras)   EXTRAS=1 ;;
    --lite|--no-model) MODEL=0; EXTRA_SPEC="[mcp]" ;;
    --model)    MODEL=1 ;;   # legacy no-op (model is the default now)
    --wire)     WIRE=1 ;;    # legacy no-op (wiring is the default now)
    --no-wire)  WIRE=0 ;;
    *) echo "unknown flag: $a"; exit 2 ;;
  esac
done
[ "$EXTRAS" = 1 ] && EXTRA_SPEC="[full]"

PY="${PYTHON:-python3}"
if [ "$LOCAL_TREE" = 1 ]; then
  SPEC=".$EXTRA_SPEC"
else
  # No source checkout (curl | sh): install the published package from PyPI.
  # Set PRIORSTATES_REPO to a git URL to install from a repo instead.
  if [ -n "${PRIORSTATES_REPO:-}" ]; then
    echo "==> no source checkout detected; installing from $PRIORSTATES_REPO"
    SPEC="priorstates$EXTRA_SPEC @ git+$PRIORSTATES_REPO"
    command -v git >/dev/null 2>&1 || { echo "ERROR: git is required (pip installs from the git repo)"; exit 1; }
  else
    echo "==> no source checkout detected; installing from PyPI"
    SPEC="priorstates$EXTRA_SPEC"
  fi
fi

# A pre-PEP621 setuptools silently builds an empty "UNKNOWN-0.0.0" wheel. Make
# sure the build front-end has a modern setuptools/wheel before we build.
echo "==> ensuring modern build tooling"
"$PY" -m pip install --user -q --upgrade pip setuptools wheel >/dev/null 2>&1 || \
  echo "    (could not upgrade build tooling; continuing)"

# Clean any prior bad install from an earlier attempt.
"$PY" -m pip uninstall -y UNKNOWN >/dev/null 2>&1 || true
"$PY" -m pip uninstall -y priorstates >/dev/null 2>&1 || true

echo "==> installing priorstates ($SPEC)"
if command -v pipx >/dev/null 2>&1; then
  if [ "$LOCAL_TREE" = 1 ]; then
    pipx install --force "$HERE"
  elif [ -n "${PRIORSTATES_REPO:-}" ]; then
    pipx install --force "git+$PRIORSTATES_REPO"
  else
    pipx install --force priorstates
  fi
  case "$EXTRA_SPEC" in
    "[full]")     pipx inject priorstates onnxruntime tokenizers mcp pyyaml pandas jupyter_client ipykernel || true ;;
    "[mcp,onnx]") pipx inject priorstates onnxruntime tokenizers mcp || true ;;
    *)            pipx inject priorstates mcp || true ;;
  esac
else
  echo "    (pipx not found; using pip --user)"
  # --no-cache-dir: source-tree/git versions are static, so pip would otherwise
  # reuse a stale cached wheel from a previous commit and "update" to old code.
  if ! "$PY" -m pip install --user --upgrade --force-reinstall --no-cache-dir "$SPEC"; then
    # onnxruntime has no wheel on some platform/Python combos — fall back to the
    # lite install (hashing recall) rather than failing the whole setup.
    case "$EXTRA_SPEC" in
      "[mcp]") exit 1 ;;
      *)
        echo "!! install with inference extras failed — retrying lite (hashing recall)"
        MODEL=0
        if [ "$LOCAL_TREE" = 1 ]; then LSPEC=".[mcp]"
        elif [ -n "${PRIORSTATES_REPO:-}" ]; then LSPEC="priorstates[mcp] @ git+$PRIORSTATES_REPO"
        else LSPEC="priorstates[mcp]"; fi
        "$PY" -m pip install --user --upgrade --force-reinstall --no-cache-dir "$LSPEC"
        ;;
    esac
  fi
fi

# Verify the build actually produced the priorstates package (not UNKNOWN).
if ! "$PY" -c "import priorstates" >/dev/null 2>&1; then
  echo "ERROR: priorstates did not import after install. Your Python's build tooling"
  echo "       is likely too old to read pyproject metadata (it produced an empty"
  echo "       'UNKNOWN' package). Upgrade and retry:"
  echo "         $PY -m pip install --user --upgrade pip setuptools wheel"
  echo "         $PY -m pip install --user --force-reinstall '$SPEC'"
  if [ "$LOCAL_TREE" = 1 ]; then
    echo "       Meanwhile you can run everything from this folder with:"
    echo "         cd $HERE && $PY -m priorstates <command>"
  fi
  exit 1
fi

# Run post-install steps via `python -m priorstates` so they work even if the
# console-script dir (e.g. ~/.local/bin) is not on PATH.
PM="$PY -m priorstates"

echo "==> priorstates init"
if [ "$WIRE" = 1 ]; then
  $PM init            # wires every detected agent by default
else
  $PM init --no-wire
fi

if [ "$MODEL" = 1 ]; then
  echo "==> downloading the semantic-recall model (~127 MB; skip with --lite)"
  # Non-fatal: on failure the hashing embedder keeps working; re-run
  # `priorstates init --download-model` any time.
  $PM init --download-model --no-wire || true
fi

# Desktop/app-menu launcher for the GUI (Linux: writes a .desktop + a Desktop
# icon; macOS/Windows: prints where the native installer creates the shortcut).
echo "==> creating GUI launcher"
$PM install-launcher --desktop || true

# PATH hint for the bare `priorstates` command.
SCRIPTDIR="$("$PY" -c 'import sysconfig,os; print(sysconfig.get_path("scripts", f"{os.name}_user"))' 2>/dev/null || true)"
echo
echo "Done. Use either form:"
echo "  $PY -m priorstates <command>     # always works"
if [ -n "$SCRIPTDIR" ] && [ -x "$SCRIPTDIR/priorstates" ]; then
  case ":$PATH:" in
    *":$SCRIPTDIR:"*) echo "  priorstates <command>            # on your PATH" ;;
    *) echo "  priorstates <command>            # after: export PATH=\"$SCRIPTDIR:\$PATH\"" ;;
  esac
fi
echo
echo "Try:"
echo "  $PY -m priorstates doctor"
echo "  $PY -m priorstates gui"
echo "  $PY -m priorstates cockpit       # → http://127.0.0.1:7700"
[ "$WIRE" = 1 ] || echo "  $PY -m priorstates agents install"
