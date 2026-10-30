"""GNOME settings backup/restore tests, without running host GNOME or dconf."""
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from local_file_backup import create_backup as make_bu, extract_settings as extract_nested, inspect_backup as inspect_bu
from universal_backup import DCONF, make_backup, inspect_backup, restore_settings


class GNOMEDesktopRestoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / 'home'
        self.home.mkdir()
        self.backup = Path(self.tmp.name) / 'settings.zip'
        self.bu = Path(self.tmp.name) / 'archive.bu'

    def runner(self, keys=None):
        keys = keys or {}
        def run(args, timeout):
            if args[:2] == ['dconf','dump']:
                return True, keys.get(args[2],''), ''
            return False,'','unexpected command'
        return run

    def test_gnome_panels_appearance_window_power_saved_and_applied(self):
        overrides = {
            '/org/gnome/shell/': '[org/gnome/shell]\nfavorite-apps=[\'org.gnome.Nautilus.desktop\']\n',
            '/org/gnome/desktop/interface/': '[org/gnome/desktop/interface]\ncolor-scheme=\'prefer-dark\'\n',
            '/org/gnome/desktop/background/': '[org/gnome/desktop/background]\npicture-uri=\'file:///tmp/wall.jpg\'\n',
            '/org/gnome/desktop/wm/preferences/': "[org/gnome/desktop/wm/preferences]\nbutton-layout=':minimize,maximize,close'\n",
            '/org/gnome/settings-daemon/plugins/power/': '[org/gnome/settings-daemon/plugins/power]\nsleep-inactive-ac-type=\'nothing\'\n',
        }
        manifest=make_backup(self.home,self.backup,{'panels','appearance','power'},desktop='gnome',run=self.runner(overrides))
        self.assertEqual(manifest['desktop'],'gnome')
        self.assertEqual(len(manifest['dconf']),len(overrides))
        self.assertNotIn('panels',manifest['empty_categories'])
        old={prefix: 'previous '+str(i) for i,prefix in enumerate(overrides)}
        restored={}
        def loader(prefix,data):
            restored[prefix]=data
            return True
        recovery=restore_settings(self.home,self.backup,{'panels','appearance','power'},'gnome',loader,dconf_run=self.runner(old))
        self.assertEqual(restored,overrides)
        stored=list((recovery/'dconf-before-restore').glob('*.ini'))
        self.assertEqual(len(stored),len(overrides))
        self.assertTrue(all(x.stat().st_mode & 0o777 == 0o600 for x in stored))

    def test_dconf_command_failure_aborts_new_backup_without_clobbering_existing(self):
        self.backup.write_bytes(b'OLDER BACKUP')
        def broken(args,timeout):
            return False,'','dconf: command not found'
        with self.assertRaisesRegex(RuntimeError,'dconf: command not found'):
            make_backup(self.home,self.backup,{'appearance'},desktop='gnome',run=broken)
        self.assertEqual(self.backup.read_bytes(),b'OLDER BACKUP')
        self.assertEqual(list(self.backup.parent.glob('.ulsm-backup-*')),[])

    def test_gnome_settings_only_empty_dump_does_not_fake_success(self):
        with self.assertRaisesRegex(ValueError,'No desktop settings'):
            make_backup(self.home,self.backup,{'appearance'},desktop='gnome',run=self.runner())
        self.assertFalse(self.backup.exists())

    def test_empty_selected_group_is_reported_but_other_data_is_retained(self):
        meta=make_backup(self.home,self.backup,{'panels','appearance'},desktop='gnome',run=self.runner({
            '/org/gnome/shell/':'[org/gnome/shell]\nfavorite-apps=[]\n'}))
        self.assertIn('appearance',meta['empty_categories'])
        self.assertNotIn('panels',meta['empty_categories'])
        self.assertEqual(len(inspect_backup(self.backup)['dconf']),1)

    def test_restore_missing_gnome_content_is_not_reported_successful(self):
        # Old archives from the pre-fix version might declare a category but contain no values.
        with patch('universal_backup._dconf_dump',return_value=''):
            # Construct a valid archived manifest by making it on KDE, where empty is allowed,
            # then use a valid older GNOME archive with a monitors file for one category.
            monitor=self.home/'.config/monitors.xml'
            monitor.parent.mkdir(parents=True)
            monitor.write_text('<monitors/>')
            make_backup(self.home,self.backup,{'appearance','display'},desktop='gnome',run=self.runner())
        with self.assertRaisesRegex(ValueError,'no saved values'):
            restore_settings(self.home,self.backup,{'appearance'},'gnome',lambda p,d: True)

    def test_dconf_failure_during_restore_does_not_modify_regular_files(self):
        original=self.home/'.config/monitors.xml'
        original.parent.mkdir(parents=True)
        original.write_text('ARCHIVED')
        make_backup(self.home,self.backup,{'display'},desktop='gnome',run=self.runner({
            '/org/gnome/mutter/':'[org/gnome/mutter]\nexperimental-features=[]\n'}))
        original.write_text('CURRENT')
        def fail(prefix,data):return False
        with self.assertRaisesRegex(RuntimeError,'dconf restore failed'):
            restore_settings(self.home,self.backup,{'display'},'gnome',fail,dconf_run=self.runner())
        self.assertEqual(original.read_text(),'CURRENT')
        self.assertTrue(list((self.home/'.local/share/UniversalLinuxSoftwareManager/restore-history').glob('*/dconf-before-restore/*.ini')))

    def test_backup_can_be_embedded_in_bu_and_restored(self):
        data='[org/gnome/desktop/interface]\ncolor-scheme=\'prefer-dark\'\n'
        make_backup(self.home,self.backup,{'appearance'},desktop='gnome',run=self.runner({
            '/org/gnome/desktop/interface/':data}))
        make_bu(self.bu,[],self.backup,source_desktop='gnome',source_distro=('arch',))
        outer=inspect_bu(self.bu)
        self.assertEqual(outer['desktop'],'gnome')
        stage=Path(self.tmp.name)/'staged';stage.mkdir()
        nested=extract_nested(self.bu,stage)
        seen=[]
        restore_settings(self.home,nested,{'appearance'},'gnome',lambda p,d:(seen.append((p,d)) or True),dconf_run=self.runner())
        self.assertEqual(seen,[('/org/gnome/desktop/interface/',data)])


if __name__=='__main__':unittest.main()
