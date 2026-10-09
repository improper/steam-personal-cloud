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

if __name__ == '__main__':
    unittest.main()
