#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
scripts="$(cd -- "$(dirname -- "$0")" && pwd)"
installer="$1"
export POCKET_ID_INSTALL_DIR="$2"
[[ "$POCKET_ID_INSTALL_DIR" == /* && ! -e "$POCKET_ID_INSTALL_DIR" ]] || { echo 'Use a fresh absolute install directory' >&2; exit 1; }
trap 'if [[ -x "$POCKET_ID_INSTALL_DIR/stop.sh" ]]; then "$POCKET_ID_INSTALL_DIR/stop.sh"; fi' EXIT
timeout 180s "$installer"
python3 "$scripts/test-https-profile.py" "$POCKET_ID_INSTALL_DIR"
identity_digest() { sha256sum "$POCKET_ID_INSTALL_DIR"/{tls/{ca.pem,server.pem,server.key},.local-oauth.json}; }
before="$(identity_digest)"
"$POCKET_ID_INSTALL_DIR/stop.sh"
for ((i=0; i<100; i++)); do
  if ! (echo > /dev/tcp/127.0.0.1/14411) >/dev/null 2>&1; then break; fi
  sleep 0.1
done
timeout 180s "$installer"
python3 "$scripts/test-https-profile.py" "$POCKET_ID_INSTALL_DIR"
[[ "$(identity_digest)" == "$before" ]]
echo 'PASS: fresh HTTPS installation and restart retained TLS and OAuth identities'
