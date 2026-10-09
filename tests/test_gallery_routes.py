"""Gallery media authorization, ranged playback and safe Immich trash contracts."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from gallery_routes import register_gallery_routes

ID = '7b7f1213-579f-4444-8e03-0a1f4974ca74'


class FakeStream:
    status_code = 206
    headers = {'Content-Type':'video/mp4','Content-Range':'bytes 0-3/400','Content-Length':'4','Accept-Ranges':'bytes'}
    def iter_content(self, chunk_size): yield b'abcd'
    def close(self): pass


class GalleryRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.db = Path(self.tmp.name) / 'db.sqlite3'
        with sqlite3.connect(self.db) as conn:
            conn.execute('CREATE TABLE media (client TEXT, account TEXT, kind TEXT, status TEXT, immich_id TEXT, updated_at REAL)')
            conn.execute('INSERT INTO media VALUES (?,?,?,?,?,0)', ('gamecenter','123','video','complete',ID))
        @contextmanager
        def database():
            with sqlite3.connect(self.db) as conn:
                conn.row_factory = sqlite3.Row
                yield conn
        def authorize(token, client=None, account=None):
            if token == 'admin':return True
            if token == 'device' and (client is None or (client=='gamecenter' and account=='123')):return False
            raise HTTPException(401, 'Invalid device')
        self.trash_calls=[]
        def immich_request(method,url,**kwargs):
            self.trash_calls.append((method,url,kwargs))
        app=FastAPI()
        register_gallery_routes(app, authorize, database, 'http://immich.test:2283', 'SECRET', immich_request)
        self.client=TestClient(app)

    def tearDown(self): self.tmp.cleanup()

    def test_video_stream_forwards_range_without_exposing_key(self):
        with patch('gallery_routes.requests.get', return_value=FakeStream()) as get:
            response=self.client.get('/api/media/'+ID+'/video', headers={'X-SPC-Token':'device','Range':'bytes=0-3'})
        self.assertEqual(response.status_code,206)
        self.assertEqual(response.content,b'abcd')
        self.assertEqual(response.headers['content-range'],'bytes 0-3/400')
        self.assertEqual(get.call_args.kwargs['headers']['Range'],'bytes=0-3')
        self.assertNotIn('SECRET',response.text)

    def test_foreign_device_does_not_access_immich_media(self):
        result=self.client.get('/api/media/'+ID+'/thumb',headers={'X-SPC-Token':'other-device'})
        self.assertEqual(result.status_code,401)

    def test_deletion_trashes_not_permanently_erases(self):
        response=self.client.delete('/api/media/'+ID+'/immich',headers={'X-SPC-Token':'device'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.trash_calls,[('DELETE','/assets',{'json':{'ids':[ID],'force':False}})])
        response=self.client.get('/api/media/'+ID+'/thumb',headers={'X-SPC-Token':'device'})
        self.assertEqual(response.status_code,404)


if __name__=='__main__':unittest.main()
