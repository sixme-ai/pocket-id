#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
scripts="$(cd -- "$(dirname -- "$0")" && pwd)"
installer="$1"
destination="$2"
case "${3:-explicit}" in
  explicit)
    install_dir="$destination"
    command=(env -u HOME "POCKET_ID_INSTALL_DIR=$install_dir")
    ;;
  default)
    install_dir="$destination/.local/share/pocket-id-local-agent-https-v1-linux-amd64"
    command=(env -u POCKET_ID_INSTALL_DIR -u XDG_DATA_HOME "HOME=$destination")
    ;;
  *) echo 'Use explicit or default installation mode' >&2; exit 1 ;;
esac
[[ "$install_dir" == /* && ! -e "$install_dir" ]] || { echo 'Use a fresh absolute install directory' >&2; exit 1; }
stop_installation() {
  [[ -x "$install_dir/stop.sh" ]] || return 0
  "$install_dir/stop.sh" || return 1
  for ((i=0; i<100; i++)); do
    if ! (echo > /dev/tcp/127.0.0.1/14411) >/dev/null 2>&1; then return 0; fi
    sleep 0.1
  done
  echo 'HTTPS listener still active after stopping the test installation' >&2
  return 1
}
trap stop_installation EXIT
timeout 180s "${command[@]}" "$installer"
python3 "$scripts/test-https-profile.py" "$install_dir"
bash "$scripts/test-https-settings.sh" "$install_dir"
identity_digest() { sha256sum "$install_dir"/{tls/{ca.pem,server.pem,server.key},.local-oauth.json}; }
before="$(identity_digest)"
stop_installation
timeout 180s "${command[@]}" "$installer"
python3 "$scripts/test-https-profile.py" "$install_dir"
[[ "$(identity_digest)" == "$before" ]]
echo 'PASS: fresh HTTPS installation and restart retained TLS and OAuth identities'
