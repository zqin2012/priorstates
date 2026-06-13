#!/usr/bin/env bash
# Build a macOS installer package (flat .pkg) for the open-source PriorStates
# core. The pkg copies the bundled wheels + install.sh to /Library/PriorStates
# and its postinstall runs install.sh as the logged-in user — same per-user
# venv install as the tarball, but double-clickable in Installer.app.
#
#   packaging/macos/build-pkg.sh        # → build/priorstates-<ver>.pkg
#
# Builds on macOS (pkgbuild/productbuild) OR on Linux with xar + mkbom
# (bomutils) on PATH or in ~/opt/pkgtools/bin — see
# https://github.com/hogliux/bomutils for the flat-package layout.
# The pkg is unsigned: macOS users right-click → Open the first time.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
VER="$(grep -m1 '^version' "$REPO/pyproject.toml" | sed 's/.*"\(.*\)".*/\1/')"
ID="com.priorstates.priorstates"
LOC="/Library/PriorStates"
OUT="$REPO/build"
WORK="$OUT/macos"
PKG="$OUT/priorstates-$VER.pkg"

export PATH="$PATH:$HOME/opt/pkgtools/bin"

echo "==> staging payload ($VER)"
rm -rf "$WORK"; mkdir -p "$WORK/payload/wheels" "$WORK/scripts" "$WORK/flat"
if ls "$OUT"/wheels/*.whl >/dev/null 2>&1; then
  cp "$OUT"/wheels/*.whl "$WORK/payload/wheels/"
else
  python3 -m pip wheel --no-deps -w "$WORK/payload/wheels" "$REPO" >/dev/null
fi
cp "$HERE/../unix/install.sh" "$WORK/payload/install.sh"
cp "$REPO/README.md" "$WORK/payload/README.md" 2>/dev/null || true
cat > "$WORK/payload/UNINSTALL.txt" <<TXT
To remove PriorStates:
  sh $LOC/install.sh --uninstall      # removes the per-user install
  sudo rm -rf $LOC                    # removes these installer files
  sudo pkgutil --forget $ID
Your memory in ~/.priorstates is always left intact.
TXT
# normalize perms (the build umask leaks into cpio/bom otherwise)
find "$WORK/payload" -type d -exec chmod 0755 {} +
find "$WORK/payload" -type f -exec chmod 0644 {} +
chmod 0755 "$WORK/payload/install.sh"

# postinstall runs as root; hand off to the console user for the per-user
# venv + agent wiring. PATH is widened because installer's root env misses
# brew / python.org locations.
cat > "$WORK/scripts/postinstall" <<'POST'
#!/bin/bash
set -u
TARGET="/Library/PriorStates"
CU="$(/usr/bin/stat -f%Su /dev/console 2>/dev/null || echo root)"
case "$CU" in root|_mbsetupuser|"")
  echo "[priorstates] no console user — run: sh $TARGET/install.sh (as your user)"
  exit 0 ;;
esac
echo "[priorstates] running per-user setup for $CU"
WIDE_PATH="/usr/local/bin:/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/Current/bin:/usr/bin:/bin:/usr/sbin:/sbin"
if /usr/bin/sudo -u "$CU" -H /usr/bin/env PATH="$WIDE_PATH" /bin/bash "$TARGET/install.sh"; then
  echo "[priorstates] setup complete"
else
  echo "[priorstates] install.sh failed — files are in $TARGET"
  # install.sh provisions its own Python (via uv) when none is present, so this
  # only fires on a genuine failure — most likely no internet during setup.
  /usr/bin/sudo -u "$CU" /usr/bin/osascript -e 'display dialog "PriorStates files were copied, but automatic setup did not finish (no internet connection?).\n\nReconnect, then run:\n\n  sh /Library/PriorStates/install.sh" buttons {"OK"} default button 1 with title "PriorStates"' >/dev/null 2>&1 || true
fi
exit 0
POST
chmod 0755 "$WORK/scripts/postinstall"

NF="$(find "$WORK/payload" | wc -l | tr -d ' ')"
KB="$(du -sk "$WORK/payload" | cut -f1)"

write_distribution() {
  cat > "$1" <<DIST
<?xml version="1.0" encoding="utf-8"?>
<installer-gui-script minSpecVersion="1">
  <title>PriorStates $VER</title>
  <options customize="never" require-scripts="true" rootVolumeOnly="true"/>
  <domains enable_localSystem="true"/>
  <volume-check><allowed-os-versions><os-version min="11.0"/></allowed-os-versions></volume-check>
  <choices-outline><line choice="default"><line choice="ps"/></line></choices-outline>
  <choice id="default"/>
  <choice id="ps" visible="false"><pkg-ref id="$ID"/></choice>
  <pkg-ref id="$ID" version="$VER" onConclusion="none" installKBytes="$KB">#priorstates-core.pkg</pkg-ref>
</installer-gui-script>
DIST
}

if command -v pkgbuild >/dev/null 2>&1 && command -v productbuild >/dev/null 2>&1; then
  # native macOS toolchain
  echo "==> pkgbuild + productbuild"
  pkgbuild --root "$WORK/payload" --scripts "$WORK/scripts" \
    --identifier "$ID" --version "$VER" --install-location "$LOC" \
    "$WORK/priorstates-core.pkg" >/dev/null
  write_distribution "$WORK/Distribution"
  productbuild --distribution "$WORK/Distribution" --package-path "$WORK" "$PKG" >/dev/null
else
  # Linux: hand-assemble the flat package with xar + mkbom + cpio
  for t in xar mkbom cpio gzip; do
    command -v "$t" >/dev/null 2>&1 || { echo "!! $t not found — need xar + bomutils (see header)"; exit 1; }
  done
  echo "==> assembling flat package (xar + mkbom)"
  COMP="$WORK/flat/priorstates-core.pkg"
  mkdir -p "$COMP"
  cat > "$COMP/PackageInfo" <<PI
<?xml version="1.0" encoding="utf-8"?>
<pkg-info format-version="2" identifier="$ID" version="$VER" install-location="$LOC" auth="root" overwrite-permissions="true">
  <payload installKBytes="$KB" numberOfFiles="$NF"/>
  <scripts><postinstall file="./postinstall"/></scripts>
</pkg-info>
PI
  ( cd "$WORK/payload" && find . | cpio -o --format odc --owner 0:80 2>/dev/null | gzip -9c ) > "$COMP/Payload"
  ( cd "$WORK/scripts" && find . | cpio -o --format odc --owner 0:80 2>/dev/null | gzip -9c ) > "$COMP/Scripts"
  mkbom -u 0 -g 80 "$WORK/payload" "$COMP/Bom"
  write_distribution "$WORK/flat/Distribution"
  rm -f "$PKG"
  ( cd "$WORK/flat" && xar --compression none -cf "$PKG" Distribution priorstates-core.pkg )
fi

echo "built: $PKG ($(du -h "$PKG" | cut -f1 | tr -d ' '))"
