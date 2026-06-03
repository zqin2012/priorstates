#!/usr/bin/env bash
# Build a macOS installer package (PriorStates-<ver>.pkg).
#
# MUST run on macOS (uses pkgbuild/productbuild from Xcode Command Line Tools).
# Produces a self-contained install:
#   /usr/local/priorstates/venv        a virtualenv (built by the postinstall script)
#   /usr/local/bin/priorstates         CLI wrapper
#   /usr/local/bin/priorstates-gui     GUI wrapper
#   /Applications/PriorStates.app      double-click launcher for the desktop GUI
#
# The postinstall builds the venv with the target machine's python3 and installs
# PriorStates + numpy from PyPI (network needed at install time).
#
#   packaging/macos/build-pkg.sh             # → build/macos/PriorStates-<ver>.pkg
#   packaging/macos/build-pkg.sh --sign "Developer ID Installer: NAME (TEAMID)"
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
VERSION="$(grep -m1 '^version' "$REPO/pyproject.toml" | sed 's/.*"\(.*\)".*/\1/')"
IDENT="org.priorstates"
PREFIX="/usr/local/priorstates"
OUT="$REPO/build/macos"
PAYLOAD="$OUT/payload"
SCRIPTS="$OUT/scripts"
SIGN=""
[ "${1:-}" = "--sign" ] && SIGN="${2:-}"

if ! command -v pkgbuild >/dev/null 2>&1; then
  echo "ERROR: pkgbuild not found. This script must run on macOS with the Xcode"
  echo "       Command Line Tools installed (xcode-select --install)."
  echo "       On Linux, build the Ubuntu .deb instead, or use the Homebrew formula"
  echo "       (packaging/macos/priorstates.rb)."
  exit 1
fi

echo "==> staging payload for PriorStates $VERSION"
rm -rf "$OUT"
mkdir -p "$PAYLOAD$PREFIX/src" "$PAYLOAD/usr/local/bin" \
         "$PAYLOAD/Applications/PriorStates.app/Contents/MacOS" \
         "$PAYLOAD/Applications/PriorStates.app/Contents/Resources" \
         "$SCRIPTS"

# project source (the postinstall pip-installs this into the venv)
for item in pyproject.toml README.md priorstates docs; do
  [ -e "$REPO/$item" ] && cp -R "$REPO/$item" "$PAYLOAD$PREFIX/src/"
done
find "$PAYLOAD$PREFIX/src" \( -name '__pycache__' -o -name '*.pyc' -o -name '*.psmem' \) \
     -prune -exec rm -rf {} + 2>/dev/null || true

# CLI wrappers
cat > "$PAYLOAD/usr/local/bin/priorstates" <<SH
#!/bin/sh
exec $PREFIX/venv/bin/python -m priorstates "\$@"
SH
cat > "$PAYLOAD/usr/local/bin/priorstates-gui" <<SH
#!/bin/sh
exec $PREFIX/venv/bin/python -m priorstates gui "\$@"
SH
chmod 0755 "$PAYLOAD/usr/local/bin/priorstates" "$PAYLOAD/usr/local/bin/priorstates-gui"

# .app launcher for the desktop GUI
cat > "$PAYLOAD/Applications/PriorStates.app/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>PriorStates</string>
  <key>CFBundleDisplayName</key><string>PriorStates</string>
  <key>CFBundleIdentifier</key><string>$IDENT.app</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>PriorStates</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
</dict></plist>
PLIST
cat > "$PAYLOAD/Applications/PriorStates.app/Contents/MacOS/PriorStates" <<SH
#!/bin/sh
exec /usr/local/bin/priorstates gui
SH
chmod 0755 "$PAYLOAD/Applications/PriorStates.app/Contents/MacOS/PriorStates"

# postinstall: build venv + install PriorStates (+ numpy) with the target's python3
cat > "$SCRIPTS/postinstall" <<POST
#!/bin/sh
set -e
PREFIX="$PREFIX"
PY="\$(command -v python3 || echo /usr/bin/python3)"
echo "PriorStates: creating virtualenv with \$PY"
"\$PY" -m venv "\$PREFIX/venv"
"\$PREFIX/venv/bin/python" -m pip install --upgrade pip wheel >/dev/null 2>&1 || true
# install the app + numpy; extras (mcp/onnx/...) are optional and added later
if ! "\$PREFIX/venv/bin/python" -m pip install "\$PREFIX/src"; then
  "\$PREFIX/venv/bin/python" -m pip install numpy && \\
  "\$PREFIX/venv/bin/python" -m pip install --no-build-isolation "\$PREFIX/src"
fi
echo "PriorStates installed. Open /Applications/PriorStates.app or run: priorstates doctor"
echo "For agent (MCP) + semantic recall: /usr/local/priorstates/venv/bin/pip install mcp onnxruntime tokenizers"
exit 0
POST
chmod 0755 "$SCRIPTS/postinstall"

# ---- build ----------------------------------------------------------------
mkdir -p "$OUT"
COMPONENT="$OUT/PriorStates-component.pkg"
FINAL="$OUT/PriorStates-$VERSION.pkg"

echo "==> pkgbuild"
pkgbuild --root "$PAYLOAD" --scripts "$SCRIPTS" \
         --identifier "$IDENT" --version "$VERSION" \
         --install-location "/" "$COMPONENT"

echo "==> productbuild"
PB_ARGS=(--identifier "$IDENT.installer" --version "$VERSION" --package "$COMPONENT")
[ -n "$SIGN" ] && PB_ARGS+=(--sign "$SIGN")
productbuild "${PB_ARGS[@]}" "$FINAL"

rm -f "$COMPONENT"
echo
echo "built: $FINAL"
echo "Install: double-click it, or:  sudo installer -pkg \"$FINAL\" -target /"
[ -z "$SIGN" ] && echo "Note: unsigned — users right-click → Open, or sign with --sign \"Developer ID Installer: ...\"."
