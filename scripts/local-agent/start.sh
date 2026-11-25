#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
fail() { printf 'Pocket ID local ERROR: %s\n' "$*" >&2; exit 1; }
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || fail 'This package needs Linux x86_64'
[[ -x bootstrap ]] || fail 'Bundled bootstrap executable missing'
[[ -x pocket-id ]] || fail 'pocket-id executable missing'
[[ ! -e shared-admin-key.txt && ! -L shared-admin-key.txt ]] || fail 'Unsafe shared admin key file: extract a fresh bundle'
readonly profile=http
port=1411
actor_port=1414
args=()
server=(./pocket-id)
if [[ "$profile" == https ]]; then
  port=14411
  actor_port=14414
  args=(--https)
  command -v flock >/dev/null || fail 'flock is required to protect startup'
  exec 9>.https-start.lock
  flock -x 9
  ./bootstrap --prepare-tls
  server=(env -i "PATH=$PATH")
  if [[ -n "${HOME:-}" ]]; then server+=("HOME=$HOME"); fi
  server+=(./pocket-id)
fi
origin="$profile://localhost:$port"
settings=("APP_URL=$origin" "INTERNAL_APP_URL=$origin" "HOST=127.0.0.1" "PORT=$port"
          "ACTORS_HOST=127.0.0.1" "ACTORS_PORT=$actor_port"
          "VERSION_CHECK_DISABLED=true" "ANALYTICS_DISABLED=true" "ICON_LIBRARY_URL=disabled"
          "ALLOW_INSECURE_CALLBACK_URLS=false")
if [[ "$profile" == https ]]; then
  settings+=("TLS_CERT_FILE=tls/server.pem" "TLS_KEY_FILE=tls/server.key")
fi
mkdir -p data logs
chmod 700 data logs
[[ ! -L .env ]] || fail 'Refusing a symlink at .env'
if [[ ! -f .env ]]; then
  key="$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')"
  api_key="$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')"
  [[ "$api_key" =~ ^[0-9a-f]{64}$ ]] || fail 'Could not generate local test API key'
  ( set -C; printf '%s\n' "${settings[@]}" "ENCRYPTION_KEY=$key" "STATIC_API_KEY=$api_key" > .env
  ) || fail 'Could not create local .env'
  chmod 600 .env
fi
if [[ "$profile" == https ]]; then
  LC_ALL=C awk -f verify-https-env.awk <(printf '%s\n' "${settings[@]}") .env ||
    fail 'Existing configuration differs from the HTTPS profile'
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
  if (echo > /dev/tcp/127.0.0.1/"$port") >/dev/null 2>&1; then
    fail "Port 127.0.0.1:$port already occupied by another process"
  fi
  nohup "${server[@]}" 9>&- > logs/pocket-id.log 2>&1 < /dev/null &
  pid=$!
  if [[ "$profile" == https ]]; then
    trap 'kill "$pid" 2>/dev/null || true' EXIT
  fi
  printf '%s\n' "$pid" > .pocket-id.pid
fi
./bootstrap "${args[@]}" || { echo 'Read logs/pocket-id.log for startup errors' >&2; exit 1; }
if [[ "$profile" == https ]]; then
  "${server[@]}" one-time-access-token agent-tester > .login-link.txt
else
  ./pocket-id one-time-access-token agent-tester | tee .login-link.txt
fi
chmod 600 .login-link.txt
trap - EXIT
printf '\nPocket ID ready on %s (PID %s)\n' "$origin" "$pid"
printf 'Local admin test API key: STATIC_API_KEY in private .env (unique to this installation)\n'
printf 'OAuth test clients: .local-oauth.json | Login code: .login-link.txt\n'
