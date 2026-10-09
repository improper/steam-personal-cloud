#!/usr/bin/env bash
set -euo pipefail
SOURCE_DIR=$(cd "$(dirname "$0")/.." && pwd)
if [[ "${SPC_PACKAGE_MODE:-0}" == 1 ]]; then
  exec /usr/bin/python3 /usr/share/steam-personal-cloud/scripts/setup.py "$@"
fi
exec /usr/bin/python3 "$SOURCE_DIR/client/setup.py" "$@"
