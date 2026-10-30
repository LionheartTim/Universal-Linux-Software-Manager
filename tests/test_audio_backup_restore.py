"""End-to-end tests for host audio snapshot and safe settings ZIP restoration.

No host audio services or Qt are needed: a fake pactl runner exercises precisely
what the Flatpak's flatpak-spawn --host wrapper would invoke on Xubuntu.
"""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from audio_backup import capture_audio_state, apply_audio_state, validate
from universal_backup import make_backup, inspect_backup, restore_settings
from local_file_backup import (create_backup as make_bu, inspect_backup as inspect_bu,
                               extract_settings as extract_bu_settings)


class FakePactl:
    def __init__(self):
        self.sink = 'alsa_output.test.analog-stereo'
        self.source = 'alsa_input.test.analog-stereo'
        self.volume = {'sink': 20, 'source': 35}
        self.mute = {'sink': False, 'source': False}
        self.installed = {'sink': [self.sink], 'source': [self.source]}
        self.calls = []
        self.fail_command = None

    def __call__(self, argv, timeout):
        args = list(argv)
        self.calls.append(tuple(args))
        if args[0] != 'pactl': return False, '', 'Unexpected program'
        if tuple(args[1:3]) == self.fail_command:
            return False, '', 'Simulated failure'
        action = args[1]
        if action == 'info': return True, 'Server Name: PulseAudio (on PipeWire)\n', ''
        if action.startswith('get-default-'):
            role = action.split('-')[-1]
            return True, getattr(self, role) + '\n', ''
        if action.startswith('get-') and action.endswith('-volume'):
            role = action[len('get-'):-len('-volume')]
            return True, f'Volume: front-left: 123 / {self.volume[role]}% / front-right: 123 / {self.volume[role]}%\n', ''
        if action.startswith('get-') and action.endswith('-mute'):
            role = action[len('get-'):-len('-mute')]
            return True, 'Mute: yes\n' if self.mute[role] else 'Mute: no\n', ''
        if action == 'list' and len(args) >= 4 and args[2] == 'short':
            role = args[3][:-1]
            return True, ''.join(f'{i}\t{name}\tmodule-test\n' for i,name in enumerate(self.installed[role])), ''
        if action.startswith('set-default-'):
            role = action.split('-')[-1]
            setattr(self, role, args[2])
            return True, '', ''
        if action.startswith('set-') and action.endswith('-volume'):
            role = action[len('set-'):-len('-volume')]
            self.volume[role] = int(args[3].rstrip('%'))
            return True, '', ''
        if action.startswith('set-') and action.endswith('-mute'):
            role = action[len('set-'):-len('-mute')]
            self.mute[role] = args[3] == '1'
            return True, '', ''
        return False, '', f'Unexpected pactl command: {args}'


class AudioRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / 'home'
        self.home.mkdir()
        self.archive = Path(self.temp.name) / 'settings.zip'
        self.host = FakePactl()

    def test_capture_restore_default_device_volume_mute_and_source(self):
        self.host.mute['sink'] = True
        self.host.volume['sink'] = 60
        created = make_backup(self.home, self.archive, {'audio'}, desktop='xfce', run=self.host)
        self.assertNotIn('audio', created['empty_categories'])
        self.assertIsNotNone(created['audio_state'])
        self.assertIn('audio/state.json', zipfile.ZipFile(self.archive).namelist())
        self.host.volume.update({'sink': 13, 'source': 70})
        self.host.mute['sink'] = False
        recovery = restore_settings(self.home, self.archive, {'audio'}, 'xfce', audio_run=self.host)
        self.assertEqual(self.host.volume, {'sink':60, 'source':35})
        self.assertTrue(self.host.mute['sink'])
        self.assertTrue((recovery/'audio-before-restore.json').exists())
        self.assertEqual((recovery/'audio-before-restore.json').stat().st_mode & 0o777, 0o600)

    def test_missing_pactl_does_not_clobber_existing_backup(self):
        self.archive.write_bytes(b'previous valid backup placeholder')
        def broken(args, timeout): return False, '', 'pactl: command not found'
        with self.assertRaisesRegex(RuntimeError, 'pactl'):
            make_backup(self.home, self.archive, {'audio'}, desktop='xfce', run=broken)
        self.assertEqual(self.archive.read_bytes(), b'previous valid backup placeholder')

    def test_missing_saved_audio_device_fails_before_any_write(self):
        background = self.home/'.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-desktop.xml'
        background.parent.mkdir(parents=True)
        background.write_text('ORIGINAL WALLPAPER')
        make_backup(self.home, self.archive, {'audio','appearance'}, desktop='xfce', run=self.host)
        background.write_text('CURRENT WALLPAPER')
        self.host.installed['sink'].clear()
        with self.assertRaisesRegex(RuntimeError, 'unavailable'):
            restore_settings(self.home, self.archive, {'audio','appearance'}, 'xfce', audio_run=self.host)
        self.assertEqual(background.read_text(), 'CURRENT WALLPAPER')

    def test_bad_audio_checksum_rejected_before_restore(self):
        make_backup(self.home, self.archive, {'audio'}, desktop='xfce', run=self.host)
        tampered = self.archive.with_name('modified.zip')
        with zipfile.ZipFile(self.archive) as src, zipfile.ZipFile(tampered, 'w') as dst:
            for name in src.namelist():
                data = src.read(name)
                if name == 'audio/state.json': data = b'x' + data[1:]
                dst.writestr(name, data)
        with self.assertRaisesRegex(ValueError, 'checksum'):
            inspect_backup(tampered)

    def test_invalid_snapshot_is_rejected(self):
        with self.assertRaises(ValueError):
            validate({'backend':'pactl','sink':{'name':';rm -rf /','volume':20,'muted':False},'source':None})
        with self.assertRaises(ValueError):
            validate({'backend':'pactl','sink':{'name':'alsa_output.test','volume':900,'muted':False},'source':None})

    def test_other_xfce_settings_covered(self):
        for path in (
            '.config/xfce4/xfconf/xfce-perchannel-xml/displays.xml',
            '.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-desktop.xml',
            '.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml',
            '.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-power-manager.xml',
            '.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-keyboard-shortcuts.xml',
        ):
            p=self.home/path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(path)
        meta=make_backup(self.home,self.archive,
            {'display','appearance','panels','power','keyboard'},desktop='xfce')
        self.assertEqual(len(meta['files']), 5)
        self.assertFalse(meta['empty_categories'])
        inspect_backup(self.archive)

    def test_nested_bu_preserves_audio_snapshot_end_to_end(self):
        make_backup(self.home, self.archive, {'audio'}, desktop='xfce', run=self.host)
        outer = self.archive.with_suffix('.bu')
        make_bu(outer, [], self.archive, source_desktop='xfce', source_distro={'ubuntu'})
        manifest = inspect_bu(outer)
        self.assertIsNotNone(manifest['settings'])
        stage = self.home/'stage'
        stage.mkdir()
        inner = extract_bu_settings(outer,stage)
        self.host.volume['sink'] = 83
        restore_settings(self.home,inner,{'audio'},'xfce',audio_run=self.host)
        self.assertEqual(self.host.volume['sink'],20)

    def test_dconf_partial_failure_restores_existing_customization(self):
        def run(args, timeout):
            if args[:2] == ['dconf','dump']:
                return True, '[group]\nkey=old\n', ''
            return False, '', 'unexpected'
        make_backup(self.home,self.archive,{'appearance'},desktop='gnome',run=run)
        values=[]
        def load(prefix, data):
            values.append((prefix,data))
            # Fail once at the first load to test best-effort rollback.
            return len(values)>1
        with self.assertRaisesRegex(RuntimeError,'dconf restore failed'):
            restore_settings(self.home,self.archive,{'appearance'},'gnome',load,dconf_run=run)
        self.assertGreaterEqual(len(values),2)
        self.assertEqual(values[-1][1],'[group]\nkey=old\n')

    def test_legacy_backup_without_live_audio_explains_limitation(self):
        legacy = self.home/'.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-mixer.xml'
        legacy.parent.mkdir(parents=True)
        legacy.write_text('<volume/>')
        make_backup(self.home,self.archive,{'audio'},desktop='xfce',run=self.host)
        # Simulate an older archive with a valid audio config but no live snapshot.
        legacyzip = self.archive.with_name('old.zip')
        with zipfile.ZipFile(self.archive) as src, zipfile.ZipFile(legacyzip,'w') as dst:
            m = json.loads(src.read('manifest.json'))
            m.pop('audio_state',None)
            m['schema']=3
            for member in src.namelist():
                if member == 'audio/state.json': continue
                dst.writestr(member, json.dumps(m) if member == 'manifest.json' else src.read(member))
        inspect_backup(legacyzip)
        with self.assertRaisesRegex(ValueError, 'older backup'):
            restore_settings(self.home, legacyzip, {'audio'}, 'xfce', audio_run=self.host)


if __name__ == '__main__': unittest.main()
