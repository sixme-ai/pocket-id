#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
fail() { printf 'Pocket ID local ERROR: %s\n' "$*" >&2; exit 1; }
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || fail 'This package needs Linux x86_64'
[[ -x bootstrap ]] || fail 'Bundled bootstrap executable missing'
[[ -x pocket-id ]] || fail 'pocket-id executable missing'
[[ -f shared-admin-key.txt && ! -L shared-admin-key.txt ]] || fail 'shared test API key missing'
mkdir -p data logs
chmod 700 data logs
if [[ ! -f .env ]]; then
  key="$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')"
  api_key="$(tr -d '\r\n' < shared-admin-key.txt)"
  [[ "$api_key" =~ ^[0-9a-f]{64}$ ]] || fail 'Invalid shared test API key'
  ( set -C; cat > .env <<EOF
APP_URL=http://localhost:1411
INTERNAL_APP_URL=http://localhost:1411
HOST=127.0.0.1
PORT=1411
ENCRYPTION_KEY=$key
STATIC_API_KEY=$api_key
VERSION_CHECK_DISABLED=true
ANALYTICS_DISABLED=true
ICON_LIBRARY_URL=disabled
ALLOW_INSECURE_CALLBACK_URLS=false
EOF
  ) || fail 'Could not create local .env'
  chmod 600 .env
fi
alive=0
if [[ -f .pocket-id.pid && ! -L .pocket-id.pid ]]; then
  pid="$(cat .pocket-id.pid)"
  if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null &&
     [[ "$(readlink -f "/proc/$pid/exe" 2>/dev/null || true)" == "$(readlink -f ./pocket-id)" ]]; then
    alive=1
  fi
fi
if (( !alive )); then
  if (echo > /dev/tcp/127.0.0.1/1411) >/dev/null 2>&1; then
    fail 'Port 127.0.0.1:1411 already occupied by another process'
  fi
  nohup ./pocket-id > logs/pocket-id.log 2>&1 < /dev/null &
  pid=$!
  printf '%s\n' "$pid" > .pocket-id.pid
fi
./bootstrap || { echo 'Read logs/pocket-id.log for startup errors' >&2; exit 1; }
./pocket-id one-time-access-token agent-tester | tee .login-link.txt
chmod 600 .login-link.txt
printf '\nPocket ID ready on http://localhost:1411 (PID %s)\n' "$pid"
printf 'Local admin test API key: shared-admin-key.txt (same for everyone downloading this build)\n'
printf 'OAuth test clients: .local-oauth.json | Login code: .login-link.txt\n'
