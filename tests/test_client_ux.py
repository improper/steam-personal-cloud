"""Basic compatibility tests for setup wizard and local library status."""
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'client'))
import setup
import local_status


class SetupTests(unittest.TestCase):
    def test_server_validation(self):
        self.assertEqual(setup.server_url('http://192.168.1.27:8787/'), 'http://192.168.1.27:8787')
        with self.assertRaises(ValueError):
            setup.server_url('javascript:alert(1)')
        with self.assertRaises(ValueError):
            setup.server_url('http://name:secret@example.com')

    def test_retry_pairing_without_reentering_details(self):
        class Agent:
            attempts = 0
            @classmethod
            def pair_device(cls, server, code, client, account):
                cls.attempts += 1
                if cls.attempts == 1:
                    raise RuntimeError('Expired code')
                return 'device-only-token'
        with patch.object(setup, 'choose', side_effect=['1', '1']), patch.object(setup, 'ask', side_effect=['expired', 'fresh']):
            token, server = setup.obtain_token(Agent, 'http://localhost:8787', 'client', 'account')
        self.assertEqual(token, 'device-only-token')
        self.assertEqual(Agent.attempts, 2)

    def test_existing_config_is_not_dropped(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / 'config.json'
            with patch.object(setup, 'CONFIG', p):
                old = dict(token='secret', server='http://localhost:8787')
                setup.write_config(old)
                setup.write_config(dict(old, server='http://localhost:9999'))
                self.assertEqual(json.loads(p.read_text())['token'], 'secret')
                self.assertTrue(p.with_suffix('.json.backup').exists())


class LocalStatusTests(unittest.TestCase):
    def test_pending_vs_backed_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            screenshots = d/'Screenshots'; screenshots.mkdir()
            videos = d/'Recordings'; videos.mkdir()
            first=screenshots/'image1.png';first.write_bytes(b'abc')
            second=screenshots/'image2.png';second.write_bytes(b'def')
            config_path=d/'client.json'
            config_path.write_text(json.dumps(dict(screenshots=str(screenshots), recordings=str(videos), client_id='demo', steam_account='123', server='http://127.0.0.1:8787', token='test', settle_seconds=0)))
            state=d/'state';state.mkdir()
            with sqlite3.connect(state/'agent.sqlite3') as db:
                db.execute('CREATE TABLE sent (remote TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, sha TEXT NOT NULL)')
                db.execute('INSERT INTO sent VALUES (?, ?, ?)', ('screenshots/image1.png', f'{first.stat().st_size}:{first.stat().st_mtime_ns}', 'hash'))
            data=local_status.local_snapshot(config_path, state, check_remote=False)
            self.assertEqual(data['local']['files'], 2)
            self.assertEqual(data['local']['sent'], 1)
            self.assertEqual(data['local']['pending'], 1)
            self.assertNotIn('token', json.dumps(data))

if __name__ == '__main__':
    unittest.main()

# Python unittest discovers the class above; these are additional manual integration checks.
