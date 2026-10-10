"""Tests for native gallery's pure-Python model and reversible deletion."""
from pathlib import Path
import json
import os
import sqlite3
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'client'))

import gallery_model as gallery
from gallery_trash import move_to_trash


class GalleryTests(unittest.TestCase):
    def test_model_combines_local_and_remote_immich(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            shots = base / 'shots'
            videos = base / 'videos'
            shots.mkdir(); videos.mkdir()
            photo = shots / 'photo.png'
            photo.write_bytes(b'test')
            (videos / 'session1').mkdir()
            clip = videos / 'session1' / 'chunk.m4s'
            clip.write_bytes(b'fragment')
            (videos / 'session1' / 'session.mpd').write_text('<MPD />')
            conf = base / 'client.json'
            conf.write_text(json.dumps({'client_id':'testbox', 'steam_account':'user123',
                                        'screenshots':str(shots),'recordings':str(videos),
                                        'state_dir':str(base/'state'),'settle_seconds':0}))
            response = {'configured':True,'local':{'files':2,'sent':0,'pending':2},
                        'remote':{'connected':True,'counts':{'complete':1},'items':[
                            {'source':'testbox/user123/screenshots/photo.png',
                             'status':'complete','immich_id':'11111111-1111-1111-1111-111111111111',
                             'updated_at':123,'kind':'screenshot'},
                            {'source':'unrelated/different/screenshots/secret.png','status':'complete',
                             'immich_id':'22222222-2222-2222-2222-222222222222'}]}}
            with patch.object(gallery, 'local_snapshot', return_value=response):
                items, _ = gallery.make_gallery(conf)
            self.assertEqual(len(items),2)
            photo_item = next(i for i in items if i.kind == 'photo')
            video_item = next(i for i in items if i.kind == 'video')
            self.assertEqual(photo_item.state,'ready')
            self.assertTrue(photo_item.immich_id)
            self.assertEqual(video_item.state,'waiting')
            self.assertEqual(gallery.validate_local_target(photo_item,json.loads(conf.read_text())),photo)
            self.assertEqual(gallery.validate_local_target(video_item,json.loads(conf.read_text())),clip.parent)

    def test_clip_nested_fragments_are_one_video_and_ignore_recording_metadata(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            shots = base / 'shots'
            videos = base / 'videos'
            shots.mkdir(); videos.mkdir()
            (videos / 'gamerecording.pb').write_bytes(b'metadata')
            clip = videos / 'clips' / 'clip_220_20261009_193426' / 'video' / 'fg_220_20261009_193426'
            clip.mkdir(parents=True)
            (clip / 'session.mpd').write_text('<MPD />')
            (clip / 'a.m4s').write_bytes(b'first')
            (clip / 'b.m4s').write_bytes(b'second')
            config = base / 'client.json'
            config.write_text(json.dumps({'client_id': 'box', 'steam_account': 'steam',
                'screenshots': str(shots), 'recordings': str(videos),
                'state_dir': str(base/'state'), 'settle_seconds': 0}))
            snap = {'configured': True, 'local': {}, 'remote': {'connected': True, 'items': [
                {'source': 'box/steam/recordings/clips/clip_220_20261009_193426/video/fg_220_20261009_193426',
                 'kind': 'video', 'status': 'complete',
                 'immich_id': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                 'game_name': 'Test Game', 'updated_at': 9}]}}
            with patch.object(gallery, 'local_snapshot', return_value=snap):
                items, _ = gallery.make_gallery(config)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].name, 'Test Game')
            self.assertEqual(items[0].state, 'ready')
            self.assertEqual(items[0].source, 'recordings/clips/clip_220_20261009_193426')
            self.assertTrue(items[0].subtitle)

    def test_generic_recordings_are_not_phantom_videos(self):
        self.assertIsNone(gallery.canonical_recording('recordings/gamerecording.pb'))
        self.assertIsNone(gallery.canonical_recording('recordings/session.pb'))
        self.assertEqual(gallery.canonical_recording(
            'recordings/clips/clip_220_20261009_193426/video/fg_220_20261009_193426/session.mpd'),
            'recordings/clips/clip_220_20261009_193426')

    def test_saved_clip_supersedes_same_original_recording(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            shots, videos = base/'shots', base/'videos'
            shots.mkdir(); videos.mkdir()
            original = videos/'video'/'fg_220_20261009_193426'
            clip = videos/'clips'/'clip_220_20261009_194000'/'video'/'fg_220_20261009_193426'
            for folder in (original, clip):
                folder.mkdir(parents=True)
                (folder/'session.mpd').write_text('<MPD />')
                (folder/'chunk.m4s').write_bytes(b'm4s')
            conf = base/'client.json'
            conf.write_text(json.dumps({
                'client_id':'box','steam_account':'user',
                'screenshots':str(shots),'recordings':str(videos),
                'state_dir':str(base/'state'),'settle_seconds':0}))
            rows = [
                {'source':'box/user/recordings/video/fg_220_20261009_193426',
                 'status':'complete','immich_id':'11111111-1111-1111-1111-111111111111'},
                {'source':'box/user/recordings/clips/clip_220_20261009_194000/video/fg_220_20261009_193426',
                 'status':'complete','immich_id':'22222222-2222-2222-2222-222222222222'},
            ]
            snap = {'configured':True,'local':{},'remote':{'connected':True,'items':rows}}
            with patch.object(gallery,'local_snapshot',return_value=snap):
                items,_ = gallery.make_gallery(conf)
            self.assertEqual(len(items),1)
            self.assertIn('/clips/',items[0].key)
            self.assertEqual(items[0].immich_id,'22222222-2222-2222-2222-222222222222')

    def test_trash_preserves_capture_and_writes_recovery_metadata(self):
        with TemporaryDirectory() as directory:
            home = Path(directory)/'home'
            home.mkdir()
            capture = Path(directory)/'capture.png'
            capture.write_bytes(b'PNG123')
            moved = move_to_trash(capture,home=home)
            self.assertFalse(capture.exists())
            self.assertEqual(moved.read_bytes(),b'PNG123')
            info = home/'.local/share/Trash/info'/ (moved.name+'.trashinfo')
            self.assertIn('DeletionDate=', info.read_text())

    def test_rejects_root_or_symlink_delete(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)/'photos'
            root.mkdir()
            other = Path(directory)/'outside.png'
            other.write_bytes(b'not ours')
            link = root/'link.png'
            link.symlink_to(other)
            item = gallery.MediaItem('screenshots/link.png','link.png','photo','ready',str(link),'','screenshots/link.png',0)
            with self.assertRaises(ValueError):
                gallery.validate_local_target(item,{'screenshots':str(root),'recordings':str(root)})


if __name__ == '__main__': unittest.main()
