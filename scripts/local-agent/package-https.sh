#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
[[ $# -eq 2 ]] || { echo 'Usage: package-https.sh <compiled binaries directory> <output directory>' >&2; exit 1; }
scripts="$(cd -- "$(dirname -- "$0")" && pwd)"
bin_dir="$(cd -- "$1" && pwd)"
mkdir -p -- "$2"
output="$(cd -- "$2" && pwd)"
temp="$(mktemp -d)"
trap 'rm -rf -- "$temp"' EXIT
stage="$temp/local-agent"
mkdir -- "$stage"
install -m 700 "$bin_dir/pocket-id" "$bin_dir/bootstrap" "$scripts/stop.sh" "$stage/"
sed 's/^readonly profile=http$/readonly profile=https/' "$scripts/start.sh" > "$stage/start.sh"
grep -Fxq 'readonly profile=https' "$stage/start.sh"
chmod 700 "$stage/start.sh"
install -m 600 "$scripts/verify-https-env.awk" "$stage/"
install -m 600 "$scripts/README-https.txt" "$stage/README.txt"
install -m 600 "$scripts/../../LICENSE" "$stage/LICENSE.pocket-id"
name=pocket-id-local-agent-https-v1-linux-amd64
tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner -C "$temp" -cf - local-agent | gzip -n > "$temp/payload.tar.gz"
hash="$(sha256sum "$temp/payload.tar.gz" | cut -d' ' -f1)"
sed -e "s/__ARCHIVE_SHA256__/$hash/" -e "s/pocket-id-local-agent-linux-amd64.run/$name.run/g" \
    -e "s|/pocket-id-local-agent\"|/$name\"|g" "$scripts/installer-header.sh" > "$temp/installer"
printf '\n__POCKET_ID_ARCHIVE_BELOW__\n' >> "$temp/installer"
cat "$temp/payload.tar.gz" >> "$temp/installer"
install -m 700 "$temp/installer" "$output/$name.run"
sha256sum "$output/$name.run"
printf '%s  payload.tar.gz\n' "$hash"
