"""Regression for missing AppImage files leaving stale GitHub registrations."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from online_sources import (link_existing_appimage, tracked_installs,
                            prune_missing_tracked_appimages, forget_removed_appimage,
                            github_updates)

REPO='zolaware/reblue'

class StaleGitHubLinksTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.apps=Path(self.tmp.name)/'Applications';self.apps.mkdir()
        self.tracker=Path(self.tmp.name)/'registry.json'

    def add(self, filename):
        (self.apps/filename).write_bytes(b'AppImage fixture')

    def test_removed_reblue_131_does_not_block_new_reblue_100(self):
        old='zolaware-reblue__v1.3.1.AppImage'
        new='reblue-1.0.0-x86_64.appimage'
        self.add(old)
        link_existing_appimage(self.apps,old,REPO,'v1.3.1',self.tracker)
        (self.apps/old).unlink()
        self.add(new)
        self.assertEqual(link_existing_appimage(self.apps,new,REPO,'v1.0.0',self.tracker), REPO)
        self.assertEqual(tracked_installs(self.tracker)[REPO]['file'],new)
        self.assertEqual(tracked_installs(self.tracker)[REPO]['tag'],'v1.0.0')

    def test_existing_different_installed_file_must_still_block(self):
        self.add('original.AppImage');self.add('other.AppImage')
        link_existing_appimage(self.apps,'original.AppImage',REPO,'v1.0.0',self.tracker)
        with self.assertRaisesRegex(ValueError,'already linked'):
            link_existing_appimage(self.apps,'other.AppImage',REPO,'v1.0.0',self.tracker)

    def test_prune_preserves_other_live_repositories(self):
        self.add('old.AppImage');self.add('live.AppImage')
        link_existing_appimage(self.apps,'old.AppImage',REPO,'v1.0.0',self.tracker)
        link_existing_appimage(self.apps,'live.AppImage','other/tool','v2.0',self.tracker)
        (self.apps/'old.AppImage').unlink()
        result=prune_missing_tracked_appimages(self.apps,self.tracker)
        self.assertNotIn(REPO,result)
        self.assertIn('other/tool',result)
        self.assertEqual(tracked_installs(self.tracker),result)

    def test_missing_or_inaccessible_app_dir_never_erases_data(self):
        self.add('old.AppImage')
        link_existing_appimage(self.apps,'old.AppImage',REPO,'v1.0.0',self.tracker)
        rename=self.apps.with_name('not-mounted')
        self.apps.rename(rename)
        self.assertIn(REPO,prune_missing_tracked_appimages(self.apps,self.tracker))
        self.assertIn(REPO,tracked_installs(self.tracker))

    def test_broken_symlink_is_not_automatically_untracked(self):
        self.add('old.AppImage')
        link_existing_appimage(self.apps,'old.AppImage',REPO,'v1.0.0',self.tracker)
        (self.apps/'old.AppImage').unlink()
        (self.apps/'old.AppImage').symlink_to('missing.AppImage')
        self.assertIn(REPO,prune_missing_tracked_appimages(self.apps,self.tracker))

    def test_direct_uninstall_drops_only_exact_file_mapping(self):
        self.add('old.AppImage');self.add('live.AppImage')
        link_existing_appimage(self.apps,'old.AppImage',REPO,'v1.0.0',self.tracker)
        link_existing_appimage(self.apps,'live.AppImage','other/tool','v2.0',self.tracker)
        with self.assertRaisesRegex(ValueError,'still exists'):
            forget_removed_appimage(self.apps,'old.AppImage',self.tracker)
        self.assertIn(REPO,tracked_installs(self.tracker))
        (self.apps/'old.AppImage').unlink()
        self.assertEqual(forget_removed_appimage(self.apps,'old.AppImage',self.tracker),1)
        self.assertEqual(set(tracked_installs(self.tracker)),{'other/tool'})

    def test_update_scan_prunes_missing_file_without_network_access(self):
        self.add('old.AppImage')
        link_existing_appimage(self.apps,'old.AppImage',REPO,'v1.0.0',self.tracker)
        (self.apps/'old.AppImage').unlink()
        hits, notes=github_updates(self.apps,fetch=lambda u:self.fail('should not network'), tracking_file=self.tracker)
        self.assertEqual(hits,[])
        self.assertEqual(notes,[])
        self.assertEqual(tracked_installs(self.tracker),{})

    def test_uninstall_gui_uses_registry_cleanup_only_after_uninstall(self):
        code=(Path(__file__).resolve().parents[1]/'main.py').read_text()
        section=code[code.index('    def remove_appimage_managed'):code.index('    def remove_selected')]
        self.assertIn('result = remove_managed_appimage(',section)
        self.assertIn('if recovery_dir is None:',section)
        self.assertLess(section.index('result = remove_managed_appimage('),
                        section.index('forget_removed_appimage(APP_DIR, filename)'))
        self.assertIn('prune_missing_tracked_appimages(APP_DIR)',code)

if __name__=='__main__':unittest.main()
