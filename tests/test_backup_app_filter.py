"""Universal backup app provenance and explicit distro-app exclusions."""
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from backup_app_filter import (native_classifications, partition_apps, identity,
                               read_exclusions, write_exclusions)
from universal_backup import make_backup, inspect_backup, restore_settings, CATEGORIES


class BackupAppFilterTests(unittest.TestCase):
    def test_distro_baseline_and_dependencies_are_hidden_not_deleted(self):
        entries=[
            {'kind':'Flatpak','id':'org.gimp.GIMP','scope':'user'},
            {'kind':'DEB','id':'base-files','scope':'SYSTEM'},
            {'kind':'DEB','id':'libutil12','scope':'SYSTEM'},
            {'kind':'DEB','id':'krita','scope':'SYSTEM'},
            {'kind':'Arch','id':'glibc','scope':'SYSTEM'},
            {'kind':'Arch','id':'vlc','scope':'SYSTEM'}]
        ev={'DEB:core':{'base-files'},'DEB:auto':{'libutil12'},'Arch:core':{'glibc'}}
        shown, hidden=partition_apps(entries,ev)
        self.assertEqual([x['id'] for x in shown],['org.gimp.GIMP','krita','vlc'])
        self.assertEqual([x['id'] for x in hidden],['base-files','libutil12','glibc'])
        self.assertEqual(len(shown)+len(hidden),len(entries))
        self.assertEqual([x['backup_class'] for x in hidden], ['system-default','dependency','system-default'])

    def test_explicit_layered_bazzite_rpm_is_user_choice(self):
        shown,hidden=partition_apps([{'kind':'RPM','id':'krita','scope':'SYSTEM','user_layered':True}])
        self.assertEqual(shown[0]['backup_class'],'user-choice')
        self.assertEqual(hidden,[])

    def test_conservative_without_provenance(self):
        for kind in ('RPM','DEB','Arch','Snap','APK','XBPS','Portage','Nix'):
            shown, hidden=partition_apps([{'kind':kind,'id':'custom-app','scope':'SYSTEM'}])
            self.assertFalse(hidden)
            self.assertEqual(shown[0]['backup_class'],'review')

    def test_app_marked_as_preinstalled_can_be_unmarked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'settings'/'excluded.json'
            row={'kind':'Flatpak','id':'org.default.APP','scope':'system'}
            key=identity(row)
            write_exclusions(path,{key})
            self.assertEqual(read_exclusions(path),{key})
            self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o600)
            shown,hidden=partition_apps([row],exclusions=read_exclusions(path))
            self.assertEqual(len(hidden),1)
            write_exclusions(path,set())
            shown,hidden=partition_apps([row],exclusions=read_exclusions(path))
            self.assertEqual(len(shown),1)

    def test_apts_manual_does_not_guess_default(self):
        def fake(args,timeout=30):
            table={
                ('apt-mark','showauto'):'libfoo\n',
                ('dpkg-query','-W','-f=${binary:Package}\t${Priority}\t${Essential}\n'):
                    'base-files\trequired\tyes\ncustom-app\toptional\tno\n',
                ('pacman','-Qdq'):'',('pacman','-Qqg','base'):''}
            return ((True,table[tuple(args)],'') if tuple(args) in table else (False,'',''))
        e=native_classifications(fake)
        self.assertEqual(e['DEB:core'],{'base-files'})
        self.assertEqual(e['DEB:auto'],{'libfoo'})
        shown, hidden=partition_apps([{'kind':'DEB','id':'custom-app'}, {'kind':'DEB','id':'base-files'}],e)
        self.assertEqual(shown[0]['id'],'custom-app')
        self.assertEqual(hidden[0]['id'],'base-files')

    def test_bad_exclusion_json_fails_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'bad.json'
            p.write_text('{broken')
            self.assertEqual(read_exclusions(p),set())

    def test_additional_settings_categories_and_backward_compatibility(self):
        self.assertTrue({'keyboard','notifications','region','fileassoc'} <= set(CATEGORIES))
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)/'home'; home.mkdir()
            (home/'.config').mkdir()
            keyboard=home/'.config/kglobalshortcutsrc'
            keyboard.write_text('shortcut=before')
            associations=home/'.config/mimeapps.list'
            associations.write_text('[Default Applications]\ntext/plain=org.kde.kwrite.desktop')
            archive=Path(tmp)/'backup.zip'
            make_backup(home,archive,{'keyboard','fileassoc'}, [], 'kde')
            meta=inspect_backup(archive)
            self.assertEqual(meta['schema'],4)
            self.assertEqual({x['category'] for x in meta['files']}, {'keyboard','fileassoc'})
            keyboard.write_text('shortcut=after')
            associations.write_text('old')
            restore_settings(home,archive,{'keyboard','fileassoc'},'kde')
            self.assertEqual(keyboard.read_text(),'shortcut=before')
            self.assertIn('org.kde.kwrite',associations.read_text())
            # v2 archives remain importable without untrusted widening of paths.
            import zipfile
            legacy=Path(tmp)/'legacy.zip'
            with zipfile.ZipFile(archive) as src, zipfile.ZipFile(legacy,'w') as dest:
                for name in src.namelist():
                    content=src.read(name)
                    if name=='manifest.json':
                        manifest=json.loads(content)
                        manifest['schema']=2
                        content=json.dumps(manifest).encode()
                    dest.writestr(name,content)
            self.assertEqual(inspect_backup(legacy)['schema'],2)

    def test_fileassoc_is_portable_between_desktops(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)/'home'; (home/'.config').mkdir(parents=True)
            setting=home/'.config/mimeapps.list'; setting.write_text('from KDE')
            archive=Path(tmp)/'portable.zip'
            make_backup(home,archive,{'fileassoc'}, [], 'kde')
            setting.write_text('now GNOME')
            restore_settings(home,archive,{'fileassoc'},'gnome')
            self.assertEqual(setting.read_text(),'from KDE')

    def test_gui_drop_only_backup_with_settings_and_no_app_inventory(self):
        p=Path(__file__).resolve().parents[1]/'main.py'
        source=p.read_text()
        self.assertIn('class PackageDropTable(QTableWidget)',source)
        self.assertIn('self.table.filesDropped.connect(self.add_files)',source)
        self.assertIn('Lokale ZIP-back-up maken...',source)
        self.assertIn('Geselecteerd bestand installeren',source)
        self.assertIn('Instellingen herstellen',source)
        self.assertNotIn('Markeer als standaardapp',source)
        self.assertIn("('keyboard',",source)
        manifest=json.loads((p.parent/'io.github.LionheartTim.UniversalLinuxSoftwareManager.json').read_text())
        self.assertIn('local_file_backup.py',
            [x['path'] for x in manifest['modules'][0]['sources']])

if __name__=='__main__':unittest.main()
