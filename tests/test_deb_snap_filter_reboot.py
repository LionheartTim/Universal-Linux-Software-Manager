"""Regression checks: DEB/Snap GUI-only inventories and universal reboot notice."""
import ast
import re
import unittest
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / 'main.py'
SOURCE = PATH.read_text(encoding='utf-8')
TREE = ast.parse(SOURCE)
NAMES = {'desktop_deb_packages', 'desktop_snap_packages', 'removal_preflight'}
NODES = [n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name in NAMES]


def make_namespace(run, allowed_deb=None, allowed_snap=None):
    def protect(name):
        return name in {'gnome-shell', 'systemd', 'libc6', 'snapd'}
    ns = {'re': re, 'command': run, 'tr': lambda nl, en: en,
          'package_is_protected': protect}
    exec(compile(ast.Module(body=NODES, type_ignores=[]), str(PATH), 'exec'), ns)
    if allowed_deb is not None:
        ns['desktop_deb_packages'] = lambda: allowed_deb
    if allowed_snap is not None:
        ns['desktop_snap_packages'] = lambda: allowed_snap
    return ns


class DEBInventoryTests(unittest.TestCase):
    def test_explicit_graphical_and_not_core_or_dependency(self):
        desktop = ['/usr/share/applications/firefox.desktop',
                   '/usr/share/applications/gnome-shell.desktop',
                   '/usr/share/applications/core-helper.desktop',
                   '/usr/share/applications/automatic.desktop']
        def run(argv, timeout=0):
            if argv[0] == 'find':
                return True, '\n'.join(desktop), ''
            if argv[:2] == ['dpkg-query', '-S']:
                # The owners are fully qualified; no guesses from filenames.
                return True, '\n'.join(['firefox: '+desktop[0],
                                         'gnome-shell: '+desktop[1],
                                         'important-helper: '+desktop[2],
                                         'automatic-app: '+desktop[3]]), ''
            if argv == ['apt-mark', 'showmanual']:
                return True, 'firefox\ngnome-shell\nimportant-helper\nlibc6\nubuntu-desktop\n', ''
            if argv[:2] == ['dpkg-query', '-W']:
                name = argv[-1]
                priority = 'important' if name == 'important-helper' else 'optional'
                return True, f'{name}\tno\t{priority}\tinstall ok installed', ''
            raise AssertionError(argv)
        ns = make_namespace(run)
        self.assertEqual(ns['desktop_deb_packages'](), {'firefox'})

    def test_check_failure_hides_all_deb_system_packages(self):
        def run(argv, timeout=0):
            if argv[0] == 'find': return True, '/usr/share/applications/firefox.desktop', ''
            if argv[:2] == ['dpkg-query', '-S']:
                return True, 'firefox: /usr/share/applications/firefox.desktop', ''
            if argv == ['apt-mark', 'showmanual']:
                return False, '', 'apt database unavailable'
            raise AssertionError(argv)
        self.assertIsNone(make_namespace(run)['desktop_deb_packages']())

    def test_unowned_launcher_is_not_an_application(self):
        def run(argv, timeout=0):
            if argv[0] == 'find': return True, '/usr/share/applications/unowned.desktop', ''
            if argv[:2] == ['dpkg-query', '-S']:
                return False, '', 'dpkg-query: no path found matching pattern /usr/share/applications/unowned.desktop'
            if argv == ['apt-mark', 'showmanual']: return True, 'firefox', ''
            raise AssertionError(argv)
        self.assertEqual(make_namespace(run)['desktop_deb_packages'](), set())

    def test_deb_removal_requires_verified_gui_package(self):
        def run(argv, timeout=0):
            if argv[:2] == ['dpkg-query', '-W']:
                return True, 'no\tinstall ok installed', ''
            if argv[:3] == ['apt-get', '-s', 'remove']:
                return True, 'Remv firefox [1.0]', ''
            raise AssertionError(argv)
        ns = make_namespace(run, allowed_deb={'firefox'})
        self.assertTrue(ns['removal_preflight']('DEB', 'firefox')[0])
        self.assertFalse(ns['removal_preflight']('DEB', 'libc6')[0])


class SnapInventoryTests(unittest.TestCase):
    def test_gui_snap_launchers_only(self):
        paths = '\n'.join('/var/lib/snapd/desktop/applications/'+x for x in (
            'firefox_firefox.desktop', 'vlc_vlc.desktop', 'core22_tool.desktop',
            'gtk-common-themes_gtk-common-themes.desktop', 'gnome-42-2204_tool.desktop',
            'snapd-desktop-integration_tool.desktop', 'snapd_tool.desktop',
            'mesa-2404_runtime.desktop', 'bare_helper.desktop', 'not-a-snap.desktop'))
        def run(argv, timeout=0):
            if argv[0] == 'find': return True, paths, ''
            raise AssertionError(argv)
        self.assertEqual(make_namespace(run)['desktop_snap_packages'](), {'firefox', 'vlc'})

    def test_snap_failed_verification_displays_nothing(self):
        def run(argv, timeout=0):
            if argv[0] == 'find': return False, '', 'Permission denied'
            raise AssertionError(argv)
        self.assertIsNone(make_namespace(run)['desktop_snap_packages']())

    def test_snap_remove_checks_gui_ownership_and_installed_name(self):
        calls = []
        def run(argv, timeout=0):
            calls.append(argv)
            if argv[:2] == ['snap', 'list']:
                return True, 'Name Version Rev Tracking Publisher Notes\nfirefox 1 1 latest/stable mozilla -', ''
            raise AssertionError(argv)
        ns = make_namespace(run, allowed_snap={'firefox'})
        self.assertTrue(ns['removal_preflight']('Snap','firefox')[0])
        self.assertFalse(ns['removal_preflight']('Snap','core22')[0])
        self.assertEqual(calls, [['snap', 'list', 'firefox']])


class GuiAndRebootTests(unittest.TestCase):
    def test_both_tab_filters_fail_closed_and_both_removals_preflight(self):
        cls = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == 'PackageTab')
        fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'reload')
        code = ast.get_source_segment(SOURCE, fn)
        self.assertIn("if k == 'DEB':\n                    allowed = desktop_deb_packages()", code)
        self.assertIn("if k == 'Snap':\n                    allowed = desktop_snap_packages()", code)
        self.assertIn('rows = []', code)
        self.assertIn("if k in ('DEB', 'Arch', 'Snap'):", SOURCE)

    def test_reboot_notice_is_global_not_gnome_only(self):
        cls = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == 'BackupPanel')
        finish = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_restore_finish')
        code = ast.get_source_segment(SOURCE, finish)
        self.assertIn("if done or restart or partial:", code)
        self.assertIn('HERSTART JE COMPUTER', code)
        self.assertIn('REBOOT YOUR COMPUTER', code)
        self.assertNotIn("self.desktop','')=='gnome'", code)
        self.assertIn('Reboot your computer to fully apply all settings', SOURCE)
        self.assertIn('A reboot is needed after restore', SOURCE)


if __name__ == '__main__':
    unittest.main()
