#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

readonly ARCHIVE_SHA256="__ARCHIVE_SHA256__"

fail() { printf 'Pocket ID installer ERROR: %s\n' "$*" >&2; exit 1; }

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  printf 'Usage: ./pocket-id-local-agent-linux-amd64.run\n'
  printf 'Set POCKET_ID_INSTALL_DIR to an absolute private directory to override the default.\n'
  exit 0
fi
[[ "$#" -eq 0 ]] || fail 'Unsupported argument (use --help)'
[[ "$(uname -s)" == "Linux" && "$(uname -m)" == "x86_64" ]] || fail 'Linux x86_64 required'

for required in awk tail sha256sum tar mktemp mkdir dirname mv rm; do
  command -v "$required" >/dev/null 2>&1 || fail "Missing required OS tool: $required"
done

if [[ -n "${POCKET_ID_INSTALL_DIR:-}" ]]; then
  install_dir="$POCKET_ID_INSTALL_DIR"
elif [[ -n "${XDG_DATA_HOME:-}" ]]; then
  install_dir="$XDG_DATA_HOME/pocket-id-local-agent"
elif [[ -n "${HOME:-}" ]]; then
  install_dir="$HOME/.local/share/pocket-id-local-agent"
else
  fail 'HOME or POCKET_ID_INSTALL_DIR required'
fi

[[ "$install_dir" == /* && "$install_dir" != "/" ]] || fail 'Installation path must be absolute and non-root'
install_dir="${install_dir%/}"
[[ -n "$install_dir" ]] || fail 'Invalid installation path'

if [[ -e "$install_dir" || -L "$install_dir" ]]; then
  [[ -d "$install_dir" && ! -L "$install_dir" ]] || fail 'Installation destination is not a real directory'
  marker_file="$install_dir/.installer-archive.sha256"
  [[ -f "$marker_file" && ! -L "$marker_file" ]] || fail 'Destination already exists; refusing to overwrite user data'
  [[ "$(< "$marker_file")" == "$ARCHIVE_SHA256" ]] || fail 'Different installer version; refusing to overwrite local data'
  [[ -x "$install_dir/start.sh" ]] || fail 'Existing installation is incomplete'
  "$install_dir/start.sh"
  exit
fi

parent_dir="$(dirname -- "$install_dir")"
mkdir -p -- "$parent_dir"
[[ ! -L "$parent_dir" ]] || fail 'Installation parent directory is a symlink'
staging="$(mktemp -d "${TMPDIR:-/tmp}/pocket-id-installer.XXXXXXXX")"
trap 'rm -rf -- "$staging"' EXIT

payload_line="$(LC_ALL=C awk '$0 == "__POCKET_ID_ARCHIVE_BELOW__" { print NR + 1; exit }' "$0")"
[[ "$payload_line" =~ ^[0-9]+$ ]] || fail 'Embedded archive marker missing'
tail -n "+$payload_line" -- "$0" > "$staging/archive.tar.gz"
actual_hash="$(sha256sum -- "$staging/archive.tar.gz")"
[[ "${actual_hash:0:64}" == "$ARCHIVE_SHA256" ]] || fail 'Embedded archive checksum mismatch'

tar --extract --gzip --file "$staging/archive.tar.gz" --directory "$staging" --no-same-owner --no-same-permissions
[[ -d "$staging/local-agent" && ! -L "$staging/local-agent" ]] || fail 'Invalid archive layout'
for binary in pocket-id bootstrap start.sh stop.sh; do
  [[ -f "$staging/local-agent/$binary" && -x "$staging/local-agent/$binary" && ! -L "$staging/local-agent/$binary" ]] || fail "Missing real executable: $binary"
done
[[ ! -e "$staging/local-agent/.env" && ! -e "$staging/local-agent/shared-admin-key.txt" ]] || fail 'Bundle must never contain a local secret'

printf '%s\n' "$ARCHIVE_SHA256" > "$staging/local-agent/.installer-archive.sha256"
chmod 600 "$staging/local-agent/.installer-archive.sha256"
chmod 700 "$staging/local-agent"
mv -T -- "$staging/local-agent" "$install_dir" || fail 'Cannot install without overwriting destination'
printf 'Pocket ID installed in %s\n' "$install_dir"
"$install_dir/start.sh"
exit 0
