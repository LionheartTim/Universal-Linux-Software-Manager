import hashlib
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from universal_backup import make_backup, inspect_backup, restore_settings, desktop_family
from portable_managers import search_extra, installed_extra

class PortableBackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.home=Path(self.tmp.name)/'home'
        self.home.mkdir()
        self.out=Path(self.tmp.name)/'test.zip'
    def tearDown(self):self.tmp.cleanup()
    def populate(self, rel, contents):
        path=self.home/rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        return path
    def test_kde_categories_selected_and_restore_preserves_prior_file(self):
        theme=self.populate('.config/kdeglobals',b'[General]\nColorScheme=Old\n')
        panel=self.populate('.config/plasma-org.kde.plasma.desktop-appletsrc',b'paneldata')
        self.populate('.config/kwalletrc',b'DO NOT EXPORT')
        manifest=make_backup(self.home,self.out,{'appearance','panels','apps'},
             [{'kind':'Flatpak','id':'org.videolan.VLC','remote':'flathub'}],'plasma', {'fedora'})
        self.assertEqual(manifest['desktop'],'kde')
        self.assertEqual(len(manifest['packages']),1)
        self.assertEqual(len(manifest['files']),2)
        self.assertNotIn(b'DO NOT EXPORT',self.out.read_bytes())
        theme.write_bytes(b'[General]\nColorScheme=Current\n')
        panel.write_bytes(b'currentpanel')
        recovery=restore_settings(self.home,self.out,{'appearance','panels'},'kde')
        self.assertEqual(theme.read_bytes(),b'[General]\nColorScheme=Old\n')
        self.assertEqual((recovery/'.config/kdeglobals').read_bytes(),b'[General]\nColorScheme=Current\n')
        self.assertEqual(panel.read_bytes(),b'paneldata')
    def test_only_checked_app_preferences_restore(self):
        pkgs=[{'kind':'Flatpak','id':'org.videolan.VLC','remote':'flathub'},
              {'kind':'Flatpak','id':'org.other.APP','remote':'flathub'}]
        one=self.populate('.var/app/org.videolan.VLC/config/app.ini',b'first')
        two=self.populate('.var/app/org.other.APP/config/app.ini',b'second')
        make_backup(self.home,self.out,{'apps','appsettings'},pkgs,'kde')
        one.write_bytes(b'current-first')
        two.write_bytes(b'current-second')
        restore_settings(self.home,self.out,{'appsettings'},'kde',app_ids={'org.videolan.VLC'})
        self.assertEqual(one.read_bytes(),b'first')
        self.assertEqual(two.read_bytes(),b'current-second')

    def test_cross_desktop_restore_is_blocked(self):
        self.populate('.config/monitors.xml',b'<monitors />')
        make_backup(self.home,self.out,{'display'},[],'gnome',
                    run=lambda argv, timeout: (True, '', ''))
        with self.assertRaisesRegex(ValueError,'Desktop mismatch'):
            restore_settings(self.home,self.out,{'display'},'kde')
    def test_app_data_explicit_optin_and_only_selected(self):
        self.populate('.var/app/org.videolan.VLC/config/preferences',b'PREF-SECRET')
        self.populate('.var/app/org.other.APP/config/preferences',b'OTHER-SECRET')
        pkgs=[{'kind':'Flatpak','id':'org.videolan.VLC','remote':'flathub'}]
        make_backup(self.home,self.out,{'apps'},pkgs,'kde')
        self.assertEqual(inspect_backup(self.out)['files'],[])
        make_backup(self.home,self.out,{'apps','appsettings'},pkgs,'kde')
        entries=[f['path'] for f in inspect_backup(self.out)['files']]
        self.assertEqual(entries,['.var/app/org.videolan.VLC/config/preferences'])
        self.assertNotIn(b'OTHER-SECRET',self.out.read_bytes())
        with self.assertRaises(ValueError):
            make_backup(self.home,self.out,{'appsettings'},pkgs,'kde')
    def test_flatpak_preferences_can_transfer_across_desktops(self):
        self.populate('.var/app/org.videolan.VLC/config/config.ini',b'portable settings')
        pkgs=[{'kind':'Flatpak','id':'org.videolan.VLC','remote':'flathub'}]
        make_backup(self.home,self.out,{'apps','appsettings'},pkgs,'kde')
        f=self.home/'.var/app/org.videolan.VLC/config/config.ini'
        f.write_bytes(b'new')
        restore_settings(self.home,self.out,{'appsettings'},'gnome')
        self.assertEqual(f.read_bytes(),b'portable settings')

    def test_bad_settings_symlink_is_not_exported_or_overwritten(self):
        outside=Path(self.tmp.name)/'outside'
        outside.write_text('PRIVATE')
        settings=self.home/'.config'
        settings.mkdir()
        (settings/'kdeglobals').symlink_to(outside)
        make_backup(self.home,self.out,{'appearance'},[],'kde')
        self.assertEqual(inspect_backup(self.out)['files'],[])
        (settings/'kdeglobals').unlink()
        self.populate('.config/kdeglobals',b'valid')
        make_backup(self.home,self.out,{'appearance'},[],'kde')
        (settings/'kdeglobals').unlink()
        (settings/'kdeglobals').symlink_to(outside)
        with self.assertRaisesRegex(ValueError,'Symlink'):
            restore_settings(self.home,self.out,{'appearance'},'kde')
        self.assertEqual(outside.read_text(),'PRIVATE')
    def test_invalid_member_rejected_and_no_write(self):
        self.populate('.config/kdeglobals',b'a')
        make_backup(self.home,self.out,{'appearance'},[],'kde')
        with zipfile.ZipFile(self.out,'a') as z:z.writestr('settings/../../evil','malicious')
        with self.assertRaisesRegex(ValueError,'Unexpected archive'):
            inspect_backup(self.out)
    def test_checksum_preflight_no_changes(self):
        f=self.populate('.config/kdeglobals',b'old')
        make_backup(self.home,self.out,{'appearance'},[],'kde')
        f.write_bytes(b'new')
        copy=self.out.with_name('tampered.zip')
        with zipfile.ZipFile(self.out) as zin, zipfile.ZipFile(copy,'w') as zout:
            for name in zin.namelist():
                data=zin.read(name)
                if name=='settings/.config/kdeglobals':data=b'bad'
                zout.writestr(name,data)
        with self.assertRaisesRegex(ValueError,'checksum'):
            restore_settings(self.home,copy,{'appearance'},'kde')
        self.assertEqual(f.read_bytes(),b'new')
    def test_dconf_data_checked_and_applied(self):
        def fake_run(argv,timeout):
            if argv[:2]==['dconf','dump']:return True,'[org]\nkey=true\n',''
            return False,'','fail'
        make_backup(self.home,self.out,{'appearance'},[],'gnome',run=fake_run)
        prefixes=[]
        restore_settings(self.home,self.out,{'appearance'},'gnome',lambda prefix,text: (prefixes.append((prefix,text)) or True),dconf_run=fake_run)
        self.assertEqual(len(prefixes),4)
        self.assertTrue(all(p[0].startswith('/org/gnome/') for p in prefixes))
    def test_detect_desktops(self):
        for k,v in [('kde','KDE:Plasma'),('gnome','GNOME'),('xfce','XFCE'),('lxqt','LXQt'),('cinnamon','X-Cinnamon'),('mate','MATE')]:
            self.assertEqual(desktop_family(v),k)

class OtherDistroTests(unittest.TestCase):
    def manager(self,k):return {'APK':'apk','XBPS':'xbps-query','Portage':None,'Nix':None}.get(k)
    def runner(self,args,t=40):
        cmds={('apk','search','-v','vlc'):'vlc-3.0.21-r1 - Media player',
              ('xbps-query','-Rs','vlc'):'[-] vlc-3.0.21_1 VLC video player',
              ('apk','info','-v'):'vlc-3.0.21-r1\nother-2.0-r0',
              ('xbps-query','-l'):'ii vlc-3.0.21_1 VLC video player\nuu half-1.0_1 Unconfigured'}
        return (True,cmds[tuple(args)],'') if tuple(args) in cmds else (False,'','not supported')
    def test_search_read_only(self):
        rows,notes=search_extra(self.runner,self.manager,'vlc')
        self.assertEqual({r['kind'] for r in rows},{'APK','XBPS'})
        self.assertEqual({r['id'] for r in rows},{'vlc'})
    def test_inventory_only_installed(self):
        rows,notes=installed_extra(self.runner,self.manager)
        self.assertEqual(len(rows),3)
        self.assertEqual({r['kind'] for r in rows},{'APK','XBPS'})
    def test_new_native_types_are_never_individually_upgraded(self):
        from feature_tools import upgrade_command, export_manifest, import_manifest
        from installed_inventory import merge_updates
        for kind in ('APK','XBPS','Portage','Nix'):
            self.assertIsNone(upgrade_command({'kind':kind,'id':'vlc'},self.manager))
            data=export_manifest([{'kind':kind,'id':'vlc'}],{'alpine'})
            self.assertEqual(import_manifest(json.dumps(data))[0]['kind'],kind)
            row=merge_updates([{'kind':kind,'id':'vlc','name':'VLC','scope':'SYSTEM'}],[])[0]
            self.assertEqual(row['status'],'system_updater')

    def test_manifest_bundles_portable_modules(self):
        base=Path(__file__).resolve().parents[1]
        m=json.loads((base/'io.github.LionheartTim.UniversalLinuxSoftwareManager.json').read_text())
        sources=[r['path'] for r in m['modules'][0]['sources']]
        self.assertIn('universal_backup.py',sources)
        self.assertIn('portable_managers.py',sources)
        code=(base/'main.py').read_text()
        self.assertIn('restore_preferences',code)
        self.assertIn('Link GitHub source',code)
if __name__=='__main__': unittest.main()
