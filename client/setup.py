#!/usr/bin/env python3
"""Interactive, non-destructive Linux onboarding and repair wizard."""
from __future__ import annotations

import getpass
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

CONFIG = Path.home() / '.config/steam-personal-cloud/client.json'
STATE = Path.home() / '.local/state/steam-personal-cloud'
DATA = Path.home() / '.local/share/steam-personal-cloud'
UNITS = Path.home() / '.config/systemd/user'
NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$')


def ask(label, default=None):
    suffix = f' [{default}]' if default is not None else ''
    answer = input(f'{label}{suffix}: ').strip()
    return answer if answer else (str(default) if default is not None else '')


def choose(label, options, default='1'):
    while True:
        print('\n' + label)
        for k, v in options.items():
            print(f'  {k}) {v}')
        answer = ask('Choose', default)
        if answer in options:
            return answer
        print('That option is not available. Please try again.')


def server_url(value):
    value = value.rstrip('/')
    u = urlsplit(value)
    if u.scheme not in ('http', 'https') or not u.hostname or u.username or u.password or u.query or u.fragment:
        raise ValueError('Enter the full server URL, e.g. http://192.168.1.27:8787')
    try:
        port = u.port
    except ValueError:
        raise ValueError('Invalid server port') from None
    if not port and u.scheme == 'http' and not u.netloc:
        raise ValueError('Missing server host')
    return value


def prompt_server(default):
    while True:
        value = ask('Server URL', default)
        try:
            return server_url(value)
        except ValueError as exc:
            print(f'  {exc}')


def prompt_identity(label, default):
    while True:
        value = ask(label, default)
        if NAME.fullmatch(value):
            return value
        print('  Only letters, digits, hyphens and underscores are supported (up to 64 characters).')


def prompt_rate(default):
    while True:
        value = ask('Maximum upload MiB/s (0 = unlimited)', default)
        try:
            speed = float(value)
            if speed >= 0 and speed != float('inf'):
                return speed
        except ValueError:
            pass
        print('  Use 0 for unlimited or a positive number such as 2.')


def health(server):
    try:
        with urlopen(server + '/health', timeout=5) as response:
            data = json.load(response)
        if data.get('status') != 'ok':
            raise ValueError('Server did not return a healthy response')
        print(f'  Server reachable (version {data.get("version", "unknown")})')
        return True
    except (OSError, URLError, HTTPError, ValueError, TimeoutError) as exc:
        print(f'  Connection failed: {exc}')
        return False


def agent_module(package_mode):
    path = (Path('/usr/lib/steam-personal-cloud/agent.py') if package_mode
            else Path(__file__).parent / 'agent.py')
    if not path.is_file():
        raise RuntimeError(f'Sync agent missing: {path}')
    spec = importlib.util.spec_from_file_location('spc_pairing_agent', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_token(server, token):
    try:
        request = Request(server + '/api/status', headers={'X-SPC-Token': token})
        with urlopen(request, timeout=6) as response:
            return response.status == 200
    except HTTPError as exc:
        if exc.code in (401, 403):
            print('  Saved authorization was rejected. Re-pair this device.')
        else:
            print(f'  Server returned HTTP {exc.code}.')
    except (OSError, URLError, TimeoutError) as exc:
        print(f'  Cannot check saved authorization: {exc}')
    return False


def obtain_token(agent, server, client, account):
    while True:
        method = choose('Connect this device', {'1': 'Fast Connect using a pairing code',
                                                 '2': 'Paste an existing token (hidden)',
                                                 '3': 'Change server URL',
                                                 '4': 'Cancel setup'})
        if method == '4':
            return None, server
        if method == '3':
            server = prompt_server(server)
            health(server)
            continue
        if method == '2':
            token = getpass.getpass('Existing token (hidden): ').strip()
            if not token:
                print('  Token was empty. Please try again.')
                continue
            if verify_token(server, token):
                return token, server
            print('  Token not verified. You can retry without restarting setup.')
            continue
        print('\nOpen your server dashboard, sign in as admin, and select Pair device.')
        print('The code expires in five minutes. You may retry without losing settings.')
        code = ask('One-time pairing code (or type back)')
        if code.lower() in ('back', 'b'):
            continue
        try:
            token = agent.pair_device(server, code, client, account)
            print('  Device paired successfully.')
            return token, server
        except (OSError, RuntimeError, ValueError, TimeoutError) as exc:
            print(f'  Pairing unsuccessful: {exc}')
            answer = choose('Next step', {'1': 'Try another pairing code', '2': 'Change connection method'}, default='1')
            if answer == '2':
                continue
            # Prompt another code without re-entering all other settings.
            while True:
                code = ask('New pairing code (or type back)')
                if code.lower() in ('back', 'b'):
                    break
                try:
                    token = agent.pair_device(server, code, client, account)
                    print('  Device paired successfully.')
                    return token, server
                except (OSError, RuntimeError, ValueError, TimeoutError) as retry_error:
                    print(f'  Pairing unsuccessful: {retry_error}')


def write_config(config):
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    old = CONFIG.read_bytes() if CONFIG.exists() else None
    encoded = (json.dumps(config, indent=2) + '\n').encode()
    if old == encoded:
        print('  Existing configuration preserved (unchanged).')
        return
    if old is not None:
        backup = CONFIG.with_suffix('.json.backup')
        with backup.open('wb') as stream:
            stream.write(old)
        backup.chmod(0o600)
        print(f'  Backed up previous configuration to {backup}')
    tmp = CONFIG.with_suffix('.json.tmp')
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(encoded)
        os.replace(tmp, CONFIG)
    finally:
        tmp.unlink(missing_ok=True)
    CONFIG.chmod(0o600)
    print('  Configuration saved.')


def install_units(package_mode):
    if not package_mode:
        root = Path(__file__).resolve().parents[1]
        DATA.mkdir(parents=True, exist_ok=True)
        UNITS.mkdir(parents=True, exist_ok=True)
        for filename in ('agent.py', 'local_status.py', 'local_dashboard.py', 'local_dashboard.html'):
            shutil.copy2(root / 'client' / filename, DATA / filename)
        for unit in ('steam-personal-cloud-sync.service', 'steam-personal-cloud-sync.timer'):
            shutil.copy2(root / 'client' / unit, UNITS / unit)
        ui = (root / 'client' / 'steam-personal-cloud-ui.service').read_text()
        ui = ui.replace('/usr/lib/steam-personal-cloud/local_dashboard.py', '%h/.local/share/steam-personal-cloud/local_dashboard.py')
        (UNITS / 'steam-personal-cloud-ui.service').write_text(ui)
    commands = [
        ['systemctl', '--user', 'daemon-reload'],
        ['systemctl', '--user', 'enable', '--now', 'steam-personal-cloud-sync.timer'],
        ['systemctl', '--user', 'enable', '--now', 'steam-personal-cloud-ui.service'],
    ]
    for command in commands:
        try:
            subprocess.run(command, check=True, timeout=25)
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            print(f'  Warning: could not enable a background service ({exc}).')
            print('  Retry after login: systemctl --user enable --now steam-personal-cloud-sync.timer')
            return False
    return True


def run():
    print('Steam Personal Cloud · Linux setup and repair\n')
    if os.geteuid() == 0:
        raise RuntimeError('Run setup as your normal desktop user, not sudo.')
    package_mode = os.environ.get('SPC_PACKAGE_MODE') == '1'
    old = None
    if CONFIG.exists():
        try:
            old = json.loads(CONFIG.read_text())
            if not isinstance(old, dict):
                raise ValueError('Not a JSON object')
        except (OSError, ValueError) as exc:
            raise RuntimeError(f'Cannot safely read existing config ({exc}); first back it up manually: {CONFIG}')
    action = 'new'
    if old:
        print(f'Existing device: {old.get("client_id", "unknown")} · {old.get("server", "unknown")}')
        action = choose('What would you like to do?', {
            '1': 'Check connection and repair background sync (keep settings)',
            '2': 'Change settings (keep existing pairing when possible)',
            '3': 'Pair this device again (keep media and sync history)',
            '4': 'Cancel'}, default='1')
        if action == '4':
            print('Nothing changed.')
            return
    agent = agent_module(package_mode)
    existing = old or {}
    if action == '1':
        config = dict(existing)
    else:
        server = prompt_server(existing.get('server', 'http://192.168.1.27:8787'))
        client = prompt_identity('Client name', existing.get('client_id', os.uname().nodename.split('.')[0]))
        account = prompt_identity('Steam userdata account ID', existing.get('steam_account', '728364463'))
        shots = ask('Screenshot directory', existing.get('screenshots', str(Path.home() / 'Gameplay/Screenshots')))
        videos = ask('Recording directory', existing.get('recordings', str(Path.home() / 'Gameplay/Recordings')))
        rate = prompt_rate(existing.get('max_mib_per_second', 0))
        for label, value in (('Screenshots', shots), ('Recordings', videos)):
            if not Path(value).expanduser().is_dir():
                print(f'  Warning: {label} path does not exist: {value}')
        config = dict(existing, server=server, client_id=client, steam_account=account,
                      screenshots=shots, recordings=videos, max_mib_per_second=rate,
                      settle_seconds=int(existing.get('settle_seconds', 45)))
    server = config['server']
    print('\nChecking family server…')
    while not health(server):
        answer = choose('Could not reach the server', {'1': 'Try again', '2': 'Change server URL',
                                                         '3': 'Continue offline with existing pairing',
                                                         '4': 'Exit without saving'})
        if answer == '1':
            continue
        if answer == '2':
            server = prompt_server(server)
            config['server'] = server
            continue
        if answer == '4':
            print('Nothing changed.')
            return
        if not existing.get('token') or action == '3':
            print('  Offline setup requires an existing pairing. Nothing changed.')
            return
        break
    needs_pair = (not config.get('token') or action == '3' or
                  config['client_id'] != existing.get('client_id') or
                  config['steam_account'] != existing.get('steam_account'))
    if needs_pair:
        token, server = obtain_token(agent, server, config['client_id'], config['steam_account'])
        if token is None:
            print('Setup cancelled; existing settings were not modified.')
            return
        config['token'] = token
        config['server'] = server
    elif action == '1':
        if not verify_token(server, config['token']):
            print('  Tip: run setup again and choose "Pair this device again" if unauthorized.')
    print('\nSaving configuration and starting background sync…')
    write_config(config)
    running = install_units(package_mode)
    print('\nSetup complete.' if running else '\nSettings saved; background sync needs attention.')
    print('  Open Steam Personal Cloud from your applications menu for LOCAL library status.')
    print('  Manual scan: systemctl --user start steam-personal-cloud-sync.service')
    print('  Logs: journalctl --user -u steam-personal-cloud-sync.service -n 30 --no-pager')


if __name__ == '__main__':
    try:
        run()
    except (EOFError, KeyboardInterrupt):
        print('\nSetup cancelled. Existing settings preserved.')
        raise SystemExit(1)
    except (OSError, RuntimeError) as exc:
        print(f'\nSetup could not finish: {exc}', file=sys.stderr)
        raise SystemExit(1)
