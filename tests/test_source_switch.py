"""Source switch tests never use a real Flatpak or access the network."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from source_switch import (InstalledFlatpak, parse_flatpak_installs, list_installed_flatpaks,
                           suggested_matches, flatpak_label, uninstall_args, restore_args,
                           migrate_github_appimage)

PACKAGE = InstalledFlatpak('org.videolan.VLC', 'VLC', 'user', 'flathub',
                           'app/org.videolan.VLC/x86_64/stable')
ALT_PACKAGE = InstalledFlatpak('org.videolan.VLC', 'VLC', 'system', 'flathub',
                               'app/org.videolan.VLC/x86_64/stable')
REPO='videolan/vlc'
RELEASE={'repo':REPO,'tag':'v4.0','url':'https://github.com/videolan/vlc/releases/tag/v4.0',
         'assets':[{'name':'vlc-linux-x86_64.AppImage','size':32,
                    'browser_download_url':f'https://github.com/{REPO}/releases/download/v4.0/vlc-linux-x86_64.AppImage'}]}


def output_for(apps):
    return ''.join(f'{x.app_id}\t{x.name}\t{x.installation}\t{x.origin}\t{x.ref}\n' for x in apps)


class FakeHost:
    def __init__(self, apps, fail_uninstall=False, fail_restore=False):
        self.apps=list(apps)
        self.fail_uninstall=fail_uninstall
        self.fail_restore=fail_restore
        self.log=[]
    def run(self, args, timeout=45):
        self.log.append(args)
        if args[:2] == ['flatpak','list']:
            return True,output_for(self.apps),''
        if args[:2] == ['flatpak','uninstall']:
            if self.fail_uninstall: return False,'','remove denied'
            flag=args[2]
            ref=args[-1]
            self.apps=[p for p in self.apps if not (p.ref==ref and ('--user' if p.installation=='user' else '--system')==flag)]
            return True,'removed',''
        if args[:2] == ['flatpak','install']:
            if self.fail_restore: return False,'','repository offline'
            self.apps.append(PACKAGE)
            return True,'installed',''
        raise AssertionError(f'unexpected operation: {args}')


class FakeAppImage:
    def __init__(self,log,fail=False):self.log=log;self.fail=fail
    def appimage_install(self,path):
        self.log.append(['publish',path.name])
        if self.fail: raise OSError('disk full')


class SwitchTest(unittest.TestCase):
    def test_full_ref_scope_and_data_kept(self):
        rows=parse_flatpak_installs(output_for([PACKAGE,ALT_PACKAGE]))
        self.assertEqual(rows,[PACKAGE,ALT_PACKAGE])
        self.assertEqual(uninstall_args(PACKAGE),['flatpak','uninstall','--user','--noninteractive','-y',PACKAGE.ref])
        self.assertEqual(uninstall_args(ALT_PACKAGE)[2],'--system')
        self.assertNotIn('--delete-data',uninstall_args(PACKAGE))
        self.assertEqual(restore_args(PACKAGE)[-2:],['flathub',PACKAGE.ref])
        self.assertIn('org.videolan.VLC',flatpak_label(PACKAGE))

    def test_only_suggest_exact_normalized_name_or_id_tail(self):
        other=InstalledFlatpak('org.other.VideoPlayer','Another video app','user','flathub',
                                'app/org.other.VideoPlayer/x86_64/stable')
        self.assertEqual(suggested_matches([other, PACKAGE],'VLC','videolan/vlc'),[PACKAGE])
        self.assertEqual(suggested_matches([PACKAGE],'Other Game','org/other'),[])

    def test_flatpak_human_header_is_ignored(self):
        header='Application ID\tName\tInstallation\tOrigin\tRef\n'
        self.assertEqual(parse_flatpak_installs(header+output_for([PACKAGE])),[PACKAGE])

    def test_bad_rows_fail_closed(self):
        for raw in ('VLC\torg.videolan.VLC\n',
                    'org.videolan.VLC\tVLC\tuser\tflathub\tapp/org.different/x86_64/stable\n',
                    'org.videolan.VLC\tVLC\t../user\tflathub\tapp/org.videolan.VLC/x86_64/stable\n'):
            with self.subTest(raw=raw),self.assertRaises(ValueError):parse_flatpak_installs(raw)

    def run_migration(self,host,app,dirname,downloader=None):
        path=Path(dirname)
        def download(asset,repo,file):
            app.log.append(['download',asset['name']])
            if downloader: return downloader(asset,repo,file)
            file.write_bytes(b'pretend validated fixture')
            return 'a'*64
        return migrate_github_appimage(RELEASE,app,PACKAGE,host.run,
                 tracking_file=path/'tracker.json',downloader=download,app_dir=path/'apps')

    def test_verified_download_then_remove_then_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            host=FakeHost([PACKAGE,ALT_PACKAGE])
            app=FakeAppImage(host.log)
            self.run_migration(host,app,tmp)
            steps=[row[1] if row[0]=='flatpak' else row[0] for row in host.log]
            self.assertLess(steps.index('download'),steps.index('uninstall'))
            self.assertLess(steps.index('uninstall'),steps.index('publish'))
            self.assertEqual(host.apps,[ALT_PACKAGE], 'only selected USER app was removed')
            self.assertEqual(json.loads((Path(tmp)/'tracker.json').read_text())[REPO]['tag'],'v4.0')

    def test_failed_download_does_not_remove_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            host=FakeHost([PACKAGE]);app=FakeAppImage(host.log)
            def fail(*_):raise OSError('network unavailable')
            with self.assertRaisesRegex(OSError,'network unavailable'):
                self.run_migration(host,app,tmp,fail)
            self.assertEqual(host.apps,[PACKAGE])
            self.assertFalse(any(x[:2]==['flatpak','uninstall'] for x in host.log))

    def test_failed_uninstall_never_installs(self):
        with tempfile.TemporaryDirectory() as tmp:
            host=FakeHost([PACKAGE],fail_uninstall=True);app=FakeAppImage(host.log)
            with self.assertRaisesRegex(RuntimeError,'Flatpak uninstall failed'):
                self.run_migration(host,app,tmp)
            self.assertEqual(host.apps,[PACKAGE])
            self.assertFalse(any(x[0]=='publish' for x in host.log))

    def test_changed_flatpak_ref_is_never_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            host=FakeHost([ALT_PACKAGE]);app=FakeAppImage(host.log)
            with self.assertRaisesRegex(RuntimeError,'changed or disappeared'):
                self.run_migration(host,app,tmp)
            self.assertEqual(host.apps,[ALT_PACKAGE])
            self.assertFalse(any(x[:2]==['flatpak','uninstall'] for x in host.log))

    def test_existing_appimage_blocks_removal(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/'apps').mkdir()
            (Path(tmp)/'apps'/'videolan-vlc__v4.0.AppImage').write_bytes(b'existing')
            host=FakeHost([PACKAGE]);app=FakeAppImage(host.log)
            with self.assertRaisesRegex(RuntimeError,'already exists'):
                self.run_migration(host,app,tmp)
            self.assertEqual(host.apps,[PACKAGE])

    def test_failed_publication_attempts_flatpak_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            host=FakeHost([PACKAGE]);app=FakeAppImage(host.log,fail=True)
            with self.assertRaisesRegex(OSError,'disk full'):
                self.run_migration(host,app,tmp)
            self.assertEqual(host.apps,[PACKAGE])
            self.assertTrue(any(x[:2]==['flatpak','install'] for x in host.log))
            self.assertFalse((Path(tmp)/'tracker.json').exists())

    def test_failed_restore_is_explained(self):
        with tempfile.TemporaryDirectory() as tmp:
            host=FakeHost([PACKAGE],fail_restore=True);app=FakeAppImage(host.log,fail=True)
            with self.assertRaisesRegex(RuntimeError,'could not be restored'):
                self.run_migration(host,app,tmp)
            self.assertEqual(host.apps,[])

    def test_non_gui_integration_and_manifest_packing(self):
        root=Path(__file__).parents[1]
        manifest=json.loads((root/'io.github.LionheartTim.UniversalLinuxSoftwareManager.json').read_text())
        build=manifest['modules'][0]
        self.assertIn('source_switch.py',[s.get('path') for s in build['sources']])
        self.assertIn('source_switch.py',' '.join(build['build-commands']))
        text=(root/'main.py').read_text()
        # Historical migration library remains covered, but is intentionally
        # not reachable from the read-only Discover UI.
        self.assertNotIn('QInputDialog.getItem',text)
        self.assertNotIn('migrate_github_appimage',text)
        self.assertNotIn('Oude Flatpak eerst verwijderen',text)


if __name__=='__main__':unittest.main()
