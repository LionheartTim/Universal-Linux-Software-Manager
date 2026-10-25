"""Local, capability-driven desktop backup. No cloud, privileged writes or shell code.

The archive is not encrypted. Restore never extracts arbitrary ZIP paths, follows
symlinks, modifies /etc, or applies settings to a different desktop family.
"""
import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from feature_tools import export_manifest, import_manifest, package_id_ok
from audio_backup import (capture_audio_state, apply_audio_state, prepare_audio_restore,
                          validate as validate_audio_state)

CATEGORIES = ('display', 'panels', 'power', 'audio', 'appearance', 'keyboard', 'notifications', 'region', 'fileassoc', 'appsettings', 'apps')
MAX_FILE = 12 * 1024 * 1024
MAX_TOTAL = 96 * 1024 * 1024
MAX_FILES = 1600
FORMAT = 'ulsm-local-backup'
SCHEMA = 4

# Exact user-level settings, not arbitrary home directories. The same list is
# authoritative during restore (so changing a crafted manifest cannot widen it).
FILES = {
    'kde': {
        # Plasma 6 Wayland uses KWin's output store. Keep the older KScreen
        # directory for X11 / older KDE versions without replacing the new file.
        'display': ['.config/kwinoutputconfig.json', '.local/share/kscreen'],
        'panels': ['.config/plasma-org.kde.plasma.desktop-appletsrc', '.config/plasmashellrc'],
        'power': ['.config/powermanagementprofilesrc', '.config/powerdevilrc'],
        'audio': ['.config/kmixrc'],
        'appearance': ['.config/kdeglobals', '.config/ksmserverrc', '.config/kwinrc',
                       '.config/plasmarc', '.config/kwinrulesrc', '.config/kscreenlockerrc',
                       '.config/ksplashrc', '.config/kcmfonts', '.config/breezerc'],
        'keyboard': ['.config/kglobalshortcutsrc', '.config/kxkbrc', '.config/kcminputrc'],
        'notifications': ['.config/plasmanotifyrc'],
        'region': ['.config/plasma-localerc'],
    },
    'gnome': {
        'display': ['.config/monitors.xml'],
        'panels': [], 'power': [], 'audio': [], 'appearance': [],
        'keyboard': [], 'notifications': [], 'region': [],
    },
    'xfce': {
        'display': ['.config/xfce4/xfconf/xfce-perchannel-xml/displays.xml'],
        'panels': ['.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml', '.config/xfce4/panel'],
        'power': ['.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-power-manager.xml'],
        'audio': ['.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-mixer.xml'],
        'appearance': ['.config/xfce4/xfconf/xfce-perchannel-xml/xsettings.xml',
                       '.config/xfce4/xfconf/xfce-perchannel-xml/xfwm4.xml',
                       '.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-desktop.xml'],
        'keyboard': ['.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-keyboard-shortcuts.xml',
                     '.config/xfce4/xfconf/xfce-perchannel-xml/keyboard-layout.xml'],
        'notifications': ['.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-notifyd.xml'],
        'region': [],
    },
    'lxqt': {
        'display': ['.config/lxqt/session.conf'],
        'panels': ['.config/lxqt/panel.conf'],
        'power': ['.config/lxqt/powermanagement.conf'],
        'audio': [],
        'appearance': ['.config/lxqt/lxqt.conf', '.config/lxqt/appearance.conf', '.config/openbox/lxqt-rc.xml',
                       '.config/pcmanfm-qt/lxqt/settings.conf'],
        'keyboard': ['.config/lxqt/globalkeyshortcuts.conf'],
        'notifications': [], 'region': [],
    },
    'cinnamon': {
        'display': ['.config/monitors.xml'],
        'panels': [], 'power': [], 'audio': [], 'appearance': [],
        'keyboard': [], 'notifications': [], 'region': [],
    },
    'mate': {
        'display': ['.config/monitors.xml'],
        'panels': [], 'power': [], 'audio': [], 'appearance': [],
        'keyboard': [], 'notifications': [], 'region': [],
    },
    'other': {'display': [], 'panels': [], 'power': [], 'audio': [], 'appearance': [],
              'keyboard': [], 'notifications': [], 'region': []},
}
DCONF = {
    'gnome': {'display': ['/org/gnome/mutter/'],
              'panels': ['/org/gnome/shell/'],
              'power': ['/org/gnome/settings-daemon/plugins/power/'],
              'audio': ['/org/gnome/desktop/sound/'],
              'appearance': ['/org/gnome/desktop/interface/', '/org/gnome/desktop/background/',
                             '/org/gnome/desktop/wm/preferences/', '/org/gnome/desktop/screensaver/'],
              'keyboard': ['/org/gnome/desktop/input-sources/', '/org/gnome/settings-daemon/plugins/media-keys/'],
              'notifications': ['/org/gnome/desktop/notifications/'],
              'region': ['/org/gnome/system/locale/']},
    'cinnamon': {'panels': ['/org/cinnamon/'],
                 'power': ['/org/cinnamon/settings-daemon/plugins/power/'],
                 'audio': ['/org/cinnamon/desktop/sound/'],
                 'appearance': ['/org/cinnamon/desktop/interface/'],
                 'keyboard': [], 'notifications': [], 'region': []},
    'mate': {'panels': ['/org/mate/panel/'],
             'power': ['/org/mate/power-manager/'],
             'audio': [],
             'appearance': ['/org/mate/desktop/interface/'],
             'keyboard': [], 'notifications': [], 'region': []},
}
# Live WirePlumber state is owned by its running daemon; it is not a safe
# generic configuration file to copy over. The active audio snapshot is saved
# separately via pactl, and verified on restore.
AUDIO_COMMON = ['.config/pipewire', '.config/wireplumber', '.config/pulse']
APP_CONFIG_ROOT = '.var/app'
XDG_ASSOCIATIONS = ['.config/mimeapps.list', '.local/share/applications/mimeapps.list']


def desktop_family(value=None):
    v = (value if value is not None else (os.getenv('XDG_CURRENT_DESKTOP') or os.getenv('DESKTOP_SESSION') or '')).lower()
    for key, fragments in {'kde': ('kde', 'plasma'), 'gnome': ('gnome',),
                           'xfce': ('xfce',), 'lxqt': ('lxqt',),
                           'cinnamon': ('cinnamon',), 'mate': ('mate',)}.items():
        if any(fragment in v for fragment in fragments): return key
    return 'other'


def _inside_home(home, relative):
    """Resolve only regular, non-symlink paths below user's home."""
    relative = str(relative)
    p = PurePosixPath(relative)
    if not relative or p.is_absolute() or '..' in p.parts or '\\' in relative or len(relative) > 500:
        raise ValueError('Unsafe home-relative filename')
    current = Path(home)
    for part in p.parts:
        current = current / part
        if current.is_symlink(): raise ValueError('Symlink in settings path: ' + relative)
    return current


def allowed_paths(desktop, category, package_ids=()):
    items = list(FILES.get(desktop, FILES['other']).get(category, ()))
    if category == 'audio': items += AUDIO_COMMON
    if category == 'fileassoc': items += XDG_ASSOCIATIONS
    if category == 'appsettings':
        for pid in package_ids:
            if package_id_ok(pid) and not pid.startswith('-') and '/' not in pid:
                items.append(APP_CONFIG_ROOT + '/' + pid + '/config')
    return items


def _permitted(relative, desktop, category, package_ids):
    if category == 'audio' and (relative == '.local/state/wireplumber' or
                                 relative.startswith('.local/state/wireplumber/')):
        return True  # Validate old schema-4 archives, but never reapply live daemon state.
    if desktop == 'kde' and category == 'appearance' and relative == '.config/kcminputrc':
        return True  # Preserve restore compatibility with original schema-2 archives.
    for root in allowed_paths(desktop, category, package_ids):
        if relative == root or relative.startswith(root + '/'):
            return True
    return False


def _iterate_files(home, paths):
    for relative in paths:
        try: p = _inside_home(home, relative)
        except ValueError: continue
        if p.is_file() and not p.is_symlink():
            yield relative, p
        elif p.is_dir():
            for root, dirs, files in os.walk(p, followlinks=False):
                dirs[:] = sorted(d for d in dirs if not (Path(root)/d).is_symlink())
                for name in sorted(files):
                    file = Path(root)/name
                    if file.is_file() and not file.is_symlink():
                        yield file.relative_to(home).as_posix(), file


def _dconf_dump(run, prefix):
    """Read the live host user's dconf, never quietly drop an error.

    An empty successful dump means there are no *overrides* under this prefix;
    an unsuccessful dump must not be mistaken for a valid empty backup.
    """
    if run is None:
        raise RuntimeError('Cannot read GNOME settings: host dconf command is unavailable')
    ok, out, err = run(['dconf', 'dump', prefix], 20)
    if not ok or not isinstance(out, str):
        raise RuntimeError(f'Cannot read desktop settings ({prefix}): '
                           f'{str(err).strip() or "host dconf dump failed"}. '
                           'Check that dconf is installed on the host and the user session is active.')
    return out


def make_backup(home, destination, categories, packages=(), desktop=None, distro=(), run=None):
    """Create single-file local ZIP with an allowlisted manifest, atomically."""
    home = Path(home)
    dest = Path(destination)
    selected = set(categories)
    if not selected or not selected.issubset(CATEGORIES): raise ValueError('No valid backup categories selected')
    if 'appsettings' in selected and 'apps' not in selected:
        raise ValueError('Choose Installed applications together with app settings')
    desk = desktop_family(desktop)
    selected_packages = export_manifest(packages, distro)['packages']
    pkgs = selected_packages if 'apps' in selected else []
    flatpaks = {e['id'] for e in selected_packages if e['kind'] == 'Flatpak'}
    selected_appids = sorted(flatpaks) if 'appsettings' in selected else []
    manifest = {'format': FORMAT, 'schema': SCHEMA, 'created_utc': datetime.now(timezone.utc).isoformat(),
                'desktop': desk, 'distro': sorted(str(x) for x in distro),
                'categories': sorted(selected), 'packages': pkgs,
                'contains_personal_files': bool(selected - {'apps'}), 'encrypted': False, 'files': [], 'dconf': [], 'audio_state': None}
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, staging = tempfile.mkstemp(prefix='.ulsm-backup-', suffix='.zip', dir=dest.parent)
    os.close(fd)
    total = 0
    seen = set()
    category_counts = {cat: 0 for cat in selected - {'apps'}}
    try:
        with zipfile.ZipFile(staging, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for category in sorted(selected - {'apps'}):
                for relative, file in _iterate_files(home, allowed_paths(desk, category, selected_appids)):
                    if relative in seen: continue
                    seen.add(relative)
                    stat = file.stat()
                    if stat.st_size > MAX_FILE: continue
                    if len(manifest['files']) >= MAX_FILES: raise ValueError('Too many settings files')
                    if total + stat.st_size > MAX_TOTAL: raise ValueError('Settings backup exceeds 96 MiB')
                    raw = file.read_bytes()
                    total += len(raw)
                    archive_name = 'settings/' + relative
                    z.writestr(archive_name, raw)
                    manifest['files'].append({'category': category, 'path': relative,
                                              'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
                    category_counts[category] += 1
                for prefix in DCONF.get(desk, {}).get(category, ()):
                    dump = _dconf_dump(run, prefix)
                    if not dump: continue
                    raw = dump.encode('utf-8')
                    if len(raw) > MAX_FILE or total + len(raw) > MAX_TOTAL: continue
                    index = len(manifest['dconf'])
                    z.writestr(f'dconf/{index}.txt', raw)
                    manifest['dconf'].append({'category': category, 'prefix': prefix,
                                              'name': f'dconf/{index}.txt',
                                              'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)})
                    category_counts[category] += 1
                    total += len(raw)
            if 'audio' in selected:
                # Capture the ACTIVE audio device, volume and mute via the real
                # host session; Xfce's mixer XML alone does not store these.
                snapshot = capture_audio_state(run)
                raw = json.dumps(snapshot, sort_keys=True).encode('utf-8')
                if total + len(raw) > MAX_TOTAL: raise ValueError('Settings backup exceeds 96 MiB')
                z.writestr('audio/state.json', raw)
                manifest['audio_state'] = {'member':'audio/state.json', 'category':'audio',
                                           'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
                category_counts['audio'] += 1
                total += len(raw)
            # A settings-only backup with no actual saved values must not
            # misleadingly report a successful GNOME desktop backup.
            manifest['empty_categories'] = sorted(cat for cat, count in category_counts.items() if count == 0)
            if desk in ('gnome', 'cinnamon', 'mate') and selected - {'apps'} and not (manifest['files'] or manifest['dconf'] or manifest['audio_state']):
                raise ValueError('No desktop settings could be saved. On GNOME, only customized '
                                 'dconf keys are exported; check the chosen categories and host dconf.')
            z.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        with open(staging, 'rb') as inp: os.fsync(inp.fileno())
        os.replace(staging, dest)
    finally:
        if os.path.exists(staging): os.unlink(staging)
    return manifest


def inspect_backup(filename):
    """Validate manifest identity and bounded contents. Legacy JSON is separate."""
    with zipfile.ZipFile(filename, 'r') as z:
        info = z.infolist()
        names = [i.filename for i in info]
        if len(names) != len(set(names)) or len(info) > MAX_FILES + 100:
            raise ValueError('Duplicated or excessive backup members')
        if 'manifest.json' not in names or z.getinfo('manifest.json').file_size > 2_000_000:
            raise ValueError('Missing or oversize manifest')
        manifest = json.loads(z.read('manifest.json'))
        if manifest.get('format') != FORMAT or manifest.get('schema') not in (2, 3, SCHEMA):
            raise ValueError('Unsupported settings backup')
        desk = manifest.get('desktop')
        if desk not in FILES: raise ValueError('Unknown source desktop')
        categories = manifest.get('categories', [])
        if not isinstance(categories, list) or not set(categories).issubset(CATEGORIES):
            raise ValueError('Invalid settings categories')
        packages = manifest.get('packages', [])
        if not isinstance(packages, list) or len(packages)>10000:
            raise ValueError('Invalid package list')
        cleaned = import_manifest(json.dumps({'format':'universal-linux-center-package-list',
                                              'schema':1, 'packages':packages}))
        ids = {e['id'] for e in cleaned if e['kind']=='Flatpak'}
        files = manifest.get('files', [])
        dconf = manifest.get('dconf', [])
        if not isinstance(files, list) or not isinstance(dconf, list) or len(files)>MAX_FILES:
            raise ValueError('Invalid settings entries')
        expected = {'manifest.json'}
        total = 0
        for e in files:
            if not isinstance(e, dict): raise ValueError('Invalid settings entry')
            path, cat = e.get('path', ''), e.get('category', '')
            if cat not in categories or cat == 'apps' or not _permitted(path, desk, cat, ids):
                raise ValueError('Unexpected settings destination')
            _inside_home('/tmp/ulsm-validator', path)
            member='settings/'+path
            if member not in names: raise ValueError('Missing settings file')
            sz=z.getinfo(member).file_size
            if sz > MAX_FILE or sz != e.get('size'): raise ValueError('Oversize settings file')
            total += sz
            expected.add(member)
        for e in dconf:
            if not isinstance(e, dict): raise ValueError('Invalid dconf entry')
            cat, prefix, name=e.get('category'), e.get('prefix'), e.get('name')
            if cat not in categories or prefix not in DCONF.get(desk,{}).get(cat,()):
                raise ValueError('Unapproved dconf path')
            if not re.fullmatch(r'dconf/\d+\.txt', str(name)) or name not in names:
                raise ValueError('Invalid dconf archive member')
            sz=z.getinfo(name).file_size
            if sz > MAX_FILE or sz != e.get('size'): raise ValueError('Oversize dconf data')
            total += sz
            expected.add(name)
        audio = manifest.get('audio_state')
        if audio is not None:
            if (not isinstance(audio, dict) or set(audio) != {'member', 'category', 'size', 'sha256'}
                    or audio['member'] != 'audio/state.json' or audio['category'] != 'audio'
                    or 'audio' not in categories or audio['member'] not in names):
                raise ValueError('Invalid audio snapshot manifest')
            size = z.getinfo('audio/state.json').file_size
            if size > 8192 or size != audio['size']:
                raise ValueError('Invalid audio snapshot size')
            raw = z.read('audio/state.json')
            if hashlib.sha256(raw).hexdigest() != audio['sha256']:
                raise ValueError('Audio snapshot checksum mismatch')
            validate_audio_state(json.loads(raw))
            total += size
            expected.add('audio/state.json')
        if set(names) != expected or total > MAX_TOTAL:
            raise ValueError('Unexpected archive content or size limit exceeded')
        return manifest


def restore_settings(home, archive, selected_categories, target_desktop=None,
                     dconf_load=None, app_ids=None, dconf_run=None, audio_run=None,
                     audio_policy='strict', return_report=False):
    """Restore chosen settings with original copies preserved under restore-history.

    All settings first verified before any files are written. Return recovery
    directory. Does NOT install packages or restore to a different desktop.
    """
    if audio_policy not in ('strict', 'best_effort'):
        raise ValueError('Invalid audio restore policy')
    warnings = []
    manifest = inspect_backup(archive)
    selected = set(selected_categories)
    if not selected or not selected.issubset(set(manifest['categories']) - {'apps'}):
        raise ValueError('No valid settings categories selected')
    desk = desktop_family(target_desktop)
    if desk != manifest['desktop'] and not selected.issubset({'appsettings', 'fileassoc'}):
        raise ValueError(f'Desktop mismatch: backup is {manifest["desktop"]}; this is {desk}')
    home = Path(home)
    # On restore, app preference selection can be narrowed to individually
    # checked Flatpak IDs. The default None preserves all archived app settings.
    chosen_apps = None if app_ids is None else set(app_ids)
    entries = [e for e in manifest['files'] if e['category'] in selected and
               # Never overwrite WirePlumber's live state files while the daemon
               # is running: it can persist its in-memory state over them at logout.
               # schema-4 pactl audio is restored via the live server instead.
               not (e['category'] == 'audio' and manifest.get('audio_state') and
                    (e['path'] == '.local/state/wireplumber' or
                     e['path'].startswith('.local/state/wireplumber/'))) and
               (e['category'] != 'appsettings' or chosen_apps is None or
                (len(PurePosixPath(e['path']).parts)>2 and
                 PurePosixPath(e['path']).parts[2] in chosen_apps))]
    dconf_entries = [e for e in manifest['dconf'] if e['category'] in selected]
    audio_info = manifest.get('audio_state') if 'audio' in selected else None
    if 'audio' in selected and not audio_info:
        raise ValueError('This older backup has no live audio volume/device snapshot. '
                         'Create a new backup with Audio selected before restoring audio.')
    if not entries and not dconf_entries and not audio_info:
        raise ValueError('This backup has no saved values for the selected desktop settings. '
                         'Create a new backup on the source desktop with the desired settings checked.')
    payloads = []
    with zipfile.ZipFile(archive) as z:
        for e in entries:
            dest = _inside_home(home, e['path'])
            raw = z.read('settings/'+e['path'])
            if hashlib.sha256(raw).hexdigest()!=e['sha256']:
                raise ValueError('Settings checksum mismatch')
            if dest.is_dir(): raise ValueError('Destination is a directory')
            payloads.append((dest, raw, e['path']))
        dconf_payloads=[]
        for e in dconf_entries:
            raw=z.read(e['name'])
            if hashlib.sha256(raw).hexdigest()!=e['sha256']:
                raise ValueError('Settings checksum mismatch')
            dconf_payloads.append((e['prefix'],raw.decode('utf-8')))
    audio_payload = None
    if audio_info:
        with zipfile.ZipFile(archive) as z:
            audio_payload = json.loads(z.read('audio/state.json'))
        validate_audio_state(audio_payload)
        if audio_run is None and audio_policy == 'strict':
            raise RuntimeError('Live audio restore needs access to the host audio service')
    if dconf_payloads and dconf_load is None:
        raise ValueError('dconf restore is unavailable on this machine')
    if dconf_payloads and dconf_run is None:
        raise ValueError('Cannot safely restore dconf without snapshot access; no changes made')
    # Preflight snapshots BEFORE writing. Never overwrite the user's desktop
    # if the host dconf service cannot be read first.
    old_audio = None
    if audio_payload and audio_policy == 'best_effort':
        try:
            if audio_run is None:
                raise RuntimeError('Host audio service is unavailable')
            audio_payload, device_warnings = prepare_audio_restore(audio_run, audio_payload)
            old_audio = capture_audio_state(audio_run)
            warnings.extend(device_warnings)
        except RuntimeError as exc:
            # The user chose multiple setting groups: never undo the display,
            # panel or appearance restore merely because the audio device has
            # disappeared or changed beyond safe identification.
            if not payloads and not dconf_payloads:
                raise
            warnings.append('Audio was not restored: ' + str(exc))
            audio_payload = None
    elif audio_payload:
        old_audio = capture_audio_state(audio_run)
    old_dconf = []
    if dconf_payloads and dconf_run is not None:
        for prefix, _ in dconf_payloads:
            old_dconf.append((prefix, _dconf_dump(dconf_run, prefix)))
    recovery_base = _inside_home(home, '.local/share/UniversalLinuxSoftwareManager/restore-history')
    recovery = recovery_base / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    recovery.mkdir(parents=True, exist_ok=False)
    saved=[]
    applied_dconf=[]
    try:
        if old_dconf:
            metadata = []
            for index, (prefix, original) in enumerate(old_dconf):
                name = f'{index}.ini'
                target = recovery / 'dconf-before-restore' / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(original, encoding='utf-8')
                target.chmod(0o600)
                metadata.append({'prefix': prefix, 'file': name})
            manifest_copy = recovery / 'dconf-before-restore' / 'paths.json'
            manifest_copy.write_text(json.dumps(metadata, indent=2), encoding='utf-8')
            manifest_copy.chmod(0o600)
        if old_audio:
            current = recovery / 'audio-before-restore.json'
            current.write_text(json.dumps(old_audio, indent=2), encoding='utf-8')
            current.chmod(0o600)
        for dest, raw, relative in payloads:
            # Recheck symlinks between validation and write.
            _inside_home(home, relative)
            dest.parent.mkdir(parents=True, exist_ok=True)
            existed = dest.exists()
            if existed:
                restore_copy = recovery / relative
                restore_copy.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, restore_copy, follow_symlinks=False)
            fd, tmp = tempfile.mkstemp(prefix='.ulsm-restore-', dir=dest.parent)
            try:
                with os.fdopen(fd, 'wb') as out:
                    out.write(raw)
                    out.flush(); os.fsync(out.fileno())
                os.chmod(tmp, 0o600)
                os.replace(tmp, dest)
            finally:
                if os.path.exists(tmp): os.unlink(tmp)
            saved.append((dest, existed, recovery/relative))
        for prefix, data in dconf_payloads:
            # A command may partially modify a dconf path before reporting a
            # failure. Include this prefix in best-effort rollback too.
            applied_dconf.append(prefix)
            if not dconf_load(prefix, data):
                raise RuntimeError('dconf restore failed at ' + prefix +
                                   '. Original settings snapshots are in: ' + str(recovery) +
                                   '. GNOME settings may be partly applied; sign out and retry after checking dconf.')
        if audio_payload:
            apply_audio_state(audio_run, audio_payload)
    except Exception:
        if old_audio:
            try: apply_audio_state(audio_run, old_audio)
            except Exception: pass
        for prefix, previous in reversed(old_dconf):
            if prefix in applied_dconf:
                try: dconf_load(prefix, previous)
                except Exception: pass
        for dest, existed, old in reversed(saved):
            if existed and old.exists(): shutil.copy2(old, dest)
            elif not existed and dest.exists(): dest.unlink()
        raise
    if return_report:
        return {'recovery_dir': str(recovery), 'warnings': warnings}
    return recovery
