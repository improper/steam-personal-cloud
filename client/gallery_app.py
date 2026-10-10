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
    QMainWindow, QMessageBox, QPushButton, QScrollArea, QSlider, QVBoxLayout, QWidget, QStackedWidget)
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
    'backed_up': ('◔ Preparing for Immich', '#80bcff'),
    'processing': ('◔ Processing', '#c7a9ff'),
    'ready': ('✓ Available in Immich', '#82ddb4'),
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
        title = QLabel(item.name[:48])
        title.setObjectName('tileName')
        title.setWordWrap(False)
        layout.addWidget(title)
        if item.subtitle:
            when = QLabel(item.subtitle)
            when.setObjectName('detail')
            layout.addWidget(when)
        label, color = BADGES.get(item.state, BADGES['waiting'])
        status = QLabel(label)
        status.setStyleSheet(f'color:{color}; background:transparent; font-size:16px; font-weight:700;')
        layout.addWidget(status)
        if item.thumbnail:
            self.set_preview(local_image(item.thumbnail))

    def set_preview(self, pix):
        if not pix.isNull():
            self.button.setIcon(QIcon(pix))
            self.button.setText('')


class Viewer(QWidget):
    """Inline media player: gallery stays inside ONE Xubuntu/Steam window."""
    def __init__(self, item, on_close, on_delete, parent=None):
        super().__init__(parent)
        self.item = item
        self.player = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 16, 28, 20)
        outer.setSpacing(14)
        top = QHBoxLayout()
        headings = QVBoxLayout()
        title = QLabel(item.name)
        title.setObjectName('headline')
        headings.addWidget(title)
        subtitle = QLabel(item.subtitle or 'Your capture')
        subtitle.setObjectName('subtitle')
        headings.addWidget(subtitle)
        top.addLayout(headings, 1)
        back = QPushButton('←  Back to gallery')
        back.clicked.connect(on_close)
        top.addWidget(back)
        outer.addLayout(top)
        self.notice = QLabel(BADGES.get(item.state, BADGES['waiting'])[0])
        self.notice.setObjectName('detail')
        self.notice.setWordWrap(True)
        if item.kind == 'photo':
            self.photo = QLabel()
            self.photo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.photo.setMinimumHeight(350)
            self.pix = local_image(item.local_path, QSize(2200, 1400)) if item.local_path else QPixmap()
            if item.immich_id and item.state == 'ready':
                try:
                    with urlopen(media_url(item, 'preview'), timeout=7) as response:
                        data = response.read(16 * 1024 * 1024)
                    immich_pix = QPixmap()
                    if immich_pix.loadFromData(data):
                        self.pix = immich_pix
                except (OSError, TimeoutError):
                    pass
            if self.pix.isNull():
                self.photo.setText('Preview is not available yet')
            else:
                self.photo.setPixmap(self.pix.scaled(QSize(1550, 720),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
            outer.addWidget(self.photo, 1)
        elif (item.immich_id and item.state == 'ready') or (item.local_path and item.local_path.lower().endswith('.mp4')):
            self.video = QVideoWidget(self)
            self.video.setMinimumHeight(340)
            outer.addWidget(self.video, 1)
            self.player = QMediaPlayer(self)
            self.audio = QAudioOutput(self)
            self.audio.setVolume(.8)
            self.player.setAudioOutput(self.audio)
            self.player.setVideoOutput(self.video)
            self.seek = QSlider(Qt.Orientation.Horizontal)
            self.seek.setRange(0, 0)
            self.player.durationChanged.connect(lambda value: self.seek.setMaximum(max(0, value)))
            self.player.positionChanged.connect(self.update_position)
            self.seek.sliderMoved.connect(self.player.setPosition)
            outer.addWidget(self.seek)
            controls = QHBoxLayout()
            rewind = QPushButton('−10s')
            rewind.clicked.connect(lambda: self.skip(-10000))
            controls.addWidget(rewind)
            self.play_button = QPushButton('Pause  ⏸')
            self.play_button.clicked.connect(self.toggle_play)
            controls.addWidget(self.play_button)
            forward = QPushButton('+10s')
            forward.clicked.connect(lambda: self.skip(10000))
            controls.addWidget(forward)
            self.position_label = QLabel('0:00 / 0:00')
            self.position_label.setObjectName('detail')
            controls.addWidget(self.position_label)
            controls.addStretch(1)
            outer.addLayout(controls)
            self.player.playbackStateChanged.connect(self.update_play_button)
            self.player.errorOccurred.connect(self.playback_error)
            self.player.setSource(QUrl(media_url(item, 'video')) if item.immich_id and item.state == 'ready'
                                  else QUrl.fromLocalFile(item.local_path))
            QTimer.singleShot(0, self.player.play)
            QTimer.singleShot(0, self.play_button.setFocus)
        else:
            message = QLabel('Waiting for Immich to prepare this recording.\nIt will become playable when video processing finishes.')
            message.setObjectName('subtitle')
            message.setAlignment(Qt.AlignmentFlag.AlignCenter)
            outer.addWidget(message, 1)
        outer.addWidget(self.notice)
        bottom = QHBoxLayout()
        more = QPushButton('More actions  ·  Remove…')
        more.clicked.connect(lambda: on_delete(item))
        bottom.addWidget(more)
        bottom.addStretch(1)
        outer.addLayout(bottom)

    def playback_error(self, error, message):
        self.notice.setText('Video cannot play yet: ' + (message or 'Immich may still be transcoding. Check Details for sync errors.'))

    def update_play_button(self, state):
        if self.player:
            self.play_button.setText('Pause  ⏸' if state == QMediaPlayer.PlaybackState.PlayingState else 'Play  ▶')

    def update_position(self, position):
        if self.player:
            self.seek.blockSignals(True)
            self.seek.setValue(position)
            self.seek.blockSignals(False)
            fmt = lambda n: f'{n // 60000}:{(n // 1000) % 60:02d}'
            self.position_label.setText(fmt(position) + ' / ' + fmt(self.player.duration()))

    def skip(self, millis):
        if self.player:
            self.player.setPosition(max(0, min(self.player.duration(), self.player.position() + millis)))

    def toggle_play(self):
        if self.player:
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self.player.pause()
            else:
                self.player.play()

    def shutdown(self):
        if self.player:
            self.player.stop()
            self.player.setSource(QUrl())


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
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.stack.addWidget(root)
        self.gallery_page = root
        self.viewer = None
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
        ready = sum(x.state == 'ready' for x in items)
        waiting = sum(x.state == 'waiting' for x in items)
        preparing = sum(x.state in ('backed_up', 'processing') for x in items)
        self.summary.setText(f"◉ {len(items)} captures     ·     ✦ {ready} in Immich     ·     ◔ {preparing} preparing     ·     ● {waiting} waiting")
        result = snap.get('last_sync', {})
        details = [f"Server: {snap.get('server', 'Not configured')}  ({'Connected' if rem.get('connected') else 'Offline'})",
                   f"Capture folders: {snap.get('paths', {}).get('screenshots', '')}  |  {snap.get('paths', {}).get('recordings', '')}",
                   f"Server received: {loc.get('sent', 0)} files · Immich processed: {media_ready} assets",
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
            # Prefer Immich's canonical thumbnail; local Steam art remains visible
            # immediately and survives an offline/processing thumbnail response.
            if item.immich_id and item.state == 'ready':
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
        self.viewer = Viewer(item, self.close_viewer, self.delete_dialog, self)
        self.stack.addWidget(self.viewer)
        self.stack.setCurrentWidget(self.viewer)

    def close_viewer(self):
        if self.viewer:
            self.viewer.shutdown()
            self.stack.setCurrentWidget(self.gallery_page)
            self.stack.removeWidget(self.viewer)
            self.viewer.deleteLater()
            self.viewer = None
        self.viewing = False
        self.refresh()

    def delete_dialog(self, item, parent=None):
        """Inline action sheet; never spawn a second Steam-focus window."""
        config = read_json(Path.home() / '.config/steam-personal-cloud/client.json') or {}
        local = bool(item.local_path)
        remote = bool(item.immich_id and item.state == 'ready')
        if not local and not remote:
            if self.viewer:
                self.viewer.notice.setText('This capture has no removable local or Immich copy.')
            return
        self.delete_page = QWidget()
        layout = QVBoxLayout(self.delete_page)
        layout.setContentsMargins(90, 60, 90, 60)
        layout.setSpacing(24)
        heading = QLabel('Remove capture')
        heading.setObjectName('headline')
        layout.addWidget(heading)
        what = QLabel(f'{item.name}  ·  {item.subtitle}')
        what.setObjectName('subtitle')
        layout.addWidget(what)
        self.delete_hint = QLabel('Choose where to remove this capture.\nLocal goes to your Xubuntu Trash; Immich goes to Immich Trash.\nThe original server inbox archive is retained.')
        self.delete_hint.setObjectName('subtitle')
        self.delete_hint.setWordWrap(True)
        layout.addWidget(self.delete_hint)
        self.delete_actions = QWidget()
        buttons = QVBoxLayout(self.delete_actions)
        layout.addWidget(self.delete_actions)
        layout.addStretch(1)
        cancel = QPushButton('←  Back to capture')
        cancel.clicked.connect(self.close_delete_page)
        layout.addWidget(cancel)
        for choice, label, enabled in [
            ('local', 'Remove local copy', local),
            ('immich', 'Move Immich copy to Trash', remote),
            ('both', 'Remove both copies', local and remote)]:
            if not enabled:
                continue
            button = QPushButton(label)
            button.clicked.connect(lambda _=False, c=choice: confirm(c))
            buttons.addWidget(button)

        def confirm(choice):
            self.delete_hint.setText(
                'Confirm removal from ' + ('both locations' if choice == 'both' else choice) +
                '.\nYour original local media may not be recoverable after Trash is emptied.')
            while buttons.count():
                item_layout = buttons.takeAt(0)
                if item_layout.widget():
                    item_layout.widget().deleteLater()
            yes = QPushButton('Yes, move to Trash')
            yes.clicked.connect(lambda: execute(choice))
            buttons.addWidget(yes)
            undo = QPushButton('No, go back')
            undo.clicked.connect(self.close_delete_page)
            buttons.addWidget(undo)
            yes.setFocus()

        def execute(choice):
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
            except Exception as exc:
                self.delete_hint.setText('Removal needs attention: ' + str(exc) +
                    '\nCheck Diagnostics before retrying; one location might have succeeded.')
                return
            self.close_delete_page()
            self.close_viewer()
            self.signature = None
            self.refresh()

        self.stack.addWidget(self.delete_page)
        self.stack.setCurrentWidget(self.delete_page)
        first = buttons.itemAt(0)
        if first and first.widget():
            first.widget().setFocus()

    def close_delete_page(self):
        page = getattr(self, 'delete_page', None)
        if page:
            self.stack.setCurrentWidget(self.viewer if self.viewer else self.gallery_page)
            self.stack.removeWidget(page)
            page.deleteLater()
            self.delete_page = None

    def on_gamepad(self, action):
        if getattr(self, 'delete_page', None) and self.stack.currentWidget() == self.delete_page:
            if action == 'back':
                self.close_delete_page()
            elif action == 'select':
                focused = QApplication.focusWidget()
                if isinstance(focused, QPushButton):
                    focused.click()
            elif action in ('up','down'):
                buttons = self.delete_page.findChildren(QPushButton)
                focused = QApplication.focusWidget()
                index = buttons.index(focused) if focused in buttons else 0
                if buttons:
                    buttons[(index + (1 if action == 'down' else -1)) % len(buttons)].setFocus()
            return
        if self.viewing and self.viewer:
            if action == 'back':
                self.close_viewer()
            elif action == 'select':
                focused = QApplication.focusWidget()
                if isinstance(focused, QPushButton) and self.viewer.isAncestorOf(focused):
                    focused.click()
                else:
                    self.viewer.toggle_play()
            elif action in ('left', 'right'):
                self.viewer.skip(-10000 if action == 'left' else 10000)
            elif action == 'details':
                self.delete_dialog(self.viewer.item)
            return
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
            if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down,
                               Qt.Key.Key_R, Qt.Key.Key_Delete, Qt.Key.Key_Escape, Qt.Key.Key_Backspace,
                               Qt.Key.Key_Space) and (self.viewing or event.key() in (
                                   Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down,
                                   Qt.Key.Key_R, Qt.Key.Key_Delete)):
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
        if getattr(self, 'delete_page', None) and self.stack.currentWidget() == self.delete_page:
            if key in (Qt.Key.Key_Escape, Qt.Key.Key_Backspace):
                self.close_delete_page()
                return
            if key in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right):
                buttons = self.delete_page.findChildren(QPushButton)
                focus = QApplication.focusWidget()
                index = buttons.index(focus) if focus in buttons else 0
                if buttons:
                    buttons[(index + (1 if key in (Qt.Key.Key_Down, Qt.Key.Key_Right) else -1)) % len(buttons)].setFocus()
                return
            return
        if self.viewing and self.viewer and self.stack.currentWidget() == self.viewer:
            if key in (Qt.Key.Key_Escape, Qt.Key.Key_Backspace):
                self.close_viewer()
                return
            if key == Qt.Key.Key_Space:
                self.viewer.toggle_play()
                return
            if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
                self.viewer.skip(-10000 if key == Qt.Key.Key_Left else 10000)
                return
            if key == Qt.Key.Key_Delete:
                self.delete_dialog(self.viewer.item)
                return
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
