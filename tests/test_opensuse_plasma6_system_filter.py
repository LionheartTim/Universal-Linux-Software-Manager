"""Keep openSUSE Plasma system packages out of removable RPM inventory."""
import ast
import pathlib
import re
import unittest

SOURCE = pathlib.Path(__file__).resolve().parents[1] / 'main.py'
TREE = ast.parse(SOURCE.read_text(encoding='utf-8'))
WANTED = {'package_is_protected', 'desktop_rpm_packages', 'removal_preflight'}
NODES = [node for node in TREE.body if isinstance(node, ast.FunctionDef) and node.name in WANTED]
NS = {
    're': re,
    'tr': lambda nl, en: en,
    'available': lambda program: True,
    'native_manager': lambda _: 'zypper',
    'rpm_erase_test': lambda name: (True, ''),
    'command': lambda *_args, **_kwargs: (False, '', ''),
}
exec(compile(ast.Module(body=NODES, type_ignores=[]), str(SOURCE), 'exec'), NS)


class OpenSUSEPlasmaSystemFilterTests(unittest.TestCase):
    def test_hide_plasma_packages_and_desktop_foundations(self):
        for pkg in (
            'plasma6-workspace', 'plasma6-desktop', 'plasma6-systemmonitor',
            'plasma6-settings', 'plasma6-integration', 'libplasma6-components',
            'kf6-kio', 'libKF6CoreAddons6', 'kcm_kscreen6', 'patterns-kde-kde_plasma',
            'kwin6', 'powerdevil6', 'xdg-desktop-portal-kde',
        ):
            with self.subTest(pkg=pkg):
                self.assertTrue(NS['package_is_protected'](pkg))

    def test_keep_independent_graphical_applications(self):
        for pkg in ('brave-browser', 'vlc', 'wireshark', 'firefox',
                    'org.kde.kate', 'kdenlive', 'okular', 'libreoffice-writer'):
            with self.subTest(pkg=pkg):
                self.assertFalse(NS['package_is_protected'](pkg))

    def test_desktop_launcher_ownership_does_not_enable_plasma_packages(self):
        def fake_command(args, timeout=0):
            if args[0] == 'find':
                return True, ('/usr/share/applications/plasma-systemsettings.desktop\n'
                              '/usr/share/applications/brave-browser.desktop\n'
                              '/usr/share/applications/vlc.desktop\n'
                              '/usr/share/applications/plasma-workspace.desktop\n'), ''
            if args[:2] == ['rpm', '-qf']:
                return True, 'plasma6-desktop\nbrave-browser\nvlc\nplasma6-workspace\n', ''
            return False, '', 'unexpected command'
        NS['command'] = fake_command
        self.assertEqual(NS['desktop_rpm_packages'](), {'brave-browser', 'vlc'})

    def test_removed_package_checked_even_if_called_directly(self):
        NS['native_manager'] = lambda _: 'zypper'
        NS['desktop_rpm_packages'] = lambda: {'plasma6-workspace', 'vlc'}
        NS['rpm_erase_test'] = lambda name: (True, '')
        ok, message = NS['removal_preflight']('RPM', 'plasma6-workspace')
        self.assertFalse(ok)
        self.assertIn('Protected', message)
        ok, message = NS['removal_preflight']('RPM', 'vlc')
        self.assertTrue(ok)

if __name__ == '__main__':
    unittest.main()
