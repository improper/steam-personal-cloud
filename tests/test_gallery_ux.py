"""Offscreen checks for spatial navigation, sparse grids and uncropped media."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import sys
import unittest
import tempfile
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'client'))
try:
    from PyQt6.QtCore import Qt, QSettings
    from PyQt6.QtGui import QPixmap
    from PyQt6.QtWidgets import QApplication, QPushButton, QSlider, QLabel
    from PyQt6.QtTest import QTest
    from gallery_app import Gallery, FitPhoto, STYLE
    from gallery_model import MediaItem
except ModuleNotFoundError as exc:
    if exc.name and exc.name.startswith('PyQt6'):
        raise unittest.SkipTest('Native UX tests run in the Qt CI job') from exc
    raise


class GalleryUXTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(STYLE)

    def setUp(self):
        self.refresh_patch = patch.object(Gallery, 'refresh')
        self.refresh_patch.start()
        self.settings_dir = tempfile.TemporaryDirectory()
        self.settings = QSettings(str(Path(self.settings_dir.name) / 'gallery.ini'), QSettings.Format.IniFormat)
        self.gallery = Gallery(settings=self.settings)
        self.gallery.timer.stop()
        self.gallery.gamepad_timer.stop()
        self.app.installEventFilter(self.gallery)
        self.app.processEvents()
        self.items = [MediaItem(f'screenshots/{i}.png', 'Clone Hero Screenshot',
                     'photo', 'waiting', '', '', f'screenshots/{i}.png', i)
                      for i in range(10)]

    def tearDown(self):
        self.app.removeEventFilter(self.gallery)
        if self.gallery.viewer:
            self.gallery.close_viewer()
        self.gallery.close()
        self.gallery.deleteLater()
        self.refresh_patch.stop()
        self.settings_dir.cleanup()

    def assert_controls_reachable(self, page):
        controls = [w for w in page.findChildren(QPushButton) + page.findChildren(QSlider) if w.isVisible() and w.isEnabled()]
        reached = {controls[0]}
        pending = [controls[0]]
        while pending:
            control = pending.pop()
            for direction in ('up', 'down', 'left', 'right'):
                self.gallery.focus_control(control)
                self.gallery.navigate(direction)
                target = self.app.focusWidget()
                if target not in reached:
                    reached.add(target)
                    pending.append(target)
        self.assertTrue(all(control in reached for control in controls))

    def test_sparse_grid_and_all_gallery_controls(self):
        for count in (0, 1, 2, 4, 10):
            self.gallery.items = self.items[:count]
            self.gallery.render()
            self.app.processEvents()
            self.assertTrue(all(tile.width() == 240 for tile in self.gallery.tiles.values()))
            tiles = list(self.gallery.tiles.values())
            for tile in tiles:
                labels = tile.findChildren(QLabel)
                self.assertTrue(all(label.y() >= tile.button.geometry().bottom() for label in labels))
            for index in range(self.gallery.columns, len(tiles)):
                self.assertGreater(tiles[index].y(), tiles[index - self.gallery.columns].geometry().bottom())
            self.assert_controls_reachable(self.gallery.gallery_page)
        self.assertIs(self.gallery.scroll.widget(), self.gallery.wrapper.parentWidget())

    def test_viewer_controls_and_keyboard_back(self):
        self.gallery.open_item(self.items[0])
        self.app.processEvents()
        self.assert_controls_reachable(self.gallery.viewer)
        QTest.keyClick(self.app.focusWidget(), Qt.Key.Key_Escape)
        self.assertFalse(self.gallery.viewing)
        self.assertIs(self.gallery.stack.currentWidget(), self.gallery.gallery_page)

    def test_video_and_removal_controls_are_reachable(self):
        item = MediaItem('recordings/test.mp4', 'Clone Hero Game Clip', 'video',
                         'waiting', '/missing.mp4', '', 'recordings/test.mp4', 1)
        self.gallery.open_item(item)
        self.app.processEvents()
        self.assert_controls_reachable(self.gallery.viewer)
        self.gallery.delete_dialog(item)
        self.app.processEvents()
        self.assert_controls_reachable(self.gallery.delete_page)
        remove = next(w for w in self.gallery.delete_page.findChildren(QPushButton)
                      if w.text() == 'Remove local copy')
        remove.click()
        self.app.processEvents()
        self.assert_controls_reachable(self.gallery.delete_page)
        self.gallery.on_gamepad('back')
        self.assertIsNone(self.gallery.delete_page)

    def test_filtered_sequence_boundaries_refresh_and_return_focus(self):
        self.gallery.items = self.items[:3] + [MediaItem('video', 'Video', 'video', 'waiting', '', '', 'video', 0)]
        self.gallery.select_filter('photo')
        self.gallery.open_item(self.items[0])
        self.app.processEvents()
        self.assertFalse(self.gallery.viewer.previous.isEnabled())
        self.assertEqual(self.gallery.viewer.counter.text(), '1 of 3')
        self.gallery.on_gamepad('previous')
        self.assertEqual(self.gallery.viewer_key, self.items[0].key)
        self.gallery.received(list(reversed(self.gallery.items)), {'configured': True})
        self.gallery.on_gamepad('next')
        self.assertEqual(self.gallery.viewer_key, self.items[1].key)
        self.gallery.on_gamepad('next')
        self.assertFalse(self.gallery.viewer.next.isEnabled())
        self.gallery.on_gamepad('next')
        self.assertEqual(self.gallery.viewer_key, self.items[2].key)
        self.gallery.close_viewer()
        self.app.processEvents()
        self.assertTrue(self.gallery.tiles[self.items[2].key].button.hasFocus())

    def test_hidden_controls_wake_without_activation_and_back_is_immediate(self):
        self.gallery.open_item(self.items[0])
        self.app.processEvents()
        pix = QPixmap(100, 100)
        pix.fill(Qt.GlobalColor.white)
        self.gallery.viewer.photo.original = pix
        self.gallery.viewer.hide_controls()
        self.assertTrue(self.gallery.viewer.hidden_controls)
        self.gallery.on_gamepad('select')
        self.assertFalse(self.gallery.viewer.hidden_controls)
        self.assertTrue(self.gallery.viewing)
        self.gallery.viewer.hide_controls()
        self.gallery.on_gamepad('back')
        self.assertFalse(self.gallery.viewing)

    def test_settings_persist_reset_and_all_controls_reachable(self):
        self.gallery.show_settings()
        self.app.processEvents()
        self.assert_controls_reachable(self.gallery.secondary_page)
        button, _ = self.gallery.setting_buttons['autoplay']
        button.click()
        self.assertFalse(self.gallery.preference('autoplay'))
        saved = QSettings(self.settings.fileName(), QSettings.Format.IniFormat)
        self.assertFalse(saved.value('autoplay', True, type=bool))
        volume = self.gallery.secondary_page.findChild(QSlider)
        self.gallery.focus_control(volume)
        self.gallery.navigate('left')
        self.assertEqual(self.gallery.preference('volume'), 75)
        reset = next(b for b in self.gallery.secondary_page.findChildren(QPushButton) if b.text() == 'Restore defaults')
        reset.click()
        self.assertEqual(self.gallery.preference('volume'), 80)
        self.assertTrue(self.gallery.preference('autoplay'))
        self.gallery.on_gamepad('back')
        self.assertIsNone(self.gallery.secondary_page)

    def test_space_never_activates_removal_and_secondary_page_blocks_shortcuts(self):
        self.gallery.open_item(self.items[0])
        self.app.processEvents()
        remove = next(b for b in self.gallery.viewer.findChildren(QPushButton) if b.text() == 'Remove…')
        remove.setFocus()
        QTest.keyClick(remove, Qt.Key.Key_Space)
        self.assertIsNone(getattr(self.gallery, 'delete_page', None))
        self.gallery.on_gamepad('details')
        self.app.processEvents()
        self.assertIsNotNone(self.gallery.secondary_page)
        self.assertIsNone(getattr(self.gallery, 'delete_page', None))
        key = self.gallery.viewer_key
        self.gallery.on_gamepad('next')
        self.gallery.on_gamepad('remove')
        self.assertEqual(self.gallery.viewer_key, key)
        self.assertIsNone(getattr(self.gallery, 'delete_page', None))
        self.gallery.on_gamepad('back')
        self.assertTrue(remove.hasFocus())

    def test_confirmation_defaults_to_cancel(self):
        item = MediaItem('photo', 'Photo', 'photo', 'waiting', '/missing.png', '', 'photo', 0)
        self.gallery.open_item(item)
        self.gallery.delete_dialog(item)
        remove = next(b for b in self.gallery.delete_page.findChildren(QPushButton) if b.text() == 'Remove local copy')
        remove.click()
        self.app.processEvents()
        self.assertEqual(self.app.focusWidget().text(), 'No, go back')
        self.gallery.on_gamepad('back')

    def test_async_photo_failure_retry_and_stale_response(self):
        item = MediaItem('photo', 'Photo', 'photo', 'ready', '', 'asset', 'photo', 0)
        with patch.object(self.gallery.pool, 'start') as start:
            self.gallery.open_item(item)
            viewer = self.gallery.viewer
            self.assertTrue(viewer.photo_loading)
            task = start.call_args.args[0]
            task.signals.failed.emit(item.key)
            self.assertTrue(viewer.failed)
            viewer.retry_media()
            self.assertEqual(start.call_count, 2)
            pix = QPixmap(200, 100)
            pix.fill(Qt.GlobalColor.white)
            from PyQt6.QtCore import QByteArray, QBuffer, QIODevice
            data = QByteArray()
            buffer = QBuffer(data)
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            pix.save(buffer, 'PNG')
            viewer.photo_ready(item.key, bytes(data))
            self.assertFalse(viewer.photo_loading)
            self.assertFalse(viewer.photo.original.isNull())
            self.gallery.close_viewer()
            viewer.photo_ready(item.key, b'invalid')
            self.assertTrue(viewer.closed)

    def test_playback_actions_volume_seek_replay_and_shutdown(self):
        from PyQt6.QtMultimedia import QMediaPlayer
        item = MediaItem('video', 'Video', 'video', 'waiting', '/missing.mp4', '', 'video', 0)
        self.gallery.set_preference('autoplay', False)
        self.gallery.open_item(item)
        self.app.processEvents()
        viewer = self.gallery.viewer
        real = viewer.player
        player = MagicMock()
        viewer.player = player
        viewer.seek.valueChanged.disconnect(real.setPosition)
        viewer.seek.valueChanged.connect(player.setPosition)
        player.playbackState.return_value = QMediaPlayer.PlaybackState.StoppedState
        player.mediaStatus.return_value = QMediaPlayer.MediaStatus.EndOfMedia
        viewer.toggle_play()
        player.setPosition.assert_called_with(0)
        player.play.assert_called_once()
        player.reset_mock()
        viewer.seek.setMaximum(60000)
        viewer.seek.setValue(20000)
        player.reset_mock()
        viewer.volume.setFocus()
        self.gallery.navigate('left')
        self.assertEqual(self.gallery.preference('volume'), 75)
        player.setPosition.assert_not_called()
        viewer.seek.setFocus()
        self.gallery.navigate('right')
        player.setPosition.assert_called_with(30000)
        self.gallery.show_settings()
        player.pause.assert_called_once()
        self.gallery.close_secondary()
        self.gallery.close_viewer()
        player.stop.assert_called_once()
        player.setSource.assert_called_once()
        real.stop()

    def test_raw_controller_buttons_route_to_distinct_actions(self):
        from gamepad_linux import JoystickReader, EVENT
        events = b''.join(EVENT.pack(0, 1, 1, number) for number in (0, 1, 2, 3, 4, 5, 7))
        actions = []
        with patch.object(JoystickReader, 'find_device'):
            reader = JoystickReader(actions.append)
        reader.fd = 123
        with patch('gamepad_linux.os.read', return_value=events):
            reader.poll()
        self.assertEqual(actions, ['select', 'back', 'play', 'details', 'previous', 'next', 'settings'])

    def test_loading_error_and_paused_video_keep_controls_visible(self):
        from PyQt6.QtMultimedia import QMediaPlayer
        item = MediaItem('video', 'Video', 'video', 'waiting', '/missing.mp4', '', 'video', 0)
        self.gallery.set_preference('autoplay', False)
        self.gallery.open_item(item)
        self.app.processEvents()
        viewer = self.gallery.viewer
        viewer.hide_controls()
        self.assertFalse(viewer.hidden_controls)
        viewer.playback_error(None, 'Codec unavailable')
        viewer.hide_controls()
        self.assertFalse(viewer.hidden_controls)
        self.assertTrue(viewer.retry.isVisible())
        self.assertIn('Codec unavailable', viewer.notice.text())
        viewer.media_status(QMediaPlayer.MediaStatus.EndOfMedia)
        self.assertEqual(viewer.play_button.text(), 'Replay')

    def test_viewer_fits_small_and_full_hd_with_long_title(self):
        from dataclasses import replace
        for width, height in ((1280, 720), (1920, 1080)):
            self.gallery.showNormal()
            self.gallery.resize(width, height)
            self.gallery.open_item(replace(self.items[0], name='A long game title with an expansion pack and a sequel'))
            self.app.processEvents()
            self.assertLessEqual(self.gallery.viewer.minimumSizeHint().width(), width)
            self.assertLessEqual(self.gallery.viewer.minimumSizeHint().height(), height)
            self.assert_controls_reachable(self.gallery.viewer)
            self.gallery.close_viewer()

    def test_complete_photo_fits_landscape_and_portrait_windows(self):
        pix = QPixmap(1600, 900)
        pix.fill(Qt.GlobalColor.white)
        photo = FitPhoto(pix)
        photo.show()
        for width, height in ((900, 650), (600, 900), (1920, 1080)):
            photo.resize(width, height)
            self.app.processEvents()
            fitted = photo.pixmap()
            self.assertLessEqual(fitted.width(), width)
            self.assertLessEqual(fitted.height(), height)
            self.assertAlmostEqual(fitted.width() / fitted.height(), 1600 / 900, delta=.01)
        photo.close()


if __name__ == '__main__':
    unittest.main()
