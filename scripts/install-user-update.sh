#!/usr/bin/env bash
# Install a compiled development bundle for the current user.
set -euo pipefail
cd "$(dirname "$0")/.."
update_stamp=$(date +%Y%m%d-%H%M%S)
update_backup="$HOME/.local/state/steam-personal-cloud/updates/$update_stamp"
update_bundle="$HOME/.local/share/steam-personal-cloud"
update_units="$HOME/.config/systemd/user"
compiled_bundle=${SPC_DIST_DIR:-build/client/main.dist}
test -x "$compiled_bundle/steam-personal-cloud" || { echo "Compile the client first." >&2; exit 1; }
mkdir -p "$update_backup" "$HOME/.local/bin"
chmod 700 "$update_backup"
if [[ -d "$update_bundle" ]]; then
    cp -a "$update_bundle" "$update_backup/bundle"
fi
if [[ -e "$HOME/.local/bin/steam-personal-cloud-gallery" ]]; then
    cp -a "$HOME/.local/bin/steam-personal-cloud-gallery" "$update_backup/launcher"
fi
for unit in steam-personal-cloud-sync steam-personal-cloud-ui; do
    if [[ -d "$update_units/$unit.service.d" ]]; then
        cp -a "$update_units/$unit.service.d" "$update_backup/"
    fi
done
if [[ $(systemctl --user is-active steam-personal-cloud-sync.service || true) == active ]]; then
    echo 'A sync is running. Run this update after it finishes.' >&2
    exit 1
fi
if pgrep -f '[p]ython3 .*[/]steam-personal-cloud/gallery_app.py|[/]steam-personal-cloud/steam-personal-cloud gallery' >/dev/null; then
    echo 'Close the gallery before running this update.' >&2
    exit 1
fi
systemctl --user stop steam-personal-cloud-ui.service
mkdir -p "$update_bundle"
# This directory is exclusively the runtime; pairing and state live elsewhere.
find "$update_bundle" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
cp -a "$compiled_bundle/." "$update_bundle/"
cat > "$HOME/.local/bin/steam-personal-cloud-gallery" <<'EOF'
#!/bin/sh
set -eu
systemctl --user start steam-personal-cloud-ui.service >/dev/null 2>&1 || true
exec "$HOME/.local/share/steam-personal-cloud/steam-personal-cloud" gallery "$@"
EOF
chmod 755 "$HOME/.local/bin/steam-personal-cloud-gallery"
for unit in steam-personal-cloud-sync steam-personal-cloud-ui; do
    mkdir -p "$update_units/$unit.service.d"
    command=sync
    if [[ "$unit" == steam-personal-cloud-ui ]]; then command=proxy; fi
    cat > "$update_units/$unit.service.d/local-update.conf" <<EOF
[Service]
ExecStart=
ExecStart=%h/.local/share/steam-personal-cloud/steam-personal-cloud $command
EOF
done
systemctl --user daemon-reload
systemctl --user restart steam-personal-cloud-ui.service
echo "Updated gallery and user services. Backup: $update_backup"
