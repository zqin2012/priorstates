#!/usr/bin/env bash
# PriorStates — self-contained installer (Linux / macOS).
#
# Bundled in the download tarball next to wheels/. Installs the open-source
# core into a private venv and wires CLI + GUI launchers, so you never touch
# pip. Only numpy is fetched from PyPI (one-time network), unless you bundled
# it too. By default it then wires every detected AI agent (install-and-forget).
#
#   ./install.sh                # install / upgrade + wire detected agents
#   ./install.sh --no-wire      # install but skip agent wiring
#   ./install.sh --uninstall    # remove
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
WHEELS="$HERE/wheels"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/priorstates"
VENV="$DATA/venv"
BIN="$HOME/.local/bin"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICONS="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"

WIRE=1
for a in "$@"; do
  case "$a" in
    --no-wire) WIRE=0 ;;
    --uninstall)
      rm -rf "$VENV" "$DATA"
      rm -f "$BIN/priorstates" "$BIN/priorstates-gui" \
            "$APPS/priorstates.desktop" "$ICONS/priorstates.svg"
      echo "PriorStates removed. (Your memory in ~/.priorstates was left intact.)"
      exit 0 ;;
    *) echo "unknown flag: $a"; exit 2 ;;
  esac
done

# ---- find a suitable python (3.10+) ---------------------------------------
PY=""
for c in python3 python3.13 python3.12 python3.11 python3.10; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys;exit(0 if sys.version_info>=(3,10) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.10+ is required but was not found."
  echo "  • Ubuntu/Debian:  sudo apt install python3 python3-venv python3-tk"
  echo "  • macOS:          brew install python-tk   (or python.org's installer)"
  exit 1
fi
echo "==> using $($PY -V) at $(command -v "$PY")"

# ---- create the venv (fall back to pip --user if venv is unavailable) -----
mkdir -p "$DATA" "$BIN"
if "$PY" -m venv "$VENV" 2>/dev/null; then
  PIP="$VENV/bin/pip"; TARGET_BIN="$VENV/bin"
  "$VENV/bin/python" -m pip install -q --upgrade pip >/dev/null 2>&1 || true
else
  echo "!! python venv unavailable (install python3-venv); falling back to pip --user"
  PIP="$PY -m pip"; TARGET_BIN="$HOME/.local/bin"
fi

# ---- install the bundled wheel (numpy + mcp from PyPI) ---------------------
# The [mcp] extra is what lets agents reach the tools — without it the install
# is not "install-and-forget", so it ships by default.
echo "==> installing PriorStates (from bundled wheels)"
# shellcheck disable=SC2086
$PIP install -q --upgrade --find-links "$WHEELS" "priorstates[mcp]"

# ---- launchers in ~/.local/bin --------------------------------------------
cat > "$BIN/priorstates" <<SH
#!/bin/sh
exec "$TARGET_BIN/priorstates" "\$@"
SH
cat > "$BIN/priorstates-gui" <<SH
#!/bin/sh
exec "$TARGET_BIN/priorstates" gui "\$@"
SH
chmod 0755 "$BIN/priorstates" "$BIN/priorstates-gui"

# ---- desktop entry + icon (Linux) -----------------------------------------
if [ "$(uname)" = "Linux" ]; then
  mkdir -p "$APPS" "$ICONS"
  cat > "$ICONS/priorstates.svg" <<'SVG'
<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">
  <rect width="128" height="128" rx="24" fill="#0d1117"/>
  <circle cx="64" cy="58" r="30" fill="none" stroke="#58a6ff" stroke-width="6"/>
  <circle cx="64" cy="58" r="12" fill="#3fb950"/>
  <line x1="86" y1="80" x2="104" y2="98" stroke="#58a6ff" stroke-width="8" stroke-linecap="round"/>
</svg>
SVG
  cat > "$APPS/priorstates.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=PriorStates
GenericName=AI memory & journal cockpit
Comment=Shared local memory, research journal, mdlab and the cockpit for your AI agents
Exec=$BIN/priorstates-gui
Icon=priorstates
Terminal=false
Categories=Development;
Keywords=AI;memory;journal;claude;codex;gemini;copilot;cursor;mcp;
DESK
  command -v update-desktop-database >/dev/null 2>&1 && \
    update-desktop-database -q "$APPS" >/dev/null 2>&1 || true
fi

case ":$PATH:" in *":$BIN:"*) ;; *)
  echo "note: add $BIN to your PATH (e.g. echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc)";;
esac

# ---- init + wire detected agents (install-and-forget) ----------------------
if [ "$WIRE" = 1 ]; then
  echo "==> initializing + wiring detected AI agents"
  "$TARGET_BIN/priorstates" init || true
else
  echo "==> initializing (agent wiring skipped: --no-wire)"
  "$TARGET_BIN/priorstates" init --no-wire || true
fi

cat <<MSG

PriorStates installed.  Next:
  priorstates doctor              # status — which agents are wired
  priorstates cockpit             # local web cockpit → http://127.0.0.1:7700
  priorstates-gui                 # desktop control panel

Restart your agents (Claude Code, Copilot, Cursor, Codex, Gemini, …) to load
the memory + journal tools.
MSG
