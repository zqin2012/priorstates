#!/usr/bin/env bash
# Upload the built open-source PriorStates installers to the website download
# area (https://priorstates.com/download/). Served from /var/www/priorstates-dl/
# — a separate dir from the static site, so the site's `rsync --delete` deploy
# never wipes these binaries. SHA256SUMS is regenerated on the box over the
# FINAL hosted set (OSS + Hub artifacts share the dir; names are distinct).
#
#   SSH_OPTS='-i ~/.ssh/ydev-ec2.pem' packaging/publish-downloads.sh ubuntu@3.208.145.97
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
HOST="${1:?usage: publish-downloads.sh ubuntu@HOST   (SSH_OPTS for the key)}"
RSH="ssh ${SSH_OPTS:-}"

STAGE="$(mktemp -d)"
shopt -s nullglob
for f in "$REPO"/build/*.tar.gz "$REPO"/build/*.deb; do
  cp "$f" "$STAGE/"
done
shopt -u nullglob
[ -n "$(ls -A "$STAGE")" ] || { echo "!! nothing to publish — run packaging/build.sh first"; exit 1; }

echo "==> uploading:"; ls -1 "$STAGE" | sed 's/^/    /'
ssh ${SSH_OPTS:-} "$HOST" "rm -rf /tmp/ps-dl-oss && mkdir -p /tmp/ps-dl-oss"
rsync -az -e "$RSH" "$STAGE"/ "$HOST:/tmp/ps-dl-oss/"
ssh ${SSH_OPTS:-} "$HOST" "sudo bash -s" <<'REMOTE'
set -euo pipefail
sudo mkdir -p /var/www/priorstates-dl
sudo rsync -a /tmp/ps-dl-oss/ /var/www/priorstates-dl/
# regenerate checksums over everything currently hosted
( cd /var/www/priorstates-dl && sudo sh -c 'sha256sum *.tar.gz *.deb *.exe *.pkg 2>/dev/null > SHA256SUMS' )
sudo chown -R www-data:www-data /var/www/priorstates-dl
echo "published. hosted artifacts:"; ls -1 /var/www/priorstates-dl
REMOTE
rm -rf "$STAGE"
