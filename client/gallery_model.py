"""Media-first gallery model. No Qt dependency, usable in tests and CLI diagnostics."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import sqlite3
import time
from urllib.parse import quote

from agent import discover, fingerprint
from local_status import local_snapshot, read_json


@dataclass(frozen=True)
class MediaItem:
    key: str
    name: str
    kind: str
    state: str
    local_path: str
    immich_id: str
    source: str
    updated: float
    error: str = ''

    @property
    def playable(self):
        return self.kind == 'photo' and bool(self.local_path or self.immich_id) or bool(self.immich_id and self.state == 'ready')


STATES = {'complete': 'ready', 'queued': 'processing', 'processing': 'processing',
          'uploading': 'processing', 'error': 'error', 'deleted': 'deleted'}


def _recording_key(relative: str):
    # A session.mpd is a recording; not each video fragment.
    return relative if relative.lower().endswith('.mp4') else relative.rsplit('/', 1)[0]


def make_gallery(config_path=None, *, remote=True):
    config_path = Path(config_path or Path.home() / '.config/steam-personal-cloud/client.json')
    config = read_json(config_path)
    if not isinstance(config, dict):
        return [], {'configured': False, 'error': 'Run steam-personal-cloud-setup'}
    snap = local_snapshot(config_path=config_path, check_remote=remote)
    remote_state = snap.get('remote', {}) or {}
    prefix = str(config.get('client_id', '')) + '/' + str(config.get('steam_account', '')) + '/'
    remote_items = {}
    for item in remote_state.get('items', []):
        source = item.get('source', '')
        if not source.startswith(prefix):
            continue
        remote_items[source[len(prefix):]] = item
    db_path = Path(config.get('state_dir', '~/.local/state/steam-personal-cloud')).expanduser() / 'agent.sqlite3'
    sent = {}
    if db_path.exists():
        try:
            with sqlite3.connect(f'file:{db_path}?mode=ro', uri=True) as db:
                sent = dict(db.execute('SELECT remote,fingerprint FROM sent'))
        except sqlite3.Error:
            pass
    groups = {}
    shots = Path(config.get('screenshots', '')).expanduser()
    recordings = Path(config.get('recordings', '')).expanduser()
    for path, rel, stat in discover(shots, recordings, int(config.get('settle_seconds', 45))):
        is_photo = rel.startswith('screenshots/')
        remote_name = rel if is_photo else _recording_key(rel)
        group = groups.setdefault(remote_name, {'path': '', 'mtime': 0, 'files': 0, 'sent': 0})
        group['files'] += 1
        group['sent'] += int(sent.get(rel) == fingerprint(path, stat))
        group['mtime'] = max(group['mtime'], stat.st_mtime)
        if is_photo:
            group['path'] = str(path)
        elif not group['path']:
            group['path'] = str(path if rel.lower().endswith('.mp4') else path.parent)
    for rel, item in remote_items.items():
        groups.setdefault(rel, {'path': '', 'mtime': item.get('updated_at', 0), 'files': 0, 'sent': 0})
    result = []
    for rel, group in groups.items():
        item = remote_items.get(rel, {})
        status = STATES.get(item.get('status', ''), '')
        if status == 'deleted' and group['files'] == 0:
            continue
        if not status:
            status = 'backed_up' if group['files'] and group['sent'] == group['files'] else 'waiting'
        elif status == 'processing' and group['files'] and group['sent'] < group['files']:
            status = 'waiting'
        kind = 'photo' if rel.startswith('screenshots/') else 'video'
        result.append(MediaItem(key=rel, name=Path(rel).name, kind=kind, state=status,
                                local_path=group['path'], immich_id=item.get('immich_id') or '',
                                source=rel, updated=group['mtime'] or item.get('updated_at', 0),
                                error=item.get('error', '')))
    result.sort(key=lambda item: (-item.updated, item.key))
    snap['gallery_count'] = len(result)
    return result, snap


def validate_local_target(item: MediaItem, config):
    """Return verified exact user-library target; fail closed on path traversal/symlinks."""
    root = Path(config['screenshots'] if item.kind == 'photo' else config['recordings']).expanduser()
    relative = item.source.split('/', 1)[1]
    target = root / relative
    if not root.is_dir() or root.is_symlink() or not target.exists() or target.is_symlink():
        raise ValueError('Media source is missing or unsafe to remove')
    if target.resolve() == root.resolve() or root.resolve() not in target.resolve().parents:
        raise ValueError('Media source is outside the configured library')
    if str(target.resolve()) != str(Path(item.local_path).resolve()):
        raise ValueError('The selected media path no longer matches the library')
    return target
