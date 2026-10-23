#!/usr/bin/env python3
"""Universal Linux Install & Uninstall Center: guarded package operations."""
import json
import configparser
import re
import time
import os
import shlex
import shutil
import stat
import tempfile
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QLocale, QThread, QTimer, QSize, QUrl, pyqtSignal
from PyQt6.QtGui import QIcon, QGuiApplication, QPainter, QColor, QDesktopServices
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView,
    QLineEdit, QFileDialog, QMessageBox, QProgressBar, QAbstractItemView, QStyle)

APP_ID = 'io.github.LionheartTim.UniversalLinuxCenter'
FEEDBACK_URL = 'https://github.com/LionheartTim/Universal-Linux-Install-Uninstall-Center/discussions/1'
LEGACY_APP_IDS = ('org.bazzite.FlatpakAndAppImageCenter',)
IN_SANDBOX = Path('/.flatpak-info').exists()
HOME = Path.home()
APP_DIR = HOME / 'Applications'
DESKTOP_DIR = HOME / '.local/share/applications'
NL = QLocale.system().name().startswith('nl')

def tr(nl, en): return nl if NL else en

def command(args, timeout=900):
    argv = (['flatpak-spawn', '--host'] if IN_SANDBOX else []) + list(map(str, args))
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return p.returncode == 0, p.stdout, (p.stderr or p.stdout).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, '', str(exc)

def available(program):
    ok, out, _ = command(['sh', '-c', 'command -v "$1"', 'sh', program], timeout=10)
    return ok and bool(out.strip())

def host_os_families():
    """Read the host OS identity; use ID_LIKE only for the expected package family."""
    ok, out, _ = command(['cat', '/etc/os-release'], timeout=10)
    if not ok:
        return set()
    result = {}
    for line in out.splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            result[key] = value.strip().strip('"').strip("'")
    return set((result.get('ID', '') + ' ' + result.get('ID_LIKE', '')).split())

def native_manager(kind):
    """Select only the actual host's supported package manager; fail closed."""
    families = host_os_families()
    if kind == 'Flatpak':
        return 'flatpak' if available('flatpak') else None
    if kind == 'AppImage':
        return 'appimage'
    if kind == 'Snap':
        return 'snap' if available('snap') else None
    if kind == 'RPM':
        if available('rpm-ostree'):
            ok, _, _ = command(['rpm-ostree', 'status', '--json'], 20)
            if ok: return 'rpm-ostree'
        # openSUSE MicroOS / Aeon use transactional updates, not ordinary zypper writes.
        if families & {'microos', 'opensuse-microos', 'aeon', 'opensuse-aeon', 'kalpa'}:
            return None
        if families & {'suse', 'opensuse', 'opensuse-tumbleweed', 'opensuse-leap', 'sled', 'sles'}:
            return 'zypper' if available('zypper') else None
        if families & {'fedora', 'rhel', 'centos', 'rocky', 'almalinux', 'nobara'}:
            if available('dnf5'): return 'dnf5'
            if available('dnf'): return 'dnf'
    if kind == 'DEB' and families & {'debian', 'ubuntu'}:
        return 'apt-get' if available('apt-get') else None
    if kind == 'Arch' and families & {'arch', 'manjaro', 'endeavouros', 'garuda'}:
        return 'pacman' if available('pacman') else None
    return None


def suitable_manager(kind):
    return native_manager(kind) is not None


def writable_location(path):
    """Check whether an existing parent can create an AppImage/launcher.

    This is an advisory startup check; actual IO errors are handled by the job.
    """
    parent = Path(path)
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    return parent.is_dir() and os.access(parent, os.W_OK | os.X_OK)


def environment_capabilities(kind):
    """(can_install, can_remove, explanation). Fail closed for unsupported hosts.

    This checks command availability, not successful PolicyKit authentication,
    repository health, free space or package-specific dependency resolution.
    """
    manager = native_manager(kind)
    if not manager:
        return False, False, tr('Niet ondersteund op deze Linux-distributie of pakketbeheerder ontbreekt.',
                                'Unsupported on this distribution or required package manager missing.')
    if kind == 'AppImage':
        if not (writable_location(APP_DIR) and writable_location(DESKTOP_DIR)):
            return False, False, tr('Geen schrijfrechten voor Applications of menu-snelkoppelingen.',
                                    'Applications or launcher directory is not writable.')
        return True, True, ''
    if kind == 'Flatpak':
        return True, True, ''
    if kind == 'RPM' and manager == 'rpm-ostree':
        return True, True, ''
    required = {
        'RPM': ('rpm',),
        'DEB': ('dpkg-query', 'apt', 'apt-get'),
        'Arch': ('pacman',),
        'Snap': ('snap',),
    }.get(kind, ())
    missing = [x for x in required if not available(x)]
    if not available('pkexec'):
        missing.append('pkexec')
    if missing:
        return False, False, tr('Benodigde host-hulpmiddelen ontbreken: ',
                                'Required host tools missing: ') + ', '.join(missing)
    return True, True, tr('Systeemautorisatie kan bij een bewerking gevraagd worden.',
                           'System authorization may be requested during an operation.')


def package_is_protected(name):
    """Additional deny list; never intended to make removal of other OS packages risk-free."""
    risky = {
        'systemd', 'systemd-libs', 'glibc', 'libc6', 'bash', 'coreutils', 'sudo',
        'pacman', 'dpkg', 'apt', 'apt-get', 'dnf', 'dnf5', 'rpm', 'zypper',
        'kernel', 'kernel-core', 'linux', 'linux-lts', 'grub', 'grub2',
        'shim', 'filesystem', 'basesystem', 'base-files', 'openssh-server',
        'gnome-shell', 'gdm', 'sddm', 'plasma-workspace', 'plasma-desktop',
        'networkmanager', 'dracut', 'selinux-policy', 'polkit', 'dbus',
        'xorg-x11-server-xorg', 'mesa-dri-drivers', 'qt6-qtbase',
    }
    return name.casefold() in risky or name.casefold().startswith(('linux-image-', 'kernel-modules-'))

def rpm_layers():
    ok, out, err = command(['rpm-ostree', 'status', '--json'], timeout=30)
    if not ok: return None, err
    try:
        data = json.loads(out)
        deployments = data.get('deployments', [])
        current = next((d for d in deployments if d.get('booted')), deployments[0] if deployments else {})
        # Normalize local NEVRAs just like the list view, so local RPMs can be removed.
        return requested_layers(current), ''
    except (ValueError, TypeError, KeyError) as exc:
        return None, str(exc)

def rpm_package_name(value):
    """Extract the package name from an rpm-ostree local NEVRA when possible."""
    import re
    value = str(value).rsplit('/', 1)[-1].removesuffix('.rpm')
    # RPM filenames generally follow NAME-VERSION-RELEASE.ARCH.
    match = re.match(r'^(.+)-([0-9][^-]*)-([^-]+)\.[^.]+$', value)
    return match.group(1) if match else value

def requested_layers(deployment):
    names = set()
    for key in ('requested-packages', 'requested-local-packages',
                'requested-local-fileoverride-packages'):
        for item in deployment.get(key, []) or []:
            if isinstance(item, str):
                names.add(rpm_package_name(item) if 'local' in key else item)
    return names

def rpm_deployment_rows():
    """Union of booted and pending explicitly requested layers only.

    The staged image is not confused with the currently booted image.
    """
    ok, output, error = command(['rpm-ostree', 'status', '--json'], 30)
    if not ok:
        return None, error
    try:
        deployments = json.loads(output).get('deployments', [])
        booted = next((d for d in deployments if d.get('booted')), None)
        if booted is None:
            return None, tr('Actieve deployment onbekend.', 'Booted deployment unknown.')
        active = requested_layers(booted)
        pending = next((d for d in deployments if d.get('staged') or d.get('pending')), None)
        # In rpm-ostree, the first non-booted deployment is the next boot target.
        if pending is None and deployments and not deployments[0].get('booted'):
            pending = deployments[0]
        staged = requested_layers(pending) if pending else active
        rows = []
        for name in sorted(active | staged, key=str.casefold):
            status = 'Reboot required' if pending and ((name in active) != (name in staged)) else ''
            rows.append((name, tr('Zelf toegevoegd', 'Layered'), name, status))
        return rows, ''
    except (ValueError, TypeError, AttributeError) as exc:
        return None, str(exc)

STATUS_FILE = HOME / '.config' / 'flatpak-appimage-center' / 'pending-status.json'

def boot_identifier():
    ok, out, _ = command(['cat', '/proc/sys/kernel/random/boot_id'], 10)
    return out.strip() if ok else ''

def load_pending_status():
    try:
        saved = json.loads(STATUS_FILE.read_text(encoding='utf-8'))
        if not isinstance(saved, dict): return {}
        # Never leave stale warnings displayed after a reboot.
        current_boot = boot_identifier()
        return {k: v for k, v in saved.items() if isinstance(v, dict) and
                v.get('boot') == current_boot and current_boot}
    except (OSError, ValueError):
        return {}

def store_pending_status(data):
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATUS_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2), encoding='utf-8')
    tmp.replace(STATUS_FILE)

def reboot_assessment(kind, rpm_ostree_job=False):
    """Return (status, explanation) based on host-side evidence, not guessed percentages.

    pending: a non-booted ostree deployment exists; reboot: host requests a restart;
    clear: this package workflow does not stage a new OS deployment;
    unknown: reliable cross-distro signal is unavailable.
    """
    if rpm_ostree_job:
        ok, out, err = command(['rpm-ostree', 'status', '--json'], timeout=30)
        if not ok:
            return 'unknown', tr('rpm-ostree-status niet beschikbaar.', 'rpm-ostree status unavailable.')
        try:
            deployments = json.loads(out).get('deployments', [])
            if deployments and not deployments[0].get('booted', False) and any(d.get('booted') for d in deployments):
                return 'pending', tr('Nieuwe systeemversie staat klaar.', 'New system deployment is ready.')
            return 'unknown', tr('Geen nieuwe systeemversie bevestigd.', 'No pending deployment verified.')
        except (TypeError, ValueError, AttributeError):
            return 'unknown', tr('Kan deploymentstatus niet lezen.', 'Cannot read deployment status.')
    if kind in ('Flatpak', 'AppImage', 'Snap'):
        # These workflows do not stage a new immutable OS deployment.
        return 'clear', ''
    # Debian and derivatives conventionally set a reboot-required marker.
    # Run on the HOST, not in the Flatpak sandbox.
    if kind == 'DEB':
        ok, out, _ = command(['sh', '-c', 'test -e /run/reboot-required && echo yes || echo no'], 10)
        if ok and out.strip() == 'yes': return 'reboot', ''
        if ok and out.strip() == 'no': return 'clear', ''
    # DNF needs-restarting -r has exit code 1 when reboot is recommended.
    # Do not call it through command(): it discards the actual exit code.
    if kind == 'RPM' and native_manager('RPM') in ('dnf', 'dnf5'):
        argv = (['flatpak-spawn', '--host'] if IN_SANDBOX else []) + [native_manager('RPM'), 'needs-restarting', '-r']
        try:
            probe = subprocess.run(argv, capture_output=True, text=True, timeout=20)
            output = (probe.stdout + probe.stderr).lower()
            if probe.returncode == 0: return 'clear', ''
            if probe.returncode == 1 and ('reboot' in output or 'restart' in output):
                return 'reboot', ''
        except (OSError, subprocess.TimeoutExpired):
            pass
    return 'unknown', ''

def desktop_rpm_packages():
    """Show real graphical programs, not libraries/base OS packages.

    There is no portable RPM metadata bit meaning 'system core'. Owning a
    desktop launcher is a positive application signal. Query on the host.
    Return None on error; never silently expose the full RPM inventory.
    """
    ok, paths, _ = command(['find', '/usr/share/applications', '-maxdepth', '1',
                            '-type', 'f', '-name', '*.desktop'], 25)
    if not ok:
        return None
    files = [p.strip() for p in paths.splitlines() if p.strip()]
    result = set()
    for start in range(0, len(files), 80):
        batch = files[start:start + 80]
        # RPM can exit nonzero when even one launcher is not package-owned;
        # successfully resolved package names are still present in stdout.
        _, output, _ = command(['rpm', '-qf', '--qf', '%{NAME}\n', *batch], 30)
        result.update(p for p in output.splitlines()
                      if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9+_.-]*', p.strip()))
    return {pkg for pkg in result if not package_is_protected(pkg)}


def rpm_erase_test(name):
    """RPM checks installed reverse dependencies without modifying packages.

    Run the exact package name, not an arbitrary package capability. If an
    unprivileged test cannot acquire the rpm lock, ask Polkit to test it.
    """
    ok, out, err = command(['rpm', '-e', '--test', name], 60)
    if ok:
        return True, ''
    detail = (err or out).strip()
    if ('Permission denied' in detail or 'not root' in detail or
            'transaction lock' in detail) and available('pkexec'):
        ok, out, err = command(['pkexec', 'rpm', '-e', '--test', name], 90)
        if ok:
            return True, ''
        detail = (err or out).strip()
    return False, detail or tr('RPM-controle mislukt.', 'RPM dependency check failed.')


def rpm_regular_remove_args(manager, name):
    """No force flags, no cleanup of unneeded dependencies."""
    if manager == 'dnf5':
        return ['pkexec', 'dnf5', 'remove', '--no-autoremove', '-y', name]
    if manager == 'dnf':
        return ['pkexec', 'dnf', '--setopt=clean_requirements_on_remove=False',
                'remove', '-y', name]
    if manager == 'zypper':
        return ['pkexec', 'zypper', '--non-interactive', 'remove',
                '--no-clean-deps', '--no-force-resolution', name]
    return None


def rpm_transaction_preview(manager, name):
    """Read-only solver preview; no privileged package operation happens here."""
    if manager in ('dnf', 'dnf5'):
        # --assumeno can return nonzero even for a valid transaction.
        args = [manager, '--assumeno', 'remove', name]
        if manager == 'dnf5':
            args.append('--no-autoremove')
        else:
            args.insert(1, '--setopt=clean_requirements_on_remove=False')
        ok, out, err = command(['env', 'LC_ALL=C', *args], 90)
        preview = (out + '\n' + err).strip()
        # The dry-run may return nonzero because the answer to the prompt is no.
        valid = bool(preview) and ('Removing:' in preview or
                                   'Remove ' in preview or 'Removing dependent' in preview)
        return valid, preview
    if manager == 'zypper':
        ok, out, err = command(['env', 'LC_ALL=C', 'zypper', '--non-interactive',
                'remove', '--dry-run', '--details', '--no-clean-deps',
                '--no-force-resolution', name], 90)
        return ok, (out + '\n' + err).strip()
    return False, ''


def removal_preflight(kind, name):
    """Read-only host-side preflight; fail closed when safe removal can't be determined."""
    if kind == 'DEB':
        ok, out, err = command(['dpkg-query', '-W', '-f=${Essential}\t${Status}', name], 20)
        if not ok or 'install ok installed' not in out:
            return False, tr('Pakket niet bevestigd als geïnstalleerd: ', 'Package not confirmed installed: ') + (err or out)
        if out.split('\t', 1)[0].strip().lower() == 'yes':
            return False, tr('Essentieel DEB-systeempakket: verwijderen geblokkeerd.', 'Essential DEB system package: removal blocked.')
        ok, out, err = command(['apt-get', '-s', 'remove', name], 45)
        if not ok: return False, tr('APT-simulatie mislukt: ', 'APT simulation failed: ') + (err or out)
        planned = [line.split()[1] for line in out.splitlines() if line.startswith('Remv ') and len(line.split()) > 1]
        if name not in planned:
            return False, tr('APT bevestigt de verwijdering niet.', 'APT did not confirm the removal.')
        if len(planned) != 1:
            return False, tr('APT wil ook andere pakketten verwijderen. Bewerking geblokkeerd: ', 'APT would remove other packages; blocked: ') + ', '.join(planned[:20])
        return True, tr('APT-simulatie: alleen dit pakket wordt verwijderd.', 'APT simulation: only this package will be removed.')
    if kind == 'RPM':
        manager = native_manager('RPM')
        if package_is_protected(name):
            return False, tr('Kritisch systeempakket: verwijderen geblokkeerd.',
                             'Protected system package: removal blocked.')
        if manager not in ('dnf', 'dnf5', 'zypper'):
            return False, tr('RPM-beheerder niet ondersteund.', 'RPM manager not supported.')
        # The user must be choosing a genuine graphical program; matching a
        # name alone does not mean that it is safe to uninstall.
        owned = desktop_rpm_packages()
        if owned is None or name not in owned:
            return False, tr('Dit pakket is niet bevestigd als grafische applicatie.',
                             'This package is not verified as a graphical application.')
        if manager in ('dnf', 'dnf5'):
            ok, out, err = command([manager, 'repoquery', '--userinstalled',
                                    '--queryformat', '%{name}'], 45)
            if not ok or name not in out.splitlines():
                return False, tr('Pakket niet bevestigd als zelf geïnstalleerd.',
                                 'Package not verified as user-requested.')
        # RPM itself refuses to remove a package that still has installed
        # reverse dependencies. This check is stricter than the solver alone.
        safe, why = rpm_erase_test(name)
        if not safe:
            return False, tr('Kan dit pakket niet afzonderlijk verwijderen:\n',
                             'Cannot safely remove this package alone:\n') + why
        return True, tr('Afhankelijkheden gecontroleerd; alleen dit pakket geselecteerd.',
                        'Dependencies checked; only this package selected.')
    if kind == 'Arch':
        ok, out, err = command(['pacman', '-Qqe'], 30)
        if not ok: return False, err
        if name not in out.splitlines():
            return False, tr('Pakket is niet expliciet geïnstalleerd; verwijderen geblokkeerd.', 'Package is not explicitly installed; removal blocked.')
        ok, out, err = command(['pacman', '-R', '--print', '--print-format', '%n', name], 30)
        if not ok: return False, tr('Pacman-controle mislukt: ', 'Pacman preflight failed: ') + (err or out)
        planned = [v.strip() for v in out.splitlines() if v.strip()]
        if planned != [name]:
            return False, tr('Onverwachte verwijdertransactie: ', 'Unexpected removal transaction: ') + ', '.join(planned[:20])
        return True, tr('Pacman bevestigt verwijdering van dit pakket.', 'Pacman confirms removal of this package.')
    return True, ''

def installation_scope(kind, flatpak_installation=''):
    """Installation ownership, not process privilege or the package's origin."""
    if kind == 'AppImage':
        return 'USER'
    if kind == 'Flatpak':
        scope = flatpak_installation.strip().casefold()
        if scope == 'user':
            return 'USER'
        # "system", "default", and named Flatpak installations are system-wide.
        return 'SYSTEM' if scope else ''
    # RPM (including rpm-ostree), DEB, pacman and Snap package managers install
    # into system-wide stores, even when invoked by an unprivileged user.
    return 'SYSTEM' if kind in ('RPM', 'DEB', 'Arch', 'Snap') else ''


def flatpak_removal_installation_arg(installation):
    """Target the exact Flatpak installation; don't silently default to --user."""
    raw = installation.strip()
    lower = raw.casefold()
    if lower == 'user': return '--user'
    if lower in ('system', 'default'): return '--system'
    if raw and re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', raw):
        return '--installation=' + raw
    return None


def desktop_path(name):
    return DESKTOP_DIR / (APP_ID + '.' + name.encode('utf-8').hex() + '.desktop')


def legacy_desktop_paths(name):
    # Previous builds generated AppImage launchers using the old application ID.
    # Only remove an exact legacy launcher for this same managed AppImage.
    encoded_name = name.encode('utf-8').hex()
    return [DESKTOP_DIR / (old_id + '.' + encoded_name + '.desktop')
            for old_id in LEGACY_APP_IDS]

def safe_quoted_path(path):
    return str(path).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%').replace('\n', '')

# Desktop-entry icon lookup is intentionally read-only and display-only.
# Package ownership cannot be inferred safely from a similar-looking desktop name.
_ICON_CACHE = {}
_DESKTOP_INDEX = None

def _icon_key(value):
    return re.sub(r'[^a-z0-9]+', '', str(value).casefold())

def _desktop_icons():
    global _DESKTOP_INDEX
    if _DESKTOP_INDEX is not None:
        return _DESKTOP_INDEX
    found = {}
    roots = [
        HOME / '.local/share/applications',
        HOME / '.local/share/flatpak/exports/share/applications',
        Path('/var/lib/flatpak/exports/share/applications'),
        Path('/usr/local/share/applications'), Path('/usr/share/applications'),
        Path('/run/host/usr/share/applications'),
        Path('/run/host/var/lib/flatpak/exports/share/applications'),
    ]
    for root in roots:
        if not root.is_dir():
            continue
        for entry in root.glob('*.desktop'):
            try:
                cfg = configparser.ConfigParser(interpolation=None, strict=False)
                cfg.optionxform = str
                cfg.read(entry, encoding='utf-8')
                if not cfg.has_section('Desktop Entry'):
                    continue
                item = cfg['Desktop Entry']
                if item.get('Hidden', '').lower() == 'true':
                    continue
                icon_name = item.get('Icon', '').strip()
                if not icon_name:
                    continue
                keys = [entry.stem, item.get('Name', ''), item.get('Exec', '').split(' ')[0]]
                for key in keys:
                    normalized = _icon_key(key)
                    if normalized and normalized not in found:
                        found[normalized] = icon_name
            except (OSError, UnicodeError, configparser.Error):
                continue
    _DESKTOP_INDEX = found
    return found

def _icon_from_value(value):
    if not value:
        return QIcon()
    path = Path(value)
    if path.is_absolute():
        return QIcon(str(path)) if path.is_file() else QIcon()
    return QIcon.fromTheme(value)

def package_icon(kind, name, identity):
    cache_key = (kind, name, identity)
    if cache_key in _ICON_CACHE:
        return _ICON_CACHE[cache_key]
    icon = QIcon()
    # AppImage integration writes its own .desktop file with a real Icon= key.
    if kind == 'AppImage':
        entry = desktop_path(identity)
        if entry.is_file():
            try:
                cfg = configparser.ConfigParser(interpolation=None)
                cfg.optionxform = str
                cfg.read(entry, encoding='utf-8')
                icon = _icon_from_value(cfg.get('Desktop Entry', 'Icon', fallback=''))
            except (OSError, UnicodeError, configparser.Error):
                pass
    # Flatpak icons follow the application ID; try them before generic matches.
    if icon.isNull() and kind == 'Flatpak':
        icon = QIcon.fromTheme(identity)
    if icon.isNull():
        index = _desktop_icons()
        for candidate in (identity, name):
            value = index.get(_icon_key(candidate))
            if value:
                icon = _icon_from_value(value)
                if not icon.isNull():
                    break
    if icon.isNull():
        for candidate in (identity, name):
            icon = QIcon.fromTheme(str(candidate))
            if not icon.isNull():
                break
    if icon.isNull():
        icon = QIcon.fromTheme('application-x-executable')
    if icon.isNull():
        icon = QIcon.fromTheme('package-x-generic')
    if icon.isNull():
        icon = QApplication.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
    _ICON_CACHE[cache_key] = icon
    return icon

class Job(QThread):
    done = pyqtSignal(bool, str)
    output = pyqtSignal(str)

    def __init__(self, args=None, action=None):
        super().__init__()
        self.args, self.action = args, action

    def run(self):
        try:
            if self.action:
                self.output.emit(tr('Lokale bestanden verwerken...', 'Processing local files...'))
                self.action()
                self.done.emit(True, tr('Bewerking voltooid.', 'Operation complete.'))
                return
            commands = self.args if self.args and isinstance(self.args[0], (list, tuple)) else [self.args]
            history = []
            returncode = 0
            for command_args in commands:
                argv = (['flatpak-spawn', '--host'] if IN_SANDBOX else []) + list(map(str, command_args))
                proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, encoding='utf-8', errors='replace', bufsize=1)
                pending = ''
                while True:
                    ch = proc.stdout.read(1)
                    if not ch:
                        if pending.strip():
                            history.append(pending.strip())
                            self.output.emit(pending.strip()[-350:])
                        break
                    if ch in ('\r', '\n'):
                        if pending.strip():
                            line = pending.strip()
                            history.append(line)
                            self.output.emit(line[-350:])
                            if len(history) > 80: history.pop(0)
                        pending = ''
                    else:
                        pending += ch
                        if len(pending) > 2000:
                            pending = pending[-1000:]
                returncode = proc.wait()
                if returncode != 0:
                    break
            message = '\n'.join(history)[-3000:] or (tr('Voltooid.', 'Completed.') if returncode == 0
                          else tr('Opdracht mislukt zonder fouttekst.', 'Command failed without diagnostic output.'))
            self.done.emit(returncode == 0, message)
        except Exception as exc:
            self.done.emit(False, str(exc))


class ConveyorProgressBar(QProgressBar):
    """Full-width seamless loop: 1-2-3-2 repeated four times."""

    COLORS = ("#90dcff", "#0862b7", "#02274f", "#0862b7")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._phase = 0.0
        self._animation = QTimer(self)
        self._animation.setInterval(30)
        self._animation.timeout.connect(self._advance)
        self.setTextVisible(True)

    def setRange(self, minimum, maximum):
        super().setRange(minimum, maximum)
        if minimum == 0 and maximum == 0:
            self._phase = 0.0
            self._animation.start()
        else:
            self._animation.stop()
            self.update()

    def _advance(self):
        self._phase = (self._phase + 0.012) % 1.0
        self.update()

    def paintEvent(self, event):
        if not (self.minimum() == 0 and self.maximum() == 0):
            super().paintEvent(event)
            return

        painter = QPainter(self)
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#092c55"))
        painter.drawRoundedRect(rect, 4, 4)
        painter.setClipRect(rect)
        # Exactly sixteen equal-width blocks span the full track at any time.
        # A four-block shift is periodic, so wrapping never reveals an empty area.
        width = max(1, rect.width())
        block_width = width / 16.0
        shift = self._phase * (4 * block_width)
        for index in range(-4, 20):
            x0 = rect.left() + index * block_width + shift
            x1 = rect.left() + (index + 1) * block_width + shift
            # Integer pixel edges avoid hairline gaps from rounding and antialiasing.
            left = round(x0)
            right = round(x1)
            painter.fillRect(left, rect.top(), max(1, right - left),
                             rect.height(), QColor(self.COLORS[index % 4]))
        painter.end()

class PackageTab(QWidget):
    EXT = {'Flatpak': ('.flatpak', '.flatpakref'), 'AppImage': ('.appimage',),
           'RPM': ('.rpm',), 'DEB': ('.deb',), 'Arch': ('.pkg.tar.zst', '.pkg.tar.xz', '.pkg.tar.gz'),
           'Snap': ('.snap',)}
    def __init__(self, kind):
        super().__init__()
        self.kind, self.busy, self.job = kind, False, None
        self.can_install, self.can_remove, self.environment_note = environment_capabilities(kind)
        self.setAcceptDrops(self.can_install)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr('Installeer via bestandsselectie of sleep een pakket hierheen. Selecteer een pakket om te verwijderen.',
                                   'Install by choosing a file or dropping a package here. Select a package to remove.')))
        self.choose = QPushButton(tr(f'{kind}-bestand installeren...', f'Install {kind} file...'))
        self.choose.clicked.connect(self.pick)
        self.choose.setEnabled(self.can_install)
        if not self.can_install:
            self.choose.setToolTip(self.environment_note)
        layout.addWidget(self.choose)
        self.drop = QLabel(tr('Sleep installatiebestand hierheen', 'Drop installation file here') + '\n' + ', '.join(self.EXT[kind]))
        self.drop.setMinimumHeight(78)
        self.drop.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop.setStyleSheet('border: 2px dashed #328cda; border-radius: 8px; padding: 12px;')
        layout.addWidget(self.drop)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr('Zoek op naam of pakket-ID...', 'Search name or package ID...'))
        self.search.textChanged.connect(self.filter)
        layout.addWidget(self.search)
        self.table = QTableWidget()
        self.table.setIconSize(QSize(22, 22))
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([tr('Naam', 'Name'), tr('Versie / details', 'Version / details'),
                                              tr('Pakket-ID', 'Package ID'), tr('Installatie', 'Installation'),
                                              tr('Status', 'Status')])
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)
        self.status = QLabel('')
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(40)
        layout.addWidget(self.status)
        self.progress_timer = QTimer(self)
        self.progress_timer.setInterval(1000)
        self.progress_timer.timeout.connect(self.update_elapsed)
        self.started_at = None
        self.last_output = ''
        self.progress = ConveyorProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat(tr('Gereed', 'Ready'))
        layout.addWidget(self.progress)
        self.remove = QPushButton(tr('Geselecteerde verwijderen', 'Uninstall selected'))
        self.remove.setObjectName('destructive')
        self.remove.clicked.connect(self.remove_selected)
        self.table.itemSelectionChanged.connect(self.update_remove_button)
        layout.addWidget(self.remove)
        self.reload()
        self.update_remove_button()

    def dragEnterEvent(self, event):
        if not self.can_install or self.busy:
            event.ignore()
            return
        urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
        if len(urls) == 1 and urls[0].isLocalFile() and self.matches(urls[0].toLocalFile()):
            event.acceptProposedAction()
    def dropEvent(self, event):
        if not self.can_install or self.busy:
            event.ignore()
            return
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            self.install_file(Path(urls[0].toLocalFile()))
            event.acceptProposedAction()
    def matches(self, path):
        return path.lower().endswith(self.EXT[self.kind])
    def pick(self):
        path, _ = QFileDialog.getOpenFileName(self, tr('Selecteer pakket', 'Choose package'), str(HOME),
            tr('Ondersteunde bestanden', 'Supported files') + ' (' + ' '.join('*' + ext for ext in self.EXT[self.kind]) + ')')
        if path: self.install_file(Path(path))
    def show_rows(self, rows):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for record in sorted(rows, key=lambda r: r[0].casefold()):
            name, version, identity, status = record[:4]
            installation = record[4] if len(record) > 4 else ''
            scope = installation_scope(self.kind, installation)
            row = self.table.rowCount()
            self.table.insertRow(row)
            for i, value in enumerate((name, version, identity, scope, status)):
                item = QTableWidgetItem(str(value))
                if i == 0:
                    item.setIcon(package_icon(self.kind, name, identity))
                if i == 3 and self.kind == 'Flatpak':
                    # The raw Flatpak installation is retained for accurate deletion,
                    # including installations named in installations.d.
                    item.setData(Qt.ItemDataRole.UserRole, installation)
                    if scope == 'SYSTEM' and installation.casefold() not in ('system', 'default'):
                        item.setToolTip(tr('Systeeminstallatie: ', 'System installation: ') + installation)
                self.table.setItem(row, i, item)
        self.table.setSortingEnabled(True)
        self.table.sortItems(0, Qt.SortOrder.AscendingOrder)
        self.filter()
        self.update_remove_button()
    def update_remove_button(self):
        self.remove.setEnabled(self.can_remove and not self.busy and bool(self.table.selectedItems()))
        if not self.can_remove:
            self.remove.setToolTip(self.environment_note)
    def filter(self):
        q = self.search.text().casefold()
        for row in range(self.table.rowCount()):
            self.table.setRowHidden(row, not any(q in self.table.item(row, i).text().casefold()
                                                     for i in range(self.table.columnCount())))
    def reload(self):
        global _DESKTOP_INDEX
        _DESKTOP_INDEX = None
        _ICON_CACHE.clear()
        k = self.kind
        rows, warning = [], ''
        if k == 'AppImage':
            if APP_DIR.is_dir():
                rows = [(p.stem, tr('AppImage', 'AppImage'), p.name, '') for p in APP_DIR.iterdir()
                        if p.is_file() and p.name.lower().endswith('.appimage')]
        elif k == 'Flatpak':
            ok, out, err = command(['flatpak', 'list', '--app',
                                     '--columns=name,application,version,installation'], 60)
            if ok:
                for line in out.splitlines():
                    parts = line.split('\t')
                    if len(parts) >= 4 and parts[1].strip():
                        rows.append((parts[0], parts[2], parts[1], '', parts[3].strip()))
            else: warning = err
        elif k == 'RPM' and native_manager('RPM') == 'rpm-ostree':
            rows, err = rpm_deployment_rows()
            if rows is None:
                warning, rows = err, []
        elif not suitable_manager(k):
            warning = tr('Pakketformaat wordt niet beheerd door deze distributie.',
                         'Package format is not managed by this distribution.')
        else:
            cmds = {'RPM': ['rpm', '-qa', '--qf', '%{NAME}\t%{VERSION}-%{RELEASE}\n'],
                    'DEB': ['dpkg-query', '-W', '-f=${binary:Package}\t${Version}\n'],
                    'Arch': ['pacman', '-Q'], 'Snap': ['snap', 'list']}
            ok, out, err = command(cmds[k], 60)
            if ok:
                for line in out.splitlines()[1 if k == 'Snap' else 0:]:
                    cols = line.split('\t') if k in ('RPM', 'DEB') else line.split()
                    if len(cols) >= 2: rows.append((cols[0], cols[1], cols[0], ''))
                if k == 'RPM':
                    owned = desktop_rpm_packages()
                    if owned is None:
                        rows = []
                        warning = tr('Kan applicatiepakketten niet controleren.',
                                     'Unable to verify graphical applications.')
                    else:
                        allowed = owned
                        if native_manager('RPM') in ('dnf', 'dnf5'):
                            ok_explicit, explicit, _ = command([native_manager('RPM'), 'repoquery',
                                             '--userinstalled', '--queryformat', '%{name}'], 45)
                            if ok_explicit:
                                allowed = allowed.intersection(explicit.splitlines())
                            else:
                                allowed = set()
                                warning = tr('Kan zelf geïnstalleerde RPM-pakketten niet controleren.',
                                             'Cannot verify user-installed RPM packages.')
                        # openSUSE uses app-owned .desktop launchers; Fedora
                        # requires both app ownership and explicit install reason.
                        rows = [r for r in rows if r[2] in allowed]
            else: warning = err
        # Every tab has the same status column. Non-ostree packages only get a
        # recorded reboot warning if this app observed one during a successful job.
        if not (k == 'RPM' and native_manager('RPM') == 'rpm-ostree'):
            records = load_pending_status()
            ids = {r[2] for r in rows}
            rows = [tuple(rec[:3]) + ('Reboot required' if records.get(k + '|' + rec[2])
                                      else rec[3],) + tuple(rec[4:]) for rec in rows]
            stale = [key for key in records if key.startswith(k + '|') and key.split('|', 1)[1] not in ids]
            if stale:
                for key in stale: del records[key]
                store_pending_status(records)
        self.show_rows(rows)
        if warning: self.status.setText(tr('Niet beschikbaar: ', 'Unavailable: ') + warning[-350:])
        elif not self.can_install or not self.can_remove:
            self.status.setText(tr('Niet beschikbaar: ', 'Unavailable: ') + self.environment_note)
        elif k == 'RPM' and native_manager('RPM') == 'rpm-ostree':
            self.status.setText(tr('Alleen expliciet toegevoegde RPM-lagen; geen basispakketten.',
                                   'Only explicitly layered RPM packages; no base OS packages.'))
        elif k == 'RPM':
            self.status.setText(tr('Alleen herkenbare applicaties; systeempakketten verborgen.',
                                   'Recognized applications only; system packages hidden.'))
        else: self.status.setText(tr('Pakketten gevonden: ', 'Packages found: ') + str(len(rows)))

    def confirm(self, message):
        return QMessageBox.question(self, tr('Bevestig bewerking', 'Confirm operation'), message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes
    def start(self, args=None, action=None, note='', operation='install'):
        if self.busy: return
        self.busy = True
        for w in (self.choose, self.remove, self.table, self.search): w.setEnabled(False)
        self.operation_name = note or self.kind
        self.reboot_marker_already_present = False
        if self.kind == 'DEB':
            self.reboot_marker_already_present = reboot_assessment('DEB')[0] == 'reboot'
        self.operation_type = operation
        self.ostree_operation = bool(args and isinstance(args[0], str) and args[0] == 'rpm-ostree')
        self.operation_identity = note if operation == 'remove' else ''
        self.before_ids = {self.table.item(r, 2).text() for r in range(self.table.rowCount())}
        self.last_output = tr('Opdracht wordt gestart...', 'Starting command...')
        self.started_at = time.monotonic()
        self.update_elapsed()
        self.progress_timer.start()
        # No fabricated percentage; indeterminate until the process finishes.
        self.progress.setRange(0, 0)
        self.progress.setFormat(tr('Bezig...', 'Working...'))
        self.job = Job(args, action)
        self.job.output.connect(self.on_job_output)
        self.job.done.connect(self.finished)
        self.job.start()
    def on_job_output(self, line):
        self.last_output = line
        self.update_elapsed()

    def update_elapsed(self):
        if self.started_at is None: return
        elapsed = int(time.monotonic() - self.started_at)
        duration = f'{elapsed // 60:02d}:{elapsed % 60:02d}'
        self.status.setText(f'{self.operation_name} | {duration} | {self.last_output}')

    def finished(self, ok, detail):
        self.progress_timer.stop()
        self.started_at = None
        self.busy = False
        for w in (self.choose, self.table, self.search):
            w.setEnabled(True)
        self.update_remove_button()

        # Keep user-facing dialogs short; verbose command output belongs only
        # in an error dialog, not in the normal details panel after completion.
        label = self.operation_name
        is_remove = self.operation_type == 'remove'
        action_nl = 'Verwijdering' if is_remove else 'Installatie'
        action_en = 'Removal' if is_remove else 'Installation'
        if ok:
            state, explanation = reboot_assessment(self.kind, self.ostree_operation)
            # An existing OS reboot request must not be attributed to this package.
            if self.kind == 'DEB' and self.reboot_marker_already_present and state == 'reboot':
                state = 'unknown'
            if not self.ostree_operation and state == 'reboot':
                # Installation name can differ from filename; resolve after reload
                # for installs. Only mark a known selected package for removals.
                if self.operation_identity:
                    records = load_pending_status()
                    records[self.kind + '|' + self.operation_identity] = {'boot': boot_identifier()}
                    store_pending_status(records)
            if state in ('pending', 'reboot'):
                message = tr(f'{label} — {action_nl.lower()} voorbereid. Herstart vereist.' if state == 'pending'
                             else f'{label} — {action_nl} voltooid. Herstart vereist.',
                             f'{label} — {action_en.lower()} queued. Restart required.' if state == 'pending'
                             else f'{label} — {action_en} complete. Restart required.')
            elif state == 'clear':
                message = tr(f'{label} — {action_nl} voltooid.', f'{label} — {action_en} complete.')
            else:
                message = tr(f'{label} — {action_nl} voltooid. Herstartstatus onbekend.',
                             f'{label} — {action_en} complete. Restart status unknown.')
        else:
            message = tr(f'{label} — {action_nl} mislukt.', f'{label} — {action_en} failed.')

        pending_reboot_for_install = bool(ok and state == 'reboot' and not self.ostree_operation and not is_remove)
        if ok:
            QMessageBox.information(self, tr('Voltooid', 'Complete'), message)
        else:
            QMessageBox.warning(self, tr('Mislukt', 'Failed'),
                message + '\n\n' + detail[-2000:])

        # reload() restores the normal summary/details text. Do not overwrite
        # it afterwards with retained rpm-ostree / package-manager logs.
        self.last_output = ''
        self.operation_name = ''
        self.reload()
        if pending_reboot_for_install:
            # Mark only the packages newly detected after an installation.
            after_ids = {self.table.item(r, 2).text() for r in range(self.table.rowCount())}
            new_ids = after_ids - self.before_ids
            if new_ids:
                records = load_pending_status()
                for ident in new_ids:
                    records[self.kind + '|' + ident] = {'boot': boot_identifier()}
                store_pending_status(records)
                self.reload()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat(tr('Gereed', 'Ready'))

    def install_file(self, path):
        if self.busy: return
        if not self.can_install:
            QMessageBox.warning(self, tr('Niet beschikbaar', 'Unavailable'), self.environment_note)
            return
        if not path.is_file() or not self.matches(str(path)):
            QMessageBox.warning(self, 'Info', tr('Ongeldig pakketbestand.', 'Invalid package file.'))
            return
        k = self.kind
        if not suitable_manager(k):
            QMessageBox.warning(self, 'Info', tr('Deze distributie ondersteunt dit pakketbeheer niet.',
                'This distribution does not support this package manager.'))
            return
        unsigned_snap = False
        assertion = None
        if k == 'Snap':
            assertion = next((candidate for candidate in
                (path.with_suffix('.assert'), Path(str(path) + '.assert'))
                if candidate.is_file()), None)
            if assertion is None:
                warning = QMessageBox(self)
                warning.setIcon(QMessageBox.Icon.Warning)
                warning.setWindowTitle(tr('Mogelijk onveilig bestand', 'Potentially unsafe file'))
                warning.setText(tr('Dit bestand kan gevaarlijk of schadelijk zijn. '
                                   'Weet je zeker dat je het wilt installeren?',
                                   'This file might be dangerous or malicious. '
                                   'Are you sure you want to install?'))
                warning.setInformativeText(tr('De ondertekening wordt niet gecontroleerd. '
                                              'Installeer alleen bestanden uit bronnen die je vertrouwt.',
                                              'The publisher signature will not be verified. '
                                              'Only install files from sources you trust.'))
                warning.setStandardButtons(QMessageBox.StandardButton.Yes |
                                           QMessageBox.StandardButton.No)
                warning.setDefaultButton(QMessageBox.StandardButton.No)
                if warning.exec() != QMessageBox.StandardButton.Yes:
                    return
                unsigned_snap = True
        manager = native_manager(k)
        if k == 'RPM':
            if manager == 'rpm-ostree':
                args = ['rpm-ostree', 'install', str(path)]
            elif manager in ('dnf', 'dnf5', 'zypper') and available('pkexec'):
                args = ['pkexec', manager, 'install', '-y', str(path)] if manager != 'zypper' else [
                    'pkexec', 'zypper', '--non-interactive', 'install', str(path)]
            else: args = None
        elif k == 'DEB': args = ['pkexec', 'apt', 'install', '-y', str(path)] if available('apt') and available('pkexec') else None
        elif k == 'Arch': args = ['pkexec', 'pacman', '-U', '--noconfirm', str(path)] if available('pacman') and available('pkexec') else None
        elif k == 'Snap':
            args = (['pkexec', 'snap', 'install', '--dangerous', str(path)] if unsigned_snap else
                    [['pkexec', 'snap', 'ack', str(assertion)], ['pkexec', 'snap', 'install', str(path)]]) if available('pkexec') else None
        elif k == 'Flatpak': args = ['flatpak', 'install', '--user', '--noninteractive', '-y', str(path)]
        else: args = None
        if k != 'AppImage' and not args:
            QMessageBox.warning(self, 'Info', tr('De benodigde pakketbeheerder of authorisatie ontbreekt.',
                'Required package manager or authorization helper is missing.'))
            return
        if not (k == 'Snap' and unsigned_snap) and not self.confirm(tr('Dit pakket installeren?', 'Install this package?') + '\n' + str(path) +
                            ('\n' + tr('RPM-OSTree: herstart vereist.', 'RPM-OSTree: reboot required.') if k == 'RPM' and manager == 'rpm-ostree' else '')):
            return
        if k == 'AppImage': self.start(action=lambda: self.appimage_install(path), note=path.name)
        else: self.start(args=args, note=path.name)

    def appimage_install(self, source):
        """Stage both files, then publish an AppImage only after a complete copy.

        The source and file size are checked before/after copying; a partial file
        never appears in the application list. Failure rolls back the new AppImage.
        """
        if not source.is_file() or not source.name.lower().endswith('.appimage'):
            raise RuntimeError(tr('Ongeldig AppImage-bestand.', 'Invalid AppImage file.'))
        if any(ch in source.name for ch in ('\n', '\r')):
            raise RuntimeError(tr('Ongeldige bestandsnaam.', 'Invalid filename.'))
        APP_DIR.mkdir(parents=True, exist_ok=True)
        DESKTOP_DIR.mkdir(parents=True, exist_ok=True)
        dest = APP_DIR / source.name
        if source.resolve() == dest.resolve() or os.path.lexists(dest):
            raise RuntimeError(tr('AppImage bestaat al; verwijder eerst de vorige versie.',
                                  'AppImage already exists; remove the old version first.'))
        before = source.stat()
        if before.st_size <= 0:
            raise RuntimeError(tr('AppImage-bestand is leeg.', 'AppImage file is empty.'))
        staged_app = staged_launcher = None
        published = False
        try:
            fd, tmp = tempfile.mkstemp(prefix='.appimage-', suffix='.partial', dir=APP_DIR)
            staged_app = Path(tmp)
            copied = 0
            with os.fdopen(fd, 'wb') as output, source.open('rb') as input_file:
                while True:
                    chunk = input_file.read(1024 * 1024)
                    if not chunk: break
                    output.write(chunk)
                    copied += len(chunk)
                output.flush()
                os.fsync(output.fileno())
            after = source.stat()
            if (copied != before.st_size or after.st_size != before.st_size or
                    after.st_mtime_ns != before.st_mtime_ns):
                raise RuntimeError(tr('AppImage is gewijzigd tijdens het kopiëren.',
                                      'AppImage changed during copying.'))
            staged_app.chmod(stat.S_IMODE(before.st_mode) | stat.S_IXUSR)
            icon = next((str(dest.with_suffix(ext)) for ext in ('.png', '.svg')
                         if dest.with_suffix(ext).is_file()), 'application-x-executable')
            name = dest.stem.replace('\n', ' ').replace('\r', ' ')
            launcher = ('[Desktop Entry]\nType=Application\nName=' + name +
                        '\nExec="' + safe_quoted_path(dest) + '"\nIcon=' + icon +
                        '\nTerminal=false\nCategories=Utility;\n')
            fd, tmp = tempfile.mkstemp(prefix='.launcher-', suffix='.partial', dir=DESKTOP_DIR)
            staged_launcher = Path(tmp)
            with os.fdopen(fd, 'w', encoding='utf-8') as desktop_file:
                desktop_file.write(launcher)
                desktop_file.flush()
                os.fsync(desktop_file.fileno())
            # Atomic creation without overwriting any existing destination.
            os.link(staged_app, dest)
            published = True
            os.replace(staged_launcher, desktop_path(dest.name))
            staged_launcher = None
        except Exception:
            if published:
                dest.unlink(missing_ok=True)
            raise
        finally:
            if staged_app is not None:
                staged_app.unlink(missing_ok=True)
            if staged_launcher is not None:
                staged_launcher.unlink(missing_ok=True)

    def remove_selected(self):
        if not self.can_remove:
            QMessageBox.warning(self, tr('Niet beschikbaar', 'Unavailable'), self.environment_note)
            return
        items = self.table.selectedItems()
        if not items or self.busy:
            QMessageBox.information(self, 'Info', tr('Selecteer een pakket.', 'Select a package.'))
            return
        row = items[0].row()
        name = self.table.item(row, 2).text()
        installation_item = self.table.item(row, 3)
        flatpak_installation = (installation_item.data(Qt.ItemDataRole.UserRole)
                                if installation_item is not None else '') or ''
        k = self.kind
        if not suitable_manager(k):
            QMessageBox.warning(self, 'Info', tr('Dit is niet de pakketbeheerder van deze distributie.',
                'This is not the package manager for this distribution.'))
            return
        if k in ('RPM', 'DEB', 'Arch') and package_is_protected(name):
            QMessageBox.warning(self, tr('Verwijdering geblokkeerd', 'Removal blocked'),
                tr('Dit pakket is belangrijk voor het besturingssysteem. Verwijderen is geblokkeerd.',
                   'This package is critical to the operating system. Removal is blocked.'))
            return
        if k == 'RPM' and native_manager('RPM') == 'rpm-ostree' and self.table.item(row, 4).text() == 'Reboot required':
            QMessageBox.information(self, 'RPM', tr('Er staat al een wijziging klaar. Herstart eerst.', 'A change is already pending. Reboot first.'))
            return
        if k == 'RPM' and native_manager('RPM') == 'rpm-ostree':
            layers, err = rpm_layers()
            if layers is None or name not in layers:
                QMessageBox.warning(self, 'RPM', tr('Dit is geen bevestigde, zelf toegevoegde RPM-laag. Verwijderen geblokkeerd. ',
                    'Not a confirmed explicitly layered RPM package. Removal blocked. ') + err)
                return
            args = ['rpm-ostree', 'uninstall', name]
        elif k == 'RPM':
            manager = native_manager('RPM')
            if not available('pkexec'):
                QMessageBox.warning(self, 'RPM', tr('Systeemautorisatie ontbreekt.',
                    'System authorization helper is unavailable.'))
                return
            ok, reason = removal_preflight('RPM', name)
            if not ok:
                QMessageBox.warning(self, tr('Verwijdering geblokkeerd', 'Removal blocked'), reason)
                return
            preview_ok, preview = rpm_transaction_preview(manager, name)
            if not preview_ok:
                QMessageBox.warning(self, tr('Transactiecontrole mislukt', 'Transaction check failed'),
                    tr('Het verwijderplan kon niet worden gecontroleerd. Geen wijzigingen uitgevoerd.',
                       'The removal plan could not be verified. No changes were made.') +
                    '\n\n' + preview[-1200:])
                return
            args = rpm_regular_remove_args(manager, name)
            # Show exactly what the native solver proposed; user must approve.
            details = QMessageBox(self)
            details.setIcon(QMessageBox.Icon.Warning)
            details.setWindowTitle(tr('RPM verwijderen', 'Remove RPM'))
            details.setText(tr('Controleer de geplande verwijdering van: ',
                               'Review the planned removal of: ') + name)
            details.setInformativeText(tr('Automatisch opruimen van afhankelijkheden staat uit. '
                                         'Dit is het voorgestelde verwijderplan:',
                                         'Automatic dependency cleanup is disabled. '
                                         'This is the proposed removal plan:') +
                                       '\n\n' + preview[-1000:])
            details.setDetailedText(preview[-12000:])
            details.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            details.setDefaultButton(QMessageBox.StandardButton.No)
            if details.exec() != QMessageBox.StandardButton.Yes:
                return
        elif k == 'Flatpak':
            flag = flatpak_removal_installation_arg(flatpak_installation)
            if not flag:
                QMessageBox.warning(self, 'Flatpak', tr(
                    'De installatielocatie kon niet betrouwbaar worden bepaald. Verwijderen geblokkeerd.',
                    'The installation location could not be verified. Removal blocked.'))
                return
            # Keep personal data by default. Data deletion is a separate explicit choice.
            ok, output, err = command(['flatpak', 'list', '--app', '--columns=application,installation'], 30)
            if not ok:
                QMessageBox.warning(self, 'Flatpak', tr('Kan Flatpak-installaties niet verifiëren.',
                    'Cannot verify Flatpak installations.') + '\n' + err)
                return
            matching = [(bits[0], bits[1]) for line in output.splitlines()
                        if len(bits := line.split('\t')) >= 2 and bits[0].strip() == name]
            same_install = [p for p in matching if p[1].strip().casefold() == str(flatpak_installation).strip().casefold()]
            # If there are multiple branches with the same ID, --delete-data also erases shared data.
            can_delete_data = len(matching) == 1 and len(same_install) == 1
            choice = QMessageBox(self)
            choice.setIcon(QMessageBox.Icon.Question)
            choice.setWindowTitle(tr('Flatpak verwijderen', 'Remove Flatpak'))
            choice.setText(tr('Wat wil je verwijderen?', 'What would you like to remove?') + '\n' + name)
            keep_button = choice.addButton(tr('App verwijderen; data bewaren', 'Remove app; keep data'),
                                          QMessageBox.ButtonRole.AcceptRole)
            data_button = None
            if can_delete_data:
                data_button = choice.addButton(tr('App en gebruikersdata verwijderen', 'Remove app and user data'),
                                               QMessageBox.ButtonRole.DestructiveRole)
            else:
                choice.setInformativeText(tr('Gebruikersdata worden bewaard, omdat dit pakket '
                                             'mogelijk ook elders is geïnstalleerd.',
                                             'User data will be kept because this app may have another installation.'))
            choice.addButton(QMessageBox.StandardButton.Cancel)
            choice.setDefaultButton(keep_button)
            choice.exec()
            if choice.clickedButton() not in (keep_button, data_button): return
            delete_data = data_button is not None and choice.clickedButton() == data_button
            args = ['flatpak', 'uninstall', flag, '--noninteractive', '-y', name]
            if delete_data: args.insert(3, '--delete-data')
        elif k == 'DEB':
            args = ['pkexec', 'apt-get', 'remove', '-y', name] if available('apt-get') and available('pkexec') else None
        elif k == 'Arch':
            args = ['pkexec', 'pacman', '-R', '--noconfirm', name] if available('pacman') and available('pkexec') else None
        elif k == 'Snap':
            args = ['pkexec', 'snap', 'remove', name] if available('snap') and available('pkexec') else None
        else: args = None
        if k == 'AppImage':
            path = APP_DIR / name
            if not path.is_file() or not path.resolve().is_relative_to(APP_DIR.resolve()):
                QMessageBox.warning(self, 'AppImage', tr('Onveilig bestandspad.', 'Unsafe file path.'))
                return
        elif not args:
            QMessageBox.warning(self, 'Info', tr('Pakketbeheerder / authenticatie ontbreekt.', 'Package manager / authorization unavailable.'))
            return
        if k in ('DEB', 'Arch'):
            ok, reason = removal_preflight(k, name)
            if not ok:
                QMessageBox.warning(self, tr('Verwijdering geblokkeerd', 'Removal blocked'), reason)
                return
        msg = tr('Dit pakket verwijderen?', 'Remove this package?') + '\n' + name
        if k == 'Flatpak': msg += '\n' + tr('Geselecteerde datakeuze wordt toegepast.', 'Your data preservation choice will be applied.')
        if k == 'RPM' and native_manager('RPM') == 'rpm-ostree': msg += '\n' + tr('Herstart is nodig om wijzigingen toe te passen. Het pakket kan tot de herstart zichtbaar blijven.', 'A reboot is required. The package may remain listed until reboot.')
        if k in ('DEB', 'Arch'): msg += '\n' + reason + '\n' + tr('Systeempakketten kunnen nog steeds kritiek zijn. Alleen doorgaan als je het pakket herkent.', 'System packages can still be critical. Continue only if you recognize the package.')
        if k not in ('Flatpak', 'RPM') and not self.confirm(msg): return
        if k == 'RPM' and native_manager('RPM') == 'rpm-ostree' and not self.confirm(msg): return
        if k == 'AppImage':
            def remove_appimage():
                if path.is_symlink(): raise RuntimeError(tr('Symbolische link geblokkeerd.', 'Symbolic link blocked.'))
                path.unlink()
                desktop_path(name).unlink(missing_ok=True)
                for previous_launcher in legacy_desktop_paths(name):
                    previous_launcher.unlink(missing_ok=True)
            self.start(action=remove_appimage, note=name, operation='remove')
        else: self.start(args=args, note=name, operation='remove')

class Center(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Universal Linux Install & Uninstall Center')
        self.resize(1020, 780)
        icon_path = Path(__file__).with_name('icon.png')
        if icon_path.is_file(): self.setWindowIcon(QIcon(str(icon_path)))
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        tabs = QTabWidget()
        self.package_tabs = []
        for kind in ('Flatpak', 'AppImage', 'RPM', 'DEB', 'Arch', 'Snap'):
            tab = PackageTab(kind)
            self.package_tabs.append(tab)
            tabs.addTab(tab, kind)
        root.addWidget(tabs)
        footer = QHBoxLayout()
        close = QPushButton(tr('Sluiten', 'Close'))
        close.clicked.connect(self.close)
        footer.addWidget(close)
        footer.addStretch()
        # Both entry points intentionally lead to the project's shared GitHub discussion.
        for nl_label, en_label in (('Feedback geven', 'Send Feedback'),
                                   ('Bug melden', 'Report a Bug')):
            feedback_button = QPushButton(tr(nl_label, en_label))
            feedback_button.setToolTip(FEEDBACK_URL)
            feedback_button.clicked.connect(self.open_feedback)
            footer.addWidget(feedback_button)
        credit = QLabel('v1.1.0 · <a href="https://github.com/LionheartTim">LionheartTim</a>')
        credit.setOpenExternalLinks(True)
        footer.addWidget(credit)
        root.addLayout(footer)
        self.setStyleSheet('''
            QPushButton#destructive { background-color: #d00000; color: white; border: 1px solid #a00000;
                border-radius: 5px; padding: 11px; font-weight: bold; }
            QPushButton#destructive:hover { background-color: #af0000; }
            QPushButton#destructive:disabled { background-color: #666; color: #bbb; }
            QTableWidget { gridline-color: palette(mid); }
            QProgressBar {
                border: 1px solid #204d77;
                border-radius: 5px;
                background-color: #092c55;
                color: white;
                text-align: center;
                min-height: 18px;
                font-weight: bold;
            }

        ''')

    def closeEvent(self, event):
        active = [tab.kind for tab in self.package_tabs if tab.busy or
                  (tab.job is not None and tab.job.isRunning())]
        if active:
            QMessageBox.warning(self, tr('Bewerking loopt nog', 'Operation in progress'),
                tr('Een pakketbewerking is nog bezig in: ',
                   'A package operation is still running in: ') + ', '.join(active) + '\n\n' +
                tr('Het venster blijft open. Wacht op het eindresultaat; '
                   'het afsluiten van de app zou de systeemopdracht niet betrouwbaar stoppen.',
                   'The window will remain open. Wait for the result; '
                   'closing the app would not reliably cancel the system operation.'))
            event.ignore()
            return
        super().closeEvent(event)

    def open_feedback(self):
        if not QDesktopServices.openUrl(QUrl(FEEDBACK_URL)):
            QMessageBox.warning(self, tr('Browser kon niet worden geopend', 'Could not open browser'),
                                tr('Open deze link handmatig:', 'Please open this link manually:')
                                + '\n' + FEEDBACK_URL)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setApplicationName(APP_ID)
    QGuiApplication.setApplicationDisplayName('Universal Linux Install & Uninstall Center')
    QGuiApplication.setDesktopFileName(APP_ID)
    icon_path = Path(__file__).with_name('icon.png')
    if icon_path.is_file():
        QGuiApplication.setWindowIcon(QIcon(str(icon_path)))
    w = Center()
    w.show()
    sys.exit(app.exec())
