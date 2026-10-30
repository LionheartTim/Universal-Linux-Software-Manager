"""Physical and virtual sound-device changes must not lose unrelated KDE settings."""
import ast
import tempfile
import unittest
from pathlib import Path

from universal_backup import make_backup, restore_settings
from audio_backup import prepare_audio_restore
from test_audio_backup_restore import FakePactl


class AudioDeviceFallbackTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / 'home'
        self.home.mkdir()
        self.path = self.home / '.config/kwinoutputconfig.json'
        self.path.parent.mkdir(parents=True)
        self.path.write_text('RESOLUTION 1280x800', encoding='utf-8')
        self.archive = Path(tmp.name) / 'settings.zip'
        self.host = FakePactl()
        self.host.volume['sink'] = 30
        self.host.mute['sink'] = True
        make_backup(self.home, self.archive, {'display', 'audio'},
                    desktop='kde', run=self.host)
        self.path.write_text('RESOLUTION 1920x1080', encoding='utf-8')
        self.host.volume['sink'] = 90
        self.host.mute['sink'] = False

    def test_one_output_renamed_restores_volume_and_display_with_warning(self):
        new = 'alsa_output.pci-0000_00_1b.0.pro-output-0'
        self.host.installed['sink'] = [new]
        self.host.sink = new
        result = restore_settings(self.home, self.archive, {'display', 'audio'},
                                  'kde', audio_run=self.host,
                                  audio_policy='best_effort', return_report=True)
        self.assertIn('only available', ' '.join(result['warnings']))
        self.assertEqual(self.path.read_text(), 'RESOLUTION 1280x800')
        self.assertEqual(self.host.volume['sink'], 30)
        self.assertTrue(self.host.mute['sink'])
        self.assertTrue((Path(result['recovery_dir']) / 'audio-before-restore.json').is_file())

    def test_ambiguous_output_skips_audio_but_restores_display_with_explicit_warning(self):
        self.host.installed['sink'] = ['new-sink-a', 'new-sink-b']
        self.host.sink = 'new-sink-a'
        result = restore_settings(self.home, self.archive, {'display', 'audio'},
                                  'kde', audio_run=self.host,
                                  audio_policy='best_effort', return_report=True)
        self.assertIn('Audio was not restored', ' '.join(result['warnings']))
        self.assertEqual(self.path.read_text(), 'RESOLUTION 1280x800')
        self.assertEqual(self.host.volume['sink'], 90)
        self.assertFalse(self.host.mute['sink'])

    def test_no_output_still_restores_display_with_warning(self):
        self.host.installed['sink'] = []
        result = restore_settings(self.home, self.archive, {'display', 'audio'},
                                  'kde', audio_run=self.host,
                                  audio_policy='best_effort', return_report=True)
        self.assertIn('Audio was not restored', ' '.join(result['warnings']))
        self.assertEqual(self.path.read_text(), 'RESOLUTION 1280x800')

    def test_strict_policy_preserves_existing_all_or_nothing_behavior(self):
        self.host.installed['sink'] = []
        with self.assertRaisesRegex(RuntimeError, 'unavailable'):
            restore_settings(self.home, self.archive, {'display', 'audio'},
                             'kde', audio_run=self.host)
        self.assertEqual(self.path.read_text(), 'RESOLUTION 1920x1080')

    def test_renamed_mic_with_multiple_sources_skips_mic_without_skipping_speakers(self):
        self.host.installed['source'] = ['microphone-a', 'monitor-b']
        self.host.source = 'microphone-a'
        self.host.volume['sink'] = 50
        result = restore_settings(self.home, self.archive, {'display', 'audio'},
                                  'kde', audio_run=self.host,
                                  audio_policy='best_effort', return_report=True)
        self.assertIn('microphone', ' '.join(result['warnings']).lower())
        self.assertEqual(self.host.volume['sink'], 30)
        self.assertEqual(self.path.read_text(), 'RESOLUTION 1280x800')

    def test_gui_shows_partial_instead_of_falsely_reporting_success(self):
        source = (Path(__file__).resolve().parents[1]/'main.py').read_text()
        tree = ast.parse(source)
        self.assertIn("audio_policy='best_effort', return_report=True", source)
        self.assertIn('Partially restored', source)
        self.assertIn('Partially restored: {partial}', source)
        self.assertIn('Problems: {errors + partial}', source)


if __name__ == '__main__':
    unittest.main()
