"""Build a one-item-per-capture gallery from local files and Immich state."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3

from agent import discover, fingerprint, steam_game_names
from local_status import local_snapshot, read_json

SESSION_RE = re.compile(r'^(?:fg|bg|clip)_[A-Za-z0-9_-]+$', re.I)
GAME_RE = re.compile(r'(?:^|[/_])(?:fg|bg)_(\d+)_(\d{8})_(\d{6})(?:$|/)', re.I)
DATE_RE = re.compile(r'(20\d{6})[_-](\d{6})')
APP_RE = re.compile(r'appmanifest_(\d+)\.acf$')
SESSION_ID_RE = re.compile(r'(?:fg|bg)_\d+_20\d{6}_\d{6}')


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
    session_ids: tuple[str, ...] = ()

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
            dt = datetime.strptime(digits, '%Y%m%d%H%M%S').replace(tzinfo=timezone.utc).astimezone()
        except ValueError:
            pass
    if dt is None and modified:
        dt = datetime.fromtimestamp(modified)
    return game_id, dt


def steam_names():
    return steam_game_names()


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
    """Use Steam's cover/thumbnail if one exists, without searching arbitrary files."""
    p = Path(path)
    folder = p if p.is_dir() else p.parent
    if not folder.is_dir():
        return ''
    locations = [folder, folder / 'thumbnails', folder / 'thumbs', folder / 'video']
    # A saved clip can contain video/fg_<appid>_<date>_<time>/session.mpd.
    video = folder / 'video'
    if video.is_dir() and not video.is_symlink():
        try:
            locations.extend(sub for sub in list(video.iterdir())[:32]
                             if sub.is_dir() and not sub.is_symlink())
        except OSError:
            pass
    names = ('thumbnail', 'thumb', 'preview', 'poster', 'cover')
    extensions = {'.jpg', '.jpeg', '.png', '.webp'}
    for location in locations:
        if not location.is_dir() or location.is_symlink():
            continue
        try:
            for candidate in list(location.iterdir())[:120]:
                if (candidate.is_file() and not candidate.is_symlink()
                    and candidate.suffix.lower() in extensions
                    and candidate.stem.lower().startswith(names)):
                    return str(candidate)
        except OSError:
            continue
    return ''


def canonical_source(relative):
    if relative.startswith('screenshots/'):
        return relative
    if not relative.startswith('recordings/'):
        return None
    # Server media keys are directories, local discovered paths are files.
    candidate = relative if '.' in Path(relative).name else relative + '/session.mpd'
    return canonical_recording(candidate)


def can_play_immich(item):
    return bool(item.immich_id and item.state == 'ready')


def is_steam_thumbnail(path):
    return bool(path and Path(path).is_file())


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
        key = canonical_source(relative)
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
        group = groups.setdefault(key, {'path': '', 'mtime': 0, 'files': 0, 'sent': 0, 'manifest': False, 'mp4': False, 'game_id': '', 'sessions': set()})
        group['sessions'].update(SESSION_ID_RE.findall(rel))
        group['files'] += 1
        group['sent'] += int(sent.get(rel) == fingerprint(path, stat))
        group['mtime'] = max(group['mtime'], stat.st_mtime)
        detected_game, _ = _game_and_datetime(rel, stat.st_mtime)
        if detected_game and not group['game_id']:
            group['game_id'] = detected_game
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
        group = groups.setdefault(key, {'path': '', 'mtime': item.get('updated_at', 0), 'files': 0, 'sent': 0, 'manifest': True, 'mp4': False, 'game_id': '', 'sessions': set()})
        group['sessions'].update(SESSION_ID_RE.findall(item.get('source', '')))
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
        game_id = group.get('game_id') or game_id
        game_name = item.get('game_name') or steam_names().get(game_id)
        if game_name:
            media_label = 'Game Clip' if '/clips/' in key else 'Game Recording' if kind == 'video' else 'Screenshot'
            name = f'{game_name} {media_label}'
        thumbnail = find_steam_thumbnail(group['path']) if kind == 'video' else group['path']
        result.append(MediaItem(key=key, name=name, kind=kind, state=state,
                                local_path=group['path'], immich_id=immich_id, source=key,
                                updated=timestamp, error=item.get('error', ''),
                                subtitle=subtitle, thumbnail=thumbnail, game_id=game_id, session_ids=tuple(sorted(group['sessions']))))
    # Steam copies an fg/bg session into clips when a clip is saved. Prefer
    # the saved, Immich-ready clip over an identically-sourced temporary session.
    clipped_sessions = {sid for capture in result
                        if '/clips/' in capture.key and capture.state == 'ready'
                        for sid in capture.session_ids}
    if clipped_sessions:
        result = [capture for capture in result
                  if '/clips/' in capture.key or
                  not set(capture.session_ids).intersection(clipped_sessions)]
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
