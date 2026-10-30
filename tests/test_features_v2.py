import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from feature_tools import (package_id_ok, flatpak_search_rows, search_software,
    scan_updates, install_command, upgrade_command, export_manifest, import_manifest)

class FeatureV2Tests(unittest.TestCase):
    def manager(self, kind):
        return {'RPM': 'dnf5', 'DEB': None, 'Arch': None, 'Snap': 'snap'}.get(kind)

    def runner(self, args, timeout=900):
        if args[:2] == ['flatpak', 'search']:
            return True, 'VLC\torg.videolan.VLC\t3.0.21\tflathub\n', ''
        if args[:2] == ['dnf5', 'search']:
            return True, 'vlc.x86_64 : Media player\n', ''
        if args[:2] == ['snap', 'find']:
            return True, 'Name Version Publisher Notes Summary\nvlc 3.0.21 snapcrafters - Video\n', ''
        if args[:2] == ['flatpak', 'remote-ls']:
            return True, 'org.videolan.VLC\t3.0.21\n' if '--user' in args else '', ''
        if args[:2] == ['dnf5', 'check-upgrade']:
            return False, 'vlc.x86_64 3.0.21-1.fc43 updates\n', ''
        if args[:2] == ['snap', 'refresh']:
            return True, 'Name Version Rev Publisher Notes\nvlc 3.0.21 10 snapcrafters -\n', ''
        return False, '', 'Unavailable'

    def test_flatpak_search_source_is_preserved(self):
        rows=flatpak_search_rows('VLC\torg.videolan.VLC\t3.0.21\tflathub\n')
        self.assertEqual(rows[0]['scope'], 'flathub')

    def test_search_multiple_backends_and_comparison(self):
        rows,warnings=search_software(self.runner, self.manager, 'vlc')
        self.assertEqual({x['kind'] for x in rows},{'Flatpak','RPM','Snap'})
        self.assertTrue(all(x['id'] for x in rows))

    def test_updates_support_dnf_exit_100(self):
        rows,notes=scan_updates(self.runner,self.manager)
        self.assertEqual({x['kind'] for x in rows},{'Flatpak','RPM','Snap'})
        self.assertTrue(any(x['scope']=='user' for x in rows if x['kind']=='Flatpak'))

    def test_commands_have_explicit_packages_and_scopes(self):
        entry={'kind':'Flatpak','id':'org.videolan.VLC','scope':'user','remote':'flathub'}
        self.assertIn('--user',upgrade_command(entry,self.manager))
        self.assertIn('flathub',install_command(entry,self.manager))
        self.assertIsNone(install_command({'kind':'Flatpak','id':'org.videolan.VLC'},self.manager))
        self.assertEqual(upgrade_command({'kind':'RPM','id':'vlc'},self.manager)[:3],['pkexec','dnf5','upgrade'])

    def test_backup_data_is_inventory_only(self):
        data=export_manifest([{'kind':'Flatpak','id':'org.videolan.VLC','remote':'flathub',
                               'secret':'DO_NOT_EXPORT'}, {'kind':'AppImage','id':'Local.AppImage'}], {'fedora'})
        text=json.dumps(data)
        self.assertNotIn('DO_NOT_EXPORT',text)
        self.assertFalse(data['contains_personal_files'])
        self.assertEqual(len(import_manifest(text)),2)

    def test_backup_rejects_commands_and_unknown_formats(self):
        data=export_manifest([{'kind':'DEB','id':'vlc'}], {'debian'})
        data['packages'][0]['id']='--force; rm -rf /'
        with self.assertRaises(ValueError): import_manifest(json.dumps(data))
        with self.assertRaises(ValueError): import_manifest('{}')
        with self.assertRaises(ValueError): import_manifest(b'x' * 2_000_001)
        self.assertFalse(package_id_ok('-malicious'))

    def test_new_module_is_installed_in_bundle(self):
        base=Path(__file__).resolve().parents[1]
        manifest=json.loads((base/'io.github.LionheartTim.UniversalLinuxSoftwareManager.json').read_text())
        self.assertIn('feature_tools.py',[x['path'] for x in manifest['modules'][0]['sources']])
        self.assertIn('feature_tools.py', ' '.join(manifest['modules'][0]['build-commands']))
        code=(base/'main.py').read_text()
        self.assertIn('class UpdatesPanel',code)
        self.assertIn('class DiscoverPanel',code)
        self.assertIn('class BackupPanel',code)
        self.assertIn('self.extra_tabs',code)

if __name__=='__main__': unittest.main()
