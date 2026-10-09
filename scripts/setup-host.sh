#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
if [[ -f .env ]]; then
  echo 'Existing .env found; refusing to overwrite. Edit it manually or make a backup first.'
  exit 1
fi
read -rp 'Bind IP on this server [192.168.1.27]: ' bind
bind=${bind:-192.168.1.27}
read -rp 'Immich server URL [http://192.168.1.27:2283]: ' immich
immich=${immich:-http://192.168.1.27:2283}
read -rsp 'Immich API key (hidden): ' immich_key; printf '\n'
[[ -n "$immich_key" ]] || { echo 'API key cannot be empty'; exit 1; }
read -rp 'Immich album [Game Center]: ' album
album=${album:-Game Center}
read -rp 'Host storage path [./storage]: ' storage
storage=${storage:-./storage}
[[ "$bind" =~ ^[0-9.]+$ ]] || { echo 'Bind must be an IPv4 address'; exit 1; }
[[ "$immich" =~ ^https?://[^[:space:]]+$ ]] || { echo 'Immich URL must start with http(s)'; exit 1; }
[[ "$album" != *$'\n'* && "$album" != *'"'* && "$album" != *'$'* ]] || { echo 'Unsupported album characters'; exit 1; }
[[ "$storage" != *$'\n'* && "$storage" != *'"'* && "$storage" != *'$'* ]] || { echo 'Unsupported storage path characters'; exit 1; }
[[ "$immich_key" != *$'\n'* && "$immich_key" != *'"'* && "$immich_key" != *'$'* ]] || { echo 'Unsupported API key characters'; exit 1; }
secret=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
cat > .env <<EOF
SPC_BIND="$bind"
SPC_TOKEN="$secret"
IMMICH_URL="$immich"
IMMICH_API_KEY="$immich_key"
IMMICH_ALBUM="$album"
SPC_IDLE_SECONDS=600
SPC_HOST_STORAGE="$storage"
EOF
chmod 600 .env
mkdir -p "$storage"
echo 'Configured. Run: docker compose up -d --build'
echo 'To retrieve the shared client token on this machine: grep ^SPC_TOKEN= .env'
echo 'Do not share .env or commit it to Git.'
