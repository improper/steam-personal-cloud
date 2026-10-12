#!/usr/bin/env python3
"""Native 10-foot Steam Personal Cloud gallery (PySide6; no embedded browser)."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
from urllib.error import URLError
from urllib.request import Request, urlopen

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThread, QTimer, QUrl, QEvent, QSettings, Signal as pyqtSignal
from PySide6.QtGui import QColor, QImage, QImageReader, QPixmap, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QMainWindow, QPushButton, QScrollArea, QSlider, QVBoxLayout, QWidget, QStackedWidget, QProgressBar, QSizePolicy)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget

from gallery_model import MediaItem, make_gallery, local_removal_targets
from gamepad_linux import JoystickReader
from local_status import read_json

BASE = 'http://127.0.0.1:18787'
STYLE = '''
QWidget { color: #f2f6ff; background: #101b2c; font-family: "Noto Sans", "DejaVu Sans"; font-size: 24px; }
QMainWindow, QScrollArea { background: #101b2c; }
QLabel { background: transparent; }
QLabel#eyebrow { color: #9ddcff; font-size: 20px; font-weight: 700; }
QLabel#headline { color: #ffffff; font-weight: 800; font-size: 48px; }
QLabel#subtitle, QLabel#hint { color: #c0cde0; font-size: 24px; }
QLabel#summary { background: #1b2c43; color: #deedff; padding: 14px 22px; border-radius: 12px; font-size: 23px; }
QPushButton { background: #253b55; color: #f2f6ff; font-size: 26px; font-weight: 600; border: 3px solid #39536f; border-radius: 12px; padding: 12px 22px; }
QPushButton:focus { border: 4px solid #ffffff; background: #387da5; color: white; }
QPushButton:checked { background: #2e6483; border-color: #82d9ff; }
QPushButton:checked:focus { border: 4px solid #ffffff; background: #387da5; }
QPushButton:hover { background: #355977; }
QPushButton:disabled { color: #8898ac; background: #19273a; border-color: #2c4058; }
QPushButton#tile { background: #20334b; text-align: center; padding: 0; border-radius: 14px; }
QWidget#captureCard { background: #1a2c43; border-radius: 16px; }
QWidget#captureCard[focused="true"] { background: #2b5271; }
QLabel#tileName { color: #ffffff; font-size: 28px; font-weight: 700; }
QLabel#detail { color: #bccce0; font-size: 22px; }
QLabel#status { font-size: 22px; font-weight: 600; }
QLabel#advanced { background: #1b2c43; padding: 20px; border-radius: 12px; font-size: 23px; }
QWidget#controlHints { background: #0a1220; border-top: 2px solid #2e4861; }
QLabel#controllerKey { background: #31455e; border-radius: 8px; padding: 3px 9px; font-size: 21px; font-weight: 800; }
QLabel#controllerKey[button="A"] { background: #246a4d; color: #d9ffea; }
QLabel#controllerKey[button="B"] { background: #7d3547; color: #ffe2e8; }
QLabel#controllerKey[button="X"] { background: #2a578e; color: #e0edff; }
QLabel#controllerKey[button="Y"] { background: #756124; color: #fff1ba; }
QLabel#keyboardKey { background: #19283b; border: 1px solid #536b83; border-radius: 6px; padding: 3px 8px; font-size: 19px; color: #d4e3f5; }
QLabel#promptAction { font-size: 23px; font-weight: 600; }
QSlider { min-height: 32px; background: transparent; }
QSlider::groove:horizontal { height: 10px; background: #405772; border-radius: 5px; }
QSlider::handle:horizontal { background: #9adeff; width: 26px; margin: -8px 0; border-radius: 10px; }
QSlider::add-page:horizontal { background: #405772; border-radius: 5px; }
QSlider::sub-page:horizontal { background: #82d9ff; border-radius: 5px; }
QSlider::groove:horizontal:focus { background: #81c9ee; }
QSlider::handle:horizontal:focus { background: white; }
QScrollArea { border: none; }
QScrollBar:vertical { background: #122238; width: 10px; }
QScrollBar::handle:vertical { background: #526e89; min-height: 40px; border-radius: 5px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
'''


def console_style(height):
    import re
    scale = max(.65, min(1.2, height / 1080))
    return re.sub(r'(\d+)px', lambda match: f'{max(1, round(int(match[1]) * scale))}px', STYLE)


class ControlHints(QWidget):
    """Always-visible, readable controller buttons and their keyboard equivalents."""
    def __init__(self, actions, parent=None):
        super().__init__(parent)
        self.setObjectName('controlHints')
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 12, 24, 12)
        layout.setSpacing(18)
        for controller, keyboard, action in actions:
            group = QVBoxLayout()
            group.setSpacing(6)
            keys = QHBoxLayout()
            keys.setSpacing(6)
            if controller:
                badge = QLabel(controller)
                badge.setObjectName('controllerKey')
                badge.setProperty('button', controller)
                keys.addWidget(badge)
            if keyboard:
                key = QLabel(keyboard)
                key.setObjectName('keyboardKey')
                keys.addWidget(key)
            keys.addStretch(1)
            group.addLayout(keys)
            label = QLabel(action)
            label.setObjectName('promptAction')
            group.addWidget(label)
            layout.addLayout(group, 1)
BADGES = {
    'waiting': ('● Waiting to back up', '#e9ae63'),
    'backed_up': ('◔ Preparing for Immich', '#80bcff'),
    'processing': ('◔ Processing', '#c7a9ff'),
    'ready': ('✓ Available in Immich', '#82ddb4'),
    'error': ('! Needs attention', '#ff8b9a'),
    'deleted': ('○ Local only · Immich trashed', '#c6d5e5'),
}


def image_from_data(data, max_size=None):
    """Qt installations may omit the optional WebP image-format plugin."""
    pix = QPixmap()
    if pix.loadFromData(data):
        return pix
    try:
        from PIL import Image, ImageOps
        from io import BytesIO
    except ImportError:
        return pix
    try:
        with Image.open(BytesIO(data)) as image:
            if image.width * image.height > 40_000_000:
                return pix
            image = ImageOps.exif_transpose(image).convert('RGBA')
            if max_size:
                image.thumbnail((max_size.width(), max_size.height()))
            rgba = image.tobytes()
            decoded = QImage(rgba, image.width, image.height, image.width * 4, QImage.Format.Format_RGBA8888).copy()
            return QPixmap.fromImage(decoded)
    except (OSError, ValueError, Image.DecompressionBombError):
        return pix


def local_image(path, max_size=QSize(350, 190)):
    if not path or not Path(path).is_file():
        return QPixmap()
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    dimension = reader.size()
    if dimension.isValid():
        reader.setScaledSize(dimension.scaled(max_size, Qt.AspectRatioMode.KeepAspectRatio))
    image = reader.read()
    if not image.isNull():
        return QPixmap.fromImage(image)
    try:
        return image_from_data(Path(path).read_bytes(), max_size)
    except OSError:
        return QPixmap()


def media_url(item, variant):
    return f'{BASE}/api/media/{item.immich_id}/{variant}'


class SnapshotWorker(QThread):
    done = pyqtSignal(object, object)
    def run(self):
        try:
            self.done.emit(*make_gallery())
        except Exception as exc:
            self.done.emit([], {'configured': False, 'error': str(exc)})


class RemovalWorker(QThread):
    done = pyqtSignal(str)
    def __init__(self, item, config, choice, parent=None):
        super().__init__(parent)
        self.item, self.config, self.choice = item, config, choice

    def run(self):
        try:
            # Preflight all originals before changing either location.
            targets = local_removal_targets(self.item, self.config) if self.choice in ('local', 'both') else []
            if self.choice in ('immich', 'both'):
                for asset in self.item.immich_copies or (self.item.immich_id,):
                    request = Request(self.config['server'].rstrip('/') + '/api/media/' + asset + '/immich',
                                      headers={'X-SPC-Token': self.config['token']}, method='DELETE')
                    with urlopen(request, timeout=18) as response:
                        if response.status != 200:
                            raise RuntimeError('Server returned HTTP ' + str(response.status))
            from gallery_trash import move_to_trash
            for target in targets:
                move_to_trash(target)
        except Exception as exc:
            self.done.emit(str(exc))
            return
        self.done.emit('')


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
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        border = 6 if self.hasFocus() else 2
        area = self.rect().adjusted(border, border, -border, -border)
        path = QPainterPath()
        from PySide6.QtCore import QRectF
        path.addRoundedRect(QRectF(area), 10, 10)
        painter.setClipPath(path)
        cover = self.cover.scaled(area.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                  Qt.TransformationMode.SmoothTransformation)
        painter.drawPixmap(area, cover, cover.rect().adjusted(
            (cover.width() - area.width()) // 2, (cover.height() - area.height()) // 2,
            -(cover.width() - area.width() + 1) // 2, -(cover.height() - area.height() + 1) // 2))
        painter.setClipping(False)
        pen = QPen(QColor('#ffffff' if self.hasFocus() else '#39536f'))
        pen.setWidth(border)
        painter.setPen(pen)
        inset = border // 2
        painter.drawRoundedRect(self.rect().adjusted(inset, inset, -inset - 1, -inset - 1), 14, 14)


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
    def __init__(self, item, on_open, parent=None, width=400):
        super().__init__(parent)
        self.setObjectName('captureCard')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.item = item
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 16)
        layout.setSpacing(8)
        self.button = CoverButton('▶  VIDEO' if item.kind == 'video' else '▣  SCREENSHOT')
        self.button.setObjectName('tile')
        self.button.setFixedHeight(round((width - 20) * 9 / 16))
        self.button.setMinimumWidth(1)
        self.setFixedWidth(width)
        self.button.setIconSize(QSize(220, 144))
        self.button.clicked.connect(lambda: on_open(self.item))
        self.button.setAccessibleName(item.name + ', ' + item.kind + ', ' + BADGES.get(item.state, BADGES['waiting'])[0])
        layout.addWidget(self.button)
        media_type = QLabel('▶  VIDEO' if item.kind == 'video' else '▣  PHOTO')
        media_type.setObjectName('eyebrow')
        layout.addWidget(media_type)
        title = QLabel(item.name.removesuffix(' Screenshot').removesuffix(' Game Clip').removesuffix(' Game Recording'))
        title.setObjectName('tileName')
        title.setWordWrap(True)
        layout.addWidget(title)
        if item.subtitle:
            when = QLabel(item.subtitle)
            when.setObjectName('detail')
            layout.addWidget(when)
        label, color = BADGES.get(item.state, BADGES['waiting'])
        status = QLabel(label)
        status.setObjectName('status')
        status.setStyleSheet(f'color:{color}; background:transparent;')
        layout.addWidget(status)
        if item.thumbnail:
            self.set_preview(local_image(item.thumbnail, QSize(width, round(width * 9 / 16))))
        # A scroll area's first layout pass can otherwise compress tile rows
        # below their labels and make the cover overlap the metadata.
        self.setMinimumHeight(max(layout.sizeHint().height(), layout.totalHeightForWidth(width)))

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
        back = QPushButton('Back · B / Esc')
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
        for label, callback in [('Details', self.gallery.show_details), ('Settings', self.gallery.show_settings),
                                ('Remove…', lambda: on_delete(item))]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            navigation.addWidget(button)
        lower.addLayout(navigation)
        hint = ControlHints([('A', 'Enter', 'Select'), ('B', 'Esc', 'Back'),
                            ('X', 'Space', 'Play / pause'), ('LB / RB', 'PgUp / PgDn', 'Browse captures'),
                            ('Y', 'I', 'Details'), ('Menu', 'S', 'Settings')])
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
        if not self.photo.original.isNull():
            self.notice.setText('Viewing local original')
            return
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
        pix = image_from_data(data)
        if pix.isNull():
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
        from PySide6.QtCore import QThreadPool as Pool
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
        self.gallery_page = QWidget()
        library_layout = QVBoxLayout(self.gallery_page)
        library_layout.setContentsMargins(0, 0, 0, 0)
        library_layout.setSpacing(0)
        library_layout.addWidget(self.scroll, 1)
        self.library_hints = ControlHints([('D-pad', '↑ ↓ ← →', 'Navigate'), ('A', 'Enter', 'Open capture'),
            ('LB / RB', 'PgUp / PgDn', 'Change filter'), ('Y', 'I', 'Details'),
            ('Menu', 'S', 'Settings'), ('', 'R', 'Refresh library')])
        library_layout.addWidget(self.library_hints)
        self.stack.addWidget(self.gallery_page)
        self.viewer = None
        self.layout = QVBoxLayout(root)
        self.layout.setContentsMargins(38, 22, 38, 24)
        self.layout.setSpacing(16)
        headline = QHBoxLayout()
        branding = QVBoxLayout()
        eyebrow = QLabel('STEAM PERSONAL CLOUD  /  YOUR LIBRARY')
        eyebrow.setObjectName('eyebrow')
        branding.addWidget(eyebrow)
        title = QLabel('Your captures')
        title.setObjectName('headline')
        branding.addWidget(title)
        subtitle = QLabel('Your screenshots and saved moments, all in one place.')
        subtitle.setObjectName('subtitle')
        branding.addWidget(subtitle)
        headline.addLayout(branding, 1)
        advanced = QPushButton('Details · Y / I')
        advanced.clicked.connect(self.toggle_advanced)
        headline.addWidget(advanced, 0, Qt.AlignmentFlag.AlignTop)
        settings_button = QPushButton('Settings · Menu / S')
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
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(22)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.layout.addWidget(self.wrapper, 1)
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
        parts = [f'{len(items)} captures', f'{ready} in Immich']
        if preparing:
            parts.append(f'{preparing} preparing')
        if waiting:
            parts.append(f'{waiting} waiting to back up')
        self.summary.setText('  ·  '.join(parts) + status)
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
        # Rebuild the layout so obsolete columns don't leave extra spacing
        # or a horizontal scrollbar after a resize or filter change.
        import shiboken6
        shiboken6.delete(self.grid)
        self.grid = QGridLayout(self.wrapper)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(22)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.tiles = {}
        shown = [x for x in self.items if self.filter == 'all' or x.kind == self.filter]
        max_columns = self.column_count()
        self.columns = max_columns
        for i, item in enumerate(shown):
            tile = Tile(item, self.open_item, width=self.card_width())
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
            target = self.tiles[focus_key].button
            QTimer.singleShot(0, lambda: self.focus_control(target) if self.stack.currentWidget() is self.gallery_page else None)
        elif self.tiles and (focused is None or focused is self.wrapper or focus_key or not getattr(self, 'initial_focus', False)):
            target = next(iter(self.tiles.values())).button
            QTimer.singleShot(0, lambda: self.focus_control(target) if self.stack.currentWidget() is self.gallery_page else None)
            self.initial_focus = True

    def apply_thumbnail(self, key, data):
        tile = self.tiles.get(key)
        if not tile:
            return
        pix = image_from_data(data)
        if not pix.isNull():
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
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)
        self.secondary_scroll = QScrollArea()
        self.secondary_scroll.setWidgetResizable(True)
        content = QWidget()
        self.secondary_scroll.setWidget(content)
        page_layout.addWidget(self.secondary_scroll, 1)
        page_layout.addWidget(ControlHints([('D-pad', '↑ ↓ ← →', 'Navigate'), ('A', 'Enter', 'Select / change'),
                                            ('B', 'Esc', 'Back')]))
        layout = QVBoxLayout(content)
        layout.setContentsMargins(40, 24, 40, 24)
        layout.setSpacing(18)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
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
        QTimer.singleShot(0, lambda: self.focus_control(back) if self.secondary_page else None)

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
        for key, label, description in [
                ('autoplay', 'Autoplay videos', 'Start playing when you open a recording.'),
                ('auto_hide', 'Hide viewer controls', 'Enjoy the full picture after four seconds of inactivity.'),
                ('muted', 'Mute audio', 'Keep video playback silent.'),
                ('fullscreen', 'Launch fullscreen', 'Open the gallery ready for your TV.')]:
            row = QHBoxLayout()
            text = QVBoxLayout()
            name = QLabel(label)
            name.setObjectName('tileName')
            text.addWidget(name)
            help_text = QLabel(description)
            help_text.setObjectName('detail')
            help_text.setWordWrap(True)
            text.addWidget(help_text)
            row.addLayout(text, 1)
            button = QPushButton()
            button.setMinimumWidth(160)
            button.setCheckable(True)
            button.setAccessibleName(label)
            def update_button(k=key, control=button):
                control.setChecked(self.preference(k))
                control.setText('✓ On' if self.preference(k) else 'Off')
            update_button()
            button.clicked.connect(lambda checked, k=key, update=update_button: (self.set_preference(k, checked), update()))
            self.setting_buttons[key] = (button, update_button)
            row.addWidget(button)
            layout.addLayout(row)
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
        other_actions = QHBoxLayout()
        other_actions.addWidget(fullscreen)
        defaults = QPushButton('Restore defaults')
        def restore():
            for key, value in self.DEFAULTS.items():
                self.set_preference(key, value)
            for button, update in self.setting_buttons.values():
                update()
            volume.setValue(self.preference('volume'))
        defaults.clicked.connect(restore)
        other_actions.addWidget(defaults)
        layout.addLayout(other_actions)
        controls = QLabel('Use left / right on volume to adjust by 5%. In videos, use left / right on the timeline to skip 10 seconds.')
        controls.setWordWrap(True)
        controls.setObjectName('subtitle')
        layout.addWidget(controls)
        exit_button = QPushButton('Exit gallery')
        exit_button.clicked.connect(self.close)
        layout.addWidget(exit_button)
        self.finish_secondary(layout)
        first = self.setting_buttons['autoplay'][0]
        QTimer.singleShot(0, lambda: self.focus_control(first) if self.secondary_page else None)

    def show_details(self):
        item = self.viewer.item if self.viewer else next((tile.item for tile in self.tiles.values()
                    if tile.button.hasFocus()), None)
        if item is None:
            self.toggle_advanced()
            return
        layout = self.open_secondary('Capture details')
        if layout is None:
            return
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
        copies = len(item.local_copies) or int(local)
        self.delete_hint = QLabel(f'Choose which copies to move to Trash.\nLocal includes all {copies} matched local copies, including Steam originals and exports.\nSteam may keep a cached media entry until its library refreshes.')
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
        layout.addWidget(ControlHints([('D-pad', '↑ ↓', 'Choose copies'), ('A', 'Enter', 'Select'), ('B', 'Esc', 'Cancel')]))
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
            self.removing = True
            self.delete_hint.setText('Moving copies to Trash…')
            for control in self.delete_page.findChildren(QPushButton):
                control.setEnabled(False)
            self.removal_worker = RemovalWorker(item, config, choice, self)
            self.removal_worker.done.connect(removal_done)
            self.removal_worker.start()

        def removal_done(error):
            self.removal_worker.wait()
            self.removing = False
            if error:
                self.delete_hint.setText('Removal needs attention: ' + error +
                    '\nA copy may already be in Trash. Go back and refresh before retrying.')
                cancel.setEnabled(True)
                cancel.setFocus()
                return
            self.pending_snapshot = None
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
        return max(1, min(4, (self.scroll.viewport().width() - 76 + 22) // 370))

    def card_width(self):
        return max(240, (self.scroll.viewport().width() - 76 - (self.column_count() - 1) * 22) // self.column_count())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.setStyleSheet(console_style(self.height()))
        if hasattr(self, 'scroll') and hasattr(self, 'tiles'):
            QTimer.singleShot(0, self.reflow)

    def reflow(self):
        if self.stack.currentWidget() is self.gallery_page and hasattr(self, 'grid') and (self.column_count(), self.card_width(), self.height()) != getattr(self, 'grid_size', None):
            self.grid_size = (self.column_count(), self.card_width(), self.height())
            self.render()

    def focus_control(self, control):
        control.setFocus(Qt.FocusReason.OtherFocusReason)
        page = self.stack.currentWidget()
        if page is self.gallery_page:
            if self.scroll.isAncestorOf(control):
                self.scroll.ensureWidgetVisible(control, 20, 20)
        elif page is self.secondary_page:
            self.secondary_scroll.ensureWidgetVisible(control, 20, 20)
        elif isinstance(page, QScrollArea):
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
        if getattr(self, 'removing', False):
            return
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
            elif page is self.gallery_page:
                keys = list(self.filters)
                self.select_filter(keys[(keys.index(self.filter) + (-1 if action == 'previous' else 1)) % len(keys)])
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
            if page is self.gallery_page and self.scroll.isAncestorOf(watched):
                self.scroll.ensureWidgetVisible(watched, 20, 20)
            elif page is self.secondary_page:
                self.secondary_scroll.ensureWidgetVisible(watched, 20, 20)
        if event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut) and isinstance(watched, CoverButton):
            card = watched.parentWidget()
            card.setProperty('focused', event.type() == QEvent.Type.FocusIn)
            card.style().unpolish(card)
            card.style().polish(card)
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
        if getattr(self, 'removing', False):
            event.ignore()
            return
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
