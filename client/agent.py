#!/usr/bin/env python3
"""Steam Personal Cloud sender. Python standard library only."""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import logging
import os
from pathlib import Path
import sqlite3
import ssl
import time
from urllib.parse import quote, urlsplit

LOG = logging.getLogger('spc-agent')
EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.m4s', '.mpd', '.pb', '.mp4'}
CHUNK = 256 * 1024


def discover(screenshot_root: Path, recording_root: Path, settle_seconds: int):
    """Yield (absolute_file, remote_name, file_stat) for eligible settled captures."""
    now = time.time()
    for root, prefix in ((screenshot_root, 'screenshots'), (recording_root, 'recordings')):
        if not root.is_dir():
            continue
        for parent, dirs, names in os.walk(root, followlinks=False):
            dirs[:] = [d for d in dirs if not (Path(parent) / d).is_symlink()]
            for name in sorted(names):
                path = Path(parent) / name
                if path.suffix.lower() not in EXTENSIONS or path.is_symlink():
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                if not path.is_file() or stat.st_size == 0 or now - stat.st_mtime < settle_seconds:
                    continue
                remote = prefix + '/' + path.relative_to(root).as_posix()
                yield path, remote, stat


def fingerprint(path: Path, stat):
    return f'{stat.st_size}:{stat.st_mtime_ns}'


def sha256_file(path: Path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def send_file(base_url: str, token: str, client: str, account: str,
              path: Path, remote: str, stat, sha256: str, rate_mib: float):
    url = urlsplit(base_url)
    if url.scheme not in {'http', 'https'} or not url.hostname or url.query or url.fragment:
        raise ValueError('Server URL must be an HTTP(S) origin, optionally with a base path')
    if url.username or url.password:
        raise ValueError('Credentials in server URLs are not supported')
    request_path = (url.path.rstrip('/') + '/api/files/' + quote(client, safe='') + '/'
                    + quote(account, safe='') + '/' + quote(remote, safe='/'))
    conn_type = http.client.HTTPSConnection if url.scheme == 'https' else http.client.HTTPConnection
    conn = conn_type(url.hostname, url.port, timeout=180)
    try:
        conn.putrequest('PUT', request_path)
        for key, value in {
            'Content-Length': str(stat.st_size), 'X-SPC-Token': token,
            'X-SPC-SHA256': sha256, 'X-SPC-Modified': str(stat.st_mtime),
            'Content-Type': 'application/octet-stream',
        }.items():
            conn.putheader(key, value)
        conn.endheaders()
        with path.open('rb') as f:
            sent = 0
            start = time.monotonic()
            while True:
                data = f.read(CHUNK)
                if not data:
                    break
                conn.send(data)
                sent += len(data)
                if rate_mib > 0:
                    deadline = sent / (rate_mib * 1024 * 1024)
                    remaining = deadline - (time.monotonic() - start)
                    if remaining > 0:
                        time.sleep(remaining)
        response = conn.getresponse()
        body = response.read(2048).decode('utf-8', errors='replace')
        if response.status not in (200, 201):
            raise RuntimeError(f'HTTP {response.status}: {body[:200]}')
    finally:
        conn.close()


def sync(config: dict):
    state = Path(config.get('state_dir', '~/.local/state/steam-personal-cloud')).expanduser()
    state.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(state / 'agent.sqlite3') as db:
        db.execute('CREATE TABLE IF NOT EXISTS sent (remote TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, sha TEXT NOT NULL)')
        ok, skipped, failed = 0, 0, 0
        for path, remote, stat in discover(Path(config['screenshots']).expanduser(),
                                           Path(config['recordings']).expanduser(),
                                           int(config.get('settle_seconds', 45))):
            fp = fingerprint(path, stat)
            row = db.execute('SELECT fingerprint FROM sent WHERE remote=?', (remote,)).fetchone()
            if row and row[0] == fp:
                skipped += 1
                continue
            try:
                sha = sha256_file(path)
                if fingerprint(path, path.stat()) != fp:
                    LOG.info('Changed during hashing, retry later: %s', remote)
                    continue
                send_file(config['server'], config['token'], config['client_id'],
                          config['steam_account'], path, remote, stat, sha,
                          float(config.get('max_mib_per_second', 2)))
                if fingerprint(path, path.stat()) != fp:
                    LOG.info('Changed during transfer; will retry: %s', remote)
                    continue
                db.execute('INSERT INTO sent(remote,fingerprint,sha) VALUES(?,?,?) '
                           'ON CONFLICT(remote) DO UPDATE SET fingerprint=excluded.fingerprint,sha=excluded.sha',
                           (remote, fp, sha))
                db.commit()
                ok += 1
                LOG.info('Sent %s (%s bytes)', remote, stat.st_size)
            except (OSError, ValueError, RuntimeError, TimeoutError, ssl.SSLError) as exc:
                LOG.warning('Could not sync %s: %s', remote, exc)
                failed += 1
        LOG.info('Sync finished: %d sent, %d unchanged, %d failed', ok, skipped, failed)
        return failed == 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='~/.config/steam-personal-cloud/client.json')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    config_file = Path(args.config).expanduser()
    config = json.loads(config_file.read_text())
    for field in ('server', 'token', 'client_id', 'steam_account', 'screenshots', 'recordings'):
        if not config.get(field):
            parser.error(f'{field} missing from {config_file}')
    if not sync(config):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
