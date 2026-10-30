"""Regression for Bazzite / KDE launchers on another filesystem (Errno 18)."""
import errno
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import test_safe_appimage_update as baseline
from test_safe_appimage_update import NEW, OLD, REPO, TAG, DATA
from appimage_lifecycle import remove_managed_appimage
from appimage_updates import replace_prepared_appimage
from online_sources import tracked_installs


class CrossDeviceRemovalTest(unittest.TestCase):
    """Reuse isolated fixture helpers, not the parent's test methods."""

    def setUp(self):
        baseline.SafeUpdateTest.setUp(self)

    def stage(self):
        return baseline.SafeUpdateTest.stage(self)

    def installer(self, file):
        return baseline.SafeUpdateTest.installer(self, file)

    def _broken_cross_device_move(self, launcher, *, fail_second_move=False):
        real_replace = os.replace
        def simulate(src, dst):
            src, dst = Path(src), Path(dst)
            if src == launcher and dst.parent != launcher.parent:
                if fail_second_move and dst.parent.name.startswith('.ulsm-retired-'):
                    raise OSError(errno.EACCES, 'permission denied')
                if not dst.parent.name.startswith('.ulsm-retired-'):
                    raise OSError(errno.EXDEV, 'Invalid cross-device link')
            return real_replace(src, dst)
        return simulate

    def _assert_no_launcher_backups(self):
        self.assertFalse(list(self.desktop.parent.glob('.ulsm-retired-*')))

    def test_direct_uninstall_across_device_removes_old_launcher(self):
        previous_launcher=self.desktop.parent/'previous.desktop'
        previous_launcher.write_text('Exec=old\n')
        with patch('appimage_lifecycle.os.replace', side_effect=self._broken_cross_device_move(previous_launcher)):
            remove_managed_appimage(self.appdir, OLD, [previous_launcher])
        self.assertFalse(os.path.lexists(self.oldpath))
        self.assertFalse(previous_launcher.exists())
        self._assert_no_launcher_backups()
        self.assertFalse(list(self.appdir.glob('.ulsm-remove-*')))

    def test_cross_device_uninstall_removes_alias_but_not_target(self):
        new_path=self.appdir/NEW
        new_path.write_bytes(DATA)
        self.oldpath.unlink()
        self.oldpath.symlink_to(NEW)
        previous_launcher=self.desktop.parent/'previous.desktop'
        previous_launcher.write_text('Exec=old\n')
        with patch('appimage_lifecycle.os.replace', side_effect=self._broken_cross_device_move(previous_launcher)):
            remove_managed_appimage(self.appdir, OLD, [previous_launcher], allow_local_alias=True)
        self.assertFalse(os.path.lexists(self.oldpath))
        self.assertFalse(previous_launcher.exists())
        self.assertEqual(new_path.read_bytes(), DATA)
        self._assert_no_launcher_backups()

    def test_update_across_device_removes_old_launcher_and_binary(self):
        previous_launcher=self.desktop.parent/'previous.desktop'
        previous_launcher.write_text('Exec=old\n')
        p=self.stage()
        class Tab:
            def appimage_install(_, staged): self.installer(staged)
            def remove_appimage_managed(_, name, recovery_dir=None):
                return remove_managed_appimage(self.appdir, name, [previous_launcher], recovery_dir=recovery_dir)
        with patch('appimage_lifecycle.os.replace', side_effect=self._broken_cross_device_move(previous_launcher)):
            replace_prepared_appimage(p, Tab(), self.tracker, self.desktop)
        self.assertFalse(os.path.lexists(self.oldpath))
        self.assertFalse(previous_launcher.exists())
        self.assertEqual((self.appdir/NEW).read_bytes(), DATA)
        self.assertTrue(self.desktop.is_file())
        self.assertEqual(tracked_installs(self.tracker)[REPO]['tag'], TAG)
        self._assert_no_launcher_backups()

    def test_registry_error_across_device_restores_old_and_shortcut(self):
        previous_launcher=self.desktop.parent/'previous.desktop'
        previous_launcher.write_text('Exec=old\n')
        p=self.stage()
        class Tab:
            def appimage_install(_, staged): self.installer(staged)
            def remove_appimage_managed(_, name, recovery_dir=None):
                return remove_managed_appimage(self.appdir, name, [previous_launcher], recovery_dir=recovery_dir)
        with patch('appimage_lifecycle.os.replace', side_effect=self._broken_cross_device_move(previous_launcher)):
            with patch('appimage_updates.save_tracked', side_effect=OSError('save registry failed')):
                try:
                    replace_prepared_appimage(p, Tab(), self.tracker, self.desktop)
                except OSError as error:
                    assert str(error) == 'save registry failed'
                else:
                    self.fail('Expected simulated save failure')
        self.assertEqual(self.oldpath.read_bytes(), b'original-working-reblue')
        self.assertEqual(previous_launcher.read_text(), 'Exec=old\n')
        self.assertFalse((self.appdir/NEW).exists())
        self.assertFalse(self.desktop.exists())
        self.assertEqual(tracked_installs(self.tracker)[REPO]['tag'], 'v1.0.0')
        self._assert_no_launcher_backups()

    def test_failed_fallback_restores_old_without_losing_shortcut(self):
        previous_launcher=self.desktop.parent/'previous.desktop'
        previous_launcher.write_text('Exec=old\n')
        with patch('appimage_lifecycle.os.replace', side_effect=self._broken_cross_device_move(previous_launcher, fail_second_move=True)):
            with self.assertRaises(OSError):
                remove_managed_appimage(self.appdir, OLD, [previous_launcher])
        self.assertEqual(self.oldpath.read_bytes(), b'original-working-reblue')
        self.assertEqual(previous_launcher.read_text(), 'Exec=old\n')
        self._assert_no_launcher_backups()
