#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
scripts="$(cd -- "$(dirname -- "$0")" && pwd)"
installer="$1"
destination="$2"
# A caller can select ANY legal HTTPS port. The smoke suites exercise
# independent installations instead of accidentally reusing port 14411.
port="${4:-14511}"
[[ "$port" =~ ^[1-9][0-9]{0,4}$ ]] && (( 10#$port <= 65535 )) || exit 2
install_args=()
verify_profile=test-https-profile.py
case "${3:-explicit}" in
  explicit|aquifer)
    install_dir="$destination"
    command=(env -u HOME "POCKET_ID_INSTALL_DIR=$install_dir")
    if [[ "${3:-explicit}" == aquifer ]]; then
      install_args=(--profile aquifer)
      verify_profile=test-aquifer-provider.py
    fi
    ;;
  default)
    install_dir="$destination/.local/share/pocket-id-local-agent-https-v1-linux-amd64"
    command=(env -u POCKET_ID_INSTALL_DIR -u XDG_DATA_HOME "HOME=$destination")
    ;;
  prompt)
    install_dir="$destination"
    command=(env -u HOME -u POCKET_ID_HTTPS_PORT "POCKET_ID_INSTALL_DIR=$install_dir")
    ;;
  *) echo 'Use explicit, default, prompt or aquifer installation mode' >&2; exit 1 ;;
esac
[[ "$install_dir" == /* && ! -e "$install_dir" ]] || { echo 'Use a fresh absolute install directory' >&2; exit 1; }
# The installer must reject invalid ports before creating a destination.
for invalid in 0 65536 not-a-port 01411; do
  rejected_dir="$destination-invalid-$invalid"
  [[ ! -e "$rejected_dir" ]] || { echo 'Negative-test path exists' >&2; exit 1; }
  if printf '%s\n' "$invalid" | env -u POCKET_ID_HTTPS_PORT "POCKET_ID_INSTALL_DIR=$rejected_dir" \
      timeout 10s "$installer" "${install_args[@]}" >/dev/null 2>&1; then
    echo "Installer accepted invalid HTTPS port $invalid" >&2
    exit 1
  fi
  [[ ! -e "$rejected_dir" ]] || { echo 'Installer wrote files before rejecting invalid port' >&2; exit 1; }
done
stop_installation() {
  [[ -x "$install_dir/stop.sh" ]] || return 0
  "$install_dir/stop.sh" || return 1
  for ((i=0; i<100; i++)); do
    if ! (echo > /dev/tcp/127.0.0.1/"$port") >/dev/null 2>&1; then return 0; fi
    sleep 0.1
  done
  echo 'HTTPS listener still active after stopping the test installation' >&2
  return 1
}
trap stop_installation EXIT
if [[ "${3:-explicit}" == prompt ]]; then
  printf '%s\n' "$port" | timeout 180s "${command[@]}" "$installer"
else
  POCKET_ID_HTTPS_PORT="$port" timeout 180s "${command[@]}" "$installer" "${install_args[@]}"
fi
# The selected issuer must be persisted, not assumed from the installer filename.
grep -Fxq "PORT=$port" "$install_dir/.env"
python3 "$scripts/$verify_profile" "$install_dir"
bash "$scripts/test-https-settings.sh" "$install_dir"
identity_digest() { sha256sum "$install_dir"/{tls/{ca.pem,server.pem,server.key},.local-oauth.json}; }
before="$(identity_digest)"
if [[ "$verify_profile" == test-https-profile.py ]]; then
  if "${command[@]}" "$installer" --profile aquifer >/dev/null 2>&1; then
    echo 'Generic installation accepted a new OAuth profile' >&2
    exit 1
  fi
  [[ "$(identity_digest)" == "$before" ]]
fi
# Reprovisioning in place with a different issuer is forbidden.
wrong_port=$((port == 14712 ? 14713 : 14712))
if POCKET_ID_HTTPS_PORT="$wrong_port" POCKET_ID_INSTALL_DIR="$install_dir" \
    timeout 10s "$installer" >/dev/null 2>&1; then
  echo 'Installer accepted a port change in an existing installation' >&2
  exit 1
fi
[[ "$(identity_digest)" == "$before" ]]
stop_installation
if [[ "${3:-explicit}" == prompt ]]; then
  printf '%s\n' "$port" | timeout 180s "${command[@]}" "$installer"
else
  POCKET_ID_HTTPS_PORT="$port" timeout 180s "${command[@]}" "$installer"
fi
# The selected issuer must be persisted, not assumed from the installer filename.
grep -Fxq "PORT=$port" "$install_dir/.env"
python3 "$scripts/$verify_profile" "$install_dir"
[[ "$(identity_digest)" == "$before" ]]
echo 'PASS: fresh HTTPS installation and restart retained TLS and OAuth identities'
