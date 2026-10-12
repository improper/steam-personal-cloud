"""Read Steam's screenshot originals alongside the user's exported captures.

Steam's live catalogue is owned by Steam. We never rewrite it behind its back.
"""
from pathlib import Path
import re
import time

IMAGES = {'.png', '.jpg', '.jpeg', '.webp'}
EXPORT = re.compile(r'^(\d+)_(\d{14}_\d+)\.(?:png|jpe?g|webp)$', re.I)
NATIVE = re.compile(r'^screenshots/steam/(\d+)/screenshots/(\d{14}_\d+)\.(?:png|jpe?g|webp)$', re.I)


def screenshot_identity(source):
    """Match JPEG originals to PNG exports by Steam's capture ID, never pixels."""
    match = NATIVE.fullmatch(source)
    if match is None and source.startswith('screenshots/'):
        match = EXPORT.fullmatch(source[len('screenshots/'):])
    return f'{match[1]}_{match[2]}' if match else None


def screenshot_key(source):
    identity = screenshot_identity(source)
    return 'screenshots/' + identity if identity else source


def steam_roots():
    roots = []
    for path in (Path.home() / '.steam/debian-installation',
                 Path.home() / '.local/share/Steam', Path.home() / '.steam/steam',
                 Path.home() / '.var/app/com.valvesoftware.Steam/data/Steam'):
        if path.is_dir() and path.resolve() not in roots:
            roots.append(path.resolve())
    return roots


def screenshot_roots(config):
    account = str(config.get('steam_account', ''))
    if not account.isdigit():
        return []
    return [root / 'userdata' / account / '760' / 'remote' for root in steam_roots()
            if (root / 'userdata' / account / '760' / 'remote').is_dir()]


def native_screenshots(config, settle_seconds=0):
    now = time.time()
    for root in screenshot_roots(config):
        for game in sorted(root.iterdir()):
            folder = game / 'screenshots'
            if not game.name.isdigit() or game.is_symlink() or not folder.is_dir() or folder.is_symlink():
                continue
            for path in sorted(folder.iterdir()):
                if path.suffix.lower() not in IMAGES or path.is_symlink() or not path.is_file():
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                if stat.st_size and now - stat.st_mtime >= settle_seconds:
                    yield path, 'screenshots/steam/' + path.relative_to(root).as_posix(), stat


def discover_captures(config, *, settle_seconds=None, include_duplicates=False):
    from agent import discover
    settle = int(config.get('settle_seconds', 45)) if settle_seconds is None else settle_seconds
    identities = set()
    for path, source, stat in discover(Path(config.get('screenshots', '/nonexistent')).expanduser(),
                                       Path(config.get('recordings', '/nonexistent')).expanduser(), settle):
        # Steam thumbnails are derivatives, never separate captures.
        if source.startswith('screenshots/') and (path.suffix.lower() not in IMAGES or
                any(part.lower() in ('thumbnails', 'thumbs') for part in source.split('/')[1:-1])):
            continue
        identities.add(screenshot_identity(source))
        yield path, source, stat
    for path, source, stat in native_screenshots(config, settle):
        identity = screenshot_identity(source)
        if include_duplicates or identity is None or identity not in identities:
            yield path, source, stat
            if identity:
                identities.add(identity)


def archived_native(source, known):
    """Don't re-upload a JPEG whose export was already archived (or trashed)."""
    identity = screenshot_identity(source)
    return bool(NATIVE.fullmatch(source) and identity and any(
        not NATIVE.fullmatch(prior) and screenshot_identity(prior) == identity for prior in known))


def native_target(source, config, local_path):
    if not NATIVE.fullmatch(source):
        raise ValueError('Invalid Steam screenshot source')
    relative = source[len('screenshots/steam/'):]
    for root in screenshot_roots(config):
        target = root / relative
        if (target == Path(local_path) and target.is_file() and not target.is_symlink()
                and not any(parent.is_symlink() for parent in (target.parent, target.parent.parent))
                and root.resolve() in target.resolve().parents):
            return target
    raise ValueError('Steam screenshot is missing or outside the active account')


def catalogue_names():
    names = {}
    for root in steam_roots():
        for file in (root / 'userdata').glob('*/760/screenshots.vdf'):
            try:
                text = file.read_text(errors='replace')
            except OSError:
                continue
            # shortcutnames is Steam's history, including since-renamed shortcuts.
            section = re.search(r'"shortcutnames"\s*\{([^{}]*)\}', text, re.S)
            if section:
                names.update(re.findall(r'"(\d+)"\s*"([^"\n]+)"', section[1]))
    return names
