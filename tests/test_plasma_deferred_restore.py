"""KDE Plasma early-login restore checks, without user services or reboots."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from universal_backup import make_backup
import plasma_deferred_restore as deferred
from test_audio_backup_restore import FakePactl


class DeferredPlasmaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / 'home'
        self.home.mkdir()
        self.archive = Path(self.tmp.name) / 'settings.zip'
        self.calls = []

    def write(self, rel, data):
        path = self.home / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data)
        return path

    def host(self, args, timeout):
        self.calls.append(args)
        if args[:2] == ['systemctl', '--user'] and 'show' in args:
            return (True, 'active\n' if '--property=ActiveState' in args else 'loaded\n', '')
        if args == ['python3', '--version']:
            return (True, 'Python 3.13\n', '')
        return (True, '', '')

    def stage(self, categories, runner=None):
        return deferred.stage_restore(self.home, self.archive, categories, 'KDE:Plasma',
                                      host_run=runner or self.host, session_type='wayland')

    def test_stages_all_settings_without_touching_live_config_and_applies_prekwin(self):
        resolution = self.write('.config/kwinoutputconfig.json', '1920x1080')
        panels = self.write('.config/plasma-org.kde.plasma.desktop-appletsrc', 'ORIGINAL PANEL')
        power = self.write('.config/powermanagementprofilesrc', 'ORIGINAL POWER')
        meta = make_backup(self.home, self.archive, {'display','panels','power'}, desktop='kde')
        for p in (resolution, panels, power):
            p.write_text('CHANGED')
        report = self.stage({'display','panels','power'})
        self.assertTrue(report['pending'])
        self.assertEqual(resolution.read_text(), 'CHANGED')
        root = deferred._root(self.home)
        self.assertEqual(json.loads((root/'status.json').read_text())['files'], 'pending')
        self.assertIn('Before=plasma-kwin_wayland.service',
                      (self.home/'.config/systemd/user'/deferred.EARLY).read_text())
        self.assertIn('WantedBy=plasma-kwin_wayland.service',
                      (self.home/'.config/systemd/user'/deferred.EARLY).read_text())
        self.assertEqual(len([x for x in self.calls if x[:3] == ['systemctl','--user','enable']]), 1)
        with patch.object(deferred, '_disable'):
            self.assertTrue(deferred.run_worker('files', home=self.home))
        self.assertEqual(resolution.read_text(), '1920x1080')
        self.assertEqual(panels.read_text(), 'ORIGINAL PANEL')
        self.assertEqual(power.read_text(), 'ORIGINAL POWER')
        status = json.loads((root/'status.json').read_text())
        self.assertEqual(status['files'], 'applied')
        self.assertEqual(status['audio'], 'not_selected')
        # One shot: should not write a second time after another manual change.
        resolution.write_text('MANUAL')
        with patch.object(deferred, '_disable'):
            self.assertTrue(deferred.run_worker('files', home=self.home))
        self.assertEqual(resolution.read_text(), 'MANUAL')
        history = Path(status['recovery_dir'])
        self.assertEqual((history/'.config/kwinoutputconfig.json').read_text(), 'CHANGED')

    def test_audio_runs_independently_after_login_with_live_device_remapping(self):
        pactl = FakePactl()
        self.write('.config/kwinoutputconfig.json', 'saved')
        make_backup(self.home, self.archive, {'audio','display'}, desktop='kde', run=pactl)
        self.write('.config/kwinoutputconfig.json', 'changed')
        pactl.volume['sink'] = 99
        self.stage({'audio','display'})
        root = deferred._root(self.home)
        self.assertTrue((self.home/'.config/systemd/user'/deferred.LATE).is_file())
        autostart = self.home/'.config/autostart'/deferred.LATE_AUTOSTART
        self.assertIn('start --no-block', autostart.read_text())
        self.assertNotIn('WantedBy=', (self.home/'.config/systemd/user'/deferred.LATE).read_text())
        with patch.object(deferred, '_disable'):
            self.assertTrue(deferred.run_worker('files', home=self.home))
        self.assertEqual((self.home/'.config/kwinoutputconfig.json').read_text(), 'saved')
        self.assertEqual(pactl.volume['sink'], 99)
        def live_runner(argv, timeout=20):
            if argv == ['pactl', 'info']:
                return True, 'Server Name: PulseAudio (on PipeWire)', ''
            return pactl(argv, timeout)
        with patch.object(deferred, '_audio_runner', side_effect=live_runner), patch.object(deferred, '_disable'):
            self.assertTrue(deferred.run_worker('audio', home=self.home))
        self.assertEqual(pactl.volume['sink'], 20)
        self.assertEqual(json.loads((root/'status.json').read_text())['audio'], 'applied')

    def test_unavailable_audio_never_rolls_back_kde_settings(self):
        pactl = FakePactl()
        screen = self.write('.config/kwinoutputconfig.json', 'saved')
        make_backup(self.home, self.archive, {'audio','display'}, desktop='kde', run=pactl)
        screen.write_text('changed')
        self.stage({'audio','display'})
        with patch.object(deferred, '_disable'):
            self.assertTrue(deferred.run_worker('files', home=self.home))
        with patch.object(deferred, '_audio_runner', return_value=(False,'','audio not ready')), \
             patch.object(deferred.time, 'sleep', return_value=None), patch.object(deferred, '_disable'):
            self.assertFalse(deferred.run_worker('audio', home=self.home))
        self.assertEqual(screen.read_text(), 'saved')
        s = json.loads((deferred._root(self.home)/'status.json').read_text())
        self.assertEqual(s['files'], 'applied')
        self.assertEqual(s['audio'], 'failed')

    def test_does_not_schedule_when_kde_systemd_unit_missing(self):
        self.write('.config/kwinoutputconfig.json', 'saved')
        make_backup(self.home, self.archive, {'display'}, desktop='kde')
        def no_unit(args, timeout):
            if 'show' in args:
                return True, 'not-found', ''
            return True, '', ''
        with self.assertRaisesRegex(RuntimeError, 'unavailable'):
            self.stage({'display'}, runner=no_unit)
        self.assertFalse((deferred._root(self.home)/'plan.json').exists())

    def test_inactive_kwin_unit_refuses_to_promise_early_restore(self):
        self.write('.config/kwinoutputconfig.json', 'saved')
        make_backup(self.home, self.archive, {'display'}, desktop='kde')
        def inactive(args, timeout):
            return (True, 'inactive' if '--property=ActiveState' in args else 'loaded', '')
        with self.assertRaisesRegex(RuntimeError, 'not using'):
            self.stage({'display'}, runner=inactive)
        self.assertFalse((deferred._root(self.home)/'plan.json').exists())

    def test_does_not_schedule_second_pending_restore(self):
        self.write('.config/kwinoutputconfig.json', 'saved')
        make_backup(self.home, self.archive, {'display'}, desktop='kde')
        self.stage({'display'})
        with self.assertRaisesRegex(RuntimeError, 'already scheduled'):
            self.stage({'display'})

    def test_tampered_plan_is_rejected_before_any_write(self):
        screen=self.write('.config/kwinoutputconfig.json','saved')
        make_backup(self.home, self.archive, {'display'}, desktop='kde')
        self.stage({'display'})
        screen.write_text('changed')
        root=deferred._root(self.home)
        plan=json.loads((root/'plan.json').read_text())
        plan['files'][0]['path']='.config/kwalletrc'
        (root/'plan.json').write_text(json.dumps(plan))
        with patch.object(deferred, '_disable'):
            self.assertFalse(deferred.run_worker('files', home=self.home))
        self.assertEqual(screen.read_text(), 'changed')
        self.assertEqual(json.loads((root/'status.json').read_text())['files'], 'failed')

    def test_portable_plasma_session_matrix_across_distros(self):
        """The same host-driven service works for Plasma 5/6 on different distros."""
        for distro, session, desktop in (
            ('Fedora KDE', 'wayland', 'KDE'),
            ('openSUSE Plasma', 'wayland', 'KDE:Plasma'),
            ('Arch KDE', 'x11', 'plasma'),
            ('Kubuntu KDE', 'x11', 'KDE'),
            ('Bazzite KDE', 'wayland', 'plasma'),
        ):
            with self.subTest(distro=distro, session=session):
                with tempfile.TemporaryDirectory() as t:
                    home = Path(t) / 'home'
                    home.mkdir()
                    config = home / '.config/kwinoutputconfig.json'
                    config.parent.mkdir(parents=True)
                    config.write_text('saved')
                    archive = Path(t) / 'backup.zip'
                    make_backup(home, archive, {'display'}, desktop='kde', distro=[distro])
                    config.write_text('changed')
                    calls = []
                    expected = deferred.KWIN_UNITS[session]

                    def host(args, timeout):
                        calls.append(args)
                        if '--property=LoadState' in args:
                            return True, 'loaded\n', ''
                        if '--property=ActiveState' in args:
                            return True, 'active\n', ''
                        return True, 'Python 3.13\n' if args == ['python3', '--version'] else '', ''

                    result = deferred.stage_restore(home, archive, {'display'},
                        target_desktop=desktop, host_run=host, session_type=session)
                    self.assertTrue(result['pending'])
                    unit_text = (home/'.config/systemd/user'/deferred.EARLY).read_text()
                    self.assertIn('Before=' + expected, unit_text)
                    self.assertIn('WantedBy=' + expected, unit_text)
                    self.assertEqual(config.read_text(), 'changed')
                    with patch.object(deferred, '_disable'):
                        self.assertTrue(deferred.run_worker('files', home=home))
                    self.assertEqual(config.read_text(), 'saved')

    def test_missing_session_env_infers_active_kwin_unit(self):
        """Some sandbox/host combinations omit XDG_SESSION_TYPE."""
        for expected_session in ('wayland', 'x11'):
            with self.subTest(session=expected_session):
                calls = []
                def host(args, timeout):
                    calls.append(args)
                    if '--property=LoadState' in args:
                        return True, 'loaded', ''
                    if '--property=ActiveState' in args:
                        return True, ('active' if args[-1] == deferred.KWIN_UNITS[expected_session]
                                      else 'inactive'), ''
                    return True, '', ''
                with patch.dict('os.environ', {'XDG_SESSION_TYPE': ''}):
                    session, unit = deferred.detect_kwin_unit(host)
                self.assertEqual(session, expected_session)
                self.assertEqual(unit, deferred.KWIN_UNITS[expected_session])
                self.assertEqual(sum('--property=ActiveState' in c for c in calls), 2)

    def test_without_explicit_session_requires_unique_active_kwin_unit(self):
        def both_active(args, timeout):
            return True, 'loaded' if '--property=LoadState' in args else 'active', ''
        with self.assertRaisesRegex(RuntimeError, 'exactly one'):
            deferred.detect_kwin_unit(both_active, session_type='')
        def none_active(args, timeout):
            return True, 'loaded' if '--property=LoadState' in args else 'inactive', ''
        with self.assertRaisesRegex(RuntimeError, 'exactly one'):
            deferred.detect_kwin_unit(none_active, session_type='')

    def test_unsupported_plasma_startup_is_never_silently_restored(self):
        def non_systemd(args, timeout):
            return True, 'not-found', ''
        with self.assertRaisesRegex(RuntimeError, 'unavailable'):
            deferred.detect_kwin_unit(non_systemd, session_type='x11')
        with self.assertRaisesRegex(RuntimeError, 'exactly one'):
            deferred.detect_kwin_unit(non_systemd, session_type='')
        with self.assertRaisesRegex(RuntimeError, 'Unsupported KDE session'):
            deferred.detect_kwin_unit(non_systemd, session_type='tty')

    def test_older_plasma_kscreen_and_keyboard_files_follow_same_path(self):
        old_display = self.write('.local/share/kscreen/old-monitor-id', 'OLD MONITOR')
        keyboard = self.write('.config/kcminputrc', 'OLD KEYBOARD')
        make_backup(self.home, self.archive, {'display', 'keyboard'}, desktop='kde')
        old_display.write_text('CHANGED')
        keyboard.write_text('CHANGED')
        self.stage({'display', 'keyboard'})
        with patch.object(deferred, '_disable'):
            self.assertTrue(deferred.run_worker('files', home=self.home))
        self.assertEqual(old_display.read_text(), 'OLD MONITOR')
        self.assertEqual(keyboard.read_text(), 'OLD KEYBOARD')

    def test_other_desktops_are_not_routed_through_plasma(self):
        self.write('.config/kwinoutputconfig.json', 'saved')
        make_backup(self.home, self.archive, {'display'}, desktop='kde')
        for desktop in ('GNOME', 'Xfce', 'LXQt', 'MATE'):
            with self.subTest(desktop=desktop):
                with self.assertRaisesRegex(ValueError, 'matching KDE'):
                    deferred.stage_restore(self.home, self.archive, {'display'},
                        target_desktop=desktop, host_run=self.host, session_type='wayland')
        self.assertFalse(self.calls)

    def test_no_host_escapes_on_desktop_mismatch(self):
        self.write('.config/kwinoutputconfig.json', 'saved')
        make_backup(self.home, self.archive, {'display'}, desktop='kde')
        with self.assertRaisesRegex(ValueError, 'matching KDE'):
            deferred.stage_restore(self.home, self.archive, {'display'}, target_desktop='xfce',
                                   host_run=self.host, session_type='wayland')
        self.assertFalse(self.calls)

if __name__ == '__main__': unittest.main()
