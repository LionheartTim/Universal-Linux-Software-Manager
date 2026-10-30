"""Safety preflight and interrupted restore regression tests, no Qt runtime needed."""
import ast
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backup_safety import (MARGIN, estimated_backup_bytes, preflight_restore, summarize_report)
import restore_journal
from local_file_backup import create_backup, inspect_backup

ROOT=Path(__file__).resolve().parents[1]
MAIN=(ROOT/'main.py').read_text()
TREE=ast.parse(MAIN)
PANEL=next(x for x in TREE.body if isinstance(x,ast.ClassDef) and x.name=='BackupPanel')


def stub_meta(kinds=('AppImage','Flatpak','RPM'), sizes=(1024,2048,4096), desktop='kde', arch='x86_64'):
    return {'packages':[{'filename':f'{kind}-{i}.pkg', 'kind':kind,'size':sizes[i]} for i,kind in enumerate(kinds)],
            'settings':{'size':8192},'desktop':desktop,'architecture':arch,'distro':['fedora','bazzite']}


class BackupSafetyTests(unittest.TestCase):
    def test_preflight_all_eligible_on_matching_host(self):
        report=preflight_restore(stub_meta(),desktop='kde',distro={'fedora','bazzite'},
            architecture='x86_64',available_kinds={'AppImage','Flatpak','RPM'},
            managers={'AppImage':'appimage','Flatpak':'flatpak','RPM':'rpm-ostree'},free_bytes=2**30)
        self.assertFalse(report['blocked'])
        self.assertEqual(sum(x['eligible'] for x in report['rows']),3)
        self.assertIn('Click Restore backup again to start',summarize_report(report))

    def test_native_cross_distro_blocked_but_portable_formats_eligible(self):
        report=preflight_restore(stub_meta(),desktop='kde',distro={'ubuntu'},
            architecture='x86_64',available_kinds={'AppImage','Flatpak','RPM'},
            managers={'AppImage':'appimage','Flatpak':'flatpak','RPM':'dnf'},free_bytes=2**30)
        self.assertTrue(report['rows'][0]['eligible'])
        self.assertTrue(report['rows'][1]['eligible'])
        self.assertFalse(report['rows'][2]['eligible'])
        self.assertIn('different distribution',report['blocked'][2])

    def test_missing_package_manager_is_not_a_silent_install(self):
        report=preflight_restore(stub_meta(('DEB',),(1024,)),desktop='kde',distro={'fedora'},
            architecture='x86_64',available_kinds=set(),managers={'DEB':None},free_bytes=2**30)
        self.assertIn(0,report['blocked'])

    def test_cpu_architecture_mismatch_exempts_flatpak_only(self):
        report=preflight_restore(stub_meta(('AppImage','Flatpak'),(1024,2048)),desktop='kde',
            distro={'fedora'},architecture='aarch64',available_kinds={'AppImage','Flatpak'},
            managers={'AppImage':'appimage','Flatpak':'flatpak'},free_bytes=2**30)
        self.assertIn(0,report['blocked'])
        self.assertNotIn(1,report['blocked'])

    def test_desktop_settings_mismatch_blocked(self):
        report=preflight_restore(stub_meta(desktop='gnome'),desktop='kde',distro={'fedora'},
            architecture='x86_64',available_kinds={'AppImage','Flatpak','RPM'},
            managers={'AppImage':'appimage','Flatpak':'flatpak','RPM':'rpm-ostree'},free_bytes=2**30)
        self.assertIn('settings',report['blocked'])
        self.assertTrue(report['warnings'])

    def test_insufficient_space_blocks_only_affected_installers(self):
        report=preflight_restore(stub_meta(('AppImage','Flatpak'),(1,20000)),desktop='kde',
            distro={'fedora'},architecture='x86_64',available_kinds={'AppImage','Flatpak'},
            managers={'AppImage':'appimage','Flatpak':'flatpak'},free_bytes=MARGIN+100)
        self.assertTrue(report['rows'][0]['eligible'])
        self.assertFalse(report['rows'][1]['eligible'])
        self.assertIn('settings',report['blocked'])

    def test_backup_disk_estimate_includes_all_packages(self):
        with tempfile.TemporaryDirectory() as d:
            a=Path(d)/'a.rpm';b=Path(d)/'b.rpm'
            a.write_bytes(b'A'*10);b.write_bytes(b'B'*15)
            self.assertEqual(estimated_backup_bytes((a,b),200),425+MARGIN)

    def test_atomic_backup_rejects_write_failure_and_keeps_old_file(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);src=d/'a.AppImage';src.write_bytes(b'\x7fELF'+b'X'*100)
            dest=d/'a.bu';dest.write_bytes(b'OLD-USER-BACKUP')
            with patch('local_file_backup._digest_stream',side_effect=OSError(28,'No space left on device')):
                with self.assertRaises(OSError):create_backup(dest,[src])
            self.assertEqual(dest.read_bytes(),b'OLD-USER-BACKUP')
            self.assertEqual(list(d.glob('.ulsm-backup-*')),[])


class RestoreJournalTests(unittest.TestCase):
    def test_unfinished_restoration_is_detected_and_never_auto_resumed(self):
        with tempfile.TemporaryDirectory() as d:
            state=restore_journal.start(d,'/home/me/manual.bu',['one.AppImage','two.rpm'])
            restore_journal.update(d,state,0,'Installed')
            unfinished=restore_journal.read_unfinished(d)
            self.assertEqual(unfinished['state'],'running')
            self.assertEqual(unfinished['items'][0]['status'],'Installed')
            self.assertEqual(unfinished['items'][1]['status'],'Waiting for approval')
            path=restore_journal.state_path(d)
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            state2=restore_journal.start(d,'/new.bu',['three.deb'])
            self.assertEqual(len(list(path.parent.glob('interrupted-*.json'))),1)
            self.assertEqual(restore_journal.read_unfinished(d)['archive'],'/new.bu')
            restore_journal.finish(d,state2)
            self.assertIsNone(restore_journal.read_unfinished(d))

    def test_atomic_journal_write_failure_preserves_previous(self):
        with tempfile.TemporaryDirectory() as d:
            state=restore_journal.start(d,'backup.bu',['a'])
            original=restore_journal.state_path(d).read_bytes()
            with patch('restore_journal.os.replace',side_effect=OSError(28,'Disk full')):
                with self.assertRaises(OSError):restore_journal.update(d,state,0,'Installed')
            self.assertEqual(restore_journal.state_path(d).read_bytes(),original)
            self.assertEqual(list(restore_journal.state_path(d).parent.glob('.restore-*')),[])

    def test_completed_journal_contains_results_and_no_installer_code(self):
        with tempfile.TemporaryDirectory() as d:
            state=restore_journal.start(d,'backup.bu',['test.AppImage'])
            restore_journal.update(d,state,0,'Skipped')
            restore_journal.finish(d,state)
            self.assertIsNone(restore_journal.read_unfinished(d))
            saved=json.loads(restore_journal.state_path(d).read_text())
            self.assertEqual(saved['items'][0]['status'],'Skipped')
            self.assertNotIn('commands',saved)

    def test_new_modules_packed_in_manifest_and_wired_into_main(self):
        manifest=json.loads((ROOT/'io.github.LionheartTim.UniversalLinuxSoftwareManager.json').read_text())
        sources={x['path'] for x in manifest['modules'][0]['sources']}
        self.assertTrue({'backup_safety.py','restore_journal.py'} <= sources)
        panel_methods={m.name for m in PANEL.body if isinstance(m,ast.FunctionDef)}
        self.assertTrue({'warn_unfinished','restore_backup','_restore_finish','_status'} <= panel_methods)
        fn=next(m for m in PANEL.body if isinstance(m,ast.FunctionDef) and m.name=='open_backup')
        self.assertIn('inspect_file_backup(file)',ast.get_source_segment(MAIN,fn))
        self.assertIn('preflight_restore(',ast.get_source_segment(MAIN,fn))
        self.assertIn('dialog.exec()',ast.get_source_segment(MAIN,fn))
        self.assertIn('restore_journal.start',MAIN)
        self.assertIn('restore_journal.finish',MAIN)

if __name__=='__main__':unittest.main()
