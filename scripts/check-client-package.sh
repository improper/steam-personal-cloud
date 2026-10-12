#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION=${1:-0.3.0~beta.1}
ARCH=$(dpkg --print-architecture)
FILE_VERSION=${VERSION//\~/.}
package="dist/steam-personal-cloud-client_${FILE_VERSION}_${ARCH}.deb"
root=$(mktemp -d)
trap 'rm -rf "$root"' EXIT
(cd dist && sha256sum -c "steam-personal-cloud-client_${FILE_VERSION}_${ARCH}.deb.sha256")
dpkg-deb --info "$package"
dpkg-deb -x "$package" "$root"
bundle="$root/usr/lib/steam-personal-cloud"
test -x "$bundle/steam-personal-cloud"
test -f "$bundle/local_dashboard.html"
test -f "$root/usr/lib/systemd/user/steam-personal-cloud-sync.timer"
test -f "$root/usr/share/doc/steam-personal-cloud-client/THIRD_PARTY_NOTICES.md"
test -f "$root/usr/share/doc/steam-personal-cloud-client/source-manifest.json"
for source in agent gallery_app gallery_model gallery_trash steam_screenshots setup local_status local_dashboard diagnostics main gamepad_linux; do
    test -z "$(find "$bundle" -name "$source.py" -o -name "$source.pyc")"
done
# Exclude GPL-only Qt modules and PyQt from the distributed runtime.
test -z "$(find "$bundle" \( -iname '*QtCharts*' -o -iname '*QtGraphs*' -o -iname '*QtDataVisualization*' -o -iname '*PyQt*' \))"
while IFS= read -r -d '' library; do
    missing=$(ldd "$library" | rg 'not found' || true)
    if [[ -n "$missing" ]]; then echo "$library: $missing" >&2; exit 1; fi
done < <(find "$bundle" -type f \( -name '*.so' -o -name '*.so.*' -o -name steam-personal-cloud \) -print0)
for mode in gallery setup dashboard; do
    bash -n "$root/usr/bin/steam-personal-cloud-$mode"
done
grep -F 'ExecStart=/usr/lib/steam-personal-cloud/steam-personal-cloud sync' "$root/usr/lib/systemd/user/steam-personal-cloud-sync.service"
grep -F 'ExecStart=/usr/lib/steam-personal-cloud/steam-personal-cloud proxy' "$root/usr/lib/systemd/user/steam-personal-cloud-ui.service"
"$bundle/steam-personal-cloud" --version
QT_QPA_PLATFORM=offscreen "$bundle/steam-personal-cloud" self-test
