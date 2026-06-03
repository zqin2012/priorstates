#!/usr/bin/env bash
# PriorStates installer. Installs the package, initializes data dirs, and (with
# --wire) registers the MCP server + pinned block into your AI agents.
#
#   ./install.sh                     # install + `priorstates init`
#   ./install.sh --extras            # also install onnx + mcp + pandas extras
#   ./install.sh --model             # also download the semantic embedding model
#   ./install.sh --wire              # also run `priorstates agents install`
#   ./install.sh --extras --model --wire   # the works
set -euo pipefail
cd "$(dirname "$0")"
HERE="$(pwd)"

EXTRAS=0; MODEL=0; WIRE=0
for a in "$@"; do
  case "$a" in
    --extras) EXTRAS=1 ;;
    --model)  MODEL=1 ;;
    --wire)   WIRE=1 ;;
    *) echo "unknown flag: $a"; exit 2 ;;
  esac
done

PY="${PYTHON:-python3}"
SPEC="."
[ "$EXTRAS" = 1 ] && SPEC=".[full]"

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
  pipx install --force "$HERE"
  [ "$EXTRAS" = 1 ] && pipx inject priorstates onnxruntime tokenizers mcp pyyaml pandas jupyter_client ipykernel || true
else
  echo "    (pipx not found; using pip --user)"
  "$PY" -m pip install --user --upgrade --force-reinstall "$SPEC"
fi

# Verify the build actually produced the priorstates package (not UNKNOWN).
if ! "$PY" -c "import priorstates" >/dev/null 2>&1; then
  echo "ERROR: priorstates did not import after install. Your Python's build tooling"
  echo "       is likely too old to read pyproject metadata (it produced an empty"
  echo "       'UNKNOWN' package). Upgrade and retry:"
  echo "         $PY -m pip install --user --upgrade pip setuptools wheel"
  echo "         $PY -m pip install --user --force-reinstall '$SPEC'"
  echo "       Meanwhile you can run everything from this folder with:"
  echo "         cd $HERE && $PY -m priorstates <command>"
  exit 1
fi

# Run post-install steps via `python -m priorstates` so they work even if the
# console-script dir (e.g. ~/.local/bin) is not on PATH.
PM="$PY -m priorstates"

echo "==> priorstates init"
$PM init

if [ "$MODEL" = 1 ]; then
  echo "==> downloading embedding model"
  $PM init --download-model
fi

if [ "$WIRE" = 1 ]; then
  echo "==> wiring agents"
  $PM agents install || true
fi

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
