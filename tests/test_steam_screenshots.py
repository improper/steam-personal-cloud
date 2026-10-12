"""Steam originals, exported copies, historical deletions and safe removal."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'client'))
import agent
import gallery_model as gallery
import steam_screenshots as steam


class SteamScreenshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / 'Steam'
        self.native = self.root / 'userdata/123/760/remote/220/screenshots/20261011011346_1.jpg'
        self.native.parent.mkdir(parents=True)
        self.native.write_bytes(b'original jpeg')
        self.thumb = self.native.parent / 'thumbnails' / self.native.name
        self.thumb.parent.mkdir()
        self.thumb.write_bytes(b'thumbnail')
        self.shots = self.base / 'exports'
        self.shots.mkdir()
        self.videos = self.base / 'recordings'
        self.videos.mkdir()
        self.export = self.shots / '220_20261011011346_1.png'
        self.config = dict(client_id='box', steam_account='123', server='http://test.invalid', token='test', screenshots=str(self.shots),
                           recordings=str(self.videos), state_dir=str(self.base / 'state'), settle_seconds=0)
        self.config_path = self.base / 'client.json'
        self.config_path.write_text(json.dumps(self.config))
        self.patch = patch.object(steam, 'steam_roots', return_value=[self.root])
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def model(self, status='deleted', source='screenshots/220_20261011011346_1.png'):
        snap = {'configured': True, 'remote': {'connected': True, 'items': [
            dict(source='box/123/' + source, status=status, immich_id='asset', updated_at=1)]}}
        with patch.object(gallery, 'local_snapshot', return_value=snap):
            return gallery.make_gallery(self.config_path)[0]

    def test_native_original_is_discovered_without_export_or_thumbnail_tile(self):
        rows = list(steam.discover_captures(self.config))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], self.native)
        self.assertIn('screenshots/steam/220/screenshots/', rows[0][1])
        self.assertEqual(agent.capture_game_name(rows[0][1]), agent.steam_game_names().get('220', ''))

    def test_new_native_capture_uploads(self):
        with patch.object(agent, 'send_file') as send:
            self.assertTrue(agent.sync(self.config))
        self.assertEqual(send.call_args.args[4], self.native)
        self.assertTrue(send.call_args.args[5].endswith('.jpg'))

    def test_missing_export_previously_deleted_from_immich_stays_locally_visible(self):
        items = self.model()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].state, 'deleted')
        self.assertEqual(items[0].local_path, str(self.native))
        self.assertFalse(items[0].immich_id)
        self.assertTrue(items[0].playable)
        self.assertEqual(gallery.local_removal_targets(items[0], self.config), [self.native, self.thumb])

    def test_export_and_native_are_one_capture_and_both_local_targets(self):
        self.export.write_bytes(b'full quality png')
        items = self.model('complete')
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].local_path, str(self.export))
        self.assertEqual(len(items[0].local_copies), 2)
        self.assertEqual(set(gallery.local_removal_targets(items[0], self.config)),
                         {self.export, self.native, self.thumb})
        # Only the full-quality export is uploaded; all originals appear in UI.
        self.assertEqual(len(list(steam.discover_captures(self.config))), 1)

    def test_deleted_capture_without_local_copies_is_hidden(self):
        self.native.unlink()
        self.assertEqual(self.model(), [])

    def test_previously_archived_export_does_not_resurrect_as_native_upload(self):
        state = Path(self.config['state_dir'])
        state.mkdir()
        with sqlite3.connect(state / 'agent.sqlite3') as db:
            db.execute('CREATE TABLE sent (remote TEXT PRIMARY KEY, fingerprint TEXT, sha TEXT)')
            db.execute('INSERT INTO sent VALUES (?, ?, ?)', ('screenshots/' + self.export.name, 'old', 'old'))
        with patch.object(agent, 'send_file') as send:
            self.assertTrue(agent.sync(self.config))
            send.assert_not_called()

    def test_native_removal_rejects_traversal_symlink_and_other_account(self):
        source = next(steam.native_screenshots(self.config))[1]
        with self.assertRaises(ValueError):
            steam.native_target(source.replace('220/', '../'), self.config, str(self.native))
        with self.assertRaises(ValueError):
            steam.native_target(source, dict(self.config, steam_account='456'), str(self.native))
        self.native.unlink()
        self.native.symlink_to(self.thumb)
        with self.assertRaises(ValueError):
            steam.native_target(source, self.config, str(self.native))

    def test_catalogue_historical_names_and_native_date(self):
        (self.root / 'userdata/123/760/screenshots.vdf').write_text(
            '"screenshots" { "shortcutnames" { "220" "A renamed game" } }')
        self.assertEqual(steam.catalogue_names()['220'], 'A renamed game')
        _, subtitle, game_id = gallery.pretty_title('screenshots/steam/220/screenshots/20261011011346_1.jpg', 1)
        self.assertEqual(game_id, '220')
        self.assertIn('1:13 AM', subtitle)

    def test_both_ready_remote_variants_are_matched_for_removal(self):
        snap = {'configured': True, 'remote': {'items': [
            dict(source='box/123/screenshots/' + self.export.name, status='complete', immich_id='png'),
            dict(source='box/123/screenshots/steam/220/screenshots/' + self.native.name,
                 status='complete', immich_id='jpg')]}}
        with patch.object(gallery, 'local_snapshot', return_value=snap):
            items, _ = gallery.make_gallery(self.config_path)
        self.assertEqual(len(items), 1)
        self.assertEqual(set(items[0].immich_copies), {'png', 'jpg'})


if __name__ == '__main__':
    unittest.main()
