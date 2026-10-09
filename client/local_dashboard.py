#!/usr/bin/env python3
"""Loopback-only personal cloud dashboard. No remote dashboard token in browser code."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path

from local_status import local_snapshot

HOST = '127.0.0.1'
PORT = 18787
HTML = Path(__file__).with_name('local_dashboard.html')


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
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

    def log_message(self, format, *args):
        pass


def serve():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.serve_forever(poll_interval=1)


if __name__ == '__main__':
    serve()
