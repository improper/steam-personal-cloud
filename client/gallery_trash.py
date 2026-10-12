"""Move captures to desktop Trash (recoverable) instead of permanent unlink."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
from urllib.parse import quote
import uuid


def move_to_trash(source: Path, *, home=None):
    source = Path(source)
    if source.is_symlink() or not source.exists():
        raise ValueError('Media is unavailable or is a symbolic link')
    home = Path(home or Path.home()).resolve()
    # XDG home trash; support path names with spaces and Unicode.
    base = home / '.local/share/Trash'
    files = base / 'files'
    info = base / 'info'
    files.mkdir(parents=True, exist_ok=True)
    info.mkdir(parents=True, exist_ok=True)
    name = source.name
    while (files / name).exists() or (info / (name + '.trashinfo')).exists():
        name = f'{source.stem}-{uuid.uuid4().hex[:8]}{source.suffix}'
    details = info / (name + '.trashinfo')
    original = source.resolve()
    try:
        fd = os.open(details, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write('[Trash Info]\nPath=' + quote(str(original), safe='/') + '\n')
            stream.write('DeletionDate=' + datetime.now().strftime('%Y-%m-%dT%H:%M:%S') + '\n')
        shutil.move(str(source), str(files / name))
    except Exception:
        details.unlink(missing_ok=True)
        raise
    return files / name
