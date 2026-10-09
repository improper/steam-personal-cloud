#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION=${1:-0.2.0~preview.1}
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(~[a-z0-9.]+)?$ ]] || { echo "Invalid Debian version: $VERSION" >&2; exit 1; }
command -v dpkg-deb >/dev/null || { echo "Install dpkg-dev" >&2; exit 1; }
for p in client/agent.py client/steam-personal-cloud-sync.service client/steam-personal-cloud-sync.timer scripts/install-linux.sh packaging/steam-personal-cloud-dashboard packaging/steam-personal-cloud-setup packaging/steam-personal-cloud.desktop; do
  test -f "$p" || { echo "Missing $p" >&2; exit 1; }
done
root=$(mktemp -d)
trap 'rm -rf "$root"' EXIT
pkg="$root/pkg"
install -d "$pkg/DEBIAN" "$pkg/usr/lib/steam-personal-cloud" "$pkg/usr/lib/systemd/user" "$pkg/usr/bin" "$pkg/usr/share/applications" "$pkg/usr/share/steam-personal-cloud/scripts"
install -m 644 client/agent.py "$pkg/usr/lib/steam-personal-cloud/agent.py"
sed 's#%h/.local/share/steam-personal-cloud/agent.py#/usr/lib/steam-personal-cloud/agent.py#' client/steam-personal-cloud-sync.service > "$pkg/usr/lib/systemd/user/steam-personal-cloud-sync.service"
install -m 644 client/steam-personal-cloud-sync.timer "$pkg/usr/lib/systemd/user/steam-personal-cloud-sync.timer"
install -m 755 scripts/install-linux.sh "$pkg/usr/share/steam-personal-cloud/scripts/install-linux.sh"
install -m 755 packaging/steam-personal-cloud-setup "$pkg/usr/bin/steam-personal-cloud-setup"
install -m 755 packaging/steam-personal-cloud-dashboard "$pkg/usr/bin/steam-personal-cloud-dashboard"
install -m 644 packaging/steam-personal-cloud.desktop "$pkg/usr/share/applications/steam-personal-cloud.desktop"
cat > "$pkg/DEBIAN/control" <<EOF
Package: steam-personal-cloud-client
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Maintainer: Steam Personal Cloud Contributors <noreply@github.com>
Depends: python3 (>= 3.10), systemd, xdg-utils
Description: Steam Personal Cloud lightweight media backup client
 Background Steam screenshot and game recording fragment sync to a self-hosted
 Steam Personal Cloud server, with Fast Connect pairing and dashboard launcher.
 Run steam-personal-cloud-setup as the desktop user to finish configuration.
EOF
install -d dist
dpkg-deb --root-owner-group --build "$pkg" "dist/steam-personal-cloud-client_${VERSION}_all.deb"
sha256sum "dist/steam-personal-cloud-client_${VERSION}_all.deb" > "dist/steam-personal-cloud-client_${VERSION}_all.deb.sha256"
echo "Built dist/steam-personal-cloud-client_${VERSION}_all.deb"
