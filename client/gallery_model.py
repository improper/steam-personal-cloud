"""Build a one-item-per-capture gallery from local files and Immich state."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
import re
import sqlite3

from agent import discover, fingerprint
from local_status import local_snapshot, read_json

SESSION_RE = re.compile(r'^(?:fg|bg|clip)_[A-Za-z0-9_-]+$', re.I)
GAME_RE = re.compile(r'(?:^|[/_])(?:fg|bg)_(\d+)_(\d{8})_(\d{6})(?:$|/)', re.I)
DATE_RE = re.compile(r'(20\d{6})[_-](\d{6})')
APP_RE = re.compile(r'appmanifest_(\d+)\.acf$')


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
    subtitle: str = ''
    thumbnail: str = ''
    game_id: str = ''

    @property
    def playable(self):
        return (self.kind == 'photo' and bool(self.local_path or self.immich_id)
                or self.kind == 'video' and
                (bool(self.immich_id and self.state == 'ready')
                 or self.local_path.lower().endswith('.mp4')))


STATES = {'complete': 'ready', 'queued': 'processing', 'processing': 'processing',
          'uploading': 'processing', 'error': 'error', 'deleted': 'deleted'}
STRENGTH = {'deleted': 0, 'waiting': 1, 'backed_up': 2,
            'processing': 3, 'error': 4, 'ready': 5}


def canonical_recording(relative):
    """Canonicalize a nested Steam recording to a single session.

    Metadata at the recordings root (gamerecording.pb) is never a gallery item.
    Nested audio/video segments belong to the enclosing fg/bg/clip session.
    """
    parts = relative.split('/')
    if not parts or parts[0] != 'recordings' or len(parts) < 3:
        return None
    for i, part in enumerate(parts[1:-1], start=1):
        if SESSION_RE.fullmatch(part):
            return '/'.join(parts[:i + 1])
    if relative.lower().endswith('.mp4'):
        return relative
    if parts[-1].lower() == 'session.mpd':
        return '/'.join(parts[:-1])
    return None


def _game_and_datetime(source, modified):
    m = GAME_RE.search(source)
    game_id = m.group(1) if m else ''
    date_match = m or DATE_RE.search(source)
    dt = None
    if date_match:
        try:
            digits = (date_match.group(2) + date_match.group(3)) if m else (date_match.group(1) + date_match.group(2))
            dt = datetime.strptime(digits, '%Y%m%d%H%M%S')
        except ValueError:
            pass
    if dt is None and modified:
        dt = datetime.fromtimestamp(modified)
    return game_id, dt


@lru_cache(maxsize=1)
def steam_names():
    """Installed game labels from local Steam library appmanifest files."""
    home = Path.home()
    roots = [home / '.steam/debian-installation/steamapps',
             home / '.local/share/Steam/steamapps',
             home / '.steam/steam/steamapps']
    for root in list(roots):
        file = root / 'libraryfolders.vdf'
        try:
            data = file.read_text(errors='replace')
        except OSError:
            continue
        for path in re.findall(r'"path"\s*"([^"]+)"', data):
            extra = Path(path.replace('\\\\', '\\')) / 'steamapps'
            if extra not in roots:
                roots.append(extra)
    names = {}
    for root in roots:
        try:
            files = root.glob('appmanifest_*.acf')
            for path in files:
                m = APP_RE.match(path.name)
                if not m:
                    continue
                content = path.read_text(errors='replace')
                name = re.search(r'"name"\s*"([^"]+)"', content, re.I)
                if name and name.group(1).strip():
                    names[m.group(1)] = name.group(1).strip()
        except OSError:
            continue
    return names


def pretty_title(source, modified):
    game_id, dt = _game_and_datetime(source, modified)
    basename = Path(source).name
    title = steam_names().get(game_id) if game_id else None
    if not title:
        title = ('Gameplay clip' if basename.lower().startswith('clip_') else
                 'Gameplay recording' if source.startswith('recordings/') else 'Screenshot')
    subtitle = dt.strftime('%b %-d, %Y · %-I:%M %p') if dt else 'Date unavailable'
    return title, subtitle, game_id


def find_steam_thumbnail(path):
    """Fallback only; Immich artwork is preferred when an asset exists."""
    p = Path(path)
    folder = p if p.is_dir() else p.parent
    if not folder.is_dir():
        return ''
    candidates = ('thumbnail.jpg', 'thumbnail.png', 'thumb.jpg', 'thumb.png',
                  'preview.jpg', 'preview.png', 'poster.jpg', 'poster.png',
                  'cover.jpg', 'cover.png')
    for name in candidates:
        result = folder / name
        if result.is_file() and not result.is_symlink():
            return str(result)
    return ''


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
        relative = source[len(prefix):]
        key = relative if relative.startswith('screenshots/') else canonical_recording(relative + '/session.mpd') if relative.count('/') == 1 else canonical_recording(relative)
        if not key:
            continue
        prior = remote_items.get(key)
        if prior is None or STRENGTH.get(STATES.get(item.get('status'), ''), 0) > STRENGTH.get(STATES.get(prior.get('status'), ''), 0):
            remote_items[key] = item
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
        key = rel if is_photo else canonical_recording(rel)
        if not key:
            continue
        group = groups.setdefault(key, {'path': '', 'mtime': 0, 'files': 0, 'sent': 0, 'manifest': False, 'mp4': False})
        group['files'] += 1
        group['sent'] += int(sent.get(rel) == fingerprint(path, stat))
        group['mtime'] = max(group['mtime'], stat.st_mtime)
        if is_photo:
            group['path'] = str(path)
        elif rel.lower().endswith('.mp4') and key == rel:
            group['path'] = str(path)
            group['mp4'] = True
        else:
            folder = recordings / key.split('/', 1)[1]
            if folder.is_dir():
                group['path'] = str(folder)
            if rel.lower().endswith('/session.mpd'):
                group['manifest'] = True
    for key, item in remote_items.items():
        groups.setdefault(key, {'path': '', 'mtime': item.get('updated_at', 0), 'files': 0, 'sent': 0, 'manifest': True, 'mp4': False})
    result = []
    seen_assets = set()
    for key, group in groups.items():
        item = remote_items.get(key, {})
        immich_id = item.get('immich_id') or ''
        if immich_id and immich_id in seen_assets:
            continue
        if immich_id:
            seen_assets.add(immich_id)
        if not key.startswith('screenshots/') and not (group['manifest'] or group['mp4'] or item):
            continue
        state = STATES.get(item.get('status', ''), '')
        if state == 'deleted' and group['files'] == 0:
            continue
        if not state:
            state = 'backed_up' if group['files'] and group['sent'] == group['files'] else 'waiting'
        elif state == 'processing' and group['files'] and group['sent'] < group['files']:
            state = 'waiting'
        kind = 'photo' if key.startswith('screenshots/') else 'video'
        timestamp = group['mtime'] or item.get('updated_at', 0)
        name, subtitle, game_id = pretty_title(key, timestamp)
        thumbnail = find_steam_thumbnail(group['path']) if kind == 'video' else group['path']
        result.append(MediaItem(key=key, name=name, kind=kind, state=state,
                                local_path=group['path'], immich_id=immich_id, source=key,
                                updated=timestamp, error=item.get('error', ''),
                                subtitle=subtitle, thumbnail=thumbnail, game_id=game_id))
    result.sort(key=lambda entry: (-entry.updated, entry.key))
    snap['gallery_count'] = len(result)
    return result, snap


def validate_local_target(item: MediaItem, config):
    """Return verified exact user-library target; fail closed on symlinks/traversal."""
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
