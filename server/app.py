"""Steam Personal Cloud receiver, processing queue, and gamepad-friendly dashboard."""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
import requests

ROOT = Path(os.environ.get('SPC_DATA_DIR', '/data'))
TOKEN = os.environ.get('SPC_TOKEN', '')
IMMICH_URL = os.environ.get('IMMICH_URL', '').rstrip('/')
IMMICH_KEY = os.environ.get('IMMICH_API_KEY', '')
ALBUM = os.environ.get('IMMICH_ALBUM', 'Game Center')
IDLE_SECONDS = int(os.environ.get('SPC_IDLE_SECONDS', '600'))
WORKER_INTERVAL = int(os.environ.get('SPC_WORKER_INTERVAL', '30'))
MAX_FILE_BYTES = int(os.environ.get('SPC_MAX_UPLOAD_MB', '128')) * 1024 * 1024
ID_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$')
EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.mpd', '.m4s', '.pb', '.mp4'}
MEDIA_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp'}
shutdown_event = threading.Event()
process_lock = threading.Lock()


def db_open():
    ROOT.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(ROOT / 'state.sqlite3', timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('''CREATE TABLE IF NOT EXISTS files (
        path TEXT PRIMARY KEY, client TEXT NOT NULL, account TEXT NOT NULL,
        sha TEXT NOT NULL, size INTEGER NOT NULL, original_mtime REAL NOT NULL,
        received_at REAL NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS media (
        key TEXT PRIMARY KEY, client TEXT NOT NULL, account TEXT NOT NULL,
        source TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL,
        fingerprint TEXT NOT NULL DEFAULT '', immich_id TEXT,
        error TEXT NOT NULL DEFAULT '', updated_at REAL NOT NULL,
        retry_at REAL NOT NULL DEFAULT 0)''')
    db.commit()
    return db


def authorize(token: Optional[str]):
    if not TOKEN or not token or not hmac.compare_digest(TOKEN, token):
        raise HTTPException(401, 'Invalid personal cloud token')


def valid_path(client: str, account: str, rel: str):
    if not ID_RE.fullmatch(client) or not ID_RE.fullmatch(account):
        raise HTTPException(400, 'Invalid client or account identifier')
    if len(rel) > 512 or '\\' in rel or '\x00' in rel:
        raise HTTPException(400, 'Invalid file path')
    p = PurePosixPath(rel)
    if not rel or rel.startswith('/') or any(part in ('.', '..', '') for part in rel.split('/')):
        raise HTTPException(400, 'Invalid file path')
    if p.parts[0] not in ('screenshots', 'recordings') or len(p.parts) < 2 or p.suffix.lower() not in EXTENSIONS:
        raise HTTPException(400, 'File type/location not accepted')
    if p.parts[0] == 'screenshots' and p.suffix.lower() not in MEDIA_EXTENSIONS:
        raise HTTPException(400, 'Invalid screenshot extension')
    return f'{client}/{account}/{rel}'


def register_media(db, client, account, rel, now):
    if rel.startswith('screenshots/'):
        kind = 'screenshot'
        source = f'{client}/{account}/{rel}'
        key = source
    elif rel.endswith('/session.mpd'):
        kind = 'video'
        source = f'{client}/{account}/{rel.rsplit("/", 1)[0]}'
        key = source
    else:
        return
    db.execute('''INSERT INTO media(key,client,account,source,kind,status,updated_at)
        VALUES(?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET
        status=CASE WHEN media.status='complete' THEN 'complete' ELSE 'queued' END,
        updated_at=excluded.updated_at''',
        (key, client, account, source, kind, 'queued', now))


def ensure_recording_index(db, client, account, rel, now):
    # When a fragment arrives AFTER a manifest we must invalidate a previously complete
    # processing state; never remove the previous Immich upload.
    if not rel.startswith('recordings/') or rel.endswith('/session.mpd'):
        return
    session = rel.rsplit('/', 1)[0]
    key = f'{client}/{account}/{session}'
    db.execute("UPDATE media SET status='queued', updated_at=?, retry_at=0 "
               "WHERE key=? AND status='complete'", (now, key))


def upsert_file(db, client, account, rel, sha, size, mtime, timestamp):
    full = f'{client}/{account}/{rel}'
    prior = db.execute('SELECT sha FROM files WHERE path=?', (full,)).fetchone()
    # Refresh last-seen only when CONTENT changes; identical retries are idempotent.
    if prior is not None and prior['sha'] == sha:
        return False
    db.execute('''INSERT INTO files(path,client,account,sha,size,original_mtime,received_at)
        VALUES (?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET
        sha=excluded.sha,size=excluded.size,original_mtime=excluded.original_mtime,
        received_at=excluded.received_at''', (full, client, account, sha, size, mtime, timestamp))
    register_media(db, client, account, rel, timestamp)
    ensure_recording_index(db, client, account, rel, timestamp)
    if rel.startswith('screenshots/'):
        db.execute("UPDATE media SET status='queued', retry_at=0 WHERE key=?", (full,))
    return True


def immich_request(method, endpoint, **kwargs):
    if not IMMICH_URL or not IMMICH_KEY:
        raise RuntimeError('Immich integration is not configured')
    response = requests.request(method, IMMICH_URL + '/api' + endpoint,
                                headers={'x-api-key': IMMICH_KEY, 'Accept': 'application/json'},
                                timeout=(10, 1800), **kwargs)
    response.raise_for_status()
    return response.json() if response.content else None


def capture_time(source: str, mtime: float, kind: str):
    if kind == 'video':
        # Steam's fg_<game_id>_<YYYYMMDD>_<HHMMSS> folder uses UTC timestamps.
        match = re.search(r'(?:fg|bg)_\d+_(\d{8})_(\d{6})$', source)
        if match:
            try:
                return datetime.strptime(match[1] + match[2], '%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)
            except ValueError:
                pass
    return datetime.fromtimestamp(mtime, timezone.utc)


def game_id(source: str):
    match = re.search(r'(?:fg|bg)_(\d+)_\d{8}_\d{6}$', source)
    if not match:
        match = re.search(r'(\d+)_\d{14}_\d+\.(?:png|jpg|jpeg|webp)$', source)
    return match[1] if match else None


def tag_asset(asset_id: str, client: str, account: str, kind: str, source: str, capture: datetime):
    """Create tags from path segments using parentId; Immich tag names may not contain '/'."""
    paths = [('Steam',), ('Steam', 'Account', account), ('Steam', 'Client', client),
             ('Steam', 'Media', 'Screenshot' if kind == 'screenshot' else 'Video'),
             ('Steam', 'Date', capture.strftime('%Y'), capture.strftime('%m'), capture.strftime('%d'))]
    game = game_id(source)
    if game:
        paths.append(('Steam', 'Game', game))
    known = {tag['value']: tag['id'] for tag in immich_request('GET', '/tags')}
    ids = set()
    for parts in paths:
        for idx, part in enumerate(parts):
            key = '/'.join(parts[:idx + 1])
            if key not in known:
                parent = '/'.join(parts[:idx])
                created = immich_request('POST', '/tags', json={
                    'name': part, 'parentId': known[parent] if parent else None})
                known[key] = created['id']
        ids.add(known['/'.join(parts)])
    for tag_id in ids:
        immich_request('PUT', f'/tags/{tag_id}/assets', json={'ids': [asset_id]})


def upload_asset(file: Path, source: str, client: str, account: str, kind: str, capture: datetime, fingerprint: str):
    when = capture.isoformat(timespec='seconds')
    modified = datetime.fromtimestamp(file.stat().st_mtime, timezone.utc).isoformat(timespec='seconds')
    # Device asset id stays deterministic across retries and process restarts.
    stable_id = hashlib.sha256(f'{client}:{account}:{source}:{fingerprint}'.encode()).hexdigest()
    with file.open('rb') as stream:
        result = immich_request('POST', '/assets', data={
            'deviceAssetId': stable_id,
            'deviceId': f'steam-personal-cloud-{client}-{account}',
            'fileCreatedAt': when, 'fileModifiedAt': modified,
        }, files={'assetData': (file.name, stream)})
    asset_id = result.get('id')
    if not asset_id:
        raise RuntimeError(f'Immich upload returned no asset id: {result}')
    albums = immich_request('GET', '/albums')
    album = next((a for a in albums if a['albumName'] == ALBUM), None)
    if not album:
        album = immich_request('POST', '/albums', json={'albumName': ALBUM})
    immich_request('PUT', f"/albums/{album['id']}/assets", json={'ids': [asset_id]})
    tag_asset(asset_id, client, account, kind, source, capture)
    return asset_id


def set_status(db, key, status, *, fingerprint=None, asset_id=None, error='', retry=0):
    db.execute('''UPDATE media SET status=?,fingerprint=COALESCE(?,fingerprint),
        immich_id=COALESCE(?,immich_id), error=?, retry_at=?,updated_at=? WHERE key=?''',
        (status, fingerprint, asset_id, str(error)[:350], retry, time.time(), key))
    db.commit()


def fingerprint_session(db, source):
    rows = db.execute('SELECT path,sha,received_at,original_mtime,size FROM files '
                      'WHERE path LIKE ? ORDER BY path', (source + '/%',)).fetchall()
    h = hashlib.sha256()
    for row in rows:
        h.update((row['path'] + ':' + row['sha'] + '\n').encode())
    return h.hexdigest(), max((row['received_at'] for row in rows), default=0), len(rows)


def processing_once():
    """One serial worker iteration; retry failures after two minutes."""
    with process_lock, db_open() as db:
        rows = db.execute("SELECT * FROM media WHERE status!='complete' AND retry_at<=? "
                          'ORDER BY updated_at ASC LIMIT 12', (time.time(),)).fetchall()
        for row in rows:
            item = dict(row)
            key = item['key']
            source = ROOT / 'inbox' / item['source']
            tmp_output = None
            try:
                if item['kind'] == 'screenshot':
                    rec = db.execute('SELECT * FROM files WHERE path=?', (item['source'],)).fetchone()
                    if not rec or not source.is_file():
                        continue
                    fp = rec['sha']
                    input_path = source
                    capture = capture_time(item['source'], rec['original_mtime'], 'screenshot')
                else:
                    manifest = source / 'session.mpd'
                    if not manifest.is_file():
                        continue
                    fp, last_received, fragment_count = fingerprint_session(db, item['source'])
                    if fragment_count < 2 or time.time() - last_received < IDLE_SECONDS:
                        continue
                    capture = capture_time(item['source'], last_received, 'video')
                    temp_dir = ROOT / 'processing'
                    temp_dir.mkdir(parents=True, exist_ok=True)
                    fd, name = tempfile.mkstemp(suffix='.mp4', prefix='steam-', dir=temp_dir)
                    os.close(fd)
                    tmp_output = Path(name)
                    set_status(db, key, 'processing')
                    result = subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error',
                        '-nostdin', '-y', '-i', str(manifest), '-map', '0:v:0', '-map', '0:a:0?',
                        '-c', 'copy', '-movflags', '+faststart', str(tmp_output)],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1800)
                    if result.returncode or not tmp_output.exists() or tmp_output.stat().st_size == 0:
                        raise RuntimeError('ffmpeg remux failed: ' + result.stderr.decode(errors='replace')[-250:])
                    input_path = tmp_output
                set_status(db, key, 'uploading')
                asset_id = upload_asset(input_path, item['source'], item['client'],
                                        item['account'], item['kind'], capture, fp)
                set_status(db, key, 'complete', fingerprint=fp, asset_id=asset_id)
            except Exception as exc:
                set_status(db, key, 'error', error=str(exc), retry=time.time() + 120)
            finally:
                if tmp_output:
                    tmp_output.unlink(missing_ok=True)


def background_worker():
    while not shutdown_event.is_set():
        try:
            processing_once()
        except Exception as exc:
            print(f'Worker error: {exc}', flush=True)
        shutdown_event.wait(WORKER_INTERVAL)


@asynccontextmanager
async def lifespan(app):
    db_open().close()
    shutdown_event.clear()
    worker = threading.Thread(target=background_worker, daemon=True)
    worker.start()
    yield
    shutdown_event.set()
    worker.join(timeout=3)


app = FastAPI(title='Steam Personal Cloud', version='0.1.0', lifespan=lifespan)


@app.get('/health')
def health():
    return {'status': 'ok', 'immich_configured': bool(IMMICH_URL and IMMICH_KEY)}


@app.put('/api/files/{client}/{account}/{rel:path}')
async def receive(client: str, account: str, rel: str, request: Request,
                  x_spc_token: Optional[str] = Header(default=None),
                  x_spc_sha256: Optional[str] = Header(default=None),
                  x_spc_modified: Optional[str] = Header(default=None)):
    authorize(x_spc_token)
    identifier = valid_path(client, account, rel)
    if not x_spc_sha256 or not re.fullmatch('[0-9a-f]{64}', x_spc_sha256):
        raise HTTPException(400, 'SHA256 required')
    try:
        orig_mtime = float(x_spc_modified)
        if not 0 < orig_mtime < time.time() + 3600:
            raise ValueError()
    except (TypeError, ValueError):
        raise HTTPException(400, 'Invalid source modification time')
    try:
        length = int(request.headers.get('content-length', '-1'))
    except ValueError:
        length = -1
    if length <= 0 or length > MAX_FILE_BYTES:
        raise HTTPException(413, 'File exceeds limit or lacks valid length')
    destination = ROOT / 'inbox' / identifier
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.incoming-', dir=destination.parent)
    os.close(fd)
    staging = Path(name)
    size = 0
    checksum = hashlib.sha256()
    try:
        with staging.open('wb') as target:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    raise HTTPException(413, 'File too large')
                target.write(chunk)
                checksum.update(chunk)
        if size != length or checksum.hexdigest() != x_spc_sha256:
            raise HTTPException(422, 'Length/checksum mismatch')
        now = time.time()
        with db_open() as db:
            old = db.execute('SELECT sha FROM files WHERE path=?', (identifier,)).fetchone()
            if old is None or old['sha'] != x_spc_sha256 or not destination.exists():
                os.replace(staging, destination)
                os.utime(destination, (orig_mtime, orig_mtime))
            changed = upsert_file(db, client, account, rel, x_spc_sha256, size, orig_mtime, now)
            db.commit()
        return {'ok': True, 'changed': changed, 'path': identifier}
    finally:
        staging.unlink(missing_ok=True)


@app.get('/api/status')
def status(x_spc_token: Optional[str] = Header(default=None)):
    authorize(x_spc_token)
    with db_open() as db:
        rows = db.execute('SELECT client,account,kind,source,status,immich_id,error,updated_at FROM media '
                          'ORDER BY updated_at DESC LIMIT 150').fetchall()
        total_bytes = db.execute('SELECT COALESCE(SUM(size),0) FROM files').fetchone()[0]
        sources = db.execute('SELECT COUNT(*) FROM files').fetchone()[0]
    result = [dict(row) for row in rows]
    return {'items': result, 'files_backed_up': sources, 'bytes_backed_up': total_bytes,
            'counts': {s: sum(row['status'] == s for row in result) for s in
                       ('queued','processing','uploading','complete','error')}}


@app.get('/')
def dashboard():
    return FileResponse(Path(__file__).parent / 'dashboard.html')
