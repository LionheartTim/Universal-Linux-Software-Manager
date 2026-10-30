"""Plasma 6 KDE desktop settings coverage and live-audio safeguards."""
import json
import tempfile
import unittest
from pathlib import Path

from universal_backup import FILES, make_backup, inspect_backup, restore_settings
from audio_backup import apply_audio_state
from test_audio_backup_restore import FakePactl


class Plasma6BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / 'home'
        self.home.mkdir()
        self.archive = Path(self.temp.name) / 'settings.zip'

    def write(self, rel, value):
        target = self.home / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value)
        return target

    def test_plasma6_settings_categories_backed_up_and_restored(self):
        expected = {
            'display': '.config/kwinoutputconfig.json',
            'panels': '.config/plasma-org.kde.plasma.desktop-appletsrc',
            'power': '.config/powerdevilrc',
            'appearance': '.config/plasmarc',
            'keyboard': '.config/kglobalshortcutsrc',
            'notifications': '.config/plasmanotifyrc',
            'region': '.config/plasma-localerc',
            'fileassoc': '.config/mimeapps.list',
        }
        for cat, rel in expected.items():
            self.write(rel, 'BEFORE ' + cat)
        self.write('.config/kwinrulesrc', 'SPECIAL RULES')
        self.write('.config/kscreenlockerrc', 'LOCK SCREEN')
        manifest = make_backup(self.home, self.archive, expected, desktop='KDE:Plasma', distro={'opensuse'})
        self.assertEqual(manifest['empty_categories'], [])
        paths = {e['path'] for e in inspect_backup(self.archive)['files']}
        self.assertEqual(paths, set(expected.values()) | {'.config/kwinrulesrc', '.config/kscreenlockerrc'})
        for rel in paths:
            self.write(rel, 'AFTER')
        history = restore_settings(self.home, self.archive, expected, target_desktop='KDE:Plasma')
        for cat, rel in expected.items():
            self.assertEqual((self.home / rel).read_text(), 'BEFORE ' + cat)
        self.assertTrue((history / '.config/kwinoutputconfig.json').exists())
        self.assertEqual((self.home / '.config/kwinrulesrc').read_text(), 'SPECIAL RULES')

    def test_legacy_kscreen_directory_still_supported(self):
        path = '.local/share/kscreen/monitor-old'
        self.write(path, 'OLD MODE')
        result = make_backup(self.home, self.archive, {'display'}, desktop='kde')
        self.assertIn(path, {e['path'] for e in result['files']})

    def test_wireplumber_live_state_is_not_overwritten_on_restore(self):
        host = FakePactl()
        saved = self.write('.local/state/wireplumber/default-nodes', 'OLD DEVICE STATE')
        current = self.write('.config/kmixrc', 'OLD KDE AUDIO')
        meta = make_backup(self.home, self.archive, {'audio'}, desktop='kde', run=host)
        self.assertNotIn('.local/state/wireplumber/default-nodes',
                         {e['path'] for e in meta['files']})
        saved.write_text('CURRENT LIVE STATE')
        current.write_text('NEW KDE AUDIO')
        host.volume['sink'] = 99
        restore_settings(self.home, self.archive, {'audio'}, target_desktop='kde', audio_run=host)
        self.assertEqual(saved.read_text(), 'CURRENT LIVE STATE')
        self.assertEqual(current.read_text(), 'OLD KDE AUDIO')
        self.assertEqual(host.volume['sink'], 20)

    def test_false_positive_audio_commands_are_detected(self):
        host = FakePactl()
        snapshot = {'backend':'pactl', 'sink':{'name':host.sink,'volume':40,'muted':False},
                    'source':{'name':host.source,'volume':35,'muted':False}}
        def ignore_successful_sets(args, timeout):
            if args[1].startswith('set-'):
                return True, '', ''
            return host(args, timeout)
        with self.assertRaisesRegex(RuntimeError, 'was not restored'):
            apply_audio_state(ignore_successful_sets, snapshot)


if __name__ == '__main__':
    unittest.main()
