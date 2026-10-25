"""Portable KDE Plasma one-shot restore before KWin, audio after login.

Works on supported systemd-managed KDE Plasma sessions regardless of Linux
distribution; no hardcoded openSUSE-specific paths or distribution checks.
The worker runs on the host after explicit user approval, without root.
Unsupported/classic KDE startup is rejected, not silently restored live.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

APP = 'UniversalLinuxSoftwareManager'
STATE = '.local/share/' + APP + '/deferred-plasma'
EARLY = 'ulsm-plasma-settings-restore.service'
LATE = 'ulsm-plasma-audio-restore.service'
LATE_AUTOSTART = 'ulsm-plasma-audio-restore.desktop'
MAX_FILE = 12 * 1024 * 1024

# Defence in depth: the host-side worker trusts neither edited plans nor
# arbitrary ZIP entry names, even though staging checks the archive already.
ALLOWED = {
    'display': ('.config/kwinoutputconfig.json', '.local/share/kscreen'),
    'panels': ('.config/plasma-org.kde.plasma.desktop-appletsrc', '.config/plasmashellrc'),
    'power': ('.config/powermanagementprofilesrc', '.config/powerdevilrc'),
    'audio': ('.config/kmixrc', '.config/pipewire', '.config/wireplumber', '.config/pulse'),
    'appearance': ('.config/kdeglobals', '.config/ksmserverrc', '.config/kwinrc',
                   '.config/plasmarc', '.config/kwinrulesrc', '.config/kscreenlockerrc',
                   '.config/ksplashrc', '.config/kcmfonts', '.config/breezerc'),
    'keyboard': ('.config/kglobalshortcutsrc', '.config/kxkbrc', '.config/kcminputrc'),
    'notifications': ('.config/plasmanotifyrc',),
    'region': ('.config/plasma-localerc',),
    'fileassoc': ('.config/mimeapps.list', '.local/share/applications/mimeapps.list'),
}


def _root(home):
    return Path(home) / STATE


def _safe(home, rel):
    rel = str(rel)
    parts = PurePosixPath(rel)
    if (not rel or len(rel) > 500 or parts.is_absolute() or '..' in parts.parts
            or '\\' in rel or any(part in ('', '.') for part in parts.parts)):
        raise ValueError('Unsafe deferred settings path')
    cur = Path(home)
    for part in parts.parts:
        cur = cur / part
        if cur.is_symlink():
            raise ValueError('Symlink in deferred settings path: ' + rel)
    return cur


def _allowed(cat, rel):
    return any(rel == root or rel.startswith(root + '/') for root in ALLOWED.get(cat, ()))


def _atomic(path, raw):
    path = Path(path)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError('Unsafe deferred restore target')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp = tempfile.mkstemp(prefix='.ulsm-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _write_status(root, state):
    state['updated_utc'] = datetime.now(timezone.utc).isoformat()
    _atomic(root / 'status.json', json.dumps(state, indent=2, ensure_ascii=False).encode())


def _unit_text(phase, kwin=None):
    if phase == 'files':
        return ('[Unit]\nDescription=One-time Universal Linux Software Manager Plasma settings restore\n'
                'Before=' + kwin + '\n'
                '[Service]\nType=oneshot\nTimeoutStartSec=60\n'
                'ExecStart=/usr/bin/env python3 %h/' + STATE + '/worker.py files\n'
                '[Install]\nWantedBy=' + kwin + '\n')
    return ('[Unit]\nDescription=One-time Universal Linux Software Manager audio restore\n'
            'After=graphical-session.target\n'
            '[Service]\nType=oneshot\nTimeoutStartSec=105\n'
            'ExecStart=/usr/bin/env python3 %h/' + STATE + '/worker.py audio\n')


def _host(host_run, args):
    ok, out, err = host_run(args, 20)
    if not ok:
        raise RuntimeError('Host systemd user service command failed: ' + ' '.join(args) + ': ' + str(err or out)[:280])
    return str(out)


# Plasma 5 (systemd startup) and Plasma 6 use these session-specific unit
# names on common distributions. Inspect the *running* unit on the host rather
# than trusting distro names or assuming Flatpak forwarded XDG_SESSION_TYPE.
KWIN_UNITS = {
    'wayland': 'plasma-kwin_wayland.service',
    'x11': 'plasma-kwin_x11.service',
}


def detect_kwin_unit(host_run, session_type=None):
    """Find a verifiably active KDE KWin systemd user unit.

    Never schedule a pre-KWin write on a non-systemd Plasma session or use
    an inferred unit that contradicts an explicitly known session type.
    A blank/missing session env can be inferred only from one active KWin
    service (not merely an installed unit file).
    """
    session = (session_type if session_type is not None
               else os.environ.get('XDG_SESSION_TYPE', '')).strip().lower()
    if session and session not in KWIN_UNITS:
        raise RuntimeError('Unsupported KDE session type: ' + session +
                           '. No deferred restore has been scheduled.')
    choices = ((session,) if session else tuple(KWIN_UNITS))
    active = []
    for candidate in choices:
        kwin = KWIN_UNITS[candidate]
        loaded = _host(host_run, ['systemctl', '--user', 'show',
                                  '--property=LoadState', '--value', kwin]).strip()
        if loaded != 'loaded':
            if session:
                raise RuntimeError('KDE systemd startup unit ' + kwin + ' is unavailable. '
                                   'No deferred restore has been scheduled.')
            continue
        running = _host(host_run, ['systemctl', '--user', 'show',
                                   '--property=ActiveState', '--value', kwin]).strip()
        if running == 'active':
            active.append((candidate, kwin))
        elif session:
            raise RuntimeError('The current Plasma session is not using the KDE systemd '
                               'KWin unit. Cannot guarantee restoration before the '
                               'compositor. Nothing was scheduled.')
    if len(active) != 1:
        raise RuntimeError('Could not identify exactly one active KDE systemd KWin '
                           'unit. No deferred restore has been scheduled. '
                           'This KDE startup method is not supported safely.')
    return active[0]


def stage_restore(home, archive, categories, target_desktop='kde', host_run=None, session_type=None):
    """Stage a verified KDE settings restore without changing live config.

    Raises before promising an upcoming restore when the host's KDE startup
    service cannot be found. Only settings specifically approved by the user.
    """
    from universal_backup import inspect_backup, desktop_family
    from audio_backup import validate

    home = Path(home)
    manifest = inspect_backup(archive)
    if desktop_family(target_desktop) != 'kde' or manifest['desktop'] != 'kde':
        raise ValueError('Deferred restore requires matching KDE Plasma desktops')
    selected = set(categories)
    if not selected or not selected.issubset(set(manifest['categories']) - {'apps', 'appsettings'}):
        raise ValueError('Invalid KDE restore categories')
    if host_run is None:
        raise RuntimeError('Host systemd user service access is required')
    session, kwin = detect_kwin_unit(host_run, session_type)
    if _host(host_run, ['systemctl', '--user', 'show', '--property=LoadState', '--value',
                        'graphical-session.target']).strip() != 'loaded':
        raise RuntimeError('graphical-session.target is unavailable; cannot schedule audio safely')
    if _host(host_run, ['python3', '--version']).strip() == '':
        # Python normally prints to stdout; check command succeeded (above).
        pass
    root = _safe(home, STATE)
    if root.is_symlink() or (root / 'plan.json').is_symlink():
        raise ValueError('Unsafe deferred restore staging path')
    if (root / 'status.json').is_file():
        status = _json(root / 'status.json')
        if status.get('files') == 'pending' or status.get('audio') == 'pending':
            raise RuntimeError('A Plasma restore is already scheduled. '
                               'Reboot and review its result before scheduling another.')
    entries = [e for e in manifest['files'] if e['category'] in selected and
               # Older backups may contain daemon-owned WirePlumber state.
               not e['path'].startswith('.local/state/wireplumber')]
    audio_info = manifest.get('audio_state') if 'audio' in selected else None
    if 'audio' in selected and not audio_info:
        raise ValueError('This backup has no live audio snapshot. Create a new backup with Audio selected.')
    if not entries and not audio_info:
        raise ValueError('No saved KDE settings for the selected categories')
    # Validate every payload before staging, and do not leave partially enabled
    # services if a symlink, bad checksum or permission error is found.
    payloads = []
    audio = None
    with zipfile.ZipFile(archive) as z:
        for e in entries:
            rel, cat = e['path'], e['category']
            if not _allowed(cat, rel):
                raise ValueError('Unexpected KDE setting in backup: ' + rel)
            _safe(home, rel)
            raw = z.read('settings/' + rel)
            if len(raw) > MAX_FILE or hashlib.sha256(raw).hexdigest() != e['sha256']:
                raise ValueError('Corrupt KDE settings backup: ' + rel)
            payloads.append((rel, cat, raw))
        if audio_info:
            audio = z.read('audio/state.json')
            validate(json.loads(audio))
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    worker_source = Path(__file__).resolve()
    audio_source = worker_source.with_name('audio_backup.py')
    if not audio_source.is_file():
        raise RuntimeError('Audio restore module is not included in this build')
    plan = {'schema': 1, 'desktop': 'kde', 'session': session, 'kwin_unit': kwin,
            'created_utc': datetime.now(timezone.utc).isoformat(), 'files': [],
            'audio': bool(audio)}
    for index, (rel, cat, raw) in enumerate(payloads):
        name = f'payload-{index:04d}.bin'
        _atomic(root / name, raw)
        plan['files'].append({'category': cat, 'path': rel, 'blob': name,
                              'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)})
    if audio is not None:
        _atomic(root / 'audio.json', audio)
    _atomic(root / 'worker.py', worker_source.read_bytes())
    _atomic(root / 'audio_backup.py', audio_source.read_bytes())
    _atomic(root / 'plan.json', json.dumps(plan, indent=2).encode())
    status = {'files': 'pending' if payloads else 'not_selected',
              'audio': 'pending' if audio is not None else 'not_selected',
              'message': 'Restore staged. Reboot and sign in to the same KDE session.',
              'warnings': []}
    _write_status(root, status)
    units = _safe(home, '.config/systemd/user')
    units.mkdir(parents=True, exist_ok=True)
    if units.is_symlink():
        raise ValueError('Unsafe user service directory')
    paths = [units / EARLY] + ([units / LATE] if audio is not None else [])
    enabled = []
    try:
        for path in paths:
            if path.exists() or path.is_symlink():
                # Overwrite ONLY app-owned regular units. Refuse custom symlinks.
                if path.is_symlink() or not path.is_file():
                    raise ValueError('User service path is unsafe: ' + str(path))
            _atomic(path, (_unit_text('files', kwin) if path.name == EARLY else _unit_text('audio')).encode('utf-8'))
        if audio is not None:
            # Avoid a WantedBy=graphical-session.target/After=graphical-session.target
            # cycle and never stall Plasma startup waiting for PipeWire. KDE XDG
            # autostart asynchronously triggers the one-shot systemd audio unit.
            startup = _safe(home, '.config/autostart/' + LATE_AUTOSTART)
            _atomic(startup, ('[Desktop Entry]\nType=Application\nName=Complete pending ULSM audio restore\n'
                              'Exec=systemctl --user start --no-block ' + LATE + '\n'
                              'OnlyShowIn=KDE;\nNoDisplay=true\nTerminal=false\n').encode())
        _host(host_run, ['systemctl', '--user', 'daemon-reload'])
        _host(host_run, ['systemctl', '--user', 'enable', EARLY])
        enabled.append(EARLY)
    except Exception:
        for name in enabled:
            try: host_run(['systemctl', '--user', 'disable', name], 20)
            except Exception: pass
        status['files'] = 'scheduling_failed'
        status['audio'] = 'scheduling_failed' if audio is not None else 'not_selected'
        _write_status(root, status)
        raise
    return {'pending': True, 'recovery_dir': str(root), 'warnings': [],
            'message': 'KDE configuration will be restored before KWin at next login; audio after login.'}


def _disable(unit):
    if unit == LATE:
        try:
            startup = _safe(Path.home(), '.config/autostart/' + LATE_AUTOSTART)
            if startup.is_file() and not startup.is_symlink():
                startup.unlink()
        except (OSError, ValueError):
            pass
    try:
        subprocess.run(['systemctl', '--user', 'disable', unit], timeout=15,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _apply_files(home, root, plan, status):
    if status.get('files') != 'pending':
        return
    # Full preflight before the first destination is touched.
    payloads = []
    for e in plan['files']:
        rel, cat, name = e['path'], e['category'], e['blob']
        if not _allowed(cat, rel) or not isinstance(name, str) or not name.startswith('payload-') or not name.endswith('.bin') or '/' in name:
            raise ValueError('Invalid staged KDE setting')
        destination = _safe(home, rel)
        blob = root / name
        if blob.is_symlink() or not blob.is_file():
            raise ValueError('Missing staged KDE settings')
        raw = blob.read_bytes()
        if len(raw) != e['size'] or len(raw) > MAX_FILE or hashlib.sha256(raw).hexdigest() != e['sha256']:
            raise ValueError('Damaged staged KDE settings')
        if destination.is_dir():
            raise ValueError('Desktop config destination became a directory')
        payloads.append((destination, raw, rel))
    history = home / '.local/share' / APP / 'restore-history' / ('before-deferred-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    history.mkdir(parents=True, exist_ok=False, mode=0o700)
    applied = []
    try:
        for dest, raw, rel in payloads:
            _safe(home, rel)
            previous = None
            if dest.is_file():
                previous = history / rel
                previous.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, previous, follow_symlinks=False)
            _atomic(dest, raw)
            applied.append((dest, previous))
            if hashlib.sha256(dest.read_bytes()).digest() != hashlib.sha256(raw).digest():
                raise RuntimeError('Verification failed immediately after writing ' + rel)
    except Exception:
        for dest, previous in reversed(applied):
            try:
                if previous is not None: _atomic(dest, previous.read_bytes())
                elif dest.exists(): dest.unlink()
            except OSError: pass
        raise
    status['files'] = 'applied'
    status['recovery_dir'] = str(history)
    status['files_written'] = len(payloads)
    status['message'] = 'KDE configuration written before KWin startup; verify display and panels after login.'
    _write_status(root, status)


def _audio_runner(args, timeout=20):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        return p.returncode == 0, p.stdout, (p.stderr or p.stdout).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, '', str(exc)


def _apply_audio(root, status):
    if status.get('audio') != 'pending':
        return
    from audio_backup import validate, prepare_audio_restore, apply_audio_state
    state = validate(_json(root / 'audio.json'))
    ready = False
    for _ in range(30):
        ok, _, _ = _audio_runner(['pactl', 'info'], 6)
        if ok:
            ready = True
            break
        time.sleep(2)
    if not ready:
        raise RuntimeError('PipeWire/PulseAudio did not become available after login')
    target, warnings = prepare_audio_restore(_audio_runner, state)
    apply_audio_state(_audio_runner, target)
    status['audio'] = 'applied'
    status.setdefault('warnings', []).extend(warnings)
    _write_status(root, status)


def run_worker(phase, home=None):
    if phase not in ('files', 'audio'):
        raise ValueError('Invalid restore phase')
    home = Path(home) if home is not None else Path.home()
    root = _root(home)
    unit = EARLY if phase == 'files' else LATE
    key = 'files' if phase == 'files' else 'audio'
    try:
        if not (root / 'plan.json').is_file() or not (root / 'status.json').is_file():
            raise RuntimeError('Missing staged restore plan')
        plan = _json(root / 'plan.json')
        status = _json(root / 'status.json')
        if plan.get('schema') != 1 or plan.get('desktop') != 'kde':
            raise ValueError('Unrecognized deferred restore plan')
        if status.get(key) != 'pending':
            return True
        if phase == 'files':
            _apply_files(home, root, plan, status)
        else:
            _apply_audio(root, status)
        return True
    except Exception as exc:
        try:
            status = _json(root / 'status.json')
            status[key] = 'failed'
            status[key + '_error'] = str(exc)[:400]
            _write_status(root, status)
        except Exception:
            pass
        return False
    finally:
        _disable(unit)


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in ('files', 'audio'):
        print('Usage: worker.py files|audio', file=sys.stderr)
        sys.exit(2)
    sys.exit(0 if run_worker(sys.argv[1]) else 1)
