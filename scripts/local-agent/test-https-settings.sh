#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
install_dir="$1"
temp="$(mktemp -d)"
trap 'rm -rf -- "$temp"' EXIT
# Exercise only the reader, with public settings and disposable literal data.
grep -Ev '^(STATIC_API_KEY|ENCRYPTION_KEY)=' "$install_dir/.env" > "$temp/public"
cp "$temp/public" "$temp/valid"
printf 'STATIC_API_KEY=%064d\nENCRYPTION_KEY=%064d\n' 0 1 >> "$temp/valid"
verify=(env LC_ALL=C awk -f "$install_dir/verify-https-env.awk" "$temp/public")
"${verify[@]}" "$temp/valid"
while IFS= read -r assignment; do
  { cat "$temp/valid"; printf '%s\n' "$assignment"; } > "$temp/repeated"
  if "${verify[@]}" "$temp/repeated"; then
    echo 'Profile reader accepted a repeated assignment' >&2
    exit 1
  fi
done < "$temp/valid"
echo 'PASS: profile reader requires one assignment per key'
