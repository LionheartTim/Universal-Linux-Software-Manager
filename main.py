#!/usr/bin/env python3
"""Universal Linux Software Manager: guarded package operations."""
import json
import html
import zipfile
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
from feature_tools import (search_software, scan_updates, upgrade_command, install_command,
                           export_manifest, import_manifest, package_id_ok)
from bulk_updates import plan_update_all, update_all_summary
from flatpak_exact_remove import FlatpakRef, parse_installed, parse_inventory, plan_uninstall, verify_removed
from online_sources import (flathub_search, github_search, github_updates,
                            choose_appimage, install_github_appimage, github_url,
                            parse_github_repository, guess_appimage_version,
                            link_existing_appimage, latest_github_release, semver_tuple,
                            forget_removed_appimage, prune_missing_tracked_appimages)
from installed_inventory import scan_all_installed_updates
from appimage_updates import (prepare_appimage_update, replace_prepared_appimage,
                              discard_prepared)
from appimage_lifecycle import remove_managed_appimage
from online_sources import tracked_installs
from version_history import (github_release_history, flatpak_history,
                             discovery_project_url, discovery_release_url)
from universal_backup import (CATEGORIES, FILES, DCONF, desktop_family, make_backup,
                              inspect_backup, restore_settings)
from plasma_deferred_restore import stage_restore, _root as plasma_restore_root
from portable_managers import installed_extra
from backup_safety import estimated_backup_bytes, preflight_restore, summarize_report, MARGIN
import restore_journal
from info_help import InfoPanel
from local_file_backup import (package_type,validate_source,create_backup as create_file_backup,
                               inspect_backup as inspect_file_backup,
                               extract_package as extract_file_package,
                               extract_settings as extract_file_settings)
import platform

from PyQt6.QtCore import Qt, QLocale, QThread, QTimer, QSize, QUrl, pyqtSignal
from PyQt6.QtGui import QIcon, QGuiApplication, QPainter, QColor, QDesktopServices, QKeySequence, QShortcut
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView,
    QLineEdit, QFileDialog, QMessageBox, QProgressBar, QAbstractItemView, QStyle,
    QCheckBox, QDialog, QInputDialog, QGridLayout, QGroupBox)

APP_ID = 'io.github.LionheartTim.UniversalLinuxSoftwareManager'
FEEDBACK_URL = 'https://github.com/LionheartTim/Universal-Linux-Software-Manager/discussions/1'
LEGACY_APP_IDS = ('org.bazzite.FlatpakAndAppImageCenter',
                  'io.github.LionheartTim.UniversalLinuxCenter')
IN_SANDBOX = Path('/.flatpak-info').exists()
HOME = Path.home()
APP_DIR = HOME / 'Applications'
DESKTOP_DIR = HOME / '.local/share/applications'
NL = QLocale.system().name().startswith('nl')

def tr(nl, en): return nl if NL else en

def prominent_notice(text, phrase, font_point_size):
    """Format only a requested warning/instruction 1pt larger and bold.

    All other text is escaped so status output cannot inject rich-text markup.
    Missing phrases remain unstyled rather than accidentally styling everything.
    """
    point_size = float(font_point_size)
    if point_size <= 0:
        point_size = 10.0  # Fallback for pixel-based fonts
    source = html.escape(text)
    escaped_phrase = html.escape(phrase)
    if escaped_phrase and escaped_phrase in source:
        marked = ('<span style="font-size:{:g}pt; font-weight:700;">{}</span>'
                  .format(point_size + 1.0, escaped_phrase))
        source = source.replace(escaped_phrase, marked, 1)
    return '<html><body>' + source.replace('\n', '<br/>') + '</body></html>'

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
    if kind == 'APK' and families & {'alpine'}:
        return 'apk' if available('apk') else None
    if kind == 'XBPS' and families & {'void'}:
        return 'xbps-query' if available('xbps-query') else None
    if kind == 'Portage' and families & {'gentoo', 'funtoo'}:
        return 'emerge' if available('emerge') else None
    if kind == 'Nix' and families & {'nixos'}:
        return 'nix' if available('nix') else None
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
    # KDE Plasma components can ship .desktop launchers (settings panels,
    # session tools and services). Launcher ownership alone must never make
    # these packages removable as ordinary GUI applications. Keep this guard
    # independent of the RPM listing so it also applies to removal preflight.
    kde_core = {
        'kwin6', 'kscreen6', 'kscreenlocker6', 'powerdevil6',
        'systemsettings6', 'kded6', 'kglobalacceld6',
        'kactivitymanagerd', 'plasma5support6', 'breeze6', 'oxygen6',
        'xdg-desktop-portal-kde', 'plasma-workspace', 'plasma-desktop',
    }
    kde_core_prefixes = (
        'plasma6-', 'plasma5-', 'libplasma6-', 'libplasma5-',
        'kf6-', 'libkf6', 'kcm_', 'kcm-',
        'patterns-kde-', 'patterns-plasma-',
        'kwin6-', 'kscreen6-', 'kscreenlocker6-',
        'powerdevil6-', 'plasma5support6-',
        'polkit-kde-agent-', 'xdg-desktop-portal-kde-',
    )
    package = name.casefold()
    return (package in risky or package in kde_core or
            package.startswith(('linux-image-', 'kernel-modules-') + kde_core_prefixes))

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



def desktop_arch_packages():
    """Identify user-requested graphical Arch packages, not all pacman entries.

    A pacman package's installation scope is SYSTEM even if the user chose
    to install it. An explicit install reason alone is insufficient to
    identify a desktop app: on a fresh Arch desktop even the base OS can be
    explicitly installed. Require both a package-owned .desktop launcher and
    an explicit install reason. Query the HOST for both sources of evidence.

    Return None when verification is unavailable (fail closed); an empty set
    means there are no verified graphical applications to display.
    """
    ok, paths, _ = command(['find', '/usr/share/applications', '-maxdepth', '1',
                            '-type', 'f', '-name', '*.desktop'], 25)
    if not ok:
        return None
    files = [p.strip() for p in paths.splitlines() if p.strip()]

    owners = set()
    for start in range(0, len(files), 80):
        batch = files[start:start + 80]
        # An unowned launcher makes pacman return a nonzero status even when
        # other launchers have valid owners. Accept only package IDs printed
        # on stdout; error messages never grant visibility.
        ok, out, err = command(['pacman', '-Qqo', *batch], 30)
        if not ok and not out.strip() and 'no package owns' not in err.casefold():
            return None
        owners.update(p.strip() for p in out.splitlines()
                      if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9+_.@-]*', p.strip()))

    ok, out, _ = command(['pacman', '-Qqe'], 30)
    if not ok:
        return None
    explicit = {name.strip() for name in out.splitlines()
                if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9+_.@-]*', name.strip())}
    return {name for name in owners & explicit if not package_is_protected(name)}



def desktop_deb_packages():
    """Only explicitly requested, non-core DEB packages with owned GUI launchers.

    APT's manual-install flag is not a guarantee that software was added by a
    human: distribution installers may mark preinstalled apps as manual. This
    deliberately conservative filter also requires a package-owned .desktop
    launcher and excludes Essential / required / important packages.

    Return None when inventory verification fails, never list all dpkg entries.
    """
    ok, paths, _ = command(['find', '/usr/share/applications', '-maxdepth', '1',
                            '-type', 'f', '-name', '*.desktop'], 25)
    if not ok:
        return None
    desktop_files = {path.strip() for path in paths.splitlines() if path.strip()}
    owners = set()
    files = sorted(desktop_files)
    for start in range(0, len(files), 60):
        batch = files[start:start + 60]
        ok, out, err = command(['dpkg-query', '-S', *batch], 35)
        # An unowned desktop file can cause a nonzero status, even if other
        # package owners were correctly printed on stdout.
        if not ok and not out.strip() and 'no path found matching pattern' not in err.casefold():
            return None
        for line in out.splitlines():
            if ': ' not in line:
                continue
            pkg_list, path = line.rsplit(': ', 1)
            if path.strip() not in desktop_files:
                continue
            for name in pkg_list.split(', '):
                name = name.strip()
                if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9+_.:-]*', name):
                    owners.add(name)

    ok, out, _ = command(['apt-mark', 'showmanual'], 35)
    if not ok:
        return None
    manual = {name.strip() for name in out.splitlines() if name.strip()}
    possible = owners & manual
    if not possible:
        return set()

    # Only query the positively matched candidates, never process the entire
    # dpkg inventory or use a prefix match that could expose core packages.
    allowed = set()
    for name in sorted(possible):
        ok, out, _ = command(['dpkg-query', '-W',
                '-f=${binary:Package}\t${Essential}\t${Priority}\t${Status}', name], 20)
        if not ok:
            return None
        parts = out.strip().split('\t')
        if len(parts) != 4 or parts[0] != name or parts[3] != 'install ok installed':
            continue
        if parts[1].casefold() == 'yes' or parts[2].casefold() in ('required', 'important'):
            continue
        if not package_is_protected(name):
            allowed.add(name)
    return allowed


def desktop_snap_packages():
    """Snap GUI applications only, never base/content/system snaps.

    Snapd publishes .desktop launchers as <snap>_<app>.desktop. The launcher
    filename is trusted only as a positive display signal, not as a request
    to install/remove a package. The selected snap is reverified on removal.
    """
    ok, out, _ = command(['find', '/var/lib/snapd/desktop/applications',
                          '-maxdepth', '1', '-type', 'f', '-name', '*.desktop'], 25)
    if not ok:
        return None
    names = set()
    for line in out.splitlines():
        basename = line.strip().rsplit('/', 1)[-1]
        if '_' not in basename or not basename.endswith('.desktop'):
            continue
        name = basename.split('_', 1)[0]
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]*[a-z0-9])?', name):
            continue
        if (name in {'bare', 'snapd', 'gtk-common-themes', 'snapd-desktop-integration'}
                or re.fullmatch(r'core\d*', name)
                or re.fullmatch(r'gnome-\d.*', name)
                or re.fullmatch(r'mesa-\d.*', name)
                or name.startswith(('kde-frameworks-', 'kf5-'))
                or package_is_protected(name)):
            continue
        names.add(name)
    return names


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
        allowed = desktop_deb_packages()
        if allowed is None or name not in allowed:
            return False, tr('Niet bevestigd als zelf geïnstalleerde grafische DEB-app; verwijderen geblokkeerd.',
                             'Not verified as an explicitly installed graphical DEB app; removal blocked.')
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
    if kind == 'Snap':
        allowed = desktop_snap_packages()
        if allowed is None or name not in allowed:
            return False, tr('Geen bevestigde grafische Snap-app; verwijderen geblokkeerd.',
                             'Not verified as a graphical Snap app; removal blocked.')
        ok, out, err = command(['snap', 'list', name], 30)
        installed = [line.split()[0] for line in out.splitlines()[1:] if line.split()] if ok else []
        if name not in installed:
            return False, tr('Snap-installatie kan niet bevestigd worden.',
                             'Snap installation cannot be verified.') + ' ' + (err or '')
        return True, tr('Grafische Snap-app gecontroleerd.', 'Graphical Snap app verified.')
    if kind == 'Arch':
        allowed = desktop_arch_packages()
        if allowed is None or name not in allowed:
            return False, tr('Niet bevestigd als zelf geïnstalleerde grafische Arch-app; verwijderen geblokkeerd.',
                             'Not verified as an explicitly installed graphical Arch app; removal blocked.')
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


def adjustable_columns(table, initial_widths):
    """All headers are drag-resizable. Provide useful initial widths and scroll if needed."""
    header = table.horizontalHeader()
    header.setStretchLastSection(False)
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    header.setMinimumSectionSize(65)
    for column, width in enumerate(initial_widths):
        table.setColumnWidth(column, width)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)


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
        search_row = QHBoxLayout()
        search_row.addWidget(self.search)
        self.refresh_button = QPushButton(tr('Verversen', 'Refresh'))
        self.refresh_button.setToolTip(tr('Laad de actuele geïnstalleerde apps opnieuw, zonder de app te herstarten.',
                                         'Reload installed applications without restarting the manager.'))
        self.refresh_button.clicked.connect(self.reload)
        search_row.addWidget(self.refresh_button)
        layout.addLayout(search_row)
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
        adjustable_columns(self.table, (200, 170, 310, 120, 240))
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
                item.setToolTip(str(value))
                if i == 0:
                    item.setIcon(package_icon(self.kind, name, identity))
                if self.kind == 'Flatpak' and i == 2 and len(record) > 5:
                    # Preserve exact app/ID/arch/branch, not just an ambiguous ID.
                    item.setData(Qt.ItemDataRole.UserRole, record[5])
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
        if self.busy:
            return  # Never interrupt an installer or removal.
        # Managers or permissions may have changed since the app was opened.
        self.can_install, self.can_remove, self.environment_note = environment_capabilities(self.kind)
        self.choose.setEnabled(self.can_install)
        self.setAcceptDrops(self.can_install)
        self.update_remove_button()
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
            # Query constituent fields, not the presentation-dependent ref column.
            # Recreate the full app/ID/ARCH/BRANCH from host-listed values.
            ok, out, err = command(['flatpak', 'list', '--app',
                '--columns=name:full,application:full,version:full,arch:full,branch:full,installation:full'], 60)
            if ok:
                try:
                    for display_name, version, item in parse_inventory(out, gui=True):
                        rows.append((display_name or item.application, version,
                                     item.application, '', item.installation, item.ref))
                except ValueError as exc:
                    warning = str(exc)
                    rows = []
            else: warning = err
        elif k == 'RPM' and native_manager('RPM') == 'rpm-ostree':
            rows, err = rpm_deployment_rows()
            if rows is None:
                warning, rows = err, []
            else:
                # An explicit rpm-ostree layer is not necessarily an app:
                # exclude libraries, daemons, build tools and other utilities.
                # Keep only booted graphical apps with host-owned launchers.
                graphical = desktop_rpm_packages()
                if graphical is None:
                    warning = tr('Grafische RPM-applicaties kunnen niet veilig worden herkend.',
                                 'Cannot safely identify graphical RPM applications.')
                    rows = []
                else:
                    rows = [r for r in rows if r[2] in graphical]
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
                if k == 'DEB':
                    allowed = desktop_deb_packages()
                    if allowed is None:
                        rows = []
                        warning = tr('Kan zelf geïnstalleerde grafische DEB-apps niet controleren.',
                                     'Cannot verify explicitly installed graphical DEB apps.')
                    else:
                        rows = [r for r in rows if r[2] in allowed]
                if k == 'Snap':
                    allowed = desktop_snap_packages()
                    if allowed is None:
                        rows = []
                        warning = tr('Kan grafische Snap-apps niet controleren.',
                                     'Cannot verify graphical Snap apps.')
                    else:
                        rows = [r for r in rows if r[2] in allowed]
                if k == 'Arch':
                    allowed = desktop_arch_packages()
                    if allowed is None:
                        rows = []
                        warning = tr('Kan zelf geïnstalleerde grafische Arch-apps niet controleren.',
                                     'Cannot verify explicitly installed graphical Arch apps.')
                    else:
                        rows = [r for r in rows if r[2] in allowed]
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
            self.status.setText(tr('Alleen zelf toegevoegde grafische RPM-applicaties; systeemhulpmiddelen verborgen.',
                                   'Only explicitly layered graphical RPM apps; system utilities hidden.'))
        elif k == 'RPM':
            self.status.setText(tr('Alleen herkenbare applicaties; systeempakketten verborgen.',
                                   'Recognized applications only; system packages hidden.'))
        elif k == 'Arch':
            self.status.setText(tr('Grafische Arch-apps gevonden: ', 'Graphical Arch apps found: ') + str(len(rows)) +
                                tr(' — systeempakketten verborgen.', ' — system packages hidden.'))
        else: self.status.setText(tr('Pakketten gevonden: ', 'Packages found: ') + str(len(rows)))

    def confirm(self, message):
        return QMessageBox.question(self, tr('Bevestig bewerking', 'Confirm operation'), message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes
    def start(self, args=None, action=None, note='', operation='install', removal_ref=None):
        if self.busy: return
        self.flatpak_removal_ref = removal_ref if operation == 'remove' and self.kind == 'Flatpak' else None
        self.busy = True
        for w in (self.choose, self.remove, self.table, self.search, self.refresh_button): w.setEnabled(False)
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
        # A zero exit status alone is not proof that a particular branch vanished.
        # Read back the host's exact Flatpak refs before displaying success.
        verification_problem = ''
        if ok and getattr(self, 'flatpak_removal_ref', None) is not None:
            checked, output, error = command(['flatpak', 'list', '--app',
                '--columns=application:full,arch:full,branch:full,installation:full'], 45)
            try:
                if not checked:
                    raise ValueError(str(error or output or 'Flatpak verification unavailable'))
                if not verify_removed(self.flatpak_removal_ref, parse_inventory(output)):
                    raise ValueError('The exact Flatpak branch is still installed')
            except ValueError as exc:
                verification_problem = str(exc)
                ok = False
                detail = tr('Verwijdering kon niet worden bevestigd: ',
                            'Removal could not be confirmed: ') + verification_problem
        self.flatpak_removal_ref = None
        self.progress_timer.stop()
        self.started_at = None
        self.busy = False
        for w in (self.table, self.search, self.refresh_button):
            w.setEnabled(True)
        self.choose.setEnabled(self.can_install)
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
            message = (tr(f'{label} — verwijdering niet bevestigd.',
                          f'{label} — removal not confirmed.') if verification_problem
                       else tr(f'{label} — {action_nl} mislukt.', f'{label} — {action_en} failed.'))

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

    def install_file(self, path, approved=False):
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
        if not approved and not (k == 'Snap' and unsigned_snap) and not self.confirm(tr('Dit pakket installeren?', 'Install this package?') + '\n' + str(path) +
                            ('\n' + tr('RPM-OSTree: herstart vereist.', 'RPM-OSTree: reboot required.') if k == 'RPM' and manager == 'rpm-ostree' else '')):
            return
        if k == 'AppImage': self.start(action=lambda: self.appimage_install(path), note=path.name)
        else: self.start(args=args, note=path.name)
        return True  # job has started; success is reported by job.done, not this return.

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

    def managed_appimage_launchers(self, filename):
        """Only exact launchers created by this manager (including old IDs)."""
        return [desktop_path(filename), *legacy_desktop_paths(filename)]

    def remove_appimage_managed(self, filename, recovery_dir=None):
        """Shared file backend for AppImage Uninstall and Updates; no GUI work."""
        result = remove_managed_appimage(
            APP_DIR, filename, self.managed_appimage_launchers(filename),
            recovery_dir=recovery_dir,
            allow_local_alias=recovery_dir is None)
        if recovery_dir is None:
            # Standalone uninstall is committed: also retire its GitHub record.
            # Transactional updates still own the registry commit/rollback.
            forget_removed_appimage(APP_DIR, filename)
        return result

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
        flatpak_ref = ((self.table.item(row, 2).data(Qt.ItemDataRole.UserRole) or '')
                       if self.kind == 'Flatpak' else '')
        k = self.kind
        if not suitable_manager(k):
            QMessageBox.warning(self, 'Info', tr('Dit is niet de pakketbeheerder van deze distributie.',
                'This is not the package manager for this distribution.'))
            return
        if k in ('RPM', 'DEB', 'Arch', 'Snap') and package_is_protected(name):
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
            # Verify fresh, exact host identity before asking for removal.
            ok, output, err = command(['flatpak', 'list', '--app',
                '--columns=application:full,arch:full,branch:full,installation:full'], 45)
            try:
                if not ok:
                    raise ValueError(err or output or 'Flatpak list failed')
                installed_refs = parse_inventory(output)
                selected_ref = FlatpakRef(name, str(flatpak_installation), str(flatpak_ref))
                args = plan_uninstall(selected_ref, installed_refs)
            except ValueError as exc:
                QMessageBox.warning(self, 'Flatpak', tr(
                    'Geselecteerde Flatpak-versie kan niet veilig worden bevestigd. Lijst opnieuw laden.',
                    'Cannot verify selected Flatpak branch safely. Reload the list.')
                    + '\n' + str(exc))
                self.reload()
                return
            # Keep personal data by default; sharing one ID makes it unsafe to
            # delete its data while any other branch or installation exists.
            can_delete_data = len([x for x in installed_refs if x.application == name]) == 1
            choice = QMessageBox(self)
            choice.setIcon(QMessageBox.Icon.Question)
            choice.setWindowTitle(tr('Flatpak verwijderen', 'Remove Flatpak'))
            choice.setText(tr('Wat wil je verwijderen?', 'What would you like to remove?') + '\n'
                           + selected_ref.ref + ' (' + selected_ref.installation + ')')
            keep_button = choice.addButton(tr('App verwijderen; data bewaren', 'Remove app; keep data'),
                                          QMessageBox.ButtonRole.AcceptRole)
            data_button = None
            if can_delete_data:
                data_button = choice.addButton(tr('App en gebruikersdata verwijderen', 'Remove app and user data'),
                                               QMessageBox.ButtonRole.DestructiveRole)
            else:
                choice.setInformativeText(tr(
                    'Er zijn meerdere branches of installaties. Gebruikersdata blijven behouden.',
                    'Multiple branches or installations exist. User data will be preserved.'))
            choice.addButton(QMessageBox.StandardButton.Cancel)
            choice.setDefaultButton(keep_button)
            choice.exec()
            if choice.clickedButton() not in (keep_button, data_button): return
            delete_data = data_button is not None and choice.clickedButton() == data_button
            try:
                args = plan_uninstall(selected_ref, installed_refs, delete_data=delete_data)
            except ValueError as exc:
                QMessageBox.warning(self, 'Flatpak', str(exc))
                return
        elif k == 'DEB':
            args = ['pkexec', 'apt-get', 'remove', '-y', name] if available('apt-get') and available('pkexec') else None
        elif k == 'Arch':
            args = ['pkexec', 'pacman', '-R', '--noconfirm', name] if available('pacman') and available('pkexec') else None
        elif k == 'Snap':
            args = ['pkexec', 'snap', 'remove', name] if available('snap') and available('pkexec') else None
        else: args = None
        if k == 'AppImage':
            # The shared backend checks the exact local file/alias immediately
            # before removal. It does not follow symlinks outside Applications.
            if not (APP_DIR / name).exists():
                QMessageBox.warning(self, 'AppImage', tr('AppImage niet gevonden.', 'AppImage not found.'))
                return
        elif not args:
            QMessageBox.warning(self, 'Info', tr('Pakketbeheerder / authenticatie ontbreekt.', 'Package manager / authorization unavailable.'))
            return
        if k in ('DEB', 'Arch', 'Snap'):
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
            self.start(action=lambda: self.remove_appimage_managed(name),
                       note=name, operation='remove')
        else: self.start(args=args, note=name, operation='remove',
                         removal_ref=selected_ref if k == 'Flatpak' else None)


class QueryWorker(QThread):
    """Keep repository lookups off the UI thread."""
    complete = pyqtSignal(object, str)

    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def run(self):
        try:
            self.complete.emit(self.callback(), '')
        except Exception as exc:
            self.complete.emit(None, str(exc))


class FeaturePanel(QWidget):
    """Common operation feedback for new feature tabs."""
    def __init__(self):
        super().__init__()
        self.busy = False
        self.job = None
        self.worker = None
        self.output_label = QLabel('')
        self.output_label.setWordWrap(True)
        self.progress = ConveyorProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat(tr('Gereed','Ready'))
        self.buttons = []
        self.refresh_callback = None

    def add_feedback(self, layout):
        layout.addWidget(self.output_label)
        layout.addWidget(self.progress)

    def set_busy(self, value):
        self.busy = value
        for btn in self.buttons:
            btn.setEnabled(not value)
        if value:
            self.progress.setRange(0, 0)
            self.output_label.setText(tr('Bezig...', 'Working...'))
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.progress.setFormat(tr('Gereed', 'Ready'))

    def run_query(self, callback, consumer):
        if self.busy: return
        self.set_busy(True)
        self.worker = QueryWorker(callback)
        def finish(result, error):
            self.set_busy(False)
            if error:
                self.output_label.setText(error[-600:])
            else:
                consumer(result)
            # Keep the QThread instance referenced until a subsequent scan.
        self.worker.complete.connect(finish)
        self.worker.start()

    def run_change(self, args, display, on_success, kind=None, action=None):
        if self.busy: return
        self.set_busy(True)
        self.output_label.setText(display)
        before_reboot = reboot_assessment('DEB')[0] == 'reboot' if kind == 'DEB' else False
        self.job = Job(args, action=action)
        self.job.output.connect(lambda txt:self.output_label.setText(str(txt)[-380:]))
        def finish(ok, detail):
            self.set_busy(False)
            if ok:
                self.output_label.setText('')
                state, _ = reboot_assessment(kind or 'AppImage', bool(args and args[0] == 'rpm-ostree'))
                if kind == 'DEB' and before_reboot and state == 'reboot':
                    state = 'unknown'
                msg = tr('Bewerking voltooid.', 'Operation complete.')
                if state in ('pending', 'reboot'):
                    msg += ' ' + tr('Herstart vereist.', 'Reboot required.')
                elif state == 'unknown' and kind in ('RPM', 'DEB', 'Arch'):
                    msg += ' ' + tr('Herstartstatus onbekend.', 'Restart status unknown.')
                QMessageBox.information(self, tr('Voltooid','Completed'), msg)
                if on_success: on_success()
            else:
                QMessageBox.warning(self, tr('Mislukt','Failed'), display + '\n\n' + detail[-1600:])
            # Keep the worker referenced until the next operation.
        self.job.done.connect(finish)
        self.job.start()


class UpdatesPanel(FeaturePanel):
    """Installed software first; update candidates are attached by real package ID."""
    STATUS = {
        'available': ('Update beschikbaar', 'Update available'),
        'no_update': ('Geen update gevonden', 'No update found'),
        'not_checked': ('Controle niet mogelijk', 'Check unavailable'),
        'unknown_source': ('Updatebron onbekend', 'Update source unknown'),
        'system_updater': ('Via systeemupdater', 'Use system updater'),
        'reboot_required': ('Herstart vereist', 'Reboot required'),
    }

    def __init__(self, appimage_tab, package_tabs=None):
        super().__init__()
        self.appimage_tab = appimage_tab
        self.package_tabs = {tab.kind: tab for tab in (package_tabs or [])}
        layout = QVBoxLayout(self)
        label = QLabel(tr(
            'Geïnstalleerde pakketten van gevonden pakketbeheerders, waaronder Flatpak, AppImage, RPM, DEB, Arch, Snap, APK en XBPS. '
            'Updates worden alleen aangeboden bij een bekende bron en veilige updater.',
            'Installed packages from detected, supported managers, including Flatpak, AppImage, RPM, DEB, Arch, Snap, APK and XBPS. '
            'Updates are offered only when their installation source and safe upgrade route are known.'))
        label.setWordWrap(True)
        layout.addWidget(label)
        controls = QHBoxLayout()
        self.check = QPushButton(tr('Controleer updates', 'Check for updates'))
        self.check.clicked.connect(self.refresh)
        controls.addWidget(self.check)
        self.refresh_button = QPushButton(tr('Verversen', 'Refresh'))
        self.refresh_button.clicked.connect(self.refresh)
        controls.addWidget(self.refresh_button)
        self.apply = QPushButton(tr('Alles bijwerken', 'Update all'))
        self.apply.setToolTip(tr('Werk alle veilig uitvoerbare updates bij; de zoekfilter bepaalt alleen wat zichtbaar is.',
                                 'Update every safely supported available package; search only filters the view.'))
        self.apply.clicked.connect(self.update_all)
        self.apply.setEnabled(False)
        controls.addWidget(self.apply)
        self.link_source = QPushButton(tr('GitHub-bron koppelen', 'Link GitHub source'))
        self.link_source.setToolTip(tr('Koppel een bestaande AppImage handmatig aan de officiële GitHub-repository.',
                                       'Manually link an installed AppImage to its official GitHub repository.'))
        self.link_source.clicked.connect(self.link_selected_source)
        self.link_source.setEnabled(False)
        controls.addWidget(self.link_source)
        layout.addLayout(controls)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr('Filter geïnstalleerde software...', 'Filter installed software...'))
        self.search.textChanged.connect(self.filter_rows)
        filters.addWidget(self.search)
        self.updates_only = QCheckBox(tr('Alleen beschikbare updates', 'Updates available only'))
        self.updates_only.toggled.connect(self.filter_rows)
        filters.addWidget(self.updates_only)
        layout.addLayout(filters)
        self.buttons = [self.check, self.refresh_button, self.apply, self.link_source]
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            tr('Type', 'Type'), tr('Applicatie', 'Application'),
            tr('Geïnstalleerd', 'Installed'), tr('Beschikbaar', 'Available'),
            tr('Installatie', 'Installation'), tr('Status', 'Status'),
            tr('Pakket-ID', 'Package ID')])
        adjustable_columns(self.table, (96, 215, 135, 135, 122, 235, 310))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.itemSelectionChanged.connect(self.update_apply_button)
        layout.addWidget(self.table)
        self.add_feedback(layout)
        self.notes = QLabel('')
        self.notes.setWordWrap(True)
        layout.addWidget(self.notes)
        self.entries = []
        self.needs_refresh = True
        self._bulk_active = False
        self._bulk_queue = []
        self._bulk_total = 0
        self._bulk_results = []
        self._bulk_preflight_skips = []
        self._bulk_qthreads = []
        self._bulk_changed = set()

    def invalidate(self):
        self.needs_refresh = True

    def refresh(self):
        if self.busy: return
        self.needs_refresh = False
        self.run_query(lambda: scan_all_installed_updates(
            command, native_manager, APP_DIR, tracking=prune_missing_tracked_appimages(APP_DIR),
            github_lookup=lambda checked: github_updates(APP_DIR, checked=checked)),
            self.show_results)

    def _update_row_values(self, entry):
        """Display values also used for case-insensitive local filtering."""
        scope = entry.get('scope', '')
        if scope == 'user': scope = 'USER'
        elif scope == 'system': scope = 'SYSTEM'
        return (entry['kind'], entry['name'], entry.get('installed_version', ''),
                entry.get('available_version', ''), scope,
                tr(*self.STATUS[entry['status']]), entry['id'])

    def show_results(self, result):
        rows, notes = result
        self.entries = rows
        self._render_filtered_rows()
        available_count = sum(r['status'] == 'available' for r in rows)
        self.output_label.setText(tr(
            f'{len(rows)} geïnstalleerde pakketten · {available_count} updates beschikbaar.',
            f'{len(rows)} installed packages · {available_count} updates available.'))
        self.notes.setText('\n'.join(notes[:8]))

    def filter_rows(self, *_):
        """Filter the saved installed inventory, never discard it on empty search."""
        self._render_filtered_rows()

    def _render_filtered_rows(self):
        # Rebuild only the *visible table* from self.entries. Hiding QTableWidget
        # rows left stale/empty-looking results on some Qt versions after clearing
        # the search field. The entire installed inventory remains in self.entries.
        text = self.search.text().strip().casefold()
        only = self.updates_only.isChecked()
        self.table.setSortingEnabled(False)
        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(0)
            for entry in self.entries:
                if only and entry['status'] != 'available':
                    continue
                values = self._update_row_values(entry)
                if text and not any(text in str(value).casefold() for value in values):
                    continue
                row = self.table.rowCount()
                self.table.insertRow(row)
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    item.setToolTip(str(value))
                    if column == 1:
                        item.setIcon(package_icon(entry['kind'], entry['name'], entry['id']))
                    if column == 0:
                        item.setData(Qt.ItemDataRole.UserRole, entry)
                    self.table.setItem(row, column, item)
        finally:
            self.table.setSortingEnabled(True)
            self.table.setUpdatesEnabled(True)
        self.update_apply_button()

    def update_apply_button(self):
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        entry = item.data(Qt.ItemDataRole.UserRole) if item else None
        selectable = not self.busy and bool(entry) and not self.table.isRowHidden(row)
        self.apply.setEnabled(not self.busy and any(e.get('status') == 'available'
                                                        for e in self.entries))
        self.link_source.setEnabled(selectable and entry['kind'] == 'AppImage'
                                    and not entry.get('github_repo'))

    def link_selected_source(self):
        """Ask for an explicit mapping; a filename alone never proves GitHub origin."""
        row = self.table.currentRow()
        cell = self.table.item(row, 0) if row >= 0 else None
        entry = cell.data(Qt.ItemDataRole.UserRole) if cell else None
        if (self.busy or not entry or entry['kind'] != 'AppImage'
                or entry.get('github_repo') or self.table.isRowHidden(row)):
            return
        name = entry['id']
        raw, ok = QInputDialog.getText(self, tr('GitHub-bron koppelen', 'Link GitHub source'),
            tr('Officiële GitHub-repository (OWNER/REPO of volledige HTTPS-link):',
               'Official GitHub repository (OWNER/REPO or complete HTTPS link):'))
        if not ok: return
        try:
            repo = parse_github_repository(raw)
        except ValueError as exc:
            QMessageBox.warning(self, 'GitHub', str(exc))
            return
        guessed = guess_appimage_version(name)
        tag, ok = QInputDialog.getText(self, tr('Geïnstalleerde versie', 'Installed version'),
            tr('Controleer de VERSIE van de geïnstalleerde AppImage. Dit wordt niet automatisch bewezen:',
               'Confirm the VERSION of the installed AppImage. Its authenticity cannot be inferred:'),
            text=guessed)
        if not ok: return
        tag = tag.strip()
        if not re.fullmatch(r'v?\d+(?:\.\d+){1,3}', tag):
            QMessageBox.warning(self, 'GitHub', tr('Vul een numerieke versie in, bijvoorbeeld v1.0.0.',
                'Enter a numeric version, for example v1.0.0.'))
            return
        # A background network query verifies that this repository has a stable
        # release and a matching Linux AppImage BEFORE accepting the association.
        def finish(release):
            asset = choose_appimage(release)
            if asset is None:
                QMessageBox.warning(self, 'GitHub', tr(
                    'Deze GitHub-repository biedt geen eenduidige AppImage voor dit systeem.',
                    'This GitHub repository has no unambiguous AppImage for this system.'))
                return
            old, new = semver_tuple(tag), semver_tuple(release['tag'])
            if old is None or new is None:
                QMessageBox.warning(self, 'GitHub', tr('De versienummers kunnen niet veilig worden vergeleken.',
                                                      'Release versions cannot be compared safely.'))
                return
            summary = (tr('Alleen als dit echt de officiële bron voor dit bestand is, kies Ja. '
                          'De koppeling wijzigt je huidige AppImage niet.',
                          'Select Yes only if this is truly the official source for this file. '
                          'The existing AppImage is not modified.') +
                       f'\n\n{name}\n{repo}\n{tag} → {release["tag"]}\n{asset["name"]}')
            if QMessageBox.question(self, tr('GitHub-bron bevestigen', 'Confirm GitHub source'), summary,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
            try:
                link_existing_appimage(APP_DIR, name, repo, tag)
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, 'GitHub', str(exc))
                return
            self.refresh()
        self.run_query(lambda: latest_github_release(repo), finish)

    def update_selected(self):
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        entry = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not entry or entry.get('status') != 'available' or self.table.isRowHidden(row):
            QMessageBox.information(self, 'Info', tr('Selecteer eerst een beschikbare update.',
                                                    'Select an available update first.'))
            return
        if entry['kind'] == 'AppImage':
            release = entry.get('release')
            if not release or not choose_appimage(release):
                QMessageBox.warning(self, 'GitHub', tr('Geen geschikte AppImage-download gevonden.',
                    'No compatible direct AppImage asset found.'))
                return
            # DOWNLOAD FIRST, then ask in the GUI thread if the old file should
            # be replaced. Never show Qt dialogs from a worker thread.
            def ask_to_replace(prepared):
                message = tr(
                    'De nieuwe AppImage is volledig gedownload en gecontroleerd.\n\n'
                    'Wil je de oude AppImage vervangen?\n\n'
                    'De oude versie en haar startmenuvermelding worden pas opgeruimd nadat de nieuwe versie is geïnstalleerd.\n\n'
                    'Nee = annuleren; er wordt niets gewijzigd.',
                    'The new AppImage has been downloaded and verified.\n\n'
                    'Replace the old AppImage?\n\n'
                    'The old executable and its managed launcher are removed only after the new version is installed.\n\n'
                    'No = cancel; nothing is changed.')
                message += (f'\n\n{prepared.repo}\n'
                            f'{prepared.old_name}  ({prepared.old_tag})\n'
                            f'→ {prepared.new_name}  ({prepared.new_tag})')
                yes = QMessageBox.question(self, tr('AppImage vervangen?', 'Replace old AppImage?'),
                    message, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes
                if not yes:
                    discard_prepared(prepared)
                    return
                self.run_change(None, entry['id'], lambda: self.after_change('AppImage'), 'AppImage',
                    action=lambda: replace_prepared_appimage(
                        prepared, self.appimage_tab,
                        launcher_path=desktop_path(prepared.new_name)))
            self.run_query(lambda: prepare_appimage_update(release, APP_DIR), ask_to_replace)
            return
        if package_is_protected(entry['id']):
            QMessageBox.warning(self, 'Info', tr('Kernsysteempakket: gebruik de systeemupdate.',
                                               'Core system package: use your system updater.'))
            return
        args = upgrade_command(entry, native_manager)
        if not args or (args[0] == 'pkexec' and not available('pkexec')):
            QMessageBox.warning(self, 'Info', tr('Deze updater is niet beschikbaar op dit systeem.',
                                               'This updater is unavailable on this system.'))
            return
        if not self.confirm_update(entry): return
        self.run_change(args, entry['id'], lambda: self.after_change(entry['kind']), entry['kind'])

    def update_all(self):
        """Execute eligible installed-source updates sequentially, never a full OS upgrade.

        Rows are read from the complete inventory rather than the current table
        selection, so 'Updates available only' and search are strictly view filters.
        """
        if self.busy or self._bulk_active:
            return
        busy_tabs = [tab.kind for tab in self.package_tabs.values()
                     if tab.busy or (tab.job is not None and tab.job.isRunning())]
        if busy_tabs:
            QMessageBox.information(self, tr('Wacht op lopende bewerking', 'Operation in progress'),
                tr('Rond eerst de andere pakketbewerking af: ',
                   'Finish the other package operation first: ') + ', '.join(busy_tabs))
            return
        ready, skipped = plan_update_all(self.entries, upgrade_command, native_manager,
                                         choose_appimage, package_is_protected, available)
        if not ready:
            QMessageBox.information(self, tr('Geen geschikte updates', 'No eligible updates'),
                tr('Er zijn geen beschikbare updates die deze app veilig kan uitvoeren.',
                   'There are no available updates that this app can safely perform.'))
            return
        examples = '\n'.join(f'• {entry["name"]} ({entry["kind"]})'
                             for entry, _ in ready[:15])
        if len(ready) > 15:
            examples += f'\n… +{len(ready) - 15}'
        warning = tr(
            f'{len(ready)} updates worden één voor één uitgevoerd.\n'
            f'{len(skipped)} niet-ondersteunde of onveilige updates worden overgeslagen.\n\n'
            'De installatiebron wordt niet gewijzigd. De pakketbeheerder kan ook noodzakelijke '
            'afhankelijkheden bijwerken. Een AppImage vraagt afzonderlijk toestemming voor vervanging.\n\n'
            'Doorgaan?\n\n',
            f'{len(ready)} updates will run one at a time.\n'
            f'{len(skipped)} unsafe or unsupported updates will be skipped.\n\n'
            'Installation sources will not change. A package manager may also update required '
            'dependencies. Each AppImage replacement requires separate approval.\n\n'
            'Continue?\n\n')
        if QMessageBox.question(self, tr('Alle updates uitvoeren?', 'Update all?'),
            warning + examples,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self._bulk_queue = list(ready)
        self._bulk_total = len(ready)
        self._bulk_results = []
        self._bulk_preflight_skips = skipped
        self._bulk_changed = set()
        self._bulk_active = True
        self.set_busy(True)
        self._bulk_next()

    def _bulk_next(self):
        if not self._bulk_active:
            return
        if not self._bulk_queue:
            self._bulk_finish()
            return
        entry, args = self._bulk_queue.pop(0)
        number = len(self._bulk_results) + 1
        prefix = f'{number}/{self._bulk_total}  {entry["kind"]}: {entry["name"]}'
        self.output_label.setText(tr('Bijwerken: ', 'Updating: ') + prefix)
        if entry['kind'] != 'AppImage':
            self._bulk_run_job(entry, args=args, prefix=prefix)
            return
        release = entry.get('release')
        worker = QueryWorker(lambda: prepare_appimage_update(release, APP_DIR))
        self.worker = worker
        self._bulk_qthreads.append(worker)
        def prepared_done(prepared, error):
            if error or prepared is None:
                self._bulk_record(entry, 'failed', error or 'AppImage download failed')
                return
            message = tr(
                'De AppImage is gedownload en gecontroleerd. Wil je de oude versie vervangen?\n'
                'Nee slaat alleen deze AppImage over; de andere updates gaan door.\n\n',
                'The AppImage was downloaded and verified. Replace the old version?\n'
                'No skips only this AppImage; the other updates continue.\n\n')
            message += (f'{prepared.repo}\n{prepared.old_name} ({prepared.old_tag})'
                        f'\n→ {prepared.new_name} ({prepared.new_tag})')
            if QMessageBox.question(self, tr('AppImage vervangen?', 'Replace old AppImage?'),
                message, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                discard_prepared(prepared)
                self._bulk_record(entry, 'skipped', 'AppImage replacement declined')
                return
            self._bulk_run_job(entry, action=lambda: replace_prepared_appimage(
                prepared, self.appimage_tab, launcher_path=desktop_path(prepared.new_name)),
                prefix=prefix)
        worker.complete.connect(prepared_done)
        worker.start()

    def _bulk_run_job(self, entry, args=None, action=None, prefix=''):
        """One asynchronous package operation; keep QThread objects alive."""
        job = Job(args, action=action)
        self.job = job
        self._bulk_qthreads.append(job)
        job.output.connect(lambda output: self.output_label.setText(prefix + '\n' + str(output)[-450:]))
        job.done.connect(lambda ok, detail: self._bulk_record(
            entry, 'updated' if ok else 'failed', str(detail)))
        job.start()

    def _bulk_record(self, entry, outcome, detail):
        if not self._bulk_active:
            return
        self._bulk_results.append((entry, outcome, detail))
        if outcome == 'updated':
            self._bulk_changed.add(entry['kind'])
        if outcome == 'failed':
            # Stop rather than keep writing while a manager may be inconsistent.
            self._bulk_finish(stopped=True)
        else:
            QTimer.singleShot(0, self._bulk_next)

    def _bulk_finish(self, stopped=False):
        self._bulk_active = False
        remaining = len(self._bulk_queue)
        self._bulk_queue = []
        stats = update_all_summary(self._bulk_results, self._bulk_preflight_skips)
        summary = tr(
            f'Bijgewerkt: {stats["updated"]}\nOvergeslagen: {stats["skipped"]}\n'
            f'Mislukt: {stats["failed"]}',
            f'Updated: {stats["updated"]}\nSkipped: {stats["skipped"]}\n'
            f'Failed: {stats["failed"]}')
        if stopped:
            summary += '\n' + tr(
                f'Nog niet uitgevoerd: {remaining}. De wachtrij is gestopt na een fout.',
                f'Not attempted: {remaining}. The queue stopped after a failure.')
        details = []
        for entry, outcome, detail in self._bulk_results:
            details.append(f'{entry["kind"]}: {entry["name"]} — {outcome}' +
                           ((': ' + detail[-200:]) if outcome == 'failed' else ''))
        for entry, reason in self._bulk_preflight_skips:
            details.append(f'{entry["kind"]}: {entry["name"]} — skipped: {reason}')
        for kind in self._bulk_changed:
            tab = self.package_tabs.get(kind)
            if tab:
                tab.reload()
        self.set_busy(False)
        self.update_apply_button()
        message = QMessageBox(self)
        message.setWindowTitle(tr('Updateoverzicht', 'Update summary'))
        message.setIcon(QMessageBox.Icon.Warning if stopped or stats['failed'] else
                        QMessageBox.Icon.Information)
        message.setText(summary)
        message.setDetailedText('\n'.join(details))
        message.setStandardButtons(QMessageBox.StandardButton.Ok)
        message.exec()
        self.refresh()

    def after_change(self, kind):
        tab = self.package_tabs.get(kind)
        if tab: tab.reload()
        self.refresh()

    def confirm_update(self, entry):
        # AppImages MUST use the separate download -> verify -> confirm flow.
        # This generic confirmation belongs only to native package managers.
        if entry['kind'] == 'AppImage':
            return False
        msg = tr('Dit geïnstalleerde pakket bijwerken? De pakketbeheerder kan noodzakelijke '
                 'afhankelijkheden bijwerken.',
                 'Update this installed package? The package manager may update required dependencies.')
        return QMessageBox.question(self, tr('Update bevestigen', 'Confirm update'),
            entry['kind'] + ' — ' + entry['id'] + '\n\n' + msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes


class VersionHistoryDialog(QDialog):
    """Read-only version information; never downloads, installs or rolls back."""
    def __init__(self, entry, versions, parent=None, complete=True):
        super().__init__(parent)
        self.entry = entry
        self.versions = versions
        self.setWindowTitle(tr('Beschikbare versies: ', 'Available versions: ') + entry['name'])
        self.resize(830, 500)
        layout = QVBoxLayout(self)
        if entry['kind'] == 'GitHub':
            explanation = tr(
                'Eerdere stabiele GitHub-releases (maximaal 150). Kies een versie om de originele releasepagina te openen. '
                'Discover downloadt of installeert niets.',
                'Previous stable GitHub releases (up to 150). Select a version to open its original release page. '
                'Discover does not download or install anything.')
        else:
            explanation = tr(
                'Eerdere Flatpak-builds (commits); dit zijn niet altijd programmaversies. '
                'Je kunt de geselecteerde commit-ID kopiëren. Discover wijzigt geen installaties.',
                'Earlier Flatpak builds (commits), which are not always application version numbers. '
                'You can copy the selected commit ID. Discover never modifies installed software.')
        self.explanation = QLabel(explanation)
        self.explanation.setWordWrap(True)
        layout.addWidget(self.explanation)
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels([tr('Versie / build','Version / build'), tr('Datum','Date'),
                                              tr('Downloads / details','Downloads / details')])
        adjustable_columns(self.table, (270,135,370))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(False)
        for i, version in enumerate(versions):
            self.table.insertRow(i)
            if entry['kind'] == 'GitHub':
                state = tr('AppImage vermeld', 'AppImage listed') if version['installable'] else tr(
                    'Bekijk releasebestanden', 'Inspect release files')
                values = (version['version'], version['date'], state)
            else:
                values = (version['commit'][:16] + '…', version['date'][:20], version['subject'])
            for j, val in enumerate(values):
                item = QTableWidgetItem(str(val))
                if j == 0:
                    item.setToolTip(version.get('commit', version.get('version', '')))
                self.table.setItem(i, j, item)
        layout.addWidget(self.table)
        buttons = QHBoxLayout()
        self.open_button = QPushButton(
            tr('Open release op GitHub', 'Open release on GitHub') if entry['kind'] == 'GitHub'
            else tr('Kopieer build-ID', 'Copy build ID'))
        self.open_button.clicked.connect(self.open_selected)
        buttons.addWidget(self.open_button)
        close = QPushButton(tr('Sluiten', 'Close'))
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.table.itemSelectionChanged.connect(
            lambda: self.open_button.setEnabled(self.table.currentRow() >= 0))
        self.table.cellDoubleClicked.connect(lambda row, col: self.open_selected())
        if versions: self.table.selectRow(0)
        self.open_button.setEnabled(bool(versions))

    def open_selected(self):
        row = self.table.currentRow()
        if not 0 <= row < len(self.versions): return
        version = self.versions[row]
        if self.entry['kind'] == 'GitHub':
            url = discovery_release_url(self.entry, version)
            if not url or not QDesktopServices.openUrl(QUrl(url)):
                QMessageBox.warning(self, tr('Link niet beschikbaar', 'Link unavailable'),
                                    tr('De releasepagina kan niet worden geopend.',
                                       'The release page could not be opened.'))
        else:
            # Flatpak exposes commits in the local remote's history, not
            # necessarily public webpages for every old build.
            commit = version.get('commit', '')
            if commit:
                QGuiApplication.clipboard().setText(commit)
                self.explanation.setText(tr('Build-ID gekopieerd. Discover verandert niets aan de installatie.',
                                            'Build ID copied. Discover did not change the installation.'))


class DiscoverPanel(FeaturePanel):
    """Repository catalogue and version browser. All actions are read-only."""
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        intro = QLabel(tr(
            'Zoek in pakketbronnen, Flathub en GitHub. Klik op een NAAM voor de versiegeschiedenis. '
            'Open de projectpagina om zelf te downloaden; installeren gebeurt buiten Discover.',
            'Search package sources, Flathub and GitHub. Click a NAME for version history. '
            'Open the project page to download software yourself; Discover never installs anything.'))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        search_line = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText(tr('Zoek software (bijv. vlc)', 'Search software (e.g. vlc)'))
        self.query.returnPressed.connect(self.search)
        search_line.addWidget(self.query)
        self.search_button = QPushButton(tr('Zoeken', 'Search'))
        self.search_button.clicked.connect(self.search)
        search_line.addWidget(self.search_button)
        self.refresh_button = QPushButton(tr('Verversen', 'Refresh'))
        self.refresh_button.clicked.connect(self.refresh)
        self.refresh_button.setEnabled(False)
        search_line.addWidget(self.refresh_button)
        layout.addLayout(search_line)
        self.open_page = QPushButton(tr('Open projectpagina', 'Open project page'))
        self.open_page.clicked.connect(self.open_selected_page)
        self.open_page.setEnabled(False)
        layout.addWidget(self.open_page)
        self.buttons = [self.search_button, self.refresh_button, self.open_page]
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([tr('Naam','Name'),tr('Bron','Source'),
          tr('Pakket-ID','Package ID'),tr('Versie','Version'),tr('Repository','Repository')])
        adjustable_columns(self.table, (220, 115, 325, 140, 215))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.cellClicked.connect(self.on_result_clicked)
        self.table.itemSelectionChanged.connect(self.update_open_button)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        layout.addWidget(self.table)
        self.add_feedback(layout)
        self.note = QLabel('')
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self._displayed_query = None
        self.query.textChanged.connect(self.on_query_changed)

    def refresh(self):
        # A refresh repeats only the *current* search; it never installs anything.
        if self.busy:
            return
        if len(self.query.text().strip()) < 2:
            self.clear_results()
            return
        self.search()

    def clear_results(self):
        """Forget old Discover matches when the user changes the search."""
        self._displayed_query = None
        self.table.setRowCount(0)
        self.open_page.setEnabled(False)
        self.output_label.setText('')
        self.note.setText(tr('Klik op Search om resultaten voor je zoekwoord te tonen.',
                             'Press Search to show results for your query.'))

    def on_query_changed(self, text):
        if hasattr(self, 'refresh_button'):
            self.refresh_button.setEnabled(not self.busy and len(text.strip()) >= 2)
        # Discover is an online lookup, not a live filter. Previous results
        # must never be presented as matches for a changed or empty query.
        if text.strip() != self._displayed_query:
            self.clear_results()

    def on_search_completed(self, submitted_query, result):
        # Network requests may finish after the search box was cleared/edited.
        # Never show stale results from a superseded online lookup.
        if self.query.text().strip() != submitted_query:
            self.clear_results()
            return
        self._displayed_query = submitted_query
        self.show_results(result)

    def set_busy(self, value):
        super().set_busy(value)
        self.refresh_button.setEnabled(not value and len(self.query.text().strip()) >= 2)
        if not value and hasattr(self, 'open_page'):
            self.update_open_button()

    def selected_entry(self):
        row = self.table.currentRow()
        cell = self.table.item(row, 0) if row >= 0 else None
        return cell.data(Qt.ItemDataRole.UserRole) if cell else None

    def update_open_button(self):
        entry = self.selected_entry()
        self.open_page.setEnabled(bool(not self.busy and entry and discovery_project_url(entry)))

    def open_selected_page(self):
        entry = self.selected_entry()
        url = discovery_project_url(entry) if entry else None
        if not url: return
        if not QDesktopServices.openUrl(QUrl(url)):
            QMessageBox.warning(self, tr('Link niet beschikbaar', 'Link unavailable'),
                                tr('Kan de projectpagina niet openen.', 'Could not open the project page.'))

    def search(self):
        text = self.query.text().strip()
        if len(text) < 2:
            QMessageBox.information(self, 'Info', tr('Typ ten minste twee tekens.', 'Type at least two characters.'))
            return
        self.run_query(lambda: search_software(command, native_manager, text,
                    flathub_lookup=flathub_search, github_lookup=github_search),
                       lambda result: self.on_search_completed(text, result))

    def show_results(self, result):
        entries, warnings = result
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        kinds_by_name = {}
        for e in entries: kinds_by_name.setdefault(e['name'].casefold(), set()).add(e['kind'])
        for e in entries:
            i = self.table.rowCount()
            self.table.insertRow(i)
            for col, key in enumerate(('name', 'kind', 'id', 'version', 'scope')):
                item = QTableWidgetItem(str(e.get(key, '')))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setToolTip(str(e.get(key, '')))
                if col == 0:
                    item.setIcon(package_icon(e['kind'], e['name'], e['id']))
                    matching = kinds_by_name[e['name'].casefold()]
                    if len(matching) > 1:
                        item.setToolTip('Possible matches across: ' + ', '.join(sorted(matching)))
                    item.setData(Qt.ItemDataRole.UserRole, e)
                if col == 2 and e.get('detail'): item.setToolTip(e['detail'])
                self.table.setItem(i, col, item)
        self.table.setSortingEnabled(True)
        self.update_open_button()
        self.output_label.setText(tr(f'{len(entries)} resultaten gevonden.', f'{len(entries)} results found.'))
        self.note.setText(tr(
            'Gelijke namen bewijzen niet dat software identiek is. Controleer de pakket-ID en uitgever. '
            'Discover downloadt, installeert of verwijdert geen software.\n',
            'Similar names do not prove identical software. Check the package ID and publisher. '
            'Discover never downloads, installs or removes software.\n') + '\n'.join(warnings))

    def on_result_clicked(self, row, column):
        if column != 0 or self.busy: return
        cell = self.table.item(row, 0)
        entry = cell.data(Qt.ItemDataRole.UserRole) if cell else None
        if not entry: return
        if entry['kind'] == 'GitHub':
            self.run_query(lambda: github_release_history(entry['id']),
                           lambda history: self.display_history(entry, *history))
        elif entry['kind'] == 'Flatpak':
            remotes = [x.strip() for x in entry.get('scope', '').split(',') if x.strip()]
            if len(remotes) != 1:
                QMessageBox.information(self, 'Flatpak', tr(
                    'Meer dan één Flatpak-repository gevonden; geschiedenis niet eenduidig.',
                    'Multiple Flatpak repositories found; history is ambiguous.'))
                return
            remote = remotes[0]
            self.run_query(lambda: flatpak_history(command, remote, entry['id']),
                           lambda versions: self.display_history(entry, versions, True))
        else:
            QMessageBox.information(self, tr('Versies', 'Versions'), tr(
                'Deze pakketbron biedt momenteel geen betrouwbare versiegeschiedenis in Discover. '
                'Gebruik de bijbehorende pakketbeheerder voor softwareversies.',
                'This source does not currently offer reliable version history in Discover. '
                'Use the corresponding package manager for software versions.'))

    def display_history(self, entry, versions, complete):
        if not versions:
            QMessageBox.information(self, tr('Versies', 'Versions'), tr(
                'Geen eerdere versies gevonden bij deze bron.',
                'No previous versions found at this source.'))
            return
        dialog = VersionHistoryDialog(entry, versions, self, complete=complete)
        dialog.exec()


class PackageDropTable(QTableWidget):
    """Receive local installer files only; never execute a drop directly."""
    filesDropped = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setDropIndicatorShown(False)

    def _paths(self, event):
        if not event.mimeData().hasUrls(): return []
        urls=event.mimeData().urls()
        if not urls or len(urls)>100 or not all(x.isLocalFile() for x in urls): return []
        return [x.toLocalFile() for x in urls]

    def dragEnterEvent(self,event):
        if self._paths(event): event.acceptProposedAction()
        else: event.ignore()

    def dragMoveEvent(self,event):
        if self._paths(event): event.acceptProposedAction()
        else: event.ignore()

    def dropEvent(self,event):
        paths=self._paths(event)
        if paths:
            self.filesDropped.emit(paths)
            event.acceptProposedAction()
        else: event.ignore()


class BackupPanel(FeaturePanel):
    """Local drag-and-drop package-file ZIPs plus independently chosen desktop settings."""
    SETTINGS = (
        ('display','Scherminstellingen','Display settings'),
        ('panels','Taakbalk / panelen','Taskbar / panels'),
        ('power','Energiebeheer','Power settings'),
        ('audio','Audio-instellingen','Audio settings'),
        ('appearance','Uiterlijk / vensters','Appearance / windows'),
        ('keyboard','Toetsenbord / sneltoetsen','Keyboard / shortcuts'),
        ('notifications','Meldingen','Notifications'),
        ('region','Taal / regio','Language / region'),
        ('fileassoc','Standaardapps / bestandstypen','Default apps / file types'),
    )

    def __init__(self,package_tabs):
        super().__init__()
        self.package_tabs=package_tabs
        self.desktop=desktop_family()
        self.sources=[]
        self.loaded_path=None
        self.loaded_meta=None
        self.table_mode='files'
        self._restore_dirs=[]
        self.restore_active=False
        self.restore_cursor=0
        self.restore_preflight=None
        self.restore_record=None
        self._restore_errors={}
        self._journal_error=''
        layout=QVBoxLayout(self)
        intro=QLabel(tr('Sleep lokale installatiebestanden naar de back-up. '
                        'Bij herstel toont de app de status per installatiebestand en vraagt waar nodig toestemming. '
                        'Systeeminstellingen kunt u afzonderlijk aanvinken. Alle bestanden blijven lokaal.',
                        'Drop local installation files into the backup. '
                        'On restore, each installer has a visible status and approval is requested when needed. '
                        'Optional desktop settings can also be saved. All files stay local.'))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        instructions=QLabel(tr('Ondersteund: .flatpak, .AppImage, .rpm, .deb, .pkg.tar.zst/.xz/.gz en .snap. '
                              'Een .flatpakref is GEEN offline installatiebestand. '
                              'Pakketten voor andere distributies worden niet automatisch geïnstalleerd.',
                              'Supported: .flatpak, .AppImage, .rpm, .deb, .pkg.tar.zst/.xz/.gz and .snap. '
                              'A .flatpakref is NOT an offline installer. '
                              'Packages from incompatible distributions are never installed automatically.'))
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        self.table=PackageDropTable()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels([tr('Bestand','File'),tr('Formaat','Format'),tr('Grootte','Size'),tr('Status','Status')])
        adjustable_columns(self.table,(365,115,115,245))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.filesDropped.connect(self.add_files)
        layout.addWidget(QLabel(tr('1. Sleep installatiebestanden naar de tabel hieronder',
                                  '1. Drop installation files onto the table below')))
        layout.addWidget(self.table)
        file_buttons=QHBoxLayout()
        self.pick_button=QPushButton(tr('Bestanden toevoegen...', 'Add files...'))
        self.pick_button.clicked.connect(self.pick_files)
        file_buttons.addWidget(self.pick_button)
        self.remove_button=QPushButton(tr('Selectie uit back-up halen', 'Remove from backup selection'))
        self.remove_button.clicked.connect(self.remove_file)
        file_buttons.addWidget(self.remove_button)
        self.refresh_button = QPushButton(tr('Verversen', 'Refresh'))
        self.refresh_button.setToolTip(tr('Controleer toegevoegde installatiebestanden opnieuw; wijzig geen selecties of back-ups.',
                                         'Recheck added installers without changing your selection or backup.'))
        self.refresh_button.clicked.connect(self.refresh)
        file_buttons.addWidget(self.refresh_button)
        layout.addLayout(file_buttons)
        settings_group=QGroupBox(tr('2. Optioneel: Linux-desktopinstellingen meenemen','2. Optional Linux desktop settings'))
        grid=QGridLayout(settings_group)
        self.category_boxes={}
        for index,(key,nl,en) in enumerate(self.SETTINGS):
            chk=QCheckBox(tr(nl,en))
            supported=(bool(FILES.get(self.desktop,FILES['other']).get(key)) or
                       bool(DCONF.get(self.desktop,{}).get(key)) or key in ('audio','fileassoc'))
            chk.setChecked(False)
            chk.setEnabled(supported)
            if not supported: chk.setToolTip(tr('Geen veilige adapter voor deze desktop.','No supported adapter for this desktop.'))
            self.category_boxes[key]=chk
            grid.addWidget(chk,index//3,index%3)
        layout.addWidget(settings_group)
        # Legacy UI labels kept here for regression tests and translation continuity:
        # 'Lokale ZIP-back-up maken...' / 'Create local ZIP backup...'
        # 'Geselecteerd bestand installeren' / 'Install selected backup file'
        # 'Instellingen herstellen' / 'Restore settings'
        actions=QGroupBox(tr('3. Back-up maken of herstellen','3. Create or restore backup'))
        bar=QHBoxLayout(actions)
        self.export_button=QPushButton(tr('Back-up maken...', 'Create backup...'))
        self.export_button.clicked.connect(self.export)
        bar.addWidget(self.export_button)
        self.restore_backup_button=QPushButton(tr('Back-up herstellen...', 'Restore backup...'))
        self.restore_backup_button.clicked.connect(self.restore_backup)
        bar.addWidget(self.restore_backup_button)
        layout.addWidget(actions)
        self.buttons=[self.pick_button,self.remove_button,self.refresh_button,
                      self.export_button,self.restore_backup_button]
        self.table.itemSelectionChanged.connect(self._update_actions)
        self.add_feedback(layout)
        self.output_label.setText(tr('Sleep bestanden of gebruik Bestanden toevoegen.','Drop files or use Add files.'))
        if self.desktop == 'kde':
            try:
                path = plasma_restore_root(HOME) / 'status.json'
                if path.is_file() and not path.is_symlink():
                    state = json.loads(path.read_text(encoding='utf-8'))
                    files_state = state.get('files', '?')
                    audio_state = state.get('audio', '?')
                    if files_state != 'not_selected' or audio_state != 'not_selected':
                        self.output_label.setText(tr(
                            f'Plasma-herstelstatus: bestanden={files_state}, audio={audio_state}. '
                            'Controleer na aanmelden ook scherm, panelen en audio.',
                            f'Plasma restore status: files={files_state}, audio={audio_state}. '
                            'Also verify display, panels and audio after login.'))
            except (OSError, UnicodeError, ValueError, TypeError):
                pass

    def run_query(self, callback, consumer):
        """Show a real failure popup for large backup/restore IO errors.

        A failed backup must leave the current selection and any old .bu file
        intact; a mere line in the status bar is easy to overlook.
        """
        if self.busy:return
        self.set_busy(True)
        self.worker=QueryWorker(callback)
        def finished(result,error):
            self.set_busy(False)
            if error:
                self.output_label.setText(error[-600:])
                QMessageBox.warning(self,tr('Back-upbewerking mislukt','Backup operation failed'),
                                    error[-1200:])
            else:
                consumer(result)
        self.worker.complete.connect(finished)
        self.worker.start()

    def set_busy(self, value):
        super().set_busy(value)
        if not value: self._update_actions()

    def _update_actions(self):
        if self.busy:return
        self.restore_backup_button.setEnabled(not self.restore_active)
        self.export_button.setEnabled(not self.restore_active)
        self.pick_button.setEnabled(not self.restore_active)
        self.refresh_button.setEnabled(not self.restore_active)
        self.remove_button.setEnabled(not self.restore_active and self.table_mode=='files' and self.table.currentRow()>=0)

    def _populate(self,items):
        self.table.setRowCount(0)
        for entry in items:
            row=self.table.rowCount();self.table.insertRow(row)
            for col,key in enumerate(('filename','kind','size')):
                value=f'{entry[key]/1048576:.1f} MiB' if key=='size' else str(entry[key])
                cell=QTableWidgetItem(value)
                cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row,col,cell)
            default = tr('Wacht op toestemming','Waiting for approval') if self.table_mode=='backup' else tr('Klaar voor back-up','Ready for backup')
            status=QTableWidgetItem(default)
            status.setFlags(status.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row,3,status)
        self._update_actions()

    def refresh(self):
        """Recheck current backup contents; never discard drafts or restart restore."""
        if self.busy or self.restore_active:
            return
        if self.table_mode == 'backup':
            if not self.loaded_path:
                return
            expected_meta = self.loaded_meta
            archive = self.loaded_path
            def done(meta):
                if meta != expected_meta:
                    # Don't silently replace a loaded archive and retain stale
                    # preflight approvals after the on-disk .bu changes.
                    self.loaded_meta = None
                    self.restore_preflight = None
                    self.output_label.setText(tr(
                        'De geopende back-up is gewijzigd. Open deze opnieuw en controleer de voorcontrole.',
                        'The opened backup changed. Reopen it and review the preflight.'))
                    self.restore_backup_button.setEnabled(False)
                else:
                    self.output_label.setText(tr('Back-up opnieuw gecontroleerd; selectie behouden.',
                                                 'Backup revalidated; selection preserved.'))
            self.run_query(lambda: inspect_file_backup(archive), done)
            return
        # Don't call clear_files(): category checkboxes and selected files stay.
        current = self.table.currentRow()
        rows = []
        errors = []
        for file in self.sources:
            try:
                kind, size = validate_source(file)
                rows.append({'filename':file.name, 'kind':kind, 'size':size})
            except (OSError, ValueError) as exc:
                rows.append({'filename':file.name, 'kind':package_type(file.name) or '-', 'size':0})
                errors.append(file.name + ': ' + str(exc))
        self._populate(rows)
        for row, file in enumerate(self.sources):
            if any(error.startswith(file.name + ':') for error in errors):
                self.table.item(row, 3).setText(tr('Bestand ontbreekt / ongeldig', 'Missing / invalid file'))
        if 0 <= current < self.table.rowCount():
            self.table.selectRow(current)
        self.output_label.setText(tr('Installatiebestanden opnieuw gecontroleerd.',
                                     'Installer files rechecked.') if not errors else '\n'.join(errors[:6]))
        if errors:
            QMessageBox.warning(self, tr('Bestand ontbreekt of ongeldig', 'Missing or invalid file'),
                                '\n'.join(errors[:10]))

    def add_files(self,paths):
        if self.busy or self.restore_active:return
        if self.table_mode!='files':
            if QMessageBox.question(self,tr('Nieuwe back-up maken?','Start a new backup?'),tr(
                'Je hebt een bestaande back-up geopend. Een nieuwe selectie starten? '
                'De bestaande ZIP wordt niet gewijzigd.',
                'You have opened an existing backup. Start a new selection? '
                'The existing ZIP will not be modified.'),
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
            self.clear_files()
        errors=[];known={p.name for p in self.sources}
        for value in paths:
            p=Path(value)
            try:
                from local_file_backup import validate_source
                kind,size=validate_source(p)
                if p.name in known:raise ValueError(tr('Bestand al toegevoegd','File already added'))
                if len(self.sources)>=100:raise ValueError('Maximum: 100 package files')
                self.sources.append(p)
                known.add(p.name)
            except (OSError,ValueError) as exc:
                errors.append(f'{p.name}: {exc}')
        self._populate([{'filename':p.name,'kind':package_type(p.name),'size':p.stat().st_size} for p in self.sources])
        if errors: QMessageBox.warning(self,tr('Sommige bestanden geweigerd','Some files rejected'),'\n'.join(errors[:15]))

    def pick_files(self):
        paths,_=QFileDialog.getOpenFileNames(self,tr('Installatiebestanden kiezen','Choose installer files'),str(HOME),
                   'Installers (*.flatpak *.AppImage *.appimage *.rpm *.deb *.snap *.pkg.tar.zst *.pkg.tar.xz *.pkg.tar.gz)')
        if paths:self.add_files(paths)

    def remove_file(self):
        if self.busy or self.table_mode!='files':return
        row=self.table.currentRow()
        if row>=0 and row<len(self.sources):
            self.sources.pop(row)
            self._populate([{'filename':p.name,'kind':package_type(p.name),'size':p.stat().st_size} for p in self.sources])

    def clear_files(self):
        """Internally start a fresh draft without a separate Clear list button."""
        if self.busy:return
        self.sources=[];self.loaded_meta=None;self.loaded_path=None;self.table_mode='files'
        self.restore_preflight=None
        self.restore_record=None
        self._restore_errors={}
        self._journal_error=''
        self.restore_active=False
        self.restore_cursor=0
        for temp in list(self._restore_dirs):
            temp.cleanup()
        self._restore_dirs.clear()
        for key, box in self.category_boxes.items():
            supported=(bool(FILES.get(self.desktop,FILES['other']).get(key)) or
                       bool(DCONF.get(self.desktop,{}).get(key)) or key in ('audio','fileassoc'))
            box.setChecked(False)
            box.setEnabled(supported)
        self._populate([])
        self.output_label.setText(tr('Sleep bestanden naar de tabel.','Drop files into the table.'))
        self._update_actions()

    def selected_categories(self):
        return {k for k,ch in self.category_boxes.items() if ch.isChecked()}

    @staticmethod
    def _dconf_load(prefix,data):
        # Send the archived values to the real user's host session, not to the
        # Flatpak runtime's isolated dconf database. Preserve diagnostic text.
        args=(['flatpak-spawn','--host'] if IN_SANDBOX else [])+['dconf','load',prefix]
        try:
            p=subprocess.run(args,input=data,text=True,capture_output=True,timeout=25)
        except (OSError,subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f'Cannot restore GNOME dconf settings at {prefix}: {exc}') from exc
        if p.returncode!=0:
            raise RuntimeError(f'Cannot restore GNOME dconf settings at {prefix}: '
                               f'{(p.stderr or p.stdout).strip() or "dconf load failed"}')
        return True

    def export(self):
        if self.busy or self.restore_active:return
        if self.table_mode!='files':
            QMessageBox.information(self,'Info',tr('Klik op Bestanden toevoegen om een nieuwe back-up te beginnen.',
                                                  'Click Add files to start a new backup.'))
            return
        settings=self.selected_categories()
        if not self.sources and not settings:
            QMessageBox.information(self,'Info',tr('Voeg bestanden toe of vink instellingen aan.',
                'Add installer files or select settings.'))
            return
        dest,_=QFileDialog.getSaveFileName(self,tr('Lokale back-up opslaan','Save local backup'),
                 str(HOME/'Documents'/'UniversalLinuxSoftwareManager-backup.bu'),'Universal Linux Backup (*.bu)')
        if not dest:return
        if not dest.lower().endswith('.bu'): dest += '.bu'
        if Path(dest).exists():
            if QMessageBox.question(self,tr('Overschrijven?','Overwrite?'),str(dest),
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        if QMessageBox.question(self,tr('Lokale back-up','Local backup'),tr(
           'Bewaar alleen installatiebestanden die je vertrouwt. Instellingen kunnen privégegevens bevatten. '
           'Het .bu-bestand is NIET versleuteld. Doorgaan?',
           'Only save installers from trusted sources. Settings may contain personal data. '
           'The .bu file is NOT encrypted. Continue?'),
           QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
           QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        sources=list(self.sources)
        desktop=self.desktop
        def build():
            # The archive is written atomically beside the final destination.
            # Estimate the *entire* staged copy, not just the largest installer.
            estimate=estimated_backup_bytes(sources, 110*1024*1024 if settings else 0)
            free=shutil.disk_usage(Path(dest).parent).free
            if free < estimate:
                raise OSError(tr(
                    f'Onvoldoende vrije ruimte voor een veilige back-up: circa {estimate // (1024*1024)} MiB nodig, '
                    f'{free // (1024*1024)} MiB beschikbaar. Het vorige .bu-bestand is niet gewijzigd.',
                    f'Not enough free space to safely create backup: about {estimate // (1024*1024)} MiB needed, '
                    f'{free // (1024*1024)} MiB available. Any previous .bu file was left unchanged.'))
            with tempfile.TemporaryDirectory(prefix='ulsm-settings-',dir=Path(dest).parent) as work:
                settings_file=None
                settings_details=None
                if settings:
                    settings_file=Path(work)/'settings.zip'
                    settings_details=make_backup(HOME,settings_file,settings,(),desktop,host_os_families(),command)
                meta=create_file_backup(dest,sources,settings_file,desktop,host_os_families())
                if settings_details:
                    meta['settings_details']={
                        'files':len(settings_details['files']),
                        'dconf':len(settings_details['dconf']),
                        'empty_categories':settings_details.get('empty_categories',[]),
                        'audio_state':bool(settings_details.get('audio_state'))}
                return meta
        def done(meta):
            message=tr(
                f'Back-up succesvol opgeslagen.\n\n{len(meta["packages"])} installatiebestanden.\n\nBestand: {dest}\n\n'
                'Na OK wordt de lijst leeggemaakt; het .bu-bestand blijft behouden.',
                f'Backup saved successfully.\n\n{len(meta["packages"])} installer files.\n\nFile: {dest}\n\n'
                'After OK the list will be cleared; the .bu file is kept.')
            if meta.get('settings_details'):
                info=meta['settings_details']
                message += tr(f'\nOpgeslagen desktopbestanden: {info["files"]}, GNOME/dconf-groepen: {info["dconf"]}.',
                              f'\nSaved desktop files: {info["files"]}, GNOME/dconf groups: {info["dconf"]}.')
                if info.get('audio_state'):
                    message += tr('\nAudio: standaardapparaten, volume en mute opgeslagen.',
                                  '\nAudio: default devices, volume and mute saved.')
                if info['empty_categories']:
                    message += tr('\nZonder aangepaste waarden: ', '\nNo customized values found for: ') + ', '.join(info['empty_categories'])
            QMessageBox.information(self,tr('Back-up geslaagd','Backup succeeded'),message)
            # Reset only after successfully writing the archive and dismissing the dialog.
            self.clear_files()
        self.run_query(build,done)

    def open_backup(self):
        if self.busy or self.restore_active:return
        file,_=QFileDialog.getOpenFileName(self,tr('Back-up openen','Open backup'),str(HOME),'Universal Linux Backup (*.bu);;Previous ZIP backups (*.zip)')
        if not file:return
        desktop=self.desktop
        allowed={tab.kind for tab in self.package_tabs if tab.can_install}
        def inspect_and_probe():
            meta=inspect_file_backup(file)
            kinds={entry['kind'] for entry in meta['packages']}
            managers={kind:native_manager(kind) for kind in kinds}
            # This is the destination filesystem of _new_staging().
            free=shutil.disk_usage(HOME).free
            report=preflight_restore(meta,desktop=desktop,
                distro=host_os_families(),architecture=platform.machine(),
                available_kinds=allowed,managers=managers,free_bytes=free)
            return meta,report
        def finished(result):
            meta,report=result
            self.loaded_meta=meta;self.loaded_path=file;self.sources=[];self.table_mode='backup'
            self.restore_preflight=report
            self._restore_errors={}
            self._populate(meta['packages'])
            settings_present=bool(meta.get('settings'))
            if settings_present:
                row=self.table.rowCount()
                self.table.insertRow(row)
                for col,value in enumerate((tr('Linux-desktopinstellingen','Linux desktop settings'),
                                            tr('Instellingen','Settings'),'-',
                                            tr('Wacht op toestemming','Waiting for approval'))):
                    cell=QTableWidgetItem(value)
                    cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.table.setItem(row,col,cell)
            for box in self.category_boxes.values(): box.setEnabled(False)
            for index in report['blocked']:
                if index=='settings':
                    if settings_present:self._status(len(meta['packages']),'Niet beschikbaar','Unavailable')
                else:
                    self._status(index,'Niet beschikbaar','Unavailable')
            preflight_status = tr(
                f'{len(meta["packages"])} apps en instellingen: {"ja" if settings_present else "nee"}. '
                'Bekijk de voorcontrole en klik opnieuw op Back-up herstellen om te beginnen.',
                f'{len(meta["packages"])} apps; settings: {"yes" if settings_present else "no"}. '
                'Review preflight results, then click Restore backup again to start.')
            self.output_label.setText(prominent_notice(
                preflight_status,
                tr('klik opnieuw op Back-up herstellen om te beginnen.',
                   'click Restore backup again to start.'),
                self.output_label.font().pointSizeF()))
            self._update_actions()
            dialog=QMessageBox(self)
            dialog.setIcon(QMessageBox.Icon.Warning if report['blocked'] or report['warnings']
                           else QMessageBox.Icon.Information)
            dialog.setWindowTitle(tr('Back-up gecontroleerd — voorcontrole','Backup verified — preflight'))
            dialog.setText(prominent_notice(
                summarize_report(report,NL),
                tr('Klik nogmaals op Restore backup om te beginnen.',
                   'Click Restore backup again to start.'),
                dialog.font().pointSizeF()))
            dialog.setInformativeText(tr(
                'De back-up is alleen ingelezen en gecontroleerd. Er is niets geïnstalleerd. '
                'Niet-ondersteunde onderdelen worden overgeslagen. Voor apps en instellingen wordt apart toestemming gevraagd.',
                'The backup has been read and checked only. Nothing has been installed. '
                'Unavailable items will be skipped. Each app and settings restore still requires approval.'))
            dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
            dialog.exec()
        self.run_query(inspect_and_probe,finished)

    def _status(self,row,nl,en):
        item=self.table.item(row,3)
        if item is not None:
            label=tr(nl,en)
            item.setText(label)
            self.table.scrollToItem(item)
            if self.restore_record is not None:
                try: restore_journal.update(HOME,self.restore_record,row,en)
                except (OSError,ValueError,IndexError) as exc:
                    self._journal_error=str(exc)

    def _restore_finish(self):
        """Show the final outcome first; reset to a clean draft only after OK."""
        self.restore_active=False
        self._update_actions()
        successful={tr('Geïnstalleerd','Installed'), tr('Hersteld','Restored')}
        partly=tr('Gedeeltelijk hersteld','Partially restored')
        reboot=tr('Herstart vereist','Reboot required')
        skipped={tr('Overgeslagen','Skipped'), tr('Geannuleerd','Cancelled')}
        failed={tr('Mislukt','Failed'), tr('Niet beschikbaar','Unavailable'),
                tr('Niet compatibel','Incompatible architecture')}
        items=[]
        for row in range(self.table.rowCount()):
            name=self.table.item(row,0)
            status=self.table.item(row,3)
            if name and status:
                items.append((name.text(),status.text()))
        statuses=[status for _,status in items]
        done=sum(status in successful for status in statuses)
        partial=sum(status == partly for status in statuses)
        restart=sum(status==reboot for status in statuses)
        ignored=sum(status in skipped for status in statuses)
        errors=sum(status in failed for status in statuses)
        pending=len(statuses)-done-partial-restart-ignored-errors
        # Do not declare success when the recovery journal cannot be written.
        if self.restore_record is not None and not self._journal_error:
            try: restore_journal.finish(HOME,self.restore_record)
            except (OSError,ValueError) as exc: self._journal_error=str(exc)

        if errors or partial or pending or self._journal_error:
            title=tr('Herstel afgerond met problemen','Restore completed with issues')
            icon=QMessageBox.Icon.Warning
        elif ignored:
            title=tr('Herstel afgerond met overgeslagen onderdelen','Restore completed with skipped items')
            icon=QMessageBox.Icon.Information
        elif restart:
            title=tr('Herstel afgerond — herstart vereist','Restore completed — restart required')
            icon=QMessageBox.Icon.Information
        else:
            title=tr('Herstel geslaagd','Restore succeeded')
            icon=QMessageBox.Icon.Information

        summary=tr(
            f'Herstelronde afgerond.\n\nGeslaagd: {done}\nHerstart vereist: {restart}\n'
            f'Gedeeltelijk hersteld: {partial}\nOvergeslagen of geannuleerd: {ignored}\nProblemen: {errors + partial}\nNog niet behandeld: {pending}',
            f'Restore run finished.\n\nSucceeded: {done}\nRestart required: {restart}\n'
            f'Partially restored: {partial}\nSkipped or cancelled: {ignored}\nProblems: {errors + partial}\nNot processed: {pending}')
        reboot_notice = tr(
            'BELANGRIJK: HERSTART JE COMPUTER na dit herstel. '
            'Dit geldt voor ALLE Linux-distributies en desktopomgevingen, '
            'zodat herstelde instellingen volledig actief worden.',
            'IMPORTANT: REBOOT YOUR COMPUTER after this restore. '
            'This applies to ALL Linux distributions and desktop environments '
            'so restored settings can take full effect.')
        if done or restart or partial:
            summary += '\n\n' + reboot_notice
        details='\n'.join(f'{name} — {status}'+
                           (f' ({self._restore_errors[index]})' if index in self._restore_errors else '')
                           for index,(name,status) in enumerate(items))
        if self._journal_error:
            summary += '\n\n' + tr('Herstelregistratie mislukt: ', 'Restore journal failed: ') + self._journal_error[:200]
        dialog=QMessageBox(self)
        dialog.setIcon(icon)
        dialog.setWindowTitle(title)
        dialog.setText(prominent_notice(
            summary, reboot_notice if done or restart else '',
            dialog.font().pointSizeF()))
        dialog.setInformativeText(tr(
            'Klik op Details om de uitkomst per app te zien.\n'
            'Na OK wordt de lijst leeggemaakt. Je .bu-bestand blijft bewaard.',
            'Open Details to review each app result.\n'
            'After OK the list will be cleared. Your .bu file is kept.'))
        if details: dialog.setDetailedText(details)
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.exec()
        # Preserve results until the modal summary is acknowledged.
        self.clear_files()

    def restore_backup(self):
        if self.busy or self.restore_active:return
        if not self.loaded_meta or not self.loaded_path or self.table_mode!='backup':
            self.open_backup()
            return
        pending={tr('Wacht op toestemming','Waiting for approval'),tr('Mislukt','Failed')}
        if not any(self.table.item(r,3) and self.table.item(r,3).text() in pending
                   for r in range(self.table.rowCount())):
            QMessageBox.information(self,'Info',tr('Er zijn geen wachtende onderdelen. Open een andere back-up om opnieuw te beginnen.',
                                              'No pending items. Open another backup to start again.'))
            return
        # Recheck free space before any changes (it may have decreased while
        # the user was reading the preflight popup).
        space=shutil.disk_usage(HOME).free
        if self.restore_preflight:
            for idx,row in enumerate(self.restore_preflight['rows']):
                if space < row['bytes'] + MARGIN:
                    self.restore_preflight['blocked'][idx] = 'Insufficient free space to stage this installer.'
                    self._status(idx,'Niet beschikbaar','Unavailable')
            if self.loaded_meta.get('settings') and space < 2*int(self.loaded_meta['settings']['size']) + MARGIN:
                self.restore_preflight['blocked']['settings'] = 'Insufficient space for settings.'
                self._status(len(self.loaded_meta['packages']),'Niet beschikbaar','Unavailable')
        try:
            self._journal_error=''
            self._restore_errors={}
            names=[self.table.item(row,0).text() for row in range(self.table.rowCount())]
            self.restore_record=restore_journal.start(HOME,self.loaded_path,names)
            # Journal starts with current preflight statuses including unavailable.
            for row in range(self.table.rowCount()):
                restore_journal.update(HOME,self.restore_record,row,self.table.item(row,3).text())
        except (OSError,ValueError) as exc:
            self.restore_record=None
            QMessageBox.warning(self,tr('Herstel niet gestart','Restore not started'),
                tr('De veilige herstelregistratie kon niet worden aangemaakt: ',
                   'Could not write the safety restore journal: ') + str(exc))
            return
        self.restore_active=True
        self.restore_cursor=0
        self._update_actions()
        QTimer.singleShot(0,self._restore_next)

    def _restore_next(self):
        if not self.restore_active:return
        if self._journal_error:
            self._restore_finish()
            return
        count=len(self.loaded_meta['packages'])
        while self.restore_cursor < count:
            i=self.restore_cursor
            self.restore_cursor+=1
            if self.table.item(i,3).text() not in (tr('Wacht op toestemming','Waiting for approval'),tr('Mislukt','Failed')):
                continue
            item=self.loaded_meta['packages'][i]
            if self.restore_preflight and i in self.restore_preflight['blocked']:
                self._status(i,'Niet beschikbaar','Unavailable')
                self._restore_errors[i]=self.restore_preflight['blocked'][i]
                continue
            target=next((t for t in self.package_tabs if t.kind==item['kind']),None)
            if not target or not target.can_install or target.busy:
                self._status(i,'Niet beschikbaar','Unavailable')
                continue
            arch=self.loaded_meta.get('architecture','')
            if arch and arch != platform.machine() and item['kind']!='Flatpak':
                self._status(i,'Niet compatibel','Incompatible architecture')
                continue
            answer=QMessageBox.question(self,tr('App herstellen?','Restore application?'),
                f'{item["filename"]} ({item["kind"]})\n\n'+tr(
                'Dit installatiebestand is afkomstig uit een lokale back-up. Alleen installeren als je de bron vertrouwt. '
                'Wil je dit pakket installeren?',
                'This installer comes from a local backup. Only install it if you trust its source. '
                'Install this package?'),
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No|QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.No)
            if answer==QMessageBox.StandardButton.Cancel:
                self._status(i,'Geannuleerd','Cancelled')
                self._restore_finish()
                return
            if answer!=QMessageBox.StandardButton.Yes:
                self._status(i,'Overgeslagen','Skipped')
                continue
            self._status(i,'Controleren...','Verifying...')
            archive=self.loaded_path
            try: stage=self._new_staging()
            except (OSError,ValueError) as exc:
                self._status(i,'Mislukt','Failed')
                self.output_label.setText(str(exc))
                continue
            self.set_busy(True)
            self.worker=QueryWorker(lambda archive=archive,i=i,stage=stage: extract_file_package(archive,i,stage))
            def extracted(path,error,i=i,target=target,stage=stage):
                self.set_busy(False)
                if error:
                    self._status(i,'Mislukt','Failed')
                    self._restore_errors[i]='Backup file extraction or checksum verification failed.'
                    self.output_label.setText(error[-500:])
                    self._cleanup_stage(stage)
                    QTimer.singleShot(0,self._restore_next)
                    return
                self._status(i,'Installeren...','Installing...')
                try: started=target.install_file(Path(path),approved=True)
                except Exception as exc:
                    started=False
                    self.output_label.setText(str(exc))
                if not started or not target.busy or target.job is None:
                    self._status(i,'Mislukt','Failed')
                    self._restore_errors[i]='Installer did not start or permission was denied.'
                    self._cleanup_stage(stage)
                    QTimer.singleShot(0,self._restore_next)
                    return
                def installed(ok,detail,i=i,kind=item['kind'],stage=stage):
                    if ok:
                        if kind=='RPM' and native_manager('RPM')=='rpm-ostree':
                            self._status(i,'Herstart vereist','Reboot required')
                        else:
                            self._status(i,'Geïnstalleerd','Installed')
                    else:
                        self._status(i,'Mislukt','Failed')
                        self._restore_errors[i]='Package installer reported an error. Check the corresponding package tab.'
                    self._cleanup_stage(stage)
                    QTimer.singleShot(0,self._restore_next)
                target.job.done.connect(installed)
            self.worker.complete.connect(extracted)
            self.worker.start()
            return
        if self.loaded_meta.get('settings'):
            i=count
            status=self.table.item(i,3)
            if status is not None and status.text() in (tr('Wacht op toestemming','Waiting for approval'),tr('Mislukt','Failed')):
                self._restore_settings_queued(i)
                return
        self._restore_finish()

    def _restore_settings_queued(self,i):
        if self.restore_preflight and 'settings' in self.restore_preflight['blocked']:
            self._status(i,'Niet beschikbaar','Unavailable')
            self._restore_errors[i]=self.restore_preflight['blocked']['settings']
            self._restore_finish()
            return
        answer=QMessageBox.question(self,tr('Instellingen herstellen?','Restore desktop settings?'),
            tr('Dit kan bestaande desktopinstellingen overschrijven. Een herstelkopie wordt gemaakt. '
               'Op KDE worden eenmalige gebruikersservices ingesteld: configuratie vóór Plasma, audio na aanmelden. '
               'Er wordt niet automatisch herstart. Op andere desktops blijft herstart vereist. Doorgaan?',
               'This may overwrite existing desktop settings. A rollback copy is made. '
               'On KDE Plasma, the app installs one-time user services to apply settings before the next Plasma login '
               'and audio after login. No automatic reboot. For other desktops a reboot is needed. Continue?'),
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No|QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.No)
        if answer==QMessageBox.StandardButton.Cancel:
            self._status(i,'Geannuleerd','Cancelled')
            self._restore_finish()
            return
        if answer!=QMessageBox.StandardButton.Yes:
            self._status(i,'Overgeslagen','Skipped')
            self._restore_finish()
            return
        archive=self.loaded_path
        self._status(i,'Herstellen...','Restoring...')
        self.set_busy(True)
        def perform():
            with tempfile.TemporaryDirectory(prefix='ulsm-settings-') as tmp:
                nested=extract_file_settings(archive,tmp)
                settings=inspect_backup(nested)
                groups=set(settings['categories'])-{'apps','appsettings'}
                if not groups:raise ValueError('No supported desktop settings in backup')
                if self.desktop == 'kde' and settings['desktop'] == 'kde':
                    return stage_restore(HOME, nested, groups, self.desktop,
                                         host_run=command)
                return restore_settings(HOME,nested,groups,self.desktop,self._dconf_load,
                                        dconf_run=command, audio_run=command,
                                        audio_policy='best_effort', return_report=True)
        self.worker=QueryWorker(perform)
        def complete(folder,error):
            self.set_busy(False)
            if error:
                self._status(i,'Mislukt','Failed')
                self._restore_errors[i]=str(error)[-800:]
                self.output_label.setText(error[-500:])
            else:
                report = folder if isinstance(folder, dict) else {'recovery_dir': str(folder), 'warnings': []}
                warnings = report.get('warnings', [])
                if report.get('pending'):
                    self._status(i, 'Herstart vereist', 'Reboot required')
                    self.output_label.setText(tr(
                        'KDE-instellingen veilig klaargezet. Herstart de computer wanneer je klaar bent. '
                        'De terugzetactie loopt eenmalig vóór Plasma; audio volgt na aanmelden. '                        'Open daarna de app en controleer de herstelstatus.',
                        'KDE settings staged safely. Reboot when ready. The one-time restore runs '
                        'before Plasma; audio follows after login. Reopen the app and inspect restore status.'))
                elif warnings:
                    self._status(i,'Gedeeltelijk hersteld','Partially restored')
                    self._restore_errors[i] = ' | '.join(warnings)[-800:]
                else:
                    self._status(i,'Hersteld','Restored')
                if not report.get('pending'):
                    note = ('\n\nWARNING: ' + ' | '.join(warnings)) if warnings else ''
                    self.output_label.setText(tr('Instellingen teruggezet. Herstart je computer om alles volledig toe te passen. '
                                                 'Vorige instellingen: ',
                                                 'Settings restored. Reboot your computer to fully apply all settings. '
                                                 'Previous settings: ')+str(report['recovery_dir'])+note)
            self._restore_finish()
        self.worker.complete.connect(complete)
        self.worker.start()

    def warn_unfinished(self):
        previous=restore_journal.read_unfinished(HOME)
        if not previous:return
        items=previous.get('items', [])
        completed=sum(entry.get('status') in ('Installed','Restored','Reboot required') for entry in items)
        box=QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(tr('Vorige herstelronde onderbroken','Previous restore was interrupted'))
        box.setText(tr(
            f'Een eerdere herstelronde is niet volledig afgesloten.\n'
            f'Bevestigde resultaten: {completed} van {len(items)}.\n\n'
            'Controleer eerst de werkelijk geïnstalleerde apps voordat je de .bu-back-up opnieuw opent. '
            'De app zal nooit vanzelf pakketten opnieuw installeren.',
            f'A previous restore did not complete cleanly.\n'
            f'Confirmed results: {completed} of {len(items)}.\n\n'
            'Check the apps actually installed before reopening the .bu file. '
            'No packages are reinstalled automatically.'))
        box.setDetailedText('\n'.join(f'{e.get("name", "?")} — {e.get("status", "?")}' for e in items))
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()

    def _new_staging(self):
        root=HOME/'.local/share/UniversalLinuxSoftwareManager/restore-tmp'
        root.mkdir(parents=True,exist_ok=True)
        if root.is_symlink():raise ValueError('Unsafe restore staging directory')
        temp=tempfile.TemporaryDirectory(prefix='selected-',dir=root)
        self._restore_dirs.append(temp)
        return temp.name

    def _cleanup_stage(self, path):
        for temp in list(self._restore_dirs):
            if temp.name == path:
                self._restore_dirs.remove(temp)
                temp.cleanup()
                return

    def restore(self):
        if self.busy or not self.loaded_meta or not self.loaded_path:return
        row=self.table.currentRow()
        if row<0 or row>=len(self.loaded_meta['packages']):return
        item=self.loaded_meta['packages'][row]
        target=next((t for t in self.package_tabs if t.kind==item['kind']),None)
        if target is None or not target.can_install:
            QMessageBox.warning(self,'Info',tr('Dit pakketformaat wordt op deze distributie niet ondersteund.',
                                                  'This package format is not supported on this distribution.'))
            return
        if target.busy:
            QMessageBox.information(self,'Info',tr('Dit pakket-tabblad is nog bezig.',
                                                  'That package tab is currently busy.'))
            return
        src_arch=self.loaded_meta.get('architecture','')
        if src_arch and src_arch!=platform.machine() and item['kind']!='Flatpak':
            QMessageBox.warning(self,tr('Architectuur verschilt','Different architecture'),
                tr('Back-uparchitectuur: ','Backup architecture: ')+src_arch+ '\n'+
                tr('Dit pakket wordt niet automatisch geïnstalleerd.','This package will not be automatically installed.'))
            return
        if QMessageBox.question(self,tr('Pakket opnieuw installeren','Reinstall package'),
            f'{item["filename"]} ({item["kind"]})\n\n'+tr(
            'Dit installatiebestand komt uit een back-up en wordt niet automatisch vertrouwd. '
            'De pakketbeheerder controleert waar mogelijk afhankelijkheden en ondertekening. '
            'Wil je het bestand uitpakken en naar het juiste installatietabblad sturen?',
            'The installer comes from a backup and is not automatically trusted. '
            'The package manager checks dependencies and signatures where supported. '
            'Extract it and pass it to the appropriate installer tab?'),
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        stage=self._new_staging()
        archive=self.loaded_path
        def done(path):
            self.output_label.setText(tr('Bestand gecontroleerd. Installer wordt geopend: ',
                                         'File verified. Opening installer: ')+str(path))
            target.install_file(Path(path))
        self.run_query(lambda:extract_file_package(archive,row,stage),done)

    def restore_preferences(self):
        if self.busy or not self.loaded_path or not self.loaded_meta or not self.loaded_meta.get('settings'):return
        if QMessageBox.question(self,tr('Systeeminstellingen herstellen?','Restore system settings?'),
            tr('Dit overschrijft geselecteerde desktopinstellingen. Bestaande bestanden worden in restore-history veilig bewaard. '
               'Instellingen zijn soms incompatibel tussen desktops of hardware. Na herstel is een herstart nodig. Doorgaan?',
               'This overwrites selected desktop settings. Existing files are saved under restore-history. '
               'Settings may be incompatible across desktops or hardware. A reboot is needed after restore. Continue?'),
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        archive=self.loaded_path
        def perform():
            with tempfile.TemporaryDirectory(prefix='ulsm-settings-') as tmp:
                nested=extract_file_settings(archive,tmp)
                settings=inspect_backup(nested)
                groups=set(settings['categories'])-{'apps','appsettings'}
                if not groups:raise ValueError('No supported desktop settings in backup')
                if self.desktop == 'kde' and settings['desktop'] == 'kde':
                    return stage_restore(HOME, nested, groups, self.desktop,
                                         host_run=command)
                return restore_settings(HOME,nested,groups,self.desktop,self._dconf_load,
                                        dconf_run=command, audio_run=command,
                                        audio_policy='best_effort', return_report=True)
        def done(folder):
            report = folder if isinstance(folder, dict) else {'recovery_dir': str(folder), 'warnings': []}
            body = tr('Herstart je computer om alle instellingen volledig toe te passen. Vorige instellingen: ',
                      'Reboot your computer to fully apply all settings. Previous settings: ') + str(report['recovery_dir'])
            if report['warnings']:
                QMessageBox.warning(self, tr('Gedeeltelijk hersteld','Settings partially restored'),
                                    body + '\n\n' + '\n'.join(report['warnings']))
            else:
                QMessageBox.information(self,tr('Instellingen hersteld','Settings restored'),body)
        self.run_query(perform,done)



class Center(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Universal Linux Software Manager')
        self.resize(1260, 800)
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
        self.updates_tab = UpdatesPanel(self.package_tabs[1], self.package_tabs)
        self.discover_tab = DiscoverPanel()
        self.backup_tab = BackupPanel(self.package_tabs)
        self.info_tab = InfoPanel()
        self.extra_tabs = [self.updates_tab, self.discover_tab, self.backup_tab]
        tabs.addTab(self.updates_tab, tr('Updates','Updates'))
        tabs.addTab(self.discover_tab, tr('Ontdekken','Discover'))
        tabs.addTab(self.backup_tab, tr('Back-up / Herstellen','Backup / Restore'))
        tabs.addTab(self.info_tab, 'Info')
        self.tabs_widget = tabs
        self.help_shortcut = QShortcut(QKeySequence('F1'), self)
        self.help_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.help_shortcut.activated.connect(self.open_context_help)
        tabs.currentChanged.connect(self.when_tab_activated)
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
        credit = QLabel('v1.0.0 · <a href="https://github.com/LionheartTim">LionheartTim</a>')
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
        QTimer.singleShot(0, self.backup_tab.warn_unfinished)

    def open_context_help(self):
        """Open the chapter for the user's currently selected app tab."""
        current = self.tabs_widget.currentWidget()
        topic = 'contents'
        if current in self.package_tabs:
            topic = current.kind.lower()
        elif current is self.updates_tab:
            topic = 'updates'
        elif current is self.discover_tab:
            topic = 'discover'
        elif current is self.backup_tab:
            topic = 'backup'
        self.tabs_widget.setCurrentWidget(self.info_tab)
        self.info_tab.show_topic(topic)

    def when_tab_activated(self, index):
        current = self.tabs_widget.widget(index)
        if current is self.updates_tab and not self.updates_tab.busy:
            self.updates_tab.refresh()

    def closeEvent(self, event):
        active = [tab.kind for tab in self.package_tabs if tab.busy or
                  (tab.job is not None and tab.job.isRunning())]
        active.extend(name for name, tab in (
            ('Updates', self.updates_tab), ('Discover', self.discover_tab),
            ('Backup / Restore', self.backup_tab))
            if tab.busy or (tab.job is not None and tab.job.isRunning()) or
            (tab.worker is not None and tab.worker.isRunning()))
        if self.backup_tab.restore_active:
            active.append('Backup / Restore')
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
    QGuiApplication.setApplicationDisplayName('Universal Linux Software Manager')
    QGuiApplication.setDesktopFileName(APP_ID)
    icon_path = Path(__file__).with_name('icon.png')
    if icon_path.is_file():
        QGuiApplication.setWindowIcon(QIcon(str(icon_path)))
    w = Center()
    w.show()
    sys.exit(app.exec())
