"""Two-phase, explicitly confirmed updates for already installed GitHub AppImages.

Phase 1 downloads and verifies to private staging without touching the old
AppImage. Phase 2 is triggered only after a GUI-thread confirmation. After
publishing a verified new AppImage, the same managed removal backend used by
the AppImage tab retires the old executable and managed shortcuts. Any failure
before commit restores the old installation and removes the new one.
"""
from dataclasses import dataclass
from appimage_lifecycle import (retire_managed_appimage, restore_retired_appimage,
                                finalize_retired_appimage)
import hashlib
import os
from pathlib import Path
import shutil
import stat
import tempfile

from online_sources import (TRACKING_FILE, choose_appimage, download_appimage,
                            _safe_filename, save_tracked, semver_tuple, tracked_installs)


def _fingerprint(path):
    p = Path(path)
    info = p.lstat()
    if not stat.S_ISREG(info.st_mode) or p.is_symlink():
        raise ValueError('AppImage must be a regular file, not a link')
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for data in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(data)
    return digest.hexdigest()


@dataclass(frozen=True)
class PreparedAppImageUpdate:
    repo: str
    old_name: str
    old_tag: str
    old_fingerprint: tuple
    new_name: str
    new_tag: str
    sha256: str
    stage_dir: Path
    stage_file: Path
    app_dir: Path


def discard_prepared(prepared):
    """Cancel without touching the installed software."""
    shutil.rmtree(prepared.stage_dir, ignore_errors=True)


def prepare_appimage_update(release, app_dir, tracking_file=TRACKING_FILE,
                            downloader=None):
    """Download/verify first; no changes to an existing installation."""
    app_dir = Path(app_dir)
    if app_dir.is_symlink() or not app_dir.is_dir():
        raise ValueError('Installed AppImage directory is missing or unsafe')
    repo = release.get('repo')
    current = tracked_installs(tracking_file).get(repo)
    if not current:
        raise ValueError('The installed AppImage is not linked to this GitHub repository')
    old_name, old_tag = current['file'], current['tag']
    old_path = app_dir / old_name
    fingerprint = _fingerprint(old_path)
    old_version, new_version = semver_tuple(old_tag), semver_tuple(release.get('tag'))
    if not old_version or not new_version or new_version + (0,) * (4-len(new_version)) <= old_version + (0,) * (4-len(old_version)):
        raise ValueError('Release is not a verified newer numeric version')
    asset = choose_appimage(release)
    if asset is None:
        raise ValueError('No unambiguous compatible direct AppImage is available')
    new_name = _safe_filename(repo, release['tag'])
    if new_name == old_name or os.path.lexists(app_dir / new_name):
        raise ValueError('The new AppImage filename already exists')
    stage_dir = Path(tempfile.mkdtemp(prefix='.ulsm-update-', dir=app_dir))
    stage_file = stage_dir / new_name
    try:
        reported_sha = (downloader or download_appimage)(asset, repo, stage_file)
        info = stage_file.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_size != asset['size'] or
                not isinstance(reported_sha, str) or
                _hash(stage_file) != reported_sha.lower()):
            raise ValueError('Staged AppImage verification failed')
        # Download helper also checks ELF format and CPU architecture. Re-check
        # the file signature in case a custom downloader has been substituted.
        with stage_file.open('rb') as stream:
            if stream.read(4) != b'\x7fELF':
                raise ValueError('Downloaded asset is not an ELF AppImage')
        digest = asset.get('digest', '')
        if isinstance(digest, str) and digest.startswith('sha256:') and digest[7:].lower() != reported_sha.lower():
            raise ValueError('GitHub published checksum does not match')
        # The original must remain unchanged even while the download occurs.
        if _fingerprint(old_path) != fingerprint:
            raise ValueError('Installed AppImage changed during download')
        return PreparedAppImageUpdate(repo, old_name, old_tag, fingerprint,
                                      new_name, release['tag'], reported_sha.lower(),
                                      stage_dir, stage_file, app_dir)
    except BaseException:
        shutil.rmtree(stage_dir, ignore_errors=True)
        raise


def replace_prepared_appimage(prepared, appimage_tab, tracking_file=TRACKING_FILE,
                              launcher_path=None, installer=None, old_launchers=()):
    """Commit an update through the AppImage tab's *shared* removal backend.

    The new binary and launcher must be installed and validated first. The old
    binary and exact managed launchers are moved to private recovery storage;
    no compatibility symlink or duplicate start menu entry is created.
    """
    old_path = prepared.app_dir / prepared.old_name
    new_path = prepared.app_dir / prepared.new_name
    new_launcher = Path(launcher_path) if launcher_path is not None else None
    registry = tracked_installs(tracking_file)
    recorded = registry.get(prepared.repo)
    if not recorded or recorded['file'] != prepared.old_name or recorded['tag'] != prepared.old_tag:
        discard_prepared(prepared)
        raise ValueError('Linked GitHub installation has changed; update cancelled')
    if new_launcher is not None and os.path.lexists(new_launcher):
        discard_prepared(prepared)
        raise ValueError('New desktop shortcut already exists')
    installed_new = False
    registry_changed = False
    retired = []
    committed = False
    keep_recovery = False
    try:
        if (prepared.app_dir.is_symlink() or
                _fingerprint(old_path) != prepared.old_fingerprint or
                os.path.lexists(new_path)):
            raise ValueError('Installed AppImage changed or target already exists')
        if (not prepared.stage_file.is_file() or prepared.stage_file.is_symlink()
                or _hash(prepared.stage_file) != prepared.sha256):
            raise ValueError('Staged AppImage has changed')
        # Reuse the exact AppImage tab install backend.
        (installer or appimage_tab.appimage_install)(prepared.stage_file)
        installed_new = True
        if not new_path.is_file() or new_path.is_symlink() or _hash(new_path) != prepared.sha256:
            raise ValueError('Published AppImage checksum mismatch')
        if (_fingerprint(old_path) != prepared.old_fingerprint or
                tracked_installs(tracking_file).get(prepared.repo) != recorded):
            raise ValueError('Old installation or tracking changed while installing')
        # Reuse AppImage tab's shared, safe remove backend. Files are MOVED,
        # not destroyed, until the registry has been committed successfully.
        if appimage_tab is not None:
            retired = appimage_tab.remove_appimage_managed(
                prepared.old_name, recovery_dir=prepared.stage_dir)
        else:
            retired = retire_managed_appimage(
                prepared.app_dir, prepared.old_name, old_launchers,
                prepared.stage_dir)
        registry[prepared.repo] = {
            'file': prepared.new_name, 'tag': prepared.new_tag,
            'sha256': prepared.sha256}
        save_tracked(registry, tracking_file)
        registry_changed = True
        # Verify the old name and tracked version are no longer installed.
        if os.path.lexists(old_path) or not new_path.is_file():
            raise RuntimeError('Old AppImage still exists or new AppImage is missing')
        committed = True
        # Cross-filesystem launcher backups live beside their original
        # .desktop files, NOT inside prepared.stage_dir.  Remove those only
        # after the new installation and registry have committed.
        finalize_retired_appimage(retired)
        return prepared.new_name
    except BaseException:
        if not committed:
            # A failed partial retirement might have stranded backups even if
            # it could not return a normal retirement manifest.
            if any(prepared.stage_dir.glob('retired-*')) and not retired:
                keep_recovery = True
                raise RuntimeError('AppImage recovery required in ' + str(prepared.stage_dir))
            try:
                if retired:
                    restore_retired_appimage(retired)
            except BaseException as exc:
                # Never discard recovery copies when restoration failed.
                keep_recovery = True
                raise RuntimeError('AppImage rollback needs manual recovery from ' +
                                   str(prepared.stage_dir)) from exc
            if registry_changed or tracked_installs(tracking_file).get(prepared.repo) != recorded:
                rollback = tracked_installs(tracking_file)
                rollback[prepared.repo] = recorded
                try:
                    save_tracked(rollback, tracking_file)
                except OSError:
                    keep_recovery = True
                    raise RuntimeError('AppImage record rollback failed; verify ' +
                                       str(tracking_file))
            if installed_new or os.path.lexists(new_path):
                if os.path.lexists(new_path):
                    new_path.unlink()
                if new_launcher is not None and os.path.lexists(new_launcher):
                    new_launcher.unlink()
        raise
    finally:
        if not keep_recovery:
            discard_prepared(prepared)
