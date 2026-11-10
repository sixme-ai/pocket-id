#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
[[ -f .pocket-id.pid && ! -L .pocket-id.pid ]] || { echo 'No local Pocket ID PID file'; exit 0; }
pid="$(cat .pocket-id.pid)"
if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
  [[ "$(readlink -f "/proc/$pid/exe" 2>/dev/null || true)" == "$(readlink -f ./pocket-id)" ]] || { echo 'PID belongs to another executable; not stopping' >&2; exit 2; }
  kill "$pid"
fi
rm -f .pocket-id.pid
printf 'Local Pocket ID stopped; private data and OAuth clients preserved\n'
