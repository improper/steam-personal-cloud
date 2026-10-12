#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
BUILD_PYTHON=${SPC_BUILD_PYTHON:-python3}
"$BUILD_PYTHON" -c 'import sys; assert sys.version_info[:2] == (3, 12), "Release builds require Ubuntu 24.04 system Python 3.12"'
mkdir -p build/client
"$BUILD_PYTHON" -m nuitka client/main.py \
    --mode=standalone --enable-plugin=pyside6 \
    --include-qt-plugins=sensible,multimedia,imageformats \
    --include-data-files=client/local_dashboard.html=local_dashboard.html \
    --output-dir=build/client --output-filename=steam-personal-cloud \
    --report=build/client/compilation-report.xml \
    --noinclude-dlls='PySide6/qt-plugins/imageformats/libqpdf.so' \
    --noinclude-dlls='libQt6Pdf.so*' \
    --lto=no --jobs="${SPC_BUILD_JOBS:-2}" --assume-yes-for-downloads \
    --nofollow-import-to=PyQt6,PyQt5,PySide2,tkinter
"$BUILD_PYTHON" scripts/use-system-libraries.py build/client/compilation-report.xml build/client/main.dist
"$BUILD_PYTHON" scripts/collect-third-party-notices.py build/client/notices
QT_QPA_PLATFORM=offscreen build/client/main.dist/steam-personal-cloud self-test
