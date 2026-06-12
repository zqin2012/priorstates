#!/usr/bin/env bash
# Build the downloadable open-source PriorStates installers.
#
# Artifacts (→ build/):
#   priorstates-<ver>.tar.gz   self-contained installer (Linux/macOS): bundled
#                              wheel + install.sh (creates a venv, no index,
#                              wires detected agents by default)
#   priorstates_<ver>_all.deb  Debian/Ubuntu package with app-menu launcher
#   SHA256SUMS
#
# (The Windows Setup.exe builds on Windows — see the release runbook; it is
#  published to GitHub Releases, not here.)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
VER="$(grep -m1 '^version' "$REPO/pyproject.toml" | sed 's/.*"\(.*\)".*/\1/')"
OUT="$REPO/build"; WH="$OUT/wheels"
rm -rf "$OUT"; mkdir -p "$WH"

echo "==> building wheel ($VER)"
python3 -m pip wheel --no-deps -w "$WH" "$REPO" >/dev/null
ls -1 "$WH"/*.whl | sed 's/^/    /'

# ---- self-contained tar.gz installer (Linux/macOS) ------------------------
echo "==> assembling tarball installer"
STAGE="$OUT/priorstates-$VER"
mkdir -p "$STAGE/wheels"
cp "$WH"/*.whl "$STAGE/wheels/"
cp "$HERE/unix/install.sh" "$STAGE/install.sh"; chmod 0755 "$STAGE/install.sh"
cp "$REPO/README.md" "$STAGE/README.md" 2>/dev/null || true
( cd "$OUT" && tar -czf "priorstates-$VER.tar.gz" "priorstates-$VER" )
rm -rf "$STAGE"
echo "    $OUT/priorstates-$VER.tar.gz"

# ---- Debian/Ubuntu .deb (with desktop launcher) ---------------------------
if command -v dpkg-deb >/dev/null 2>&1; then
  echo "==> building .deb"
  bash "$HERE/deb/build-deb.sh" >/dev/null \
    && ls -1 "$OUT"/*.deb 2>/dev/null | sed 's/^/    /' \
    || echo "!! .deb build failed"
else
  echo "!! dpkg-deb not found — skipping .deb (run on Debian/Ubuntu)"
fi

# Emit a SHA256SUMS over everything for the website.
( cd "$OUT" && command -v sha256sum >/dev/null 2>&1 && sha256sum ./*.tar.gz ./*.deb 2>/dev/null > SHA256SUMS || true )

echo; echo "Done. Artifacts in $OUT:"; ls -1 "$OUT" | grep -E '\.(tar\.gz|deb)$' | sed 's/^/    /'
