"""Best-effort Linux joystick navigation: complements Steam Input keyboard mapping."""
from __future__ import annotations

import os
from pathlib import Path
import struct
import time

# Linux joystick ABI: struct js_event { uint32 time; int16 value; uint8 type; uint8 number; }.
EVENT = struct.Struct('IhBB')


class JoystickReader:
    def __init__(self, callback):
        self.callback = callback
        self.fd = None
        self.last = {}
        self.axes = {}
        self.find_device()

    def find_device(self):
        available = sorted(Path('/dev/input').glob('js*')) if Path('/dev/input').exists() else []
        candidates = []
        for path in available:
            try:
                name = (Path('/sys/class/input') / path.name / 'device/name').read_text().strip().lower()
            except OSError:
                name = ''
            priority = 3 if 'steam' in name or 'x-box 360' in name or 'xbox 360' in name else 2 if 'controller' in name else 1
            candidates.append((priority, str(path)))
        for _, path in sorted(candidates, reverse=True):
            try:
                self.fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                return
            except OSError:
                continue

    def emit(self, action):
        now = time.monotonic()
        if now - self.last.get(action, 0) >= 0.18:
            self.last[action] = now
            self.callback(action)

    def poll(self):
        if self.fd is None:
            self.find_device()
            return
        try:
            data = os.read(self.fd, 256)
        except BlockingIOError:
            return
        except OSError:
            os.close(self.fd)
            self.fd = None
            return
        for offset in range(0, len(data) - EVENT.size + 1, EVENT.size):
            _, value, type_, number = EVENT.unpack_from(data, offset)
            if type_ & 0x80:
                continue
            if type_ & 0x01 and value:
                if number == 0:
                    self.emit('select')
                elif number == 1:
                    self.emit('back')
                elif number in (2, 3):
                    self.emit('details')
            elif type_ & 0x02 and number in (0, 1, 6, 7):
                # Supports thumbstick and common Linux hat axes.
                if value < -18000:
                    self.emit('left' if number in (0, 6) else 'up')
                elif value > 18000:
                    self.emit('right' if number in (0, 6) else 'down')

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
