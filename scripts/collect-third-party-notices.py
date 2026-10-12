#!/usr/bin/env python3
"""Collect license texts and corresponding upstream sources for the binary release."""
import ctypes
import fcntl
import hashlib
from importlib import metadata
import json
from pathlib import Path
import shutil
import sys
import tarfile
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = Path(sys.argv[1])
SOURCES = ROOT / 'dist/third-party-sources'
OUTPUT.mkdir(parents=True, exist_ok=True)
lock = (OUTPUT.parent / "notices.lock").open("w")
fcntl.flock(lock, fcntl.LOCK_EX)
SOURCES.mkdir(parents=True, exist_ok=True)
manifest = []


def archive(url, component):
    destination = SOURCES / url.rsplit('/', 1)[-1]
    if not destination.exists():
        print('Downloading corresponding source: ' + component, flush=True)
        with urlopen(url, timeout=120) as response, destination.with_suffix(destination.suffix + '.part').open('wb') as target:
            shutil.copyfileobj(response, target)
        destination.with_suffix(destination.suffix + '.part').replace(destination)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    manifest.append({'component': component, 'url': url, 'file': destination.name, 'sha256': digest})
    with tarfile.open(destination) as source:
        for member in source.getmembers():
            path = Path(member.name)
            name = path.name.lower()
            if not member.isfile() or member.size > 2_000_000:
                continue
            if not (name.startswith(('license', 'copying', 'copyright', 'notice')) or name == 'qt_attribution.json' or any(part.lower() == 'licenses' for part in path.parts)):
                continue
            if '..' in path.parts or path.is_absolute():
                raise RuntimeError('Unsafe archive path')
            target = OUTPUT / 'licenses' / component / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.extractfile(member).read())


import PySide6
qt_version = PySide6.__version__
qt_series = '.'.join(qt_version.split('.')[:2])
archive(f'https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-{qt_version}-src/pyside-setup-everywhere-src-{qt_version}.tar.xz', 'pyside-shiboken')
# Modules used by QWidget, Qt Multimedia, image formats and desktop platform plugins.
for module in ('qtbase', 'qtdeclarative', 'qtmultimedia', 'qtsvg', 'qtimageformats', 'qtwayland', 'qtshadertools'):
    archive(f'https://download.qt.io/official_releases/qt/{qt_series}/{qt_version}/submodules/{module}-everywhere-src-{qt_version}.tar.xz', module)

# ICU is supplied in the Qt wheel under the Unicode license.
archive('https://github.com/unicode-org/icu/releases/download/release-73-2/icu4c-73_2-src.tgz', 'icu')

# Qt's FFmpeg build must remain LGPL; fail closed if a future wheel enables GPL.
ctypes.CDLL('libcrypto.so.3', mode=ctypes.RTLD_GLOBAL)
ctypes.CDLL('libssl.so.3', mode=ctypes.RTLD_GLOBAL)
avutil = ctypes.CDLL(str(Path(PySide6.__file__).parent / 'Qt/lib/libavutil.so'), mode=ctypes.RTLD_GLOBAL)
for function in ('av_version_info', 'avutil_license', 'avutil_configuration'):
    getattr(avutil, function).restype = ctypes.c_char_p
ffmpeg_version = avutil.av_version_info().decode()
ffmpeg_license = avutil.avutil_license().decode()
ffmpeg_configuration = avutil.avutil_configuration().decode()
if not ffmpeg_license.startswith('LGPL') or '--enable-gpl' in ffmpeg_configuration or '--enable-nonfree' in ffmpeg_configuration:
    raise RuntimeError('Only LGPL FFmpeg builds are permitted in this package')
archive(f'https://ffmpeg.org/releases/ffmpeg-{ffmpeg_version}.tar.xz', 'ffmpeg')
(OUTPUT / 'ffmpeg-build.txt').write_text(ffmpeg_version + '\n' + ffmpeg_license + '\n' + ffmpeg_configuration + '\n')

# Pillow's wheel license includes notices for its bundled codec libraries.
for package in ('Pillow', 'Nuitka', 'ordered-set', 'zstandard'):
    distribution = metadata.distribution(package)
    for file in distribution.files or ():
        if 'license' in str(file).lower() or file.name.lower() in ('copying', 'notice'):
            original = Path(distribution.locate_file(file))
            if original.is_file() and original.suffix not in ('.py', '.pyc'):
                target = OUTPUT / 'licenses' / package / Path(str(file).replace('../', ''))
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(original, target)

python_copyright = Path(f'/usr/share/doc/python{sys.version_info.major}.{sys.version_info.minor}/copyright')
if not python_copyright.exists():
    raise RuntimeError('Build with Ubuntu system Python so its complete copyright notices are available')
shutil.copyfile(python_copyright, OUTPUT / 'licenses/python-copyright')
shutil.copyfile(ROOT / 'THIRD_PARTY_NOTICES.md', OUTPUT / 'THIRD_PARTY_NOTICES.md')
(OUTPUT / 'source-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
shutil.copyfile(OUTPUT / 'source-manifest.json', SOURCES / 'source-manifest.json')
# Bundle all corresponding sources alongside the client release, rather than relying on upstream URLs.
with tarfile.open(ROOT / 'dist/steam-personal-cloud-third-party-sources.tar', 'w') as bundle:
    for file in sorted(SOURCES.iterdir()):
        if file.is_file():
            bundle.add(file, arcname=file.name)
print('Third-party notices and corresponding sources collected', flush=True)
