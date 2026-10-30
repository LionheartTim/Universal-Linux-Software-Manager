"""Isolated two-phase AppImage replacement tests; no network or host changes."""
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from appimage_updates import (prepare_appimage_update, replace_prepared_appimage,
                              discard_prepared)
from installed_inventory import installed_software
from online_sources import link_existing_appimage, tracked_installs, _safe_filename

REPO = 'zolaware/reblue'
TAG = 'v1.3.1'
OLD = 'reblue-1.0.0-x86_64.appimage'
NEW = _safe_filename(REPO, TAG)
DATA = b'\x7fELF' + b'\x02\x01\x01' + b'\0' * 9 + b'\x02\0\x3e\0' + b'new-appimage-fixture' * 11
RELEASE = {'repo': REPO, 'tag': TAG, 'url': 'https://github.com/zolaware/reblue/releases/tag/v1.3.1',
           'assets': [{'name':'reblue-1.3.1-x86_64.AppImage', 'size':len(DATA),
                       'browser_download_url': f'https://github.com/{REPO}/releases/download/{TAG}/reblue-1.3.1-x86_64.AppImage',
                       'digest': 'sha256:'+hashlib.sha256(DATA).hexdigest()}]}


def fake_download(asset, repo, path):
    assert repo == REPO
    Path(path).write_bytes(DATA)
    return hashlib.sha256(DATA).hexdigest()


class SafeUpdateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.appdir = root / 'Applications'
        self.appdir.mkdir()
        self.tracker = root / 'github.json'
        self.oldpath = self.appdir / OLD
        self.oldpath.write_bytes(b'original-working-reblue')
        link_existing_appimage(self.appdir, OLD, REPO, 'v1.0.0', self.tracker)
        self.desktop = root / 'app.desktop'
        self.prepared = None

    def stage(self):
        self.prepared = prepare_appimage_update(RELEASE, self.appdir, self.tracker, fake_download)
        return self.prepared

    def installer(self, file):
        (self.appdir / Path(file).name).write_bytes(Path(file).read_bytes())
        self.desktop.write_text('Exec="new"\n')

    def test_staging_does_not_modify_old_binary_or_tracking(self):
        p = self.stage()
        self.assertTrue(p.stage_file.is_file())
        self.assertEqual(self.oldpath.read_bytes(),b'original-working-reblue')
        self.assertFalse((self.appdir/NEW).exists())
        self.assertEqual(tracked_installs(self.tracker)[REPO]['tag'],'v1.0.0')
        discard_prepared(p)
        self.assertFalse(p.stage_dir.exists())

    def test_yes_replaces_binary_only_after_successful_new_install(self):
        p = self.stage()
        trace=[]
        def do_install(file):
            trace.append((self.oldpath.read_bytes(),tracked_installs(self.tracker)[REPO]['tag']))
            self.installer(file)
        result = replace_prepared_appimage(p, None, self.tracker, self.desktop, do_install)
        self.assertEqual(result, NEW)
        self.assertEqual(trace,[(b'original-working-reblue','v1.0.0')])
        self.assertEqual((self.appdir/NEW).read_bytes(),DATA)
        self.assertFalse(os.path.lexists(self.oldpath))
        self.assertEqual(tracked_installs(self.tracker)[REPO]['file'],NEW)
        self.assertEqual(tracked_installs(self.tracker)[REPO]['tag'],TAG)
        self.assertFalse(p.stage_dir.exists())
        self.assertTrue(self.desktop.exists())

    def test_old_shortcut_alias_is_not_counted_as_second_install(self):
        p=self.stage()
        replace_prepared_appimage(p,None,self.tracker,self.desktop,self.installer)
        rows,_=installed_software(lambda argv,limit:(False,'','absent'),lambda k:None,
                                 self.appdir,tracked_installs(self.tracker))
        apps=[r for r in rows if r['kind']=='AppImage']
        self.assertEqual(len(apps),1)
        self.assertEqual(apps[0]['id'],NEW)
        self.assertEqual(apps[0]['github_repo'],REPO)

    def test_no_discards_download_without_installing(self):
        p=self.stage()
        discard_prepared(p)
        self.assertEqual(self.oldpath.read_bytes(),b'original-working-reblue')
        self.assertFalse((self.appdir/NEW).exists())
        self.assertEqual(tracked_installs(self.tracker)[REPO]['file'],OLD)
        self.assertFalse(p.stage_dir.exists())

    def test_downloader_failure_leaves_old_intact_and_no_temp(self):
        def failed_download(*args):
            raise OSError('download failed')
        with self.assertRaises(OSError):
            prepare_appimage_update(RELEASE,self.appdir,self.tracker,failed_download)
        self.assertEqual(self.oldpath.read_bytes(),b'original-working-reblue')
        self.assertEqual([p for p in self.appdir.iterdir() if p.name.startswith('.ulsm-update-')],[])

    def test_corrupt_download_fails_before_confirmation(self):
        def wrong_data(asset,repo,path):
            Path(path).write_bytes(b'wrong')
            return hashlib.sha256(b'wrong').hexdigest()
        with self.assertRaises(ValueError):
            prepare_appimage_update(RELEASE,self.appdir,self.tracker,wrong_data)
        self.assertEqual(self.oldpath.read_bytes(),b'original-working-reblue')

    def test_installer_failure_restores_old_and_tracking(self):
        p=self.stage()
        def crash(file):
            self.installer(file)
            raise RuntimeError('publisher failed')
        with self.assertRaisesRegex(RuntimeError,'publisher failed'):
            replace_prepared_appimage(p,None,self.tracker,self.desktop,crash)
        self.assertEqual(self.oldpath.read_bytes(),b'original-working-reblue')
        self.assertFalse(os.path.lexists(self.appdir/NEW))
        self.assertFalse(self.desktop.exists())
        self.assertEqual(tracked_installs(self.tracker)[REPO]['file'],OLD)

    def test_changed_old_file_during_download_cancels(self):
        def changing(asset,repo,path):
            result=fake_download(asset,repo,path)
            self.oldpath.write_bytes(b'user changed the original')
            return result
        with self.assertRaisesRegex(ValueError,'changed during download'):
            prepare_appimage_update(RELEASE,self.appdir,self.tracker,changing)
        self.assertEqual(self.oldpath.read_bytes(),b'user changed the original')

    def test_changed_old_file_after_download_cancels_safely(self):
        p=self.stage()
        self.oldpath.write_bytes(b'new user modifications')
        with self.assertRaisesRegex(ValueError,'changed'):
            replace_prepared_appimage(p,None,self.tracker,self.desktop,self.installer)
        self.assertEqual(self.oldpath.read_bytes(),b'new user modifications')
        self.assertEqual(tracked_installs(self.tracker)[REPO]['file'],OLD)

    def test_tracking_changed_after_download_blocks_update(self):
        p=self.stage()
        link = tracked_installs(self.tracker)
        link[REPO]['tag']='v1.1.0'
        from online_sources import save_tracked
        save_tracked(link,self.tracker)
        with self.assertRaisesRegex(ValueError,'changed'):
            replace_prepared_appimage(p,None,self.tracker,self.desktop,self.installer)
        self.assertEqual(self.oldpath.read_bytes(),b'original-working-reblue')
        self.assertEqual(tracked_installs(self.tracker)[REPO]['tag'],'v1.1.0')

    def test_refuse_existing_new_binary(self):
        (self.appdir/NEW).write_bytes(b'existing')
        with self.assertRaisesRegex(ValueError,'already exists'):
            self.stage()
        self.assertEqual((self.appdir/NEW).read_bytes(),b'existing')
        self.assertEqual(self.oldpath.read_bytes(),b'original-working-reblue')

    def test_refuse_existing_new_launcher(self):
        p=self.stage()
        self.desktop.write_text('another program')
        with self.assertRaisesRegex(ValueError,'shortcut already exists'):
            replace_prepared_appimage(p,None,self.tracker,self.desktop,self.installer)
        self.assertEqual(self.desktop.read_text(),'another program')
        self.assertEqual(self.oldpath.read_bytes(),b'original-working-reblue')

    def test_registry_failure_rolls_back_new_and_keeps_old(self):
        p=self.stage()
        with patch('appimage_updates.save_tracked', side_effect=OSError('registry write failed')):
            with self.assertRaisesRegex(OSError,'registry write failed'):
                replace_prepared_appimage(p,None,self.tracker,self.desktop,self.installer)
        self.assertEqual(self.oldpath.read_bytes(),b'original-working-reblue')
        self.assertFalse((self.appdir/NEW).exists())
        self.assertFalse(self.desktop.exists())
        self.assertEqual(tracked_installs(self.tracker)[REPO]['file'],OLD)

    def test_shared_removal_failure_rolls_back_old_and_new(self):
        p=self.stage()
        from appimage_lifecycle import remove_managed_appimage
        original_replace=os.replace
        def fail_move(src,dst):
            if Path(src) == self.oldpath and str(dst).endswith('retired-0'):
                raise OSError('cannot retire old AppImage')
            return original_replace(src,dst)
        with patch('appimage_lifecycle.os.replace', side_effect=fail_move):
            with self.assertRaisesRegex(OSError,'cannot retire old AppImage'):
                replace_prepared_appimage(p,None,self.tracker,self.desktop,self.installer)
        self.assertEqual(self.oldpath.read_bytes(),b'original-working-reblue')
        self.assertEqual(tracked_installs(self.tracker)[REPO]['file'],OLD)
        self.assertFalse((self.appdir/NEW).exists())
        self.assertFalse(self.desktop.exists())

    def test_managed_old_launcher_is_removed_after_success(self):
        from appimage_lifecycle import remove_managed_appimage
        old_launcher=self.appdir.parent/'old.desktop'
        old_launcher.write_text('Exec=old AppImage\n')
        p=self.stage()
        class Tab:
            def appimage_install(_, staged):
                self.installer(staged)
            def remove_appimage_managed(_, name, recovery_dir=None):
                return remove_managed_appimage(self.appdir, name, [old_launcher],
                                               recovery_dir=recovery_dir)
        replace_prepared_appimage(p, Tab(), self.tracker, self.desktop)
        self.assertFalse(os.path.lexists(self.oldpath))
        self.assertFalse(old_launcher.exists())
        self.assertTrue(self.desktop.is_file())
        self.assertTrue((self.appdir/NEW).is_file())
        self.assertEqual(tracked_installs(self.tracker)[REPO]['tag'],TAG)

    def test_old_launcher_retire_error_restores_old_and_rolls_back_new(self):
        from appimage_lifecycle import remove_managed_appimage
        old_launcher=self.appdir.parent/'old.desktop'
        old_launcher.write_text('Exec=old AppImage\n')
        p=self.stage()
        class Tab:
            def appimage_install(_, staged):
                self.installer(staged)
            def remove_appimage_managed(_, name, recovery_dir=None):
                return remove_managed_appimage(self.appdir,name,[old_launcher],
                                               recovery_dir=recovery_dir)
        original_replace=os.replace
        def fail_launcher(src,dst):
            if Path(src) == old_launcher:
                raise OSError('cannot retire old launcher')
            return original_replace(src,dst)
        with patch('appimage_lifecycle.os.replace',side_effect=fail_launcher):
            with self.assertRaisesRegex(OSError,'cannot retire old launcher'):
                replace_prepared_appimage(p,Tab(),self.tracker,self.desktop)
        self.assertTrue(old_launcher.exists())
        self.assertEqual(self.oldpath.read_bytes(),b'original-working-reblue')
        self.assertFalse((self.appdir/NEW).exists())
        self.assertFalse(self.desktop.exists())
        self.assertEqual(tracked_installs(self.tracker)[REPO]['tag'],'v1.0.0')

    def test_safe_removal_of_leftover_symlink_preserves_new_target(self):
        from appimage_lifecycle import remove_managed_appimage
        target=self.appdir/NEW
        target.write_bytes(DATA)
        self.oldpath.unlink()
        self.oldpath.symlink_to(target.name)
        old_launcher=self.appdir.parent/'old.desktop'
        old_launcher.write_text('Exec=old AppImage\n')
        remove_managed_appimage(self.appdir, OLD, [old_launcher],
                                allow_local_alias=True)
        self.assertFalse(os.path.lexists(self.oldpath))
        self.assertFalse(old_launcher.exists())
        self.assertEqual(target.read_bytes(),DATA)

    def test_never_remove_external_symlink_target(self):
        from appimage_lifecycle import remove_managed_appimage
        target=self.appdir.parent/'other.AppImage'
        target.write_bytes(b'external-image')
        self.oldpath.unlink()
        self.oldpath.symlink_to(target)
        with self.assertRaises(ValueError):
            remove_managed_appimage(self.appdir, OLD, [], allow_local_alias=True)
        self.assertEqual(target.read_bytes(),b'external-image')
        self.assertTrue(self.oldpath.is_symlink())

    def test_versioned_removal_backend_routed_from_package_tab(self):
        code=(Path(__file__).resolve().parents[1]/'main.py').read_text()
        self.assertIn('def remove_appimage_managed(self, filename, recovery_dir=None)',code)
        self.assertIn('self.remove_appimage_managed(name)',code)
        self.assertIn('prepared.old_name, recovery_dir=prepared.stage_dir',
                      (Path(__file__).resolve().parents[1]/'appimage_updates.py').read_text())

    def test_no_downgrade_or_reinstall_same_release(self):
        for tag in ('v1.0.0','v0.9.0'):
            with self.subTest(tag=tag),self.assertRaisesRegex(ValueError,'not a verified newer'):
                prepare_appimage_update({**RELEASE,'tag':tag},self.appdir,self.tracker,fake_download)

    def test_ui_has_download_before_confirmation_and_no_legacy_keep_old(self):
        root=Path(__file__).resolve().parents[1]
        code=(root/'main.py').read_text()
        section=code[code.index('    def update_selected(self):',code.index('class UpdatesPanel')):]
        self.assertIn('prepare_appimage_update(release, APP_DIR)',section)
        self.assertIn('ask_to_replace',section)
        self.assertIn('replace_prepared_appimage(',section)
        self.assertIn('QMessageBox.StandardButton.No',section)
        self.assertIn('discard_prepared(prepared)',section)


if __name__ == '__main__':
    unittest.main()
