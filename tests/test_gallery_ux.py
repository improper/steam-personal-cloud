"""Offscreen checks for spatial navigation, sparse grids and uncropped media."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'client'))
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication, QPushButton, QSlider
from PyQt6.QtTest import QTest
from gallery_app import Gallery, FitPhoto, STYLE
from gallery_model import MediaItem


class GalleryUXTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(STYLE)

    def setUp(self):
        self.refresh_patch = patch.object(Gallery, 'refresh')
        self.refresh_patch.start()
        self.gallery = Gallery()
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
