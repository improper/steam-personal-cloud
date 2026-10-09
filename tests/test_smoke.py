"""Small dependency-free sender contract tests; run `python3 -m unittest discover -s tests`."""
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest

MODULE = Path(__file__).resolve().parents[1] / 'client' / 'agent.py'
spec = importlib.util.spec_from_file_location('spc_agent', MODULE)
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


class AgentTests(unittest.TestCase):
    def test_discovery_skips_recent_and_unsupported_files(self):
        with TemporaryDirectory() as t:
            root = Path(t)
            shots = root / 'screenshots'
            videos = root / 'recordings'
            shots.mkdir()
            videos.mkdir()
            (shots / 'old.png').write_bytes(b'PNG')
            (shots / 'ignore.txt').write_bytes(b'skip')
            (videos / 'chunk.m4s').write_bytes(b'fragment')
            results = list(agent.discover(shots, videos, settle_seconds=0))
            self.assertEqual({r[1] for r in results}, {'screenshots/old.png', 'recordings/chunk.m4s'})
            self.assertEqual(list(agent.discover(shots, videos, settle_seconds=3600)), [])

    def test_fingerprint_content(self):
        with TemporaryDirectory() as t:
            f = Path(t) / 'a.png'
            f.write_bytes(b'test')
            self.assertEqual(len(agent.sha256_file(f)), 64)
            self.assertTrue(agent.fingerprint(f, f.stat()).startswith('4:'))

    def test_unlimited_upload_does_not_throttle(self):
        from unittest.mock import patch
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'capture.png'
            path.write_bytes(b'PNG')
            class FakeResponse:
                status = 201
                def read(self, size):
                    return b'{}'
            class FakeConnection:
                def __init__(self, *args, **kwargs):
                    self.chunks = []
                def putrequest(self, *args): pass
                def putheader(self, *args): pass
                def endheaders(self): pass
                def send(self, data):
                    self.chunks.append(data)
                def getresponse(self):
                    return FakeResponse()
                def close(self): pass
            with patch.object(agent.http.client, 'HTTPConnection', FakeConnection), patch.object(agent.time, 'sleep') as sleeper:
                agent.send_file('http://example.test:8787', 'token', 'gamecenter', '728364463', path, 'screenshots/capture.png', path.stat(), agent.sha256_file(path), 0)
                sleeper.assert_not_called()

if __name__ == '__main__':
    unittest.main()
