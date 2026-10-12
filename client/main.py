"""Compiled client entry point; application modules are linked by Nuitka."""
import os
import sys

VERSION = '0.3.0-beta.1'


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ('--help', '-h'):
        print('Steam Personal Cloud ' + VERSION)
        print('Usage: steam-personal-cloud {gallery|setup|sync|proxy|diagnostics|--version} [options]')
        return
    command = sys.argv.pop(1)
    if command == '--version':
        print(VERSION)
    elif command == 'gallery':
        from gallery_app import main as gallery
        gallery()
    elif command == 'setup':
        os.environ['SPC_PACKAGE_MODE'] = '1'
        from setup import run
        try:
            run()
        except (EOFError, KeyboardInterrupt):
            print('\nSetup cancelled. Existing settings preserved.')
    elif command == 'sync':
        from agent import main as sync
        sync()
    elif command == 'proxy':
        from local_dashboard import serve
        serve()
    elif command == 'diagnostics':
        from diagnostics import main as diagnostics
        diagnostics()
    elif command == 'self-test':
        self_test()
    else:
        raise SystemExit('Unknown command: ' + command)


def self_test():
    """Exercise the compiled UI and photo decoder without pairing or uploading."""
    from pathlib import Path
    import tempfile
    from unittest.mock import patch
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    from gallery_app import Gallery, STYLE, image_from_data
    from gallery_model import MediaItem
    from PIL import Image
    from io import BytesIO
    app = QApplication([])
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    data = BytesIO()
    Image.new('RGB', (160, 90), '#238bd4').save(data, 'WEBP', lossless=True)
    decoded = image_from_data(data.getvalue())
    if decoded.isNull():
        raise RuntimeError('WebP decoder unavailable')
    with tempfile.TemporaryDirectory() as directory, patch.object(Gallery, 'refresh'):
        window = Gallery(settings=QSettings(str(Path(directory) / 'settings.ini'), QSettings.Format.IniFormat))
        window.timer.stop()
        window.gamepad_timer.stop()
        window.items = [MediaItem('screenshots/test.png', 'Example game', 'photo', 'waiting', '', '', 'screenshots/test.png', 0)]
        window.render()
        window.open_item(window.items[0])
        app.processEvents()
        if window.viewer.isWindow():
            raise RuntimeError('Viewer must remain in the gallery window')
        window.close_viewer()
        window.show_settings()
        app.processEvents()
        window.close()
    print('Compiled client self-test passed (' + VERSION + ')')


if __name__ == '__main__':
    main()
