"""Read-only local transfer accounting for the Steam Personal Cloud dashboard."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from agent import discover, fingerprint


def read_json(path):
    try:
        return json.loads(Path(path).expanduser().read_text())
    except (OSError, ValueError):
        return None


def get_remote_status(config, timeout=5):
    server = config.get('server', '').rstrip('/')
    token = config.get('token', '')
    if not server or not token:
        return None, 'Not paired with a server'
    request = Request(server + '/api/status', headers={'X-SPC-Token': token})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response), None
    except (URLError, HTTPError, OSError, ValueError, TimeoutError) as exc:
        return None, f'Server unavailable: {exc}'


def local_snapshot(config_path=None, state_dir=None, check_remote=True):
    config_path = Path(config_path or Path.home() / '.config/steam-personal-cloud/client.json').expanduser()
    config = read_json(config_path)
    if not isinstance(config, dict):
        return {'configured': False, 'error': 'Run steam-personal-cloud-setup to connect this device'}
    state = Path(state_dir or config.get('state_dir', '~/.local/state/steam-personal-cloud')).expanduser()
    known = {}
    db_path = state / 'agent.sqlite3'
    if db_path.is_file():
        try:
            with sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=1) as db:
                known = {row[0]: row[1] for row in db.execute('SELECT remote,fingerprint FROM sent')}
        except sqlite3.Error:
            known = {}

    settle = int(config.get('settle_seconds', 45))
    shots = Path(config.get('screenshots', '/nonexistent')).expanduser()
    videos = Path(config.get('recordings', '/nonexistent')).expanduser()
    groups = defaultdict(lambda: {'files': 0, 'sent': 0, 'pending': 0, 'bytes': 0, 'pending_bytes': 0})
    total = {'files': 0, 'sent': 0, 'pending': 0, 'bytes': 0, 'pending_bytes': 0}
    for path, remote, stat in discover(shots, videos, settle):
        uploaded = known.get(remote) == fingerprint(path, stat)
        group_name = remote if remote.startswith('screenshots/') else '/'.join(remote.split('/')[:3])
        row = groups[group_name]
        for target in (row, total):
            target['files'] += 1
            target['bytes'] += stat.st_size
            if uploaded:
                target['sent'] += 1
            else:
                target['pending'] += 1
                target['pending_bytes'] += stat.st_size
    rows = [{'name': name, 'kind': 'screenshot' if name.startswith('screenshots/') else 'recording fragments', **data}
            for name, data in groups.items()]
    rows.sort(key=lambda row: (row['pending'] == 0, row['name']))
    runtime = read_json(state / 'last_sync.json') or {}
    payload = {
        'configured': True,
        'client': config.get('client_id', ''),
        'account': config.get('steam_account', ''),
        'server': config.get('server', ''),
        'local': total,
        'groups': rows[:100],
        'group_count': len(rows),
        'last_sync': {key: runtime.get(key) for key in ('started_at', 'finished_at', 'uploaded', 'skipped', 'failed', 'last_error', 'running')},
        'paths': {'screenshots': str(shots), 'recordings': str(videos), 'screenshots_found': shots.is_dir(), 'recordings_found': videos.is_dir()},
    }
    if check_remote:
        remote, error = get_remote_status(config)
        payload['remote'] = {'connected': remote is not None, 'error': error,
                             'counts': (remote or {}).get('counts', {}),
                             'files_backed_up': (remote or {}).get('files_backed_up', 0),
                             'items': (remote or {}).get('items', [])[:30]}
    return payload
