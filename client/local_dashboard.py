#!/usr/bin/env python3
"""Local client status and authenticated media proxy, on loopback only."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from local_status import local_snapshot, read_json

HOST = '127.0.0.1'
PORT = 18787
HTML = Path(__file__).with_name('local_dashboard.html')
MEDIA = re.compile(r'^/api/media/([0-9a-fA-F-]{36})/(thumb|preview|video)$')


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Deny remote host-header aliases; do not turn loopback into a DNS-rebinding proxy.
        if self.headers.get('Host', '').split(':')[0] not in ('127.0.0.1', 'localhost'):
            self.send_error(403)
            return
        match = MEDIA.fullmatch(self.path)
        if match:
            self.media(match)
            return
        if self.path in ('/', '/index.html'):
            data = HTML.read_bytes()
            typ = 'text/html; charset=utf-8'
        elif self.path == '/api/local-status':
            data = json.dumps(local_snapshot()).encode('utf-8')
            typ = 'application/json; charset=utf-8'
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', typ)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def media(self, match):
        config = read_json(Path.home() / '.config/steam-personal-cloud/client.json')
        if not isinstance(config, dict) or not config.get('server') or not config.get('token'):
            self.send_error(503, 'Not paired')
            return
        url = config['server'].rstrip('/') + '/api/media/' + match.group(1) + '/' + match.group(2)
        headers = {'X-SPC-Token': config['token']}
        if self.headers.get('Range') and match.group(2) == 'video':
            headers['Range'] = self.headers['Range']
        req = Request(url, headers=headers)
        try:
            with urlopen(req, timeout=30) as upstream:
                self.send_response(upstream.status)
                for key in ('Content-Type', 'Content-Length', 'Content-Range', 'Accept-Ranges'):
                    if upstream.headers.get(key):
                        self.send_header(key, upstream.headers[key])
                self.send_header('Cache-Control', 'private, no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.end_headers()
                while True:
                    chunk = upstream.read(128 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except HTTPError as exc:
            try:
                self.send_error(exc.code, 'Immich media unavailable')
            except OSError:
                pass
        except (URLError, OSError, TimeoutError):
            try:
                self.send_error(502, 'Media server unavailable')
            except OSError:
                pass

    def log_message(self, fmt, *args):
        pass


def serve():
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever(poll_interval=0.5)


if __name__ == '__main__':
    serve()
