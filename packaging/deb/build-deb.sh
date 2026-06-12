#!/usr/bin/env bash
# Build a Debian/Ubuntu .deb for the open-source PriorStates core with a
# desktop launcher (app-menu entry + icon) and CLI/GUI commands.
#
# The built wheel is unzipped into dist-packages — so the wheel's `.dist-info`
# (with entry_points.txt) ships too and plugins are discoverable via
# importlib.metadata. numpy is an apt dependency (python3-numpy); no pip /
# no network at install time.
#
#   packaging/deb/build-deb.sh           # → build/priorstates_<ver>_all.deb
#
# Requires: dpkg-deb, python3 (to build the wheel). No root.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
VER="$(grep -m1 '^version' "$REPO/pyproject.toml" | sed 's/.*"\(.*\)".*/\1/')"
PKG="priorstates"
ARCH=all
OUT="$REPO/build"
STAGE="$OUT/deb/${PKG}_${VER}_${ARCH}"
WH="$OUT/deb/wheels"

echo "==> building ${PKG} ${VER} (${ARCH})"
rm -rf "$STAGE" "$WH"; mkdir -p "$WH" \
  "$STAGE/DEBIAN" \
  "$STAGE/usr/lib/python3/dist-packages" \
  "$STAGE/usr/bin" \
  "$STAGE/usr/share/applications" \
  "$STAGE/usr/share/icons/hicolor/scalable/apps" \
  "$STAGE/usr/share/man/man1" \
  "$STAGE/usr/share/doc/$PKG"

# ---- payload: build the wheel, unzip into dist-packages (incl. .dist-info) --
echo "==> building wheel"
python3 -m pip wheel --no-deps -w "$WH" "$REPO" >/dev/null
DP="$STAGE/usr/lib/python3/dist-packages"
for whl in "$WH"/*.whl; do
  echo "    unpacking $(basename "$whl")"
  python3 - "$whl" "$DP" <<'PY'
import sys, zipfile
zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])
PY
done
# strip caches + drop RECORD (paths won't match the deb layout) to keep lintian quiet
find "$DP" \( -name '__pycache__' -o -name '*.pyc' -o -name '*.psmem' \) -prune -exec rm -rf {} + 2>/dev/null || true
find "$DP" -name 'RECORD' -path '*.dist-info/*' -delete 2>/dev/null || true

# ---- CLI + GUI launchers --------------------------------------------------
cat > "$STAGE/usr/bin/priorstates" <<'SH'
#!/bin/sh
exec /usr/bin/python3 -m priorstates "$@"
SH
cat > "$STAGE/usr/bin/priorstates-gui" <<'SH'
#!/bin/sh
exec /usr/bin/python3 -m priorstates gui "$@"
SH
chmod 0755 "$STAGE/usr/bin/priorstates" "$STAGE/usr/bin/priorstates-gui"

# ---- desktop launcher (app-menu entry) + icon -----------------------------
cat > "$STAGE/usr/share/applications/priorstates.desktop" <<'DESK'
[Desktop Entry]
Type=Application
Name=PriorStates
GenericName=AI memory & journal cockpit
Comment=Shared local memory, research journal, mdlab and the cockpit for your AI agents
Exec=priorstates-gui
Icon=priorstates
Terminal=false
Categories=Development;Utility;
Keywords=AI;memory;journal;claude;codex;gemini;copilot;cursor;mcp;
StartupNotify=true
DESK

cat > "$STAGE/usr/share/icons/hicolor/scalable/apps/priorstates.svg" <<'SVG'
<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">
  <rect width="128" height="128" rx="24" fill="#0d1117"/>
  <circle cx="64" cy="58" r="30" fill="none" stroke="#58a6ff" stroke-width="6"/>
  <circle cx="64" cy="58" r="12" fill="#3fb950"/>
  <line x1="86" y1="80" x2="104" y2="98" stroke="#58a6ff" stroke-width="8" stroke-linecap="round"/>
</svg>
SVG

# ---- man pages ------------------------------------------------------------
DATE_MAN="$(date +%Y-%m-%d)"
cat > "$STAGE/usr/share/man/man1/priorstates.1" <<MAN
.TH PRIORSTATES 1 "$DATE_MAN" "priorstates $VER" "User Commands"
.SH NAME
priorstates \- local AI memory, research journal, mdlab and cockpit
.SH SYNOPSIS
.B priorstates
.I command
.RI [ options ]
.SH DESCRIPTION
PriorStates gives AI agents (Claude Code, VSCode Copilot, Cursor, Codex,
Gemini, ...) a shared local memory, a research journal, runnable-Markdown
(mdlab) and a web cockpit \- all on this machine, no cloud calls.
Equivalent to \fBpython3 -m priorstates\fR.
.SH COMMANDS
.TP
.B init
Initialize the data dirs and wire every detected AI agent (use
\fB--no-wire\fR to skip wiring).
.TP
.B agents \fR{install,uninstall,status}\fR
Wire / unwire the MCP server and protocol block per agent.
.TP
.B memory / journal
Manage memories and journal entries from the CLI.
.TP
.B cockpit
Launch the local web cockpit.
.TP
.B gui
Launch the desktop control panel.
.TP
.B doctor
Report configuration and agent status.
.SH SEE ALSO
.BR priorstates-gui (1)
MAN
cat > "$STAGE/usr/share/man/man1/priorstates-gui.1" <<MAN
.TH PRIORSTATES-GUI 1 "$DATE_MAN" "priorstates $VER" "User Commands"
.SH NAME
priorstates-gui \- desktop control panel for PriorStates
.SH SYNOPSIS
.B priorstates-gui
.SH DESCRIPTION
Opens the control panel to manage memory, the journal, agent wiring and mdlab.
Equivalent to \fBpriorstates gui\fR. Requires python3-tk.
.SH SEE ALSO
.BR priorstates (1)
MAN
gzip -9n "$STAGE/usr/share/man/man1/priorstates.1" "$STAGE/usr/share/man/man1/priorstates-gui.1"

# ---- docs + copyright + changelog ----------------------------------------
cp "$REPO/README.md" "$STAGE/usr/share/doc/$PKG/README.md" 2>/dev/null || true
YEAR="$(date +%Y)"
cat > "$STAGE/usr/share/doc/$PKG/copyright" <<COPY
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: priorstates
Source: https://github.com/zqin2012/priorstates

Files: *
Copyright: $YEAR Zhendong Qin
License: Apache-2.0
 On Debian systems the full text is in /usr/share/common-licenses/Apache-2.0.
COPY
cat > "$STAGE/usr/share/doc/$PKG/changelog" <<CHANGELOG
$PKG ($VER) unstable; urgency=low

  * Open-source PriorStates core: shared local memory, research journal,
    mdlab, web cockpit, desktop GUI, and MCP wiring for AI agents.

 -- Zhendong Qin <service@priorstates.com>  $(date -R)
CHANGELOG
gzip -9n "$STAGE/usr/share/doc/$PKG/changelog"

# ---- control + maintainer scripts ----------------------------------------
INSTALLED_KB=$(du -sk "$STAGE/usr" | cut -f1)
cat > "$STAGE/DEBIAN/control" <<CTRL
Package: $PKG
Version: $VER
Architecture: $ARCH
Maintainer: Zhendong Qin <service@priorstates.com>
Section: utils
Priority: optional
Installed-Size: $INSTALLED_KB
Depends: python3 (>= 3.10), python3-numpy, python3-tk, python3-cryptography
Suggests: python3-pip
Conflicts: priorstates-hub
Homepage: https://github.com/zqin2012/priorstates
Description: PriorStates — shared AI memory, research journal & cockpit
 PriorStates gives AI agents (Claude Code, VSCode Copilot, Cursor, Codex,
 Gemini, ...) a shared local memory, a research journal, runnable-Markdown
 (mdlab) and a web cockpit, with a desktop control panel and a CLI. Install
 once: every detected agent is wired over MCP and uses the memory
 automatically. 100% local, Apache-2.0.
 .
 Installs a desktop launcher in your application menu. Agent (MCP)
 integration and semantic recall use extra pip packages (mcp, onnxruntime,
 tokenizers).
CTRL

cat > "$STAGE/DEBIAN/postinst" <<'POST'
#!/bin/sh
set -e
command -v py3compile >/dev/null 2>&1 && py3compile -p priorstates >/dev/null 2>&1 || true
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q /usr/share/applications >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t -q /usr/share/icons/hicolor >/dev/null 2>&1 || true
cat <<'MSG'

PriorStates installed.  Quick start (as your normal user, not root):
  python3 -m pip install --user mcp   # agent (MCP) tool support
  priorstates init               # wire every detected AI agent (once)
  priorstates doctor             # status — which agents are wired
  priorstates cockpit            # local web cockpit
  priorstates-gui                # desktop control panel

Find "PriorStates" in your application menu, too.
MSG
exit 0
POST

cat > "$STAGE/DEBIAN/prerm" <<'PRE'
#!/bin/sh
set -e
command -v py3clean >/dev/null 2>&1 && py3clean -p priorstates >/dev/null 2>&1 || true
exit 0
PRE

# ---- normalize perms + build --------------------------------------------
find "$STAGE" -type d -exec chmod 0755 {} +
find "$STAGE" -type f -exec chmod 0644 {} +
chmod 0755 "$STAGE/usr/bin/priorstates" "$STAGE/usr/bin/priorstates-gui" \
           "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/prerm"

DEB="$OUT/${PKG}_${VER}_${ARCH}.deb"
echo "==> dpkg-deb --build"
dpkg-deb --root-owner-group --build "$STAGE" "$DEB" >/dev/null
rm -rf "$WH"
echo "built: $DEB"
echo
echo "Install with:   sudo apt install $DEB"
