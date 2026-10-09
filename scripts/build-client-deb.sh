#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION=${1:-0.3.0~preview.1}
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(~[a-z0-9.]+)?$ ]] || { echo "Invalid Debian version: $VERSION" >&2; exit 1; }
command -v dpkg-deb >/dev/null || { echo "Install dpkg-deb" >&2; exit 1; }
for file in agent.py setup.py local_status.py local_dashboard.py local_dashboard.html gallery_app.py gallery_model.py gallery_trash.py gamepad_linux.py; do
    test -f "client/$file" || { echo "Missing client/$file" >&2; exit 1; }
done
root=$(mktemp -d)
trap 'rm -rf "$root"' EXIT
pkg="$root/pkg"
install -d "$pkg/DEBIAN" "$pkg/usr/lib/steam-personal-cloud" "$pkg/usr/lib/systemd/user" "$pkg/usr/bin" \
  "$pkg/usr/share/applications" "$pkg/usr/share/icons/hicolor/scalable/apps" "$pkg/usr/share/steam-personal-cloud/scripts"
for file in agent.py local_status.py local_dashboard.py local_dashboard.html gallery_app.py gallery_model.py gallery_trash.py gamepad_linux.py; do
    install -m 644 "client/$file" "$pkg/usr/lib/steam-personal-cloud/$file"
done
install -m 644 client/steam-personal-cloud-ui.service "$pkg/usr/lib/systemd/user/steam-personal-cloud-ui.service"
sed 's#%h/.local/share/steam-personal-cloud/agent.py#/usr/lib/steam-personal-cloud/agent.py#' client/steam-personal-cloud-sync.service > "$pkg/usr/lib/systemd/user/steam-personal-cloud-sync.service"
install -m 644 client/steam-personal-cloud-sync.timer "$pkg/usr/lib/systemd/user/steam-personal-cloud-sync.timer"
install -m 755 client/setup.py "$pkg/usr/share/steam-personal-cloud/scripts/setup.py"
install -m 755 scripts/install-linux.sh "$pkg/usr/share/steam-personal-cloud/scripts/install-linux.sh"
for tool in steam-personal-cloud-setup steam-personal-cloud-dashboard steam-personal-cloud-gallery; do
    install -m 755 "packaging/$tool" "$pkg/usr/bin/$tool"
done
install -m 644 packaging/steam-personal-cloud.desktop "$pkg/usr/share/applications/steam-personal-cloud.desktop"
install -m 644 packaging/steam-personal-cloud-gallery.desktop "$pkg/usr/share/applications/steam-personal-cloud-gallery.desktop"
install -m 644 packaging/steam-personal-cloud.svg "$pkg/usr/share/icons/hicolor/scalable/apps/steam-personal-cloud.svg"
cat > "$pkg/DEBIAN/control" <<EOF
Package: steam-personal-cloud-client
Version: $VERSION
Section: games
Priority: optional
Architecture: all
Maintainer: Steam Personal Cloud Contributors <noreply@github.com>
Depends: python3 (>= 3.10), python3-pyqt6, python3-pyqt6.qtmultimedia, systemd, xdg-utils
Description: Steam Personal Cloud native gallery and backup client
 Native Steam Input-friendly Qt6 gallery for screenshots and Immich videos,
 with background file sync, secure pairing, live status and media actions.
 Run steam-personal-cloud-setup as desktop user after installing.
EOF
install -d dist
dpkg-deb --root-owner-group --build "$pkg" "dist/steam-personal-cloud-client_${VERSION}_all.deb"
sha256sum "dist/steam-personal-cloud-client_${VERSION}_all.deb" > "dist/steam-personal-cloud-client_${VERSION}_all.deb.sha256"
echo "Built dist/steam-personal-cloud-client_${VERSION}_all.deb"
