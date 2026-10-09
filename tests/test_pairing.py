"""Fast Connect integration tests with an isolated temporary SQLite data directory."""
from __future__ import annotations
import hashlib
import importlib.util
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

MODULE = Path(__file__).resolve().parents[1] / 'server' / 'app.py'
spec = importlib.util.spec_from_file_location('spc_server_for_tests', MODULE)
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class PairingTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.original_root, self.original_token = server.ROOT, server.TOKEN
        server.ROOT = Path(self.temp.name)
        server.TOKEN = 'admin-test-token'
        self.http = TestClient(server.app)

    def tearDown(self):
        self.http.close()
        server.ROOT, server.TOKEN = self.original_root, self.original_token
        self.temp.cleanup()

    def issue(self):
        resp = self.http.post('/api/pair/codes', headers={'X-SPC-Token': server.TOKEN})
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()['code']

    def test_pairing_redeem_once_and_scoped_upload(self):
        self.assertEqual(self.http.post('/api/pair/codes').status_code, 401)
        code = self.issue()
        payload = {'code': code, 'client_id': 'gamecenter', 'steam_account': '728364463'}
        resp = self.http.post('/api/pair/redeem', json=payload)
        self.assertEqual(resp.status_code, 200, resp.text)
        device_token = resp.json()['token']
        self.assertGreater(len(device_token), 32)
        self.assertEqual(self.http.post('/api/pair/redeem', json=payload).status_code, 401)
        self.assertEqual(self.http.get('/api/status', headers={'X-SPC-Token': device_token}).status_code, 200)
        data = b'png-test-image'
        h = {'X-SPC-Token': device_token, 'X-SPC-SHA256': hashlib.sha256(data).hexdigest(),
             'X-SPC-Modified': str(time.time()-200)}
        result = self.http.put('/api/files/gamecenter/728364463/screenshots/example.png',
                               headers=h, content=data)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.http.put('/api/files/gamecenter/another/screenshots/example.png',
                                       headers=h, content=data).status_code, 401)
        self.assertEqual(self.http.get('/api/pair/devices', headers={'X-SPC-Token': device_token}).status_code, 403)
        self.assertEqual(self.http.get('/api/pair/devices', headers={'X-SPC-Token': server.TOKEN}).status_code, 200)
        # End-to-end screenshot receiver -> worker -> completed record, without actual Immich.
        with patch.object(server, 'upload_asset', return_value='mock-immich-asset'):
            server.processing_once()
        status = self.http.get('/api/status', headers={'X-SPC-Token': device_token}).json()
        self.assertEqual(status['counts']['complete'], 1)
        self.assertEqual(status['items'][0]['immich_id'], 'mock-immich-asset')
        # A different account's media must not be visible with this device credential.
        master_headers = dict(h, **{'X-SPC-Token': server.TOKEN})
        other = self.http.put('/api/files/other/else/screenshots/private.png', headers=master_headers, content=data)
        self.assertEqual(other.status_code, 200)
        self.assertEqual(len(self.http.get('/api/status', headers={'X-SPC-Token': device_token}).json()['items']), 1)
        self.assertEqual(len(self.http.get('/api/status', headers={'X-SPC-Token': server.TOKEN}).json()['items']), 2)

    def test_code_expiration(self):
        code = self.issue()
        with server.database() as db:
            db.execute('UPDATE pairings SET expires_at=?', (time.time()-10,))
            db.commit()
        resp = self.http.post('/api/pair/redeem', json={
            'code': code, 'client_id': 'gamecenter', 'steam_account': '728364463'})
        self.assertEqual(resp.status_code, 401)


if __name__ == '__main__':
    unittest.main()
