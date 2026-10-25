"""Shared, conservative lifecycle operations for locally managed AppImages.

Called by both the AppImage package tab and the Updates coordinator.  Removing
an AppImage never follows a symbolic link to unlink its target. During an
update, old files/managed launchers are first moved into a private recovery
folder. If subsequent steps fail, the old installation can be restored.
"""
import errno
import os
from pathlib import Path
import shutil
import stat
import tempfile


def _checked_path(app_dir, filename, *, allow_local_alias=False):
    app_dir = Path(app_dir)
    if app_dir.is_symlink() or not app_dir.is_dir():
        raise ValueError('Unsafe AppImage directory')
    if (not isinstance(filename, str) or Path(filename).name != filename
            or filename.startswith('.') or not filename.lower().endswith('.appimage')):
        raise ValueError('Invalid AppImage filename')
    path = app_dir / filename
    info = path.lstat()
    if stat.S_ISREG(info.st_mode):
        return path
    if allow_local_alias and stat.S_ISLNK(info.st_mode):
        # Old builds left aliases to an upgraded image.  Unlink ONLY the
        # alias, and only if it resolves to a local, regular AppImage.
        target = path.resolve(strict=True)
        if (target.parent == app_dir.resolve() and target != path
                and target.name.lower().endswith('.appimage')
                and target.is_file() and not target.is_symlink()):
            return path
    raise ValueError('AppImage is not a safe local file or verified local alias')


def _checked_launchers(launchers):
    unique = []
    for launcher in launchers:
        path = Path(launcher)
        if path in unique:
            continue
        if path.suffix != '.desktop':
            raise ValueError('Unsafe desktop shortcut path')
        try:
            kind = path.lstat().st_mode
        except FileNotFoundError:
            continue
        # Moving/unlinking a launcher symlink does not follow its target.
        if not (stat.S_ISREG(kind) or stat.S_ISLNK(kind)):
            raise ValueError('Unsupported desktop shortcut type')
        unique.append(path)
    return unique


def retire_managed_appimage(app_dir, filename, launchers, recovery_dir,
                            *, allow_local_alias=False):
    """Move the named AppImage and its exact managed shortcuts to recovery.

    Returns a list of (recovery, original) pairs; caller MUST restore the
    list on failure. The old executable is never discarded by this function.
    """
    path = _checked_path(app_dir, filename, allow_local_alias=allow_local_alias)
    recovery_dir = Path(recovery_dir)
    if recovery_dir.is_symlink() or not recovery_dir.is_dir():
        raise ValueError('Unsafe AppImage recovery directory')
    # The caller generates a private recovery directory within Applications.
    if recovery_dir.parent != Path(app_dir):
        raise ValueError('Recovery directory must be inside Applications')
    paths = [path] + _checked_launchers(launchers)
    moved = []
    try:
        for i, source in enumerate(paths):
            backup = recovery_dir / ('retired-%d' % i)
            if os.path.lexists(backup):
                raise ValueError('Recovery file already exists')
            try:
                os.replace(source, backup)
            except OSError as exc:
                if exc.errno != errno.EXDEV:
                    raise
                # Bazzite may mount ~/.local/share/applications and
                # ~/Applications on different filesystems.  A rename to the
                # central recovery folder fails with EXDEV.  Retire the
                # launcher atomically into a private *sibling* directory on
                # the source filesystem instead, so rollback is also a rename.
                sibling_dir = Path(tempfile.mkdtemp(
                    prefix='.ulsm-retired-', dir=source.parent))
                sibling_backup = sibling_dir / ('retired-%d' % i)
                try:
                    os.replace(source, sibling_backup)
                except BaseException:
                    sibling_dir.rmdir()
                    raise
                backup = sibling_backup
            moved.append((backup, source))
        return moved
    except BaseException:
        try:
            restore_retired_appimage(moved)
        except BaseException as recovery_error:
            raise RuntimeError('AppImage recovery required in ' + str(recovery_dir)) from recovery_error
        raise


def _prune_sibling_backup(backup):
    """Remove only the empty, private sibling directory we created."""
    parent = Path(backup).parent
    if parent.name.startswith('.ulsm-retired-') and parent.is_dir() and not parent.is_symlink():
        parent.rmdir()  # Refuse to remove a folder containing unexpected files.


def restore_retired_appimage(moved):
    """Undo retirement in reverse order; never overwrite unexpected files."""
    for backup, destination in reversed(moved):
        if os.path.lexists(destination):
            raise RuntimeError('Cannot restore AppImage: destination now exists: ' + str(destination))
        os.replace(backup, destination)
        _prune_sibling_backup(backup)


def finalize_retired_appimage(moved):
    """Discard verified retired files after the update is committed.

    Called only when a new AppImage is installed and registered successfully.
    Works for recovery copies on multiple distinct filesystems.
    """
    for backup, _ in reversed(moved):
        if os.path.lexists(backup):
            Path(backup).unlink()  # A symlink is unlinked, never followed.
        _prune_sibling_backup(backup)


def remove_managed_appimage(app_dir, filename, launchers, *,
                            recovery_dir=None, allow_local_alias=False):
    """The same removal backend is used by Uninstall and post-update cleanup.

    If recovery_dir is given, return moved files for commit/rollback by Updates.
    Otherwise delete a private quarantine after moving the chosen installation.
    """
    if recovery_dir is not None:
        return retire_managed_appimage(app_dir, filename, launchers, recovery_dir,
                                      allow_local_alias=allow_local_alias)
    folder = Path(tempfile.mkdtemp(prefix='.ulsm-remove-', dir=app_dir))
    succeeded = False
    try:
        retired = retire_managed_appimage(app_dir, filename, launchers, folder,
                                          allow_local_alias=allow_local_alias)
        finalize_retired_appimage(retired)
        succeeded = True
    finally:
        # Never discard recovery files if an unexpected rollback failure left
        # any files in the quarantine folder.
        if succeeded or not any(folder.iterdir()):
            shutil.rmtree(folder, ignore_errors=True)
