"""Explicit, fail-closed Flatpak -> GitHub AppImage source migration.

An app's display name is *not* proof of identity. All deletion requires an
explicit GUI choice of the full Flatpak ID/ref/installation. Data is preserved.
"""
from dataclasses import dataclass
import os
import re
from pathlib import Path

from online_sources import install_github_appimage, _safe_filename

APP_ID = re.compile(r'^[A-Za-z0-9_]+(?:[.][A-Za-z0-9_-]+)+$')
ATOM = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9_.-]*$')


@dataclass(frozen=True)
class InstalledFlatpak:
    app_id: str
    name: str
    installation: str
    origin: str
    ref: str


def parse_flatpak_installs(output):
    """Require full Flatpak refs; never act on a truncated package identity."""
    if not isinstance(output, str):
        raise ValueError('Invalid Flatpak list output')
    installed = []
    for index, line in enumerate(output.splitlines()):
        if not line.strip():
            continue
        cells = line.split('\t')
        if len(cells) != 5:
            raise ValueError('Incomplete Flatpak app list; refusing source switch')
        app_id, name, installation, origin, ref = (c.strip() for c in cells)
        # Flatpak's human-readable output generally begins with a column header.
        # It is metadata, not an installed application.
        if (index == 0 and ref.casefold() in ('ref', 'reference') and
                ('application' in app_id.casefold() or 'applicatie' in app_id.casefold())):
            continue
        if not APP_ID.fullmatch(app_id) or not ATOM.fullmatch(installation):
            raise ValueError('Invalid Flatpak ID or installation')
        parts = ref.split('/')
        if len(parts) != 4 or parts[0] != 'app' or parts[1] != app_id or not all(ATOM.fullmatch(v) for v in parts[2:]):
            raise ValueError('Invalid or ambiguous installed Flatpak ref')
        if not name or not ATOM.fullmatch(origin):
            raise ValueError('Flatpak app list has no safe name or origin')
        installed.append(InstalledFlatpak(app_id, name, installation, origin, ref))
    return installed


def list_installed_flatpaks(run_command):
    ok, output, error = run_command([
        'flatpak', 'list', '--app',
        '--columns=application:full,name:full,installation:full,origin:full,ref:full'
    ], 45)
    if not ok:
        raise RuntimeError('Cannot verify installed Flatpaks: ' + str(error or output)[:350])
    return parse_flatpak_installs(output)


def suggested_matches(installed, github_name, repo):
    """Suggest similar titles; suggestions never authorize a removal."""
    def key(s):
        return ''.join(c for c in str(s).casefold() if c.isalnum())
    names = {key(github_name), key(str(repo).split('/')[-1])}
    names.discard('')
    return [item for item in installed if key(item.name) in names or key(item.app_id.split('.')[-1]) in names]


def installation_flag(location):
    if location == 'user':
        return '--user'
    if location in ('system', 'default'):
        return '--system'
    if ATOM.fullmatch(location):
        return '--installation=' + location
    raise ValueError('Unsafe Flatpak installation identity')


def uninstall_args(app):
    # Never pass --delete-data, --unused or an ambiguous bare application ID.
    return ['flatpak','uninstall',installation_flag(app.installation),
            '--noninteractive','-y',app.ref]


def restore_args(app):
    # Restoration is best effort: the original remote may no longer be available.
    return ['flatpak','install',installation_flag(app.installation),
            '--noninteractive','-y',app.origin,app.ref]


def flatpak_label(app):
    return f'{app.name} — {app.app_id} — {app.installation} — {app.ref}'


def migrate_github_appimage(release, appimage_tab, selected, run_command,
                             tracking_file=None, downloader=None, app_dir=None):
    """Download and verify first; uninstall chosen Flatpak; publish AppImage.

    On failed publication, best-effort reinstall the exact original Flatpak.
    If recovery fails, surface the failure rather than claiming a safe switch.
    """
    if not isinstance(selected, InstalledFlatpak):
        raise ValueError('Flatpak replacement must be explicitly selected')
    removed = False
    target_dir = Path(app_dir) if app_dir is not None else Path.home()/'Applications'
    destination = target_dir / _safe_filename(release['repo'], release['tag'])

    def remove_before_publish():
        nonlocal removed
        # Do not touch the existing app if the target would already collide.
        if os.path.lexists(destination):
            raise RuntimeError('Target AppImage already exists; Flatpak was not removed')
        # A selection made minutes earlier is not authority to delete a changed app.
        now = list_installed_flatpaks(run_command)
        if selected not in now:
            raise RuntimeError('Selected Flatpak changed or disappeared; nothing removed')
        ok, output, error = run_command(uninstall_args(selected), 900)
        if not ok:
            raise RuntimeError('Flatpak uninstall failed; GitHub installation cancelled: ' + str(error or output)[-650:])
        removed = True
        # Do not proceed if Flatpak still reports the exact installation.
        if selected in list_installed_flatpaks(run_command):
            raise RuntimeError('Flatpak still installed after uninstall; GitHub installation cancelled')

    def recover_failed_install(error):
        if not removed:
            return
        # If a failed post-removal verification actually found the original
        # still installed, avoid trying to reinstall it a second time.
        try:
            if selected in list_installed_flatpaks(run_command):
                return
        except (RuntimeError, ValueError):
            pass
        ok, output, problem = run_command(restore_args(selected), 900)
        if not ok:
            raise RuntimeError('GitHub installation failed and original Flatpak could not be restored. '
                               'Use the Flatpak tab to reinstall '+selected.ref+' from '+selected.origin+'. '
                               'Original error: '+str(error)+'; recovery: '+str(problem or output)[-600:]) from error

    kwargs = {'before_install':remove_before_publish,
              'on_install_failure':recover_failed_install}
    if tracking_file is not None: kwargs['tracking_file'] = tracking_file
    if downloader is not None: kwargs['downloader'] = downloader
    return install_github_appimage(release, appimage_tab, **kwargs)
