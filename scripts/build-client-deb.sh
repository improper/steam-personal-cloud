#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION=${1:-0.3.0~beta.1}
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(~[a-z0-9.]+)?$ ]] || { echo 'Invalid Debian version' >&2; exit 1; }
DIST=${SPC_DIST_DIR:-build/client/main.dist}
ARCH=$(dpkg --print-architecture)
test -x "$DIST/steam-personal-cloud" || { echo 'Run scripts/compile-client.sh first.' >&2; exit 1; }
readelf -h "$DIST/steam-personal-cloud" >/dev/null
for source in agent gallery_app gallery_model gallery_trash steam_screenshots setup local_status local_dashboard diagnostics main gamepad_linux; do
    if [[ -n $(find "$DIST" -name "$source.py" -o -name "$source.pyc") ]]; then
        echo "Application source leaked into compiled bundle: $source" >&2
        exit 1
    fi
done
test -f build/client/notices/THIRD_PARTY_NOTICES.md
root=$(mktemp -d)
trap 'rm -rf "$root"' EXIT
pkg="$root/pkg"
install -d "$pkg/DEBIAN" "$pkg/usr/lib/steam-personal-cloud" "$pkg/usr/lib/systemd/user" "$pkg/usr/bin" \
    "$pkg/usr/share/applications" "$pkg/usr/share/icons/hicolor/scalable/apps" "$pkg/usr/share/doc/steam-personal-cloud-client"
cp -a "$DIST/." "$pkg/usr/lib/steam-personal-cloud/"
cp -a build/client/notices/. "$pkg/usr/share/doc/steam-personal-cloud-client/"
install -m 644 COPYRIGHT "$pkg/usr/share/doc/steam-personal-cloud-client/copyright"
install -m 644 client/steam-personal-cloud-ui.service "$pkg/usr/lib/systemd/user/steam-personal-cloud-ui.service"
sed 's#ExecStart=.*#ExecStart=/usr/lib/steam-personal-cloud/steam-personal-cloud sync#' client/steam-personal-cloud-sync.service > "$pkg/usr/lib/systemd/user/steam-personal-cloud-sync.service"
install -m 644 client/steam-personal-cloud-sync.timer "$pkg/usr/lib/systemd/user/steam-personal-cloud-sync.timer"
for tool in steam-personal-cloud-setup steam-personal-cloud-dashboard steam-personal-cloud-gallery; do
    install -m 755 "packaging/$tool" "$pkg/usr/bin/$tool"
done
install -m 644 packaging/steam-personal-cloud.desktop "$pkg/usr/share/applications/steam-personal-cloud.desktop"
install -m 644 packaging/steam-personal-cloud-gallery.desktop "$pkg/usr/share/applications/steam-personal-cloud-gallery.desktop"
install -m 644 packaging/steam-personal-cloud.svg "$pkg/usr/share/icons/hicolor/scalable/apps/steam-personal-cloud.svg"
cat > "$pkg/DEBIAN/control" <<CONTROL
Package: steam-personal-cloud-client
Version: $VERSION
Section: games
Priority: optional
Architecture: $ARCH
Maintainer: Steam Personal Cloud <4887071+tylers-username@users.noreply.github.com>
Depends: libc6 (>= 2.39), libstdc++6, libglib2.0-0t64, libx11-6, libxcb1, libxcb-cursor0, libxkbcommon0, libxkbcommon-x11-0, libegl1, libgl1, libfontconfig1, libdbus-1-3, libasound2t64, libpulse0, libssl3t64, libffi8, libbz2-1.0, liblzma5, libsqlite3-0, zlib1g, libcrypt1, libuuid1, libzstd1, libcups2t64, libdrm2, libgbm1, libudev1, libexpat1, libfreetype6, libxrender1, libxext6, libxcb-icccm4, libxcb-image0, libxcb-keysyms1, libxcb-render-util0, libxcb-xinerama0, libxcb-xkb1, libxcb-randr0, libxcb-shape0, libxcb-sync1, libxcb-xfixes0, libxcb-render0, libxcb-shm0, libwayland-client0, libwayland-cursor0, libwayland-egl1, systemd, xdg-utils
Description: Steam Personal Cloud compiled gallery and backup client
 Controller-friendly screenshot and recording library for Steam Big Picture,
 with background backup and authenticated Immich playback.
CONTROL
install -d dist
dpkg-deb --root-owner-group --build "$pkg" "dist/steam-personal-cloud-client_${VERSION}_${ARCH}.deb"
sha256sum "dist/steam-personal-cloud-client_${VERSION}_${ARCH}.deb" > "dist/steam-personal-cloud-client_${VERSION}_${ARCH}.deb.sha256"
echo "Built dist/steam-personal-cloud-client_${VERSION}_${ARCH}.deb"
