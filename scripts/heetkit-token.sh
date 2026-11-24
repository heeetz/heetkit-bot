#!/usr/bin/env bash
# Show or replace the HeetKit Server management token on the Docker host.
# Run as the account that owns the secret file and can use Docker.
# Usage: bash scripts/heetkit-token.sh show|reset
set -euo pipefail

action=${1:-}
if [[ $action != show && $action != reset ]]; then
  echo "Usage: $0 show|reset" >&2
  exit 2
fi

# The running container names the host file behind its management_token secret.
found=()
while read -r id; do
  [[ -n $id ]] || continue
  source=$(docker inspect --format \
    '{{range .Mounts}}{{if eq .Destination "/run/secrets/management_token"}}{{.Source}}{{end}}{{end}}' "$id")
  [[ -z $source ]] || found+=("$id $source")
done < <(docker ps --all --filter label=com.docker.compose.service=bot --format '{{.ID}}')

if (( ${#found[@]} != 1 )); then
  echo "Expected one HeetKit container with a management_token secret, found ${#found[@]}." >&2
  exit 1
fi
read -r container file <<<"${found[0]}"
if [[ ! -f $file || -L $file ]]; then
  echo "The management token file is missing or is a symbolic link: $file" >&2
  exit 1
fi

if [[ $action == show ]]; then
  cat -- "$file"
  exit 0
fi

token=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
chmod 600 -- "$file"
# Rewrite in place: Docker bind-mounts this exact file, so a renamed replacement
# would stay invisible to the container.
printf '%s\n' "$token" > "$file"
chmod 444 -- "$file"
docker restart --time 30 "$container" >/dev/null
echo "HeetKit restarted with a new management token. Every browser, including"
echo "remembered devices, must sign in again. Store it privately:"
echo "$token"
