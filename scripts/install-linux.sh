#!/usr/bin/env bash
set -euo pipefail
SRC_DIR=$(cd "$(dirname "$0")/.." && pwd)
mkdir -p "$HOME/.local/share/steam-personal-cloud" "$HOME/.config/steam-personal-cloud" "$HOME/.config/systemd/user"
read -rp 'Server URL [http://192.168.1.27:8787]: ' server
server=${server:-http://192.168.1.27:8787}
read -rp "Client name [$(hostname -s)]: " client_id
client_id=${client_id:-$(hostname -s)}
read -rp 'Steam userdata account ID [728364463]: ' account
account=${account:-728364463}
read -rp "Screenshots [$HOME/Gameplay/Screenshots]: " shots
shots=${shots:-$HOME/Gameplay/Screenshots}
read -rp "Recording storage [$HOME/Gameplay/Recordings]: " recordings
recordings=${recordings:-$HOME/Gameplay/Recordings}
read -rp 'Maximum upload MiB/sec [2]: ' bandwidth
bandwidth=${bandwidth:-2}
[[ "$client_id" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$ ]] || { echo 'Invalid client name'; exit 1; }
[[ "$account" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$ ]] || { echo 'Invalid account'; exit 1; }
[[ "$bandwidth" =~ ^[0-9]+([.][0-9]+)?$ ]] || { echo 'Invalid bandwidth'; exit 1; }
if [[ -f "$HOME/.config/steam-personal-cloud/client.json" ]]; then
  echo 'Existing client config found. Refusing to overwrite.'
  exit 1
fi
read -rp 'Authentication [1=Fast Connect pairing code, 2=existing token] (default 1): ' method
method=${method:-1}
if [[ "$method" == 1 ]]; then
  printf '\nOn the Steam Personal Cloud server dashboard, click Pair Device to generate a short code.\n'
  read -rp 'Pairing code: ' pair_code
  token=$(SPC_PAIR_CODE="$pair_code" python3 "$SRC_DIR/client/agent.py" --pair --server "$server" --client-id "$client_id" --steam-account "$account")
  unset pair_code
elif [[ "$method" == 2 ]]; then
  read -rsp 'Existing client token (hidden): ' token; printf '\n'
else
  echo 'Invalid authentication method'; exit 1
fi
[[ -n "$token" ]] || { echo 'Authentication failed'; exit 1; }
umask 077
# Avoid passing secrets through command arguments or shell history.
export SPC_SETUP_SERVER="$server" SPC_SETUP_TOKEN="$token" SPC_SETUP_CLIENT="$client_id" \
       SPC_SETUP_ACCOUNT="$account" SPC_SETUP_SHOTS="$shots" \
       SPC_SETUP_RECORDINGS="$recordings" SPC_SETUP_BANDWIDTH="$bandwidth"
python3 - <<'PY'
import json,os
from pathlib import Path
config={
 'server':os.environ['SPC_SETUP_SERVER'], 'token':os.environ['SPC_SETUP_TOKEN'],
 'client_id':os.environ['SPC_SETUP_CLIENT'],'steam_account':os.environ['SPC_SETUP_ACCOUNT'],
 'screenshots':os.environ['SPC_SETUP_SHOTS'],'recordings':os.environ['SPC_SETUP_RECORDINGS'],
 'max_mib_per_second':float(os.environ['SPC_SETUP_BANDWIDTH']), 'settle_seconds':45}
p=Path.home()/'.config/steam-personal-cloud/client.json'
p.write_text(json.dumps(config,indent=2)+'\n')
p.chmod(0o600)
PY
unset SPC_SETUP_SERVER SPC_SETUP_TOKEN SPC_SETUP_CLIENT SPC_SETUP_ACCOUNT SPC_SETUP_SHOTS SPC_SETUP_RECORDINGS SPC_SETUP_BANDWIDTH token
install -m 755 "$SRC_DIR/client/agent.py" "$HOME/.local/share/steam-personal-cloud/agent.py"
install -m 644 "$SRC_DIR/client/steam-personal-cloud-sync.service" "$HOME/.config/systemd/user/"
install -m 644 "$SRC_DIR/client/steam-personal-cloud-sync.timer" "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now steam-personal-cloud-sync.timer
printf '\nSync enabled. Run once now: systemctl --user start steam-personal-cloud-sync.service\n'
printf 'Follow logs: journalctl --user -u steam-personal-cloud-sync.service -f\n'
echo "Dashboard: open $server on the game center."
