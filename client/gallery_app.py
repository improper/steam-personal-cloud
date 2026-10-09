#!/usr/bin/env python3
"""Native 10-foot Steam Personal Cloud gallery (PyQt6; no embedded browser)."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from urllib.error import URLError
from urllib.request import Request, urlopen

from PyQt6.QtCore import QObject, QRunnable, QSize, Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QImageReader, QPixmap, QFont
from PyQt6.QtWidgets import (QApplication, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QMainWindow, QMessageBox, QPushButton, QScrollArea, QSlider, QVBoxLayout, QWidget)
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget

from gallery_model import MediaItem, make_gallery, validate_local_target
from gamepad_linux import JoystickReader
from local_status import read_json

BASE = 'http://127.0.0.1:18787'
STYLE = '''
QWidget { color: #f3f7ff; background: #0d1523; font-family: "Noto Sans", "DejaVu Sans"; }
QMainWindow, QScrollArea, QScrollArea > QWidget > QWidget { background: #0d1523; }
QLabel#eyebrow { color: #89baff; font-size: 16px; font-weight: 700; }
QLabel#headline { color: #f7fbff; font-weight: 800; font-size: 34px; }
QLabel#subtitle, QLabel#hint { color: #9eb0c9; font-size: 15px; }
QLabel#summary { background: #19283c; color: #dceaff; padding: 11px 20px; border-radius: 14px; font-size: 16px; }
QPushButton { background: #233954; color: #e4f0ff; font-size: 18px; font-weight: 600; border: 2px solid #304b67; border-radius: 13px; padding: 11px 19px; }
QPushButton:focus { border: 3px solid #80ceff; background: #2d5476; }
QPushButton:hover { background: #355977; }
QPushButton#tile { background: #1a2a3f; text-align: center; padding: 10px; min-height: 166px; }
QPushButton#tile:focus { border: 4px solid #9ae6ff; background: #2e5775; }
QLabel#tileName { color: #e6f2ff; font-size: 18px; font-weight: 600; }
QLabel#detail { color: #9db2cc; font-size: 14px; }
QLabel#advanced { background: #17273b; padding: 16px; border-radius: 12px; font-size: 15px; }
QDialog { background: #0e1728; }
QSlider::groove:horizontal { height: 8px; background: #304056; border-radius: 4px; }
QSlider::handle:horizontal { background: #89d6ff; width: 20px; margin: -7px 0; border-radius: 9px; }
'''
BADGES = {
    'waiting': ('● Waiting to back up', '#e9ae63'),
    'backed_up': ('✓ Backed up', '#80bcff'),
    'processing': ('◔ Processing', '#c7a9ff'),
    'ready': ('✓ In Immich', '#82ddb4'),
    'error': ('! Needs attention', '#ff8b9a'),
    'deleted': ('○ Removed from Immich', '#adb4c1'),
}


def local_image(path, max_size=QSize(350, 190)):
    if not path or not Path(path).is_file():
        return QPixmap()
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    dimension = reader.size()
    if dimension.isValid():
        reader.setScaledSize(dimension.scaled(max_size, Qt.AspectRatioMode.KeepAspectRatio))
    image = reader.read()
    return QPixmap.fromImage(image) if not image.isNull() else QPixmap()


def media_url(item, variant):
    return f'{BASE}/api/media/{item.immich_id}/{variant}'


class SnapshotWorker(QThread):
    done = pyqtSignal(object, object)
    def run(self):
        try:
            self.done.emit(*make_gallery())
        except Exception as exc:
            self.done.emit([], {'configured': False, 'error': str(exc)})


class ImageSignals(QObject):
    ready = pyqtSignal(str, bytes)


class ImageTask(QRunnable):
    def __init__(self, key, url, signals):
        super().__init__()
        self.key, self.url, self.signals = key, url, signals

    def run(self):
        try:
            with urlopen(self.url, timeout=7) as response:
                content = response.read(4 * 1024 * 1024)
            self.signals.ready.emit(self.key, content)
        except (OSError, URLError, TimeoutError):
            pass


class Tile(QWidget):
    def __init__(self, item, on_open, parent=None):
        super().__init__(parent)
        self.item = item
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        self.button = QPushButton('▶  VIDEO' if item.kind == 'video' else '▣  SCREENSHOT')
        self.button.setObjectName('tile')
        self.button.setMinimumSize(226, 168)
        self.button.setIconSize(QSize(220, 144))
        self.button.clicked.connect(lambda: on_open(self.item))
        self.button.setAccessibleName(item.name + ', ' + BADGES.get(item.state, BADGES['waiting'])[0])
        layout.addWidget(self.button)
        title = QLabel(item.name.replace('_', ' ')[:36])
        title.setObjectName('tileName')
        title.setWordWrap(False)
        layout.addWidget(title)
        label, color = BADGES.get(item.state, BADGES['waiting'])
        status = QLabel(label)
        status.setStyleSheet(f'color:{color}; background:transparent; font-size:16px; font-weight:700;')
        layout.addWidget(status)
        if item.kind == 'photo' and item.local_path:
            self.set_preview(local_image(item.local_path))

    def set_preview(self, pix):
        if not pix.isNull():
            self.button.setIcon(QIcon(pix))
            self.button.setText('')


class Viewer(QDialog):
    def __init__(self, item, on_delete, parent):
        super().__init__(parent)
        self.item = item
        self.setWindowTitle(item.name)
        self.resize(1200, 800)
        outer = QVBoxLayout(self)
        top = QHBoxLayout()
        heading = QLabel(item.name.replace('_', ' '))
        heading.setObjectName('headline')
        top.addWidget(heading, 1)
        close = QPushButton('Back  Esc')
        close.clicked.connect(self.accept)
        top.addWidget(close)
        outer.addLayout(top)
        self.player = None
        if item.kind == 'photo':
            self.photo = QLabel()
            self.photo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.photo.setMinimumHeight(450)
            self.pix = local_image(item.local_path, QSize(2000, 1400)) if item.local_path else QPixmap()
            if self.pix.isNull() and item.immich_id and item.state == 'ready':
                try:
                    with urlopen(media_url(item, 'preview'), timeout=10) as response:
                        data = response.read(16 * 1024 * 1024)
                    self.pix.loadFromData(data)
                except (OSError, TimeoutError):
                    pass
            if self.pix.isNull():
                self.photo.setText('Preview not yet available')
            else:
                self.photo.setPixmap(self.pix.scaled(QSize(1050, 650), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            outer.addWidget(self.photo, 1)
        elif (item.immich_id and item.state == 'ready') or (item.local_path and item.local_path.lower().endswith('.mp4')):
            self.video = QVideoWidget()
            self.video.setMinimumHeight(420)
            outer.addWidget(self.video, 1)
            self.player = QMediaPlayer(self)
            self.audio = QAudioOutput(self)
            self.player.setAudioOutput(self.audio)
            self.player.setVideoOutput(self.video)
            self.player.setSource(QUrl(media_url(item, 'video')) if item.immich_id and item.state == 'ready' else QUrl.fromLocalFile(item.local_path))
            self.player.errorOccurred.connect(lambda _e, msg: self.notice.setText('Playback unavailable: ' + msg))
            self.seek = QSlider(Qt.Orientation.Horizontal)
            self.seek.setRange(0, 0)
            self.player.durationChanged.connect(lambda n: self.seek.setMaximum(max(0, n)))
            self.player.positionChanged.connect(self.seek.setValue)
            self.seek.sliderMoved.connect(self.player.setPosition)
            outer.addWidget(self.seek)
            play = QPushButton('Pause / Resume  Space')
            play.clicked.connect(self.toggle_play)
            outer.addWidget(play)
            self.player.play()
        else:
            message = QLabel('Video processing in progress.\nPlayback becomes available after Immich accepts the recording.')
            message.setObjectName('subtitle')
            message.setAlignment(Qt.AlignmentFlag.AlignCenter)
            outer.addWidget(message, 1)
        self.notice = QLabel(BADGES.get(item.state, BADGES['waiting'])[0])
        self.notice.setObjectName('detail')
        outer.addWidget(self.notice)
        delete = QPushButton('More actions · Delete…')
        delete.clicked.connect(lambda: on_delete(item, self))
        outer.addWidget(delete)

    def toggle_play(self):
        if self.player:
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self.player.pause()
            else:
                self.player.play()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self.toggle_play()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        if self.player:
            self.player.stop()
        super().closeEvent(event)


class Gallery(QMainWindow):
    def __init__(self, fullscreen=False):
        super().__init__()
        self.setWindowTitle('Steam Personal Cloud Gallery')
        self.resize(1600, 900)
        self.items = []
        self.tiles = {}
        self.signals = ImageSignals()
        self.signals.ready.connect(self.apply_thumbnail)
        self.pool = None
        from PyQt6.QtCore import QThreadPool as Pool
        self.pool = Pool.globalInstance()
        self.worker = None
        self.viewing = False
        self.filter = 'all'
        root = QWidget()
        self.setCentralWidget(root)
        self.layout = QVBoxLayout(root)
        self.layout.setContentsMargins(38, 22, 38, 24)
        self.layout.setSpacing(16)
        headline = QHBoxLayout()
        branding = QVBoxLayout()
        eyebrow = QLabel('YOUR CAPTURES  /  GAME CENTER')
        eyebrow.setObjectName('eyebrow')
        branding.addWidget(eyebrow)
        title = QLabel('Steam Personal Cloud')
        title.setObjectName('headline')
        branding.addWidget(title)
        subtitle = QLabel('Your screenshots and saved moments, all in one place.')
        subtitle.setObjectName('subtitle')
        branding.addWidget(subtitle)
        headline.addLayout(branding, 1)
        advanced = QPushButton('Details  ⚙')
        advanced.clicked.connect(self.toggle_advanced)
        headline.addWidget(advanced, 0, Qt.AlignmentFlag.AlignTop)
        self.layout.addLayout(headline)
        self.summary = QLabel('Loading your library…')
        self.summary.setObjectName('summary')
        self.layout.addWidget(self.summary)
        self.advanced = QLabel()
        self.advanced.setObjectName('advanced')
        self.advanced.setWordWrap(True)
        self.advanced.setVisible(False)
        self.layout.addWidget(self.advanced)
        actions = QHBoxLayout()
        self.filters = {}
        for key, label in [('all', 'All media'), ('photo', 'Screenshots'), ('video', 'Recordings')]:
            button = QPushButton(label)
            button.clicked.connect(lambda _=False, k=key: self.select_filter(k))
            self.filters[key] = button
            actions.addWidget(button)
        actions.addStretch(1)
        refresh = QPushButton('↻ Refresh')
        refresh.clicked.connect(self.refresh)
        actions.addWidget(refresh)
        self.layout.addLayout(actions)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.wrapper = QWidget()
        self.grid = QGridLayout(self.wrapper)
        self.grid.setSpacing(22)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.wrapper)
        self.layout.addWidget(self.scroll, 1)
        foot = QLabel('D-pad / arrows  Navigate       A / Enter  View       B / Esc  Back       Delete  Actions       R  Refresh')
        foot.setObjectName('hint')
        self.layout.addWidget(foot)
        self.gamepad = JoystickReader(self.on_gamepad)
        self.gamepad_timer = QTimer(self)
        self.gamepad_timer.timeout.connect(self.gamepad.poll)
        self.gamepad_timer.start(60)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(12000)
        QTimer.singleShot(80, self.refresh)
        if fullscreen:
            self.showFullScreen()
        else:
            self.showMaximized()

    def select_filter(self, key):
        self.filter = key
        self.render()

    def refresh(self):
        if self.worker is not None and self.worker.isRunning():
            return
        self.worker = SnapshotWorker(self)
        self.worker.done.connect(self.received)
        self.worker.start()

    def received(self, items, snap):
        if self.viewing:
            return
        self.items = items
        loc = snap.get('local', {})
        rem = snap.get('remote', {})
        counts = rem.get('counts', {})
        media_ready = counts.get('complete', 0)
        self.summary.setText(f"◉ {len(items)} memories     ·     ◔ {loc.get('pending', 0)} files waiting     ·     ✓ {loc.get('sent', 0)} backed-up files     ·     ✦ {media_ready} in Immich")
        result = snap.get('last_sync', {})
        details = [f"Server: {snap.get('server', 'Not configured')}  ({'Connected' if rem.get('connected') else 'Offline'})",
                   f"Capture folders: {snap.get('paths', {}).get('screenshots', '')}  |  {snap.get('paths', {}).get('recordings', '')}",
                   f"Last sync: {result.get('finished_at', 'No completed sync')} · Uploaded: {result.get('uploaded', 0)}, Failed: {result.get('failed', 0)}"]
        if snap.get('error') or rem.get('error') or result.get('last_error'):
            details.append('Attention: ' + str(snap.get('error') or rem.get('error') or result.get('last_error')))
        self.advanced.setText('\n'.join(details))
        signature = tuple((x.key, x.state, x.immich_id, x.local_path) for x in items if self.filter == 'all' or x.kind == self.filter)
        if signature != getattr(self, 'signature', None):
            self.signature = signature
            self.render()

    def render(self):
        focus_key = next((key for key, tile in self.tiles.items() if tile.button.hasFocus()), None)
        while self.grid.count():
            holder = self.grid.takeAt(0)
            if holder.widget():
                holder.widget().deleteLater()
        self.tiles = {}
        shown = [x for x in self.items if self.filter == 'all' or x.kind == self.filter]
        max_columns = max(3, min(6, max(1, self.width() - 70) // 260))
        for i, item in enumerate(shown):
            tile = Tile(item, self.open_item)
            self.grid.addWidget(tile, i // max_columns, i % max_columns)
            self.tiles[item.key] = tile
            if item.kind == 'photo' and not item.local_path and item.immich_id and item.state == 'ready':
                self.pool.start(ImageTask(item.key, media_url(item, 'thumb'), self.signals))
            elif item.kind == 'video' and item.immich_id and item.state == 'ready':
                self.pool.start(ImageTask(item.key, media_url(item, 'thumb'), self.signals))
        if not shown:
            empty = QLabel('No captures yet\nTake a Steam screenshot or save a gameplay recording to get started.')
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet('font-size: 23px; color:#9ebbd9; padding: 100px;')
            self.grid.addWidget(empty, 0, 0)
        if focus_key and focus_key in self.tiles:
            self.tiles[focus_key].button.setFocus()
        elif self.tiles:
            next(iter(self.tiles.values())).button.setFocus()

    def apply_thumbnail(self, key, data):
        tile = self.tiles.get(key)
        if not tile:
            return
        pix = QPixmap()
        if pix.loadFromData(data):
            tile.set_preview(pix)

    def toggle_advanced(self):
        self.advanced.setVisible(not self.advanced.isVisible())

    def open_item(self, item):
        self.viewing = True
        dialog = Viewer(item, self.delete_dialog, self)
        dialog.exec()
        self.viewing = False
        self.refresh()

    def delete_dialog(self, item, parent=None):
        config = read_json(Path.home() / '.config/steam-personal-cloud/client.json') or {}
        local = bool(item.local_path)
        remote = bool(item.immich_id and item.state == 'ready')
        if not local and not remote:
            QMessageBox.information(parent or self, 'Delete', 'No local copy or available Immich asset can be deleted.')
            return
        dialog = QDialog(parent or self)
        dialog.setWindowTitle('Remove capture')
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel('Choose where to remove this capture.\nLocal deletion moves the source into your Trash; Immich deletion moves it into Immich Trash.'))
        choices = []
        for key, title, enabled in [('local', 'Local copy only', local), ('immich', 'Immich copy only', remote), ('both', 'Both local and Immich copies', local and remote)]:
            if enabled:
                button = QPushButton(title)
                button.clicked.connect(lambda _=False, value=key: (choices.append(value), dialog.accept()))
                layout.addWidget(button)
        back = QPushButton('Cancel')
        back.clicked.connect(dialog.reject)
        layout.addWidget(back)
        if dialog.exec() != QDialog.DialogCode.Accepted or not choices:
            return
        choice = choices[0]
        confirm = QMessageBox.question(parent or self, 'Confirm deletion',
             'Remove "' + item.name + '" from ' + ('both destinations' if choice == 'both' else choice) + '?\n\nThis affects your original media. Are you sure?',
             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            if choice in ('immich', 'both'):
                req = Request(config['server'].rstrip('/') + '/api/media/' + item.immich_id + '/immich',
                              headers={'X-SPC-Token': config['token']}, method='DELETE')
                with urlopen(req, timeout=18) as response:
                    if response.status != 200:
                        raise RuntimeError('Server returned HTTP ' + str(response.status))
            if choice in ('local', 'both'):
                from gallery_trash import move_to_trash
                move_to_trash(validate_local_target(item, config))
            QMessageBox.information(parent or self, 'Removed', 'Capture removal completed. You can refresh the library now.')
            self.signature = None
        except Exception as exc:
            QMessageBox.warning(parent or self, 'Removal not complete', str(exc))
        self.refresh()

    def on_gamepad(self, action):
        dialog = QApplication.activeModalWidget()
        if dialog:
            if action == 'back':
                dialog.reject()
            elif action == 'select':
                focused = QApplication.focusWidget()
                if isinstance(focused, QPushButton):
                    focused.click()
                elif isinstance(dialog, Viewer):
                    dialog.toggle_play()
            return
        if action == 'details':
            self.toggle_advanced()
            return
        buttons = [tile.button for tile in self.tiles.values()]
        if action == 'select':
            focused = next((b for b in buttons if b.hasFocus()), buttons[0] if buttons else None)
            if focused:
                focused.click()
        elif action == 'back':
            if self.isFullScreen():
                self.showMaximized()
        elif action in ('up', 'down', 'left', 'right') and buttons:
            col = max(3, min(6, max(1, self.width() - 70) // 260))
            step = {'left': -1, 'right': 1, 'up': -col, 'down': col}[action]
            current = next((i for i, b in enumerate(buttons) if b.hasFocus()), 0)
            buttons[(current + step) % len(buttons)].setFocus()

    def eventFilter(self, watched, event):
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.KeyPress and QApplication.activeModalWidget() is None:
            if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_R, Qt.Key.Key_Delete):
                self.keyPressEvent(event)
                return True
        return super().eventFilter(watched, event)

    def closeEvent(self, event):
        self.timer.stop()
        self.gamepad_timer.stop()
        self.gamepad.close()
        if self.worker and self.worker.isRunning():
            self.worker.wait(3500)
        super().closeEvent(event)

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_R:
            self.refresh()
            return
        if key in (Qt.Key.Key_Down, Qt.Key.Key_Up, Qt.Key.Key_Left, Qt.Key.Key_Right):
            tiles = [x.button for x in self.tiles.values()]
            if tiles:
                current = next((i for i, b in enumerate(tiles) if b.hasFocus()), 0)
                stride = max(3, min(6, max(1, self.width() - 70) // 260))
                diff = {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1, Qt.Key.Key_Up: -stride, Qt.Key.Key_Down: stride}[key]
                tiles[(current + diff) % len(tiles)].setFocus()
                return
        if key == Qt.Key.Key_Delete:
            selected = next((k for k, b in self.tiles.items() if b.button.hasFocus()), None)
            if selected:
                self.delete_dialog(self.tiles[selected].item)
                return
        if key == Qt.Key.Key_Escape and self.isFullScreen():
            self.showMaximized()
            return
        super().keyPressEvent(event)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fullscreen', action='store_true')
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    gallery = Gallery(fullscreen=args.fullscreen)
    app.installEventFilter(gallery)
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
