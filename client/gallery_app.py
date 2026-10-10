#!/usr/bin/env python3
"""Native 10-foot Steam Personal Cloud gallery (PyQt6; no embedded browser)."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
from urllib.error import URLError
from urllib.request import Request, urlopen

from PyQt6.QtCore import QObject, QRunnable, QSize, Qt, QThread, QTimer, QUrl, QEvent, QSettings, pyqtSignal
from PyQt6.QtGui import QColor, QImageReader, QPixmap, QPainter
from PyQt6.QtWidgets import (QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QMainWindow, QPushButton, QScrollArea, QSlider, QVBoxLayout, QWidget, QStackedWidget, QProgressBar, QSizePolicy)
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
QPushButton:checked { background: #365f83; border-color: #89d6ff; }
QPushButton:checked:focus { border: 3px solid #d4f3ff; background: #2d5476; }
QPushButton:hover { background: #355977; }
QPushButton:disabled { color: #718299; background: #172437; border-color: #24364b; }
QPushButton#tile { background: #1a2a3f; text-align: center; padding: 0; }
QPushButton#tile:focus { border: 4px solid #9ae6ff; background: #2e5775; }
QLabel#tileName { color: #e6f2ff; font-size: 18px; font-weight: 600; }
QLabel#detail { color: #9db2cc; font-size: 14px; }
QLabel#advanced { background: #17273b; padding: 16px; border-radius: 12px; font-size: 15px; }
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
    failed = pyqtSignal(str)


class ImageTask(QRunnable):
    def __init__(self, key, url, signals, limit=4 * 1024 * 1024):
        super().__init__()
        self.key, self.url, self.signals = key, url, signals
        self.limit = limit

    def run(self):
        try:
            with urlopen(self.url, timeout=7) as response:
                content = response.read(self.limit)
        except (OSError, URLError, TimeoutError):
            try:
                self.signals.failed.emit(self.key)
            except RuntimeError:  # The owning page was closed while fetching.
                pass
            return
        try:
            self.signals.ready.emit(self.key, content)
        except RuntimeError:
            pass


class CoverButton(QPushButton):
    """Paint cover art to the inside edge of the focus border."""
    def __init__(self, text):
        super().__init__(text)
        self.cover = QPixmap()

    def paintEvent(self, event):
        if self.cover.isNull():
            return super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        border = 4 if self.hasFocus() else 2
        area = self.rect().adjusted(border, border, -border, -border)
        cover = self.cover.scaled(area.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                  Qt.TransformationMode.SmoothTransformation)
        painter.drawPixmap(area, cover, cover.rect().adjusted(
            (cover.width() - area.width()) // 2, (cover.height() - area.height()) // 2,
            -(cover.width() - area.width() + 1) // 2, -(cover.height() - area.height() + 1) // 2))
        painter.setPen(QColor('#9ae6ff' if self.hasFocus() else '#304b67'))
        for inset in range(border):
            painter.drawRect(self.rect().adjusted(inset, inset, -inset - 1, -inset - 1))


class FitPhoto(QLabel):
    """Keep the complete image visible as the viewer changes size."""
    def __init__(self, pix):
        super().__init__()
        self.original = pix
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(1, 1)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        if pix.isNull():
            self.setText('Preview is not available yet')

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self.original.isNull():
            self.setPixmap(self.original.scaled(self.contentsRect().size(),
                Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))


class Tile(QWidget):
    def __init__(self, item, on_open, parent=None):
        super().__init__(parent)
        self.item = item
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        self.button = CoverButton('▶  VIDEO' if item.kind == 'video' else '▣  SCREENSHOT')
        self.button.setObjectName('tile')
        self.button.setFixedHeight(168)
        self.button.setMinimumWidth(1)
        self.setFixedWidth(240)
        self.button.setIconSize(QSize(220, 144))
        self.button.clicked.connect(lambda: on_open(self.item))
        self.button.setAccessibleName(item.name + ', ' + item.kind + ', ' + BADGES.get(item.state, BADGES['waiting'])[0])
        layout.addWidget(self.button)
        media_type = QLabel('▶  VIDEO' if item.kind == 'video' else '▣  PHOTO')
        media_type.setObjectName('eyebrow')
        layout.addWidget(media_type)
        title = QLabel(item.name)
        title.setObjectName('tileName')
        title.setWordWrap(True)
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
        # A scroll area's first layout pass can otherwise compress tile rows
        # below their labels and make the cover overlap the metadata.
        self.setMinimumHeight(max(layout.sizeHint().height(), layout.totalHeightForWidth(240)))

    def set_preview(self, pix):
        if not pix.isNull():
            self.button.cover = pix
            self.button.setText('')
            self.button.update()


class Viewer(QWidget):
    """Single-window media stage with collapsible, controller-accessible chrome."""
    def __init__(self, item, on_close, on_delete, parent=None):
        super().__init__(parent)
        self.item, self.gallery = item, parent
        self.player = None
        self.closed = False
        self.photo_loading = False
        self.failed = False
        self.hidden_controls = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.idle = QTimer(self)
        self.idle.setSingleShot(True)
        self.idle.timeout.connect(self.hide_controls)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 16, 24, 16)
        outer.setSpacing(8)
        self.header = QWidget()
        top = QHBoxLayout(self.header)
        headings = QVBoxLayout()
        title = QLabel(item.name)
        title.setWordWrap(True)
        title.setObjectName('headline')
        headings.addWidget(title)
        subtitle = QLabel(item.subtitle or 'Your capture')
        subtitle.setObjectName('subtitle')
        headings.addWidget(subtitle)
        top.addLayout(headings, 1)
        back = QPushButton('Back to gallery')
        back.clicked.connect(on_close)
        top.addWidget(back)
        outer.addWidget(self.header)
        self.chrome = QWidget()
        lower = QVBoxLayout(self.chrome)
        self.notice = QLabel(BADGES.get(item.state, BADGES['waiting'])[0])
        self.notice.setObjectName('detail')
        self.notice.setWordWrap(True)
        self.buffering = QProgressBar()
        self.buffering.setRange(0, 0)
        self.buffering.setFixedHeight(8)
        self.buffering.hide()
        self.retry = QPushButton('Retry loading')
        self.retry.hide()
        self.retry.clicked.connect(self.retry_media)
        if item.kind == 'photo':
            self.photo = FitPhoto(local_image(item.local_path, QSize(2200, 1400)))
            outer.addWidget(self.photo, 1)
            self.image_signals = ImageSignals(self)
            self.image_signals.ready.connect(self.photo_ready)
            self.image_signals.failed.connect(self.photo_failed)
            self.load_photo()
        elif item.playable:
            self.video = QVideoWidget(self)
            self.video.setMinimumSize(1, 1)
            self.video.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
            self.video.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
            outer.addWidget(self.video, 1)
            self.player = QMediaPlayer(self)
            self.audio = QAudioOutput(self)
            self.player.setAudioOutput(self.audio)
            self.player.setVideoOutput(self.video)
            self.seek = QSlider(Qt.Orientation.Horizontal)
            self.seek.setAccessibleName('Playback position')
            self.seek.setRange(0, 0)
            self.seek.setSingleStep(10000)
            self.seek.valueChanged.connect(self.player.setPosition)
            self.player.durationChanged.connect(lambda value: self.seek.setMaximum(max(0, value)))
            self.player.positionChanged.connect(self.update_position)
            lower.addWidget(self.seek)
            controls = QHBoxLayout()
            for label, callback in [('−10s', lambda: self.skip(-10000)),
                                    ('Play', self.toggle_play), ('+10s', lambda: self.skip(10000))]:
                button = QPushButton(label)
                button.clicked.connect(callback)
                controls.addWidget(button)
                if label == 'Play':
                    self.play_button = button
            self.position_label = QLabel('0:00 / 0:00')
            controls.addWidget(self.position_label)
            self.mute_button = QPushButton('Mute')
            self.mute_button.clicked.connect(lambda: self.gallery.set_preference('muted', not self.gallery.preference('muted')))
            controls.addWidget(self.mute_button)
            lower.addLayout(controls)
            self.volume = QSlider(Qt.Orientation.Horizontal)
            self.volume.setRange(0, 100)
            self.volume.setSingleStep(5)
            self.volume.setAccessibleName('Volume')
            self.volume.valueChanged.connect(lambda value: self.gallery.set_preference('volume', value))
            volume_row = QHBoxLayout()
            volume_row.addWidget(QLabel('Volume'))
            volume_row.addWidget(self.volume)
            lower.addLayout(volume_row)
            self.player.playbackStateChanged.connect(self.update_play_button)
            self.player.errorOccurred.connect(self.playback_error)
            self.player.mediaStatusChanged.connect(self.media_status)
            self.apply_preferences()
            self.retry_media()
        else:
            message = QLabel('This recording is still being prepared.\nYou can browse other captures while it finishes.')
            message.setAlignment(Qt.AlignmentFlag.AlignCenter)
            message.setWordWrap(True)
            outer.addWidget(message, 1)
        lower.addWidget(self.buffering)
        lower.addWidget(self.notice)
        lower.addWidget(self.retry)
        navigation = QHBoxLayout()
        self.previous = QPushButton('Previous')
        self.previous.clicked.connect(lambda: self.gallery.step_capture(-1))
        self.next = QPushButton('Next')
        self.next.clicked.connect(lambda: self.gallery.step_capture(1))
        self.counter = QLabel()
        navigation.addWidget(self.previous)
        navigation.addWidget(self.counter)
        navigation.addWidget(self.next)
        navigation.addStretch(1)
        lower.addLayout(navigation)
        actions = QHBoxLayout()
        for label, callback in [('Details', self.gallery.show_details), ('Settings', self.gallery.show_settings),
                                ('Remove…', lambda: on_delete(item))]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            actions.addWidget(button)
        lower.addLayout(actions)
        hint = QLabel('A / Enter  Select   B / Esc  Back   X / Space  Play   LB/RB / PgUp/PgDn  Browse')
        hint.setWordWrap(True)
        hint.setObjectName('hint')
        lower.addWidget(hint)
        outer.addWidget(self.chrome)
        for child in self.findChildren(QWidget):
            child.setMouseTracking(True)
        self.reveal_controls()

    def apply_preferences(self):
        if self.player:
            self.audio.setVolume(self.gallery.preference('volume') / 100)
            self.audio.setMuted(self.gallery.preference('muted'))
            self.volume.blockSignals(True)
            self.volume.setValue(self.gallery.preference('volume'))
            self.volume.blockSignals(False)
            self.mute_button.setText('Unmute' if self.audio.isMuted() else 'Mute')

    def load_photo(self):
        if not (self.item.immich_id and self.item.state == 'ready'):
            return
        self.photo_loading = True
        self.failed = False
        self.retry.hide()
        self.notice.setText('Loading photo…')
        self.gallery.pool.start(ImageTask(self.item.key, media_url(self.item, 'preview'), self.image_signals, 16 * 1024 * 1024))

    def photo_ready(self, key, data):
        if self.closed:
            return
        pix = QPixmap()
        if not pix.loadFromData(data):
            self.photo_failed(key)
            return
        self.photo_loading = False
        self.failed = False
        self.retry.hide()
        self.photo.original = pix
        self.photo.setPixmap(pix.scaled(self.photo.contentsRect().size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.notice.setText('Available in Immich')
        self.reveal_controls()

    def photo_failed(self, key):
        if self.closed:
            return
        self.photo_loading = False
        self.failed = True
        self.notice.setText('Unable to load the Immich photo. Showing the local copy if available.')
        self.retry.show()
        self.reveal_controls()

    def retry_media(self):
        if not self.player:
            self.load_photo()
            return
        self.failed = False
        self.retry.hide()
        remote = self.item.immich_id and self.item.state == 'ready'
        self.notice.setText('Loading video…')
        self.buffering.show()
        self.player.setSource(QUrl(media_url(self.item, 'video')) if remote else QUrl.fromLocalFile(self.item.local_path))
        if self.gallery.preference('autoplay'):
            QTimer.singleShot(0, self.start_playback)

    def start_playback(self):
        if not self.closed and self.gallery.stack.currentWidget() is self:
            self.player.play()

    def playback_error(self, error, message):
        self.failed = True
        self.buffering.hide()
        self.notice.setText('Unable to play video: ' + (message or 'Check Details and try again.'))
        self.retry.show()
        self.reveal_controls()

    def media_status(self, status):
        loading = status in (QMediaPlayer.MediaStatus.LoadingMedia, QMediaPlayer.MediaStatus.BufferingMedia, QMediaPlayer.MediaStatus.StalledMedia)
        self.buffering.setVisible(loading)
        if loading:
            self.notice.setText('Loading video…' if status == QMediaPlayer.MediaStatus.LoadingMedia else 'Buffering video…')
        elif status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia):
            self.notice.setText('Ready to play')
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.notice.setText('Playback finished')
            self.play_button.setText('Replay')
        self.reveal_controls()

    def update_play_button(self, state):
        self.play_button.setText('Pause' if state == QMediaPlayer.PlaybackState.PlayingState else 'Play')
        if self.player.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia:
            self.play_button.setText('Replay')
        self.reveal_controls()

    def update_position(self, position):
        self.seek.blockSignals(True)
        self.seek.setValue(position)
        self.seek.blockSignals(False)
        def fmt(n):
            return f'{n // 60000}:{(n // 1000) % 60:02d}'
        self.position_label.setText(fmt(position) + ' / ' + fmt(self.player.duration()))

    def skip(self, millis):
        if self.player and self.player.isSeekable():
            self.player.setPosition(max(0, min(self.player.duration(), self.player.position() + millis)))

    def toggle_play(self):
        if self.player:
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self.player.pause()
            else:
                if self.player.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia:
                    self.player.setPosition(0)
                self.player.play()
        self.reveal_controls()

    def reveal_controls(self):
        was_hidden = self.hidden_controls
        self.hidden_controls = False
        self.header.show()
        self.chrome.show()
        self.idle.start(4000)
        if was_hidden:
            self.gallery.focus_control(self.play_button if self.player else self.previous if self.previous.isEnabled() else self.next if self.next.isEnabled() else self.header.findChild(QPushButton))
        return was_hidden

    def hide_controls(self):
        if (not self.gallery.preference('auto_hide') or self.closed or self.failed or self.photo_loading
                or self.gallery.stack.currentWidget() is not self):
            return
        if self.player and (self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState or self.buffering.isVisible()):
            return
        if self.item.kind != 'photo' and not self.player:
            return
        if self.item.kind == 'photo' and self.photo.original.isNull():
            return
        self.header.hide()
        self.chrome.hide()
        self.hidden_controls = True
        self.setFocus()

    def shutdown(self):
        self.closed = True
        self.idle.stop()
        if self.player:
            self.player.stop()
            self.player.setSource(QUrl())


class Gallery(QMainWindow):
    DEFAULTS = {'autoplay': True, 'auto_hide': True, 'volume': 80, 'muted': False, 'fullscreen': False}

    def __init__(self, fullscreen=False, settings=None):
        super().__init__()
        self.setWindowTitle('Steam Personal Cloud Gallery')
        self.resize(1600, 900)
        self.settings = settings if settings is not None else QSettings('SteamPersonalCloud', 'Gallery')
        self.secondary_page = None
        self.pending_snapshot = None
        self.snapshot = {}
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
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidget(root)
        self.stack.addWidget(self.scroll)
        self.gallery_page = self.scroll
        self.viewer = None
        self.layout = QVBoxLayout(root)
        self.layout.setContentsMargins(38, 22, 38, 24)
        self.layout.setSpacing(16)
        headline = QHBoxLayout()
        branding = QVBoxLayout()
        eyebrow = QLabel('YOUR CAPTURES  /  GAME CENTER')
        eyebrow.setObjectName('eyebrow')
        branding.addWidget(eyebrow)
        title = QLabel('Your captures')
        title.setObjectName('headline')
        branding.addWidget(title)
        subtitle = QLabel('Your screenshots and saved moments, all in one place.')
        subtitle.setObjectName('subtitle')
        branding.addWidget(subtitle)
        headline.addLayout(branding, 1)
        advanced = QPushButton('Details')
        advanced.clicked.connect(self.toggle_advanced)
        headline.addWidget(advanced, 0, Qt.AlignmentFlag.AlignTop)
        settings_button = QPushButton('Settings')
        settings_button.clicked.connect(self.show_settings)
        headline.addWidget(settings_button, 0, Qt.AlignmentFlag.AlignTop)
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
            button.setCheckable(True)
            button.setChecked(key == self.filter)
            self.filters[key] = button
            actions.addWidget(button)
        actions.addStretch(1)
        refresh = QPushButton('↻ Refresh')
        refresh.clicked.connect(self.refresh)
        actions.addWidget(refresh)
        self.layout.addLayout(actions)
        self.wrapper = QWidget()
        self.grid = QGridLayout(self.wrapper)
        self.grid.setSpacing(22)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.layout.addWidget(self.wrapper, 1)
        foot = QLabel('D-pad / arrows  Navigate    A / Enter  View    Y / I  Details    Menu / S  Settings    R  Refresh')
        foot.setWordWrap(True)
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
        if fullscreen or self.preference('fullscreen'):
            self.showFullScreen()
        else:
            self.showMaximized()

    def select_filter(self, key):
        self.filter = key
        for name, button in self.filters.items():
            button.setChecked(name == key)
        self.render()

    def refresh(self):
        if self.worker is not None and self.worker.isRunning():
            return
        self.worker = SnapshotWorker(self)
        self.worker.done.connect(self.received)
        self.worker.start()

    def received(self, items, snap):
        if self.viewing or self.secondary_page:
            self.pending_snapshot = (items, snap)
            return
        self.snapshot = snap
        if not items and snap.get('error') and self.items:
            items = self.items
        self.items = items
        loc = snap.get('local', {})
        rem = snap.get('remote', {})
        counts = rem.get('counts', {})
        media_ready = counts.get('complete', 0)
        ready = sum(x.state == 'ready' for x in items)
        waiting = sum(x.state == 'waiting' for x in items)
        preparing = sum(x.state in ('backed_up', 'processing') for x in items)
        status = ' · Server offline — local captures are available' if not rem.get('connected') else ''
        if not snap.get('configured', True):
            status = ' · Run steam-personal-cloud-setup to connect this device'
        self.summary.setText(f"{len(items)} captures  ·  {ready} in Immich  ·  {preparing} preparing  ·  {waiting} waiting{status}")
        self.summary.setWordWrap(True)
        result = snap.get('last_sync', {})
        details = [f"Server: {snap.get('server', 'Not configured')}  ({'Connected' if rem.get('connected') else 'Offline'})",
                   f"Capture folders: {snap.get('paths', {}).get('screenshots', '')}  |  {snap.get('paths', {}).get('recordings', '')}",
                   f"Server received: {loc.get('sent', 0)} files · Immich processed: {media_ready} assets",
                   f"Last sync: {result.get('finished_at', 'No completed sync')} · Uploaded: {result.get('uploaded', 0)}, Failed: {result.get('failed', 0)}"]
        if snap.get('error') or rem.get('error') or result.get('last_error'):
            details.append('Attention: ' + str(snap.get('error') or rem.get('error') or result.get('last_error')))
        self.advanced.setText('\n'.join(details))
        signature = tuple((x.key, x.state, x.immich_id, x.local_path, x.name, x.subtitle, x.thumbnail) for x in items if self.filter == 'all' or x.kind == self.filter)
        if signature != getattr(self, 'signature', None):
            self.signature = signature
            self.render()

    def render(self):
        focused = QApplication.focusWidget()
        focus_key = next((key for key, tile in self.tiles.items() if tile.button.hasFocus()), None)
        return_key = getattr(self, 'return_key', None)
        if not focus_key and return_key:
            focus_key = return_key
        while self.grid.count():
            holder = self.grid.takeAt(0)
            if holder.widget():
                holder.widget().hide()
                holder.widget().deleteLater()
        self.tiles = {}
        for row in range(self.grid.rowCount()):
            self.grid.setRowMinimumHeight(row, 0)
        shown = [x for x in self.items if self.filter == 'all' or x.kind == self.filter]
        max_columns = self.column_count()
        self.columns = max_columns
        for col in range(6):
            self.grid.setColumnStretch(col, 0)
            self.grid.setColumnMinimumWidth(col, 0)
        for i, item in enumerate(shown):
            tile = Tile(item, self.open_item)
            self.grid.addWidget(tile, i // max_columns, i % max_columns)
            self.tiles[item.key] = tile
            row = i // max_columns
            self.grid.setRowMinimumHeight(row, max(self.grid.rowMinimumHeight(row), tile.minimumHeight()))
            # Prefer Immich's canonical thumbnail; local Steam art remains visible
            # immediately and survives an offline/processing thumbnail response.
            if item.immich_id and item.state == 'ready':
                self.pool.start(ImageTask(item.key, media_url(item, 'thumb'), self.signals))
        if not shown:
            message = ('No captures in this filter\nChoose All media to see your other captures.' if self.items else
                       'Loading your library…' if not self.snapshot else
                       'No captures yet\nTake a Steam screenshot or save a gameplay recording to get started.')
            empty = QLabel(message)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet('font-size: 23px; color:#9ebbd9; padding: 40px;')
            self.grid.addWidget(empty, 0, 0)
        self.wrapper.setMinimumHeight(self.grid.minimumSize().height())
        self.wrapper.adjustSize()
        if focus_key and focus_key in self.tiles:
            self.tiles[focus_key].button.setFocus()
        elif self.tiles and (focused is None or focused is self.wrapper or focus_key):
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

    def preference(self, key):
        default = self.DEFAULTS[key]
        return self.settings.value(key, default, type=type(default))

    def set_preference(self, key, value):
        self.settings.setValue(key, value)
        self.settings.sync()
        if self.viewer:
            self.viewer.apply_preferences()
            self.viewer.reveal_controls()

    def toggle_fullscreen(self):
        self.showMaximized() if self.isFullScreen() else self.showFullScreen()

    def pause_viewer(self):
        if self.viewer:
            self.viewer.idle.stop()
            self.viewer.reveal_controls()
            if self.viewer.player:
                self.viewer.player.pause()

    def open_secondary(self, title):
        if self.secondary_page or getattr(self, 'delete_page', None):
            return None
        self.pause_viewer()
        self.secondary_return = self.stack.currentWidget()
        self.secondary_focus = QApplication.focusWidget()
        page = QScrollArea()
        page.setWidgetResizable(True)
        content = QWidget()
        page.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(40, 24, 40, 24)
        heading = QLabel(title)
        heading.setObjectName('headline')
        layout.addWidget(heading)
        self.secondary_page = page
        self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)
        return layout

    def finish_secondary(self, layout):
        back = QPushButton('Back')
        back.clicked.connect(self.close_secondary)
        layout.addWidget(back)
        back.setFocus()

    def close_secondary(self):
        page = self.secondary_page
        if not page:
            return
        self.stack.setCurrentWidget(self.secondary_return)
        self.stack.removeWidget(page)
        self.secondary_page = None
        page.deleteLater()
        if self.secondary_focus:
            self.focus_control(self.secondary_focus)
        if not self.viewer and self.pending_snapshot:
            items, snap = self.pending_snapshot
            self.pending_snapshot = None
            self.received(items, snap)

    def show_settings(self):
        layout = self.open_secondary('Settings')
        if layout is None:
            return
        self.setting_buttons = {}
        for key, label in [('autoplay', 'Autoplay videos'), ('auto_hide', 'Hide viewer controls'),
                           ('muted', 'Mute audio'), ('fullscreen', 'Launch fullscreen')]:
            button = QPushButton()
            button.setCheckable(True)
            def update_button(k=key, text=label, control=button):
                control.setChecked(self.preference(k))
                control.setText(text + (' · On' if self.preference(k) else ' · Off'))
            update_button()
            button.clicked.connect(lambda checked, k=key, update=update_button: (self.set_preference(k, checked), update()))
            self.setting_buttons[key] = (button, update_button)
            layout.addWidget(button)
        volume_label = QLabel()
        volume = QSlider(Qt.Orientation.Horizontal)
        volume.setRange(0, 100)
        volume.setSingleStep(5)
        volume.setValue(self.preference('volume'))
        volume.setAccessibleName('Volume')
        volume_label.setText(f'Volume · {volume.value()}%')
        volume.valueChanged.connect(lambda value: (self.set_preference('volume', value), volume_label.setText(f'Volume · {value}%')))
        layout.addWidget(volume_label)
        layout.addWidget(volume)
        fullscreen = QPushButton('Toggle fullscreen now · F11')
        fullscreen.clicked.connect(self.toggle_fullscreen)
        layout.addWidget(fullscreen)
        defaults = QPushButton('Restore defaults')
        def restore():
            for key, value in self.DEFAULTS.items():
                self.set_preference(key, value)
            for button, update in self.setting_buttons.values():
                update()
            volume.setValue(self.preference('volume'))
        defaults.clicked.connect(restore)
        layout.addWidget(defaults)
        controls = QLabel('Controls\nD-pad / arrows: navigate · A / Enter: select · B / Escape: back\nX / Space: play or pause · LB/RB / Page Up/Down: previous/next capture\nY / I: details · Menu / S: settings · F11: fullscreen · Tab: next control\nOn the seek bar, left/right skips 10 seconds. On volume, it adjusts 5%.\nSteam Input can map these keyboard shortcuts. Raw joystick mappings vary by controller.')
        controls.setWordWrap(True)
        controls.setObjectName('subtitle')
        layout.addWidget(controls)
        exit_button = QPushButton('Exit gallery')
        exit_button.clicked.connect(self.close)
        layout.addWidget(exit_button)
        self.finish_secondary(layout)

    def show_details(self):
        if not self.viewer:
            self.toggle_advanced()
            return
        layout = self.open_secondary('Capture details')
        if layout is None:
            return
        item = self.viewer.item
        text = QLabel(f'{item.name}\n{item.subtitle}\n{item.kind.title()} · {BADGES.get(item.state, BADGES["waiting"])[0]}\nLocal copy: {"Available" if item.local_path else "Unavailable"}\nImmich copy: {"Available" if item.immich_id and item.state == "ready" else "Unavailable"}' + (f'\nNeeds attention: {item.error}' if item.error else ''))
        text.setWordWrap(True)
        text.setObjectName('subtitle')
        layout.addWidget(text)
        self.finish_secondary(layout)

    def open_item(self, item):
        if self.viewer:
            return
        self.view_sequence = [x for x in self.items if self.filter == 'all' or x.kind == self.filter]
        if item.key not in [x.key for x in self.view_sequence]:
            self.view_sequence = [item]
        self.view_index = next(i for i, x in enumerate(self.view_sequence) if x.key == item.key)
        self.viewing = True
        self.show_capture()

    def show_capture(self):
        if self.viewer:
            old = self.viewer
            old.shutdown()
            self.stack.removeWidget(old)
            old.deleteLater()
        item = self.view_sequence[self.view_index]
        self.viewer_key = item.key
        self.viewer = Viewer(item, self.close_viewer, self.delete_dialog, self)
        self.viewer.counter.setText(f'{self.view_index + 1} of {len(self.view_sequence)}')
        self.viewer.previous.setEnabled(self.view_index > 0)
        self.viewer.next.setEnabled(self.view_index < len(self.view_sequence) - 1)
        self.stack.addWidget(self.viewer)
        self.stack.setCurrentWidget(self.viewer)
        self.focus_control(self.viewer.play_button if self.viewer.player else self.viewer.header.findChild(QPushButton))

    def step_capture(self, delta):
        if not self.viewer or self.stack.currentWidget() is not self.viewer:
            return
        target = self.view_index + delta
        if 0 <= target < len(self.view_sequence):
            self.view_index = target
            self.show_capture()

    def close_viewer(self):
        if self.secondary_page:
            self.close_secondary()
        if self.viewer:
            self.viewer.shutdown()
            self.stack.setCurrentWidget(self.gallery_page)
            self.stack.removeWidget(self.viewer)
            self.viewer.deleteLater()
            self.viewer = None
        self.viewing = False
        self.reflow()
        self.return_key = getattr(self, 'viewer_key', None)
        if self.pending_snapshot:
            items, snap = self.pending_snapshot
            self.pending_snapshot = None
            self.received(items, snap)
        tile = self.tiles.get(self.return_key)
        if tile:
            self.focus_control(tile.button)
        self.refresh()

    def delete_dialog(self, item, parent=None):
        """Inline action sheet; never spawn a second Steam-focus window."""
        if getattr(self, 'delete_page', None) or self.secondary_page:
            return
        self.pause_viewer()
        self.delete_focus = QApplication.focusWidget()
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
                    item_layout.widget().hide()
                    item_layout.widget().deleteLater()
            yes = QPushButton('Yes, move to Trash')
            yes.clicked.connect(lambda: execute(choice))
            buttons.addWidget(yes)
            undo = QPushButton('No, go back')
            undo.clicked.connect(self.close_delete_page)
            buttons.addWidget(undo)
            undo.setFocus()

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
            if self.viewer:
                self.focus_control(self.delete_focus)

    def column_count(self):
        return max(1, min(6, (self.scroll.viewport().width() - 76 + 22) // 262))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'scroll') and hasattr(self, 'tiles'):
            QTimer.singleShot(0, self.reflow)

    def reflow(self):
        if self.stack.currentWidget() is self.gallery_page and hasattr(self, 'grid') and self.column_count() != getattr(self, 'columns', None):
            self.render()

    def focus_control(self, control):
        control.setFocus(Qt.FocusReason.OtherFocusReason)
        page = self.stack.currentWidget()
        if isinstance(page, QScrollArea):
            page.ensureWidgetVisible(control, 20, 20)

    def navigate(self, action):
        page = self.stack.currentWidget()
        controls = [w for w in page.findChildren(QWidget)
                    if isinstance(w, (QPushButton, QSlider)) and w.isVisible()
                    and w.isEnabled() and w.focusPolicy() != Qt.FocusPolicy.NoFocus]
        if not controls:
            return
        current = QApplication.focusWidget()
        if current not in controls:
            self.focus_control(controls[0])
            return
        if isinstance(current, QSlider) and action in ('left', 'right'):
            current.setValue(max(current.minimum(), min(current.maximum(),
                current.value() + (current.singleStep() if action == 'right' else -current.singleStep()))))
            return
        origin = current.mapTo(page, current.rect().center())
        candidates = []
        for control in controls:
            if control is current:
                continue
            center = control.mapTo(page, control.rect().center())
            dx, dy = center.x() - origin.x(), center.y() - origin.y()
            forward, sideways = {'left': (-dx, abs(dy)), 'right': (dx, abs(dy)),
                                 'up': (-dy, abs(dx)), 'down': (dy, abs(dx))}[action]
            if forward > 0:
                candidates.append((forward + sideways * 3, sideways, control))
        if candidates:
            self.focus_control(min(candidates, key=lambda candidate: candidate[:2])[2])

    def on_gamepad(self, action):
        page = self.stack.currentWidget()
        in_viewer = self.viewer is not None and page is self.viewer
        if in_viewer:
            was_hidden = self.viewer.reveal_controls()
            if was_hidden and action in ('up', 'down', 'left', 'right', 'select', 'tab'):
                return
        if action in ('up', 'down', 'left', 'right'):
            self.navigate(action)
        elif action == 'select':
            focused = QApplication.focusWidget()
            if isinstance(focused, QPushButton) and page.isAncestorOf(focused):
                focused.click()
        elif action == 'play':
            if in_viewer:
                self.viewer.toggle_play()
        elif action in ('previous', 'next'):
            if in_viewer:
                self.step_capture(-1 if action == 'previous' else 1)
        elif action == 'back':
            if getattr(self, 'delete_page', None):
                self.close_delete_page()
            elif self.secondary_page:
                self.close_secondary()
            elif in_viewer:
                self.close_viewer()
        elif action == 'details':
            if in_viewer or page is self.gallery_page:
                self.show_details()
        elif action == 'settings':
            if in_viewer or page is self.gallery_page:
                self.show_settings()
        elif action == 'fullscreen':
            self.toggle_fullscreen()
        elif action == 'refresh':
            self.refresh()
        elif action == 'remove' and (in_viewer or page is self.gallery_page):
            focused = QApplication.focusWidget()
            capture = self.viewer.item if in_viewer else next((tile.item for tile in self.tiles.values() if tile.button is focused), None)
            if capture:
                if not in_viewer:
                    self.open_item(capture)
                self.delete_dialog(capture)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseMove and self.viewer and self.stack.currentWidget() is self.viewer:
            self.viewer.reveal_controls()
        if event.type() == QEvent.Type.FocusIn and isinstance(watched, (QPushButton, QSlider)):
            page = self.stack.currentWidget()
            if isinstance(page, QScrollArea) and page.isAncestorOf(watched):
                page.ensureWidgetVisible(watched, 20, 20)
        if event.type() == QEvent.Type.KeyPress and QApplication.activeModalWidget() is None:
            actions = {Qt.Key.Key_Left: 'left', Qt.Key.Key_Right: 'right',
                       Qt.Key.Key_Up: 'up', Qt.Key.Key_Down: 'down',
                       Qt.Key.Key_Return: 'select', Qt.Key.Key_Enter: 'select',
                       Qt.Key.Key_Escape: 'back', Qt.Key.Key_Backspace: 'back',
                       Qt.Key.Key_Space: 'play', Qt.Key.Key_PageUp: 'previous',
                       Qt.Key.Key_PageDown: 'next', Qt.Key.Key_I: 'details',
                       Qt.Key.Key_S: 'settings', Qt.Key.Key_F11: 'fullscreen',
                       Qt.Key.Key_R: 'refresh', Qt.Key.Key_Delete: 'remove'}
            action = actions.get(event.key())
            if action:
                if not event.isAutoRepeat() or action in ('left', 'right', 'up', 'down'):
                    self.on_gamepad(action)
                return True
            if event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab) and self.viewer and self.stack.currentWidget() is self.viewer:
                if self.viewer.reveal_controls():
                    return True
        return super().eventFilter(watched, event)

    def closeEvent(self, event):
        self.timer.stop()
        self.gamepad_timer.stop()
        self.gamepad.close()
        if self.worker and self.worker.isRunning():
            self.worker.wait()
        if self.viewer:
            self.viewer.shutdown()
        super().closeEvent(event)



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
