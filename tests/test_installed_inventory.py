"""Network-free regression tests: installed system state, NEVER Discover search state."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from installed_inventory import (installed_software, merge_updates, scan_all_installed_updates,
                                 flatpak_scope)
from feature_tools import record, upgrade_command


class InstalledInventoryTests(unittest.TestCase):
    def manager(self, kind):
        return {'RPM': 'rpm-ostree', 'Snap': 'snap'}.get(kind)

    def runner(self, args, timeout=60):
        if args[:2] == ['flatpak', 'list']:
            return True, ('VLC\torg.videolan.VLC\t3.0.20\tuser\n'
                          'Example\torg.example.Example\t1.0\tsystem\n'
                          'Other\torg.example.Other\t1.0\tcustom\n'), ''
        if args[:2] == ['flatpak', 'remote-ls']:
            if '--user' in args:
                return True, 'org.videolan.VLC\t3.0.21\norg.missing.NotInstalled\t8\n', ''
            if '--system' in args: return True, '', ''
            if '--installation=custom' in args: return False, '', 'network offline'
        if args[:3] == ['rpm-ostree', 'status', '--json']:
            return True, json.dumps({'deployments': [{'booted': True, 'requested-packages': ['wireshark']}]}), ''
        if args[:2] == ['snap', 'list']:
            return True, 'Name Version Rev Tracking Publisher Notes\nspotify 1.2 3 stable vendor -\n', ''
        if args[:3] == ['snap', 'refresh', '--list']:
            return True, 'Name Version Rev Publisher Notes\n', ''
        return False, '', 'not available'

    def test_scope_mapping_and_validation(self):
        self.assertEqual(flatpak_scope('USER'), 'user')
        self.assertEqual(flatpak_scope('default'), 'system')
        self.assertEqual(flatpak_scope('custom'), 'custom')
        self.assertIsNone(flatpak_scope('--dangerous'))
        self.assertIn('--installation=custom', upgrade_command(
            record('Flatpak', 'Other', 'org.example.Other', scope='custom'), self.manager))

    def test_reads_every_existing_source_including_manual_appimage(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            (folder/'Manual.AppImage').write_bytes(b'test')
            (folder/'Registered.AppImage').write_bytes(b'test')
            (folder/'ignore.txt').write_bytes(b'test')
            rows, notes = installed_software(self.runner, self.manager, folder, {
                'publisher/Repo': {'file': 'Registered.AppImage', 'tag': 'v1'}})
            self.assertEqual(len(rows), 7)  # 3 Flatpaks, 2 AppImages, 1 RPM, 1 Snap
            self.assertEqual({row['kind'] for row in rows}, {'Flatpak','AppImage','RPM','Snap'})
            manual = next(r for r in rows if r['id']=='Manual.AppImage')
            github = next(r for r in rows if r['id']=='Registered.AppImage')
            self.assertEqual(manual['update_source'], 'unknown')
            self.assertEqual(github['github_repo'], 'publisher/Repo')
            self.assertEqual(github['version'], 'v1')

    def test_uninstalled_update_never_offered(self):
        installed=[record('Flatpak','VLC','org.videolan.VLC', '3.0.20', 'user')]
        updates=[record('Flatpak','not installed','org.bad.Uninstalled','4.0','user')]
        combined=merge_updates(installed,updates,{('Flatpak','user')})
        self.assertEqual(len(combined),1)
        self.assertEqual(combined[0]['status'],'no_update')

    def test_installed_identity_must_match_kind_and_scope(self):
        inventory=[record('Flatpak','VLC','org.videolan.VLC', '3.0.20',scope)
                   for scope in ('user','system','custom')]
        updates=[record('Flatpak','VLC','org.videolan.VLC','3.0.21','user')]
        rows=merge_updates(inventory,updates,{('Flatpak',scope) for scope in ('user','system','custom')})
        self.assertEqual(sum(r['status']=='available' for r in rows), 1)
        self.assertEqual([r['scope'] for r in rows if r['status']=='available'],['user'])

    def test_manual_appimages_never_assume_github_updates(self):
        items=[record('AppImage','Great Game','game.AppImage'),
               {**record('AppImage','Game Release','installed.AppImage'),
                'github_repo':'official/Game'}]
        updates=[{**record('GitHub','Game Release','official/Game','v2'), 'release':{'tag':'v2'}}]
        result=merge_updates(items, updates, {('GitHub','official/Game')})
        self.assertEqual({r['id']:r['status'] for r in result},
                         {'game.AppImage':'unknown_source','installed.AppImage':'available'})

    def test_failed_update_check_not_reported_as_up_to_date(self):
        installed=[record('Flatpak','VLC','org.videolan.VLC', '1','custom')]
        row=merge_updates(installed,[],set())[0]
        self.assertEqual(row['status'],'not_checked')

    def test_atomic_host_updates_require_system_updater(self):
        inventory=[record('RPM','wireshark','wireshark',scope='SYSTEM')]
        rows=merge_updates(inventory,[record('RPM','wireshark','wireshark','9.0')],
                           {('RPM','system_updater')})
        self.assertEqual(rows[0]['status'],'system_updater')
        self.assertIsNone(upgrade_command(rows[0], self.manager))

    def test_arch_partial_upgrade_is_not_issued(self):
        mgr=lambda kind: 'pacman' if kind=='Arch' else None
        row=record('Arch','firefox','firefox')
        self.assertIsNone(upgrade_command(row,mgr))
        result=merge_updates([row],[record('Arch','firefox','firefox','2')],{('Arch','')})
        self.assertEqual(result[0]['status'],'system_updater')

    def test_integration_real_inventory_with_offline_statuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            (folder/'manual.AppImage').write_bytes(b'placeholder')
            rows,notes=scan_all_installed_updates(self.runner,self.manager,folder,
                github_lookup=lambda checked:([],[]))
            available=[r for r in rows if r['status']=='available']
            self.assertEqual([r['id'] for r in available],['org.videolan.VLC'])
            self.assertEqual(next(r['status'] for r in rows if r['id']=='org.example.Other'),
                             'not_checked')
            self.assertEqual(next(r['status'] for r in rows if r['id']=='manual.AppImage'),
                             'unknown_source')
            self.assertTrue(any('network offline' in note for note in notes))

    def test_deb_multiarch_is_only_mapped_when_unambiguous(self):
        row=record('DEB', 'VLC', 'vlc:amd64', '1.0')
        upd=record('DEB', 'VLC', 'vlc', '2.0')
        self.assertEqual(merge_updates([row], [upd], {('DEB','')})[0]['status'], 'available')
        both=[row,record('DEB','VLC','vlc:i386','1.0')]
        self.assertEqual([r['status'] for r in merge_updates(both, [upd], {('DEB','')})],
                         ['no_update','no_update'])

    def test_snap_no_updates_message_is_a_successful_check(self):
        from feature_tools import scan_updates
        def runner(args, timeout):
            if args[:3] == ['snap','refresh','--list']:
                return False, '', 'All snaps up to date.'
            return False, '', 'missing'
        checked=set()
        scan_updates(runner, lambda k: 'snap' if k=='Snap' else None,
                     checked=checked, flatpak_scopes=[])
        self.assertIn(('Snap',''),checked)

    def test_manifest_contains_inventory_module_and_updates_wiring(self):
        folder=Path(__file__).resolve().parents[1]
        manifest=json.loads((folder/'io.github.LionheartTim.UniversalLinuxSoftwareManager.json').read_text())
        module=manifest['modules'][0]
        self.assertIn('installed_inventory.py',[v['path'] for v in module['sources']])
        self.assertIn('installed_inventory.py',' '.join(module['build-commands']))
        main=(folder/'main.py').read_text()
        self.assertNotIn('def after_discover_install(',main)
        self.assertIn('self.discover_tab = DiscoverPanel()',main)
        self.assertIn('def when_tab_activated(',main)
        self.assertIn('scan_all_installed_updates(',main)


if __name__ == '__main__': unittest.main()
