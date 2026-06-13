#!/bin/sh
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
#
# POSIX sh — must run under dash (Ubuntu's /bin/sh), not just bash.
set -eu
# pipefail isn't POSIX; enable it only where the shell supports it.
(set -o pipefail) 2>/dev/null && set -o pipefail || true

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

# ---- find a suitable python (3.10+) ----------------------------------------
PY=""
for c in "${PYTHON:-python3}" python3 python3.13 python3.12 python3.11 python3.10; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys;exit(0 if sys.version_info>=(3,10) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
PROVISIONED=0
if [ -z "$PY" ]; then
  # No suitable Python — install a private copy ourselves (no admin needed) so
  # the user never has to. uv is a single static binary that drops a relocatable
  # CPython in seconds without touching the system Python. When we provision this
  # way we install into a dedicated venv (below), since pipx/system-pip wouldn't
  # see it.
  echo "==> no Python 3.10+ found — installing a private copy automatically (no admin needed)"
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  if ! command -v uv >/dev/null 2>&1; then
    if command -v curl >/dev/null 2>&1; then
      curl -fsSL https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 || true
    elif command -v wget >/dev/null 2>&1; then
      wget -qO- https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 || true
    fi
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  fi
  if command -v uv >/dev/null 2>&1; then
    uv python install 3.12 >/dev/null 2>&1 || true
    PY="$(uv python find 3.12 2>/dev/null || true)"
  fi
  if [ -z "$PY" ] || [ ! -x "$PY" ]; then
    echo "ERROR: could not auto-install Python (no network?). Install Python 3.10+ and re-run:"
    echo "  - macOS:  brew install python   (or python.org's installer)"
    echo "  - Linux:  sudo apt install python3 python3-venv   /   sudo dnf install python3.12"
    exit 1
  fi
  PROVISIONED=1
  echo "==> provisioned $("$PY" -V) via uv"
fi

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

# ---- install ----------------------------------------------------------------
if [ "$PROVISIONED" = 1 ]; then
  # We installed our own Python via uv → install into a dedicated venv (pipx and
  # system pip wouldn't use it). The venv bootstraps its own pip via ensurepip.
  VENV="${XDG_DATA_HOME:-$HOME/.local/share}/priorstates/venv"
  mkdir -p "$(dirname "$VENV")" "$HOME/.local/bin"
  "$PY" -m venv "$VENV"
  "$VENV/bin/python" -m pip install -q --upgrade pip >/dev/null 2>&1 || true
  echo "==> installing priorstates ($SPEC) into a private venv"
  if ! "$VENV/bin/python" -m pip install --upgrade --no-cache-dir "$SPEC"; then
    case "$EXTRA_SPEC" in
      "[mcp]") exit 1 ;;
      *) echo "!! install with inference extras failed — retrying lite (hashing recall)"
         MODEL=0
         if [ "$LOCAL_TREE" = 1 ]; then LSPEC=".[mcp]"
         elif [ -n "${PRIORSTATES_REPO:-}" ]; then LSPEC="priorstates[mcp] @ git+$PRIORSTATES_REPO"
         else LSPEC="priorstates[mcp]"; fi
         "$VENV/bin/python" -m pip install --upgrade --no-cache-dir "$LSPEC" ;;
    esac
  fi
  printf '#!/bin/sh\nexec "%s/bin/priorstates" "$@"\n' "$VENV" > "$HOME/.local/bin/priorstates"
  chmod 0755 "$HOME/.local/bin/priorstates"
  PM="$VENV/bin/priorstates"
else
# ---- pick the install method: pipx if present, else pip --user --------------
USE_PIPX=0
if command -v pipx >/dev/null 2>&1; then
  USE_PIPX=1
elif ! "$PY" -m pip --version >/dev/null 2>&1; then
  echo "ERROR: neither pipx nor pip is available for $PY."
  echo "  - Debian/Ubuntu:      sudo apt install pipx        (recommended)"
  echo "                        or: sudo apt install python3-pip python3-venv"
  echo "  - RHEL/Rocky/Alma 9:  sudo dnf install python3.12-pip   (pip for python3.12)"
  echo "  - Fedora:             sudo dnf install pipx        (or python3-pip)"
  echo "  - macOS (brew):       brew install pipx"
  echo "Then re-run this installer."
  exit 1
fi

# PEP 668: distro pythons (Ubuntu 23.04+/Debian 12+) refuse `pip --user` unless
# --break-system-packages is passed. --user installs stay in ~/.local, so this
# is safe; pipx (preferred above) sidesteps the issue entirely.
PIPFLAGS="--user"
STDLIB="$("$PY" -c 'import sysconfig; print(sysconfig.get_path("stdlib"))' 2>/dev/null || true)"
if [ -n "$STDLIB" ] && [ -f "$STDLIB/EXTERNALLY-MANAGED" ]; then
  PIPFLAGS="--user --break-system-packages"
fi

if [ "$USE_PIPX" = 0 ]; then
  # A pre-PEP621 setuptools silently builds an empty "UNKNOWN-0.0.0" wheel. Make
  # sure the build front-end has a modern setuptools/wheel before we build.
  echo "==> ensuring modern build tooling"
  # shellcheck disable=SC2086
  "$PY" -m pip install $PIPFLAGS -q --upgrade pip setuptools wheel >/dev/null 2>&1 || \
    echo "    (could not upgrade build tooling; continuing)"

  # Clean any prior bad install from an earlier attempt.
  # shellcheck disable=SC2086
  "$PY" -m pip uninstall $PIPFLAGS -y UNKNOWN >/dev/null 2>&1 || true
  # shellcheck disable=SC2086
  "$PY" -m pip uninstall $PIPFLAGS -y priorstates >/dev/null 2>&1 || true
fi

echo "==> installing priorstates ($SPEC)"
if [ "$USE_PIPX" = 1 ]; then
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
  pipx ensurepath >/dev/null 2>&1 || true
else
  echo "    (pipx not found; using pip $PIPFLAGS)"
  # --no-cache-dir: source-tree/git versions are static, so pip would otherwise
  # reuse a stale cached wheel from a previous commit and "update" to old code.
  # shellcheck disable=SC2086
  if ! "$PY" -m pip install $PIPFLAGS --upgrade --force-reinstall --no-cache-dir "$SPEC"; then
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
        # shellcheck disable=SC2086
        "$PY" -m pip install $PIPFLAGS --upgrade --force-reinstall --no-cache-dir "$LSPEC"
        ;;
    esac
  fi
fi

# ---- verify + pick how to run post-install steps ----------------------------
# pipx installs into its own venv: the system python can NOT `import priorstates`
# there, so verify (and run init etc.) via the installed entry point instead.
PM=""
if [ "$USE_PIPX" = 1 ]; then
  for cand in "$(command -v priorstates 2>/dev/null || true)" "$HOME/.local/bin/priorstates"; do
    if [ -n "$cand" ] && [ -x "$cand" ] && "$cand" --help >/dev/null 2>&1; then
      PM="$cand"; break
    fi
  done
  if [ -z "$PM" ]; then
    echo "ERROR: pipx reported success but the 'priorstates' command does not run."
    echo "       Check 'pipx list' and ensure ~/.local/bin is on your PATH"
    echo "       (run: pipx ensurepath), then retry."
    exit 1
  fi
else
  if "$PY" -c "import priorstates" >/dev/null 2>&1; then
    PM="$PY -m priorstates"
  else
    echo "ERROR: priorstates did not import after install. Your Python's build tooling"
    echo "       is likely too old to read pyproject metadata (it produced an empty"
    echo "       'UNKNOWN' package). Upgrade and retry:"
    echo "         $PY -m pip install $PIPFLAGS --upgrade pip setuptools wheel"
    echo "         $PY -m pip install $PIPFLAGS --force-reinstall '$SPEC'"
    if [ "$LOCAL_TREE" = 1 ]; then
      echo "       Meanwhile you can run everything from this folder with:"
      echo "         cd $HERE && $PY -m priorstates <command>"
    fi
    exit 1
  fi
fi
fi  # end PROVISIONED branch

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
if [ "$USE_PIPX" = 1 ]; then
  SCRIPTDIR="$(dirname "$PM")"
else
  SCRIPTDIR="$("$PY" -c 'import sysconfig,os; print(sysconfig.get_path("scripts", f"{os.name}_user"))' 2>/dev/null || true)"
fi
echo
echo "Done. Use either form:"
echo "  $PM <command>     # always works"
if [ -n "$SCRIPTDIR" ] && [ -x "$SCRIPTDIR/priorstates" ]; then
  case ":$PATH:" in
    *":$SCRIPTDIR:"*) echo "  priorstates <command>            # on your PATH" ;;
    *) echo "  priorstates <command>            # after: export PATH=\"$SCRIPTDIR:\$PATH\"" ;;
  esac
fi
echo
echo "Try:"
echo "  $PM doctor"
echo "  $PM gui"
echo "  $PM cockpit       # → http://127.0.0.1:7700"
[ "$WIRE" = 1 ] || echo "  $PM agents install"
