#!/usr/bin/env bash
# Build a Debian/Ubuntu .deb for PriorStates.
#
# Pure-Python (Architecture: all). Installs the `priorstates` package into the
# system dist-packages so `python3 -m priorstates` / the `priorstates` command work
# with the system python3. Only numpy is a hard dependency (apt: python3-numpy);
# Tk (GUI) and Node (cockpit) are Recommends. The MCP server + semantic model
# need extra pip packages (printed by postinst).
#
#   packaging/deb/build-deb.sh           # → build/deb/priorstates_<ver>_all.deb
#
# Requires: dpkg-deb (and optionally lintian). No root needed.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
VERSION="$(grep -m1 '^version' "$REPO/pyproject.toml" | sed 's/.*"\(.*\)".*/\1/')"
ARCH=all
PKG="priorstates"
OUT="$REPO/build/deb"
STAGE="$OUT/${PKG}_${VERSION}_${ARCH}"

echo "==> building ${PKG} ${VERSION} (${ARCH})"
rm -rf "$STAGE"
mkdir -p "$STAGE/DEBIAN" \
         "$STAGE/usr/lib/python3/dist-packages" \
         "$STAGE/usr/bin" \
         "$STAGE/usr/share/applications" \
         "$STAGE/usr/share/icons/hicolor/scalable/apps" \
         "$STAGE/usr/share/man/man1" \
         "$STAGE/usr/share/doc/$PKG"

# ---- payload: the python package (no caches / indexes) --------------------
echo "==> staging package files"
cp -r "$REPO/priorstates" "$STAGE/usr/lib/python3/dist-packages/priorstates"
find "$STAGE/usr/lib/python3/dist-packages/priorstates" \
     \( -name '__pycache__' -o -name '*.pyc' -o -name '*.psmem' \) -prune -exec rm -rf {} + 2>/dev/null || true

# ---- launchers ------------------------------------------------------------
cat > "$STAGE/usr/bin/priorstates" <<'SH'
#!/bin/sh
exec /usr/bin/python3 -m priorstates "$@"
SH
cat > "$STAGE/usr/bin/priorstates-gui" <<'SH'
#!/bin/sh
exec /usr/bin/python3 -m priorstates gui "$@"
SH
chmod 0755 "$STAGE/usr/bin/priorstates" "$STAGE/usr/bin/priorstates-gui"

# ---- desktop entry + icon -------------------------------------------------
cat > "$STAGE/usr/share/applications/priorstates.desktop" <<'DESK'
[Desktop Entry]
Type=Application
Name=PriorStates
GenericName=AI memory & journal cockpit
Comment=Manage memory, research journal, agents and the web cockpit
Exec=priorstates-gui
Icon=priorstates
Terminal=false
Categories=Development;
Keywords=AI;memory;journal;claude;codex;gemini;mcp;antigravity;
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
.TH PRIORSTATES 1 "$DATE_MAN" "priorstates $VERSION" "User Commands"
.SH NAME
priorstates \- local memory, research journal, mdlab and cockpit for AI agents
.SH SYNOPSIS
.B priorstates
.I command
.RI [ options ]
.SH DESCRIPTION
PriorStates gives Claude, Codex and Gemini a shared local memory, a durable
research journal, runnable-Markdown (mdlab) and a web cockpit, all on your
machine. Equivalent to running \fBpython3 -m priorstates\fR.
.SH COMMANDS
.TP
.B init
Create ~/.priorstates and the project's ./.priorstates scopes.
.TP
.B memory
Add, search, list, pin or delete memories.
.TP
.B journal
Add, search or regenerate the research journal.
.TP
.B mdlab run \fIFILE\fR
Execute runnable blocks in a Markdown file.
.TP
.B agents \fR{install,uninstall,status}\fR
Wire the MCP server and pinned block into Claude / Codex / Gemini.
.TP
.B cockpit
Launch the web cockpit (default http://127.0.0.1:7700).
.TP
.B gui
Launch the desktop control panel.
.TP
.B doctor
Report configuration, embedder backend and agent status.
.SH FILES
.TP
.B ~/.priorstates/
Global config, memory and the embedding model.
.TP
.B <project>/.priorstates/
Project memory and journal.
.SH SEE ALSO
.BR priorstates-gui (1)
MAN

cat > "$STAGE/usr/share/man/man1/priorstates-gui.1" <<MAN
.TH PRIORSTATES-GUI 1 "$DATE_MAN" "priorstates $VERSION" "User Commands"
.SH NAME
priorstates-gui \- desktop control panel for PriorStates
.SH SYNOPSIS
.B priorstates-gui
.SH DESCRIPTION
Opens the Tkinter control panel to manage memory, the research journal,
agent wiring, mdlab files and the cockpit. Equivalent to \fBpriorstates gui\fR.
Requires python3-tk.
.SH SEE ALSO
.BR priorstates (1)
MAN
gzip -9n "$STAGE/usr/share/man/man1/priorstates.1" "$STAGE/usr/share/man/man1/priorstates-gui.1"

# ---- docs -----------------------------------------------------------------
cp "$REPO/README.md" "$STAGE/usr/share/doc/$PKG/README.md"
# ship the full guide set
[ -d "$REPO/docs" ] && cp "$REPO"/docs/*.md "$STAGE/usr/share/doc/$PKG/" 2>/dev/null || true

YEAR="$(date +%Y)"
cat > "$STAGE/usr/share/doc/$PKG/copyright" <<COPY
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: priorstates
Source: https://github.com/priorstates/priorstates

Files: *
Copyright: $YEAR PriorStates contributors
License: Apache-2.0
 Licensed under the Apache License, Version 2.0 (the "License"); you may not
 use this software except in compliance with the License.
 .
 On Debian systems, the full text of the Apache 2.0 license can be found in
 /usr/share/common-licenses/Apache-2.0.
COPY

# Native package → changelog must be named "changelog.gz" (no Debian revision).
cat > "$STAGE/usr/share/doc/$PKG/changelog" <<CHANGELOG
$PKG ($VERSION) unstable; urgency=low

  * PriorStates $VERSION: memory + journal + mdlab + cockpit + desktop GUI,
    with Claude/Codex/Gemini MCP wiring.

 -- PriorStates contributors <priorstates@example.com>  $(date -R)
CHANGELOG
gzip -9n "$STAGE/usr/share/doc/$PKG/changelog"

# ---- control + maintainer scripts ----------------------------------------
INSTALLED_KB=$(du -sk "$STAGE/usr" | cut -f1)
cat > "$STAGE/DEBIAN/control" <<CTRL
Package: $PKG
Version: $VERSION
Architecture: $ARCH
Maintainer: PriorStates contributors <priorstates@example.com>
Section: utils
Priority: optional
Installed-Size: $INSTALLED_KB
Depends: python3 (>= 3.10), python3-numpy
Recommends: python3-tk, nodejs
Suggests: python3-pip
Homepage: https://github.com/priorstates/priorstates
Description: Shared memory and research journal for your AI agents
 PriorStates gives Claude, Codex and Gemini a shared local memory, a durable
 research journal, runnable-Markdown (mdlab), and a web cockpit - all on your
 own machine, with a desktop control panel (priorstates-gui) and a CLI.
 .
 Memory, journal, mdlab and the cockpit work out of the box. The MCP server
 (agent integration) and semantic embeddings need extra Python packages:
 run "pip3 install --user mcp onnxruntime tokenizers".
CTRL

cat > "$STAGE/DEBIAN/postinst" <<'POST'
#!/bin/sh
set -e
if command -v py3compile >/dev/null 2>&1; then
    py3compile -p priorstates >/dev/null 2>&1 || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t -q /usr/share/icons/hicolor >/dev/null 2>&1 || true
fi
cat <<'MSG'

PriorStates installed.  Quick start:
  priorstates doctor            # status
  priorstates init              # set up ~/.priorstates and this project
  priorstates gui               # desktop control panel
  priorstates cockpit           # web cockpit  → http://127.0.0.1:7700
  priorstates agents install    # wire Claude / Codex / Gemini

For agent (MCP) integration and semantic recall, also run:
  pip3 install --user mcp onnxruntime tokenizers

MSG
exit 0
POST

cat > "$STAGE/DEBIAN/prerm" <<'PRE'
#!/bin/sh
set -e
if command -v py3clean >/dev/null 2>&1; then
    py3clean -p priorstates >/dev/null 2>&1 || true
fi
exit 0
PRE

# ---- normalize permissions (clear group-writable bits from repo umask) ----
find "$STAGE" -type d -exec chmod 0755 {} +
find "$STAGE" -type f -exec chmod 0644 {} +
chmod 0755 "$STAGE/usr/bin/priorstates" "$STAGE/usr/bin/priorstates-gui" \
           "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/prerm" \
           "$STAGE/usr/lib/python3/dist-packages/priorstates/cockpit/server.js"

# ---- build ----------------------------------------------------------------
DEB="$OUT/${PKG}_${VERSION}_${ARCH}.deb"
echo "==> dpkg-deb --build"
dpkg-deb --root-owner-group --build "$STAGE" "$DEB" >/dev/null
echo "built: $DEB"

if command -v lintian >/dev/null 2>&1; then
    echo "==> lintian (informational)"
    lintian --no-tag-display-limit "$DEB" || true
fi
echo
echo "Install with:   sudo apt install $DEB"
echo "          or:   sudo dpkg -i $DEB && sudo apt-get -f install"
