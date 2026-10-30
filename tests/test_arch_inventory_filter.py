"""Arch GNOME regression tests: never show all pacman system packages."""
import ast
import unittest
from pathlib import Path

MAIN = Path(__file__).resolve().parents[1] / 'main.py'
SOURCE = MAIN.read_text(encoding='utf-8')
TREE = ast.parse(SOURCE)
NAMES = {'desktop_arch_packages', 'package_is_protected', 'removal_preflight'}
NODES = [node for node in TREE.body if isinstance(node, ast.FunctionDef) and node.name in NAMES]


def context(runner):
    import re
    ns = {
        're': re,
        'command': runner,
        'tr': lambda nl, en: en,
    }
    exec(compile(ast.Module(body=NODES, type_ignores=[]), str(MAIN), 'exec'), ns)
    return ns


class ArchInventoryFilterTests(unittest.TestCase):
    def good_runner(self, argv, timeout=0):
        if argv[0] == 'find':
            return True, ('/usr/share/applications/firefox.desktop\n'
                          '/usr/share/applications/org.gnome.Nautilus.desktop\n'
                          '/usr/share/applications/gnome-shell.desktop\n'), ''
        if argv[:2] == ['pacman', '-Qqo']:
            return True, 'firefox\nnautilus\ngnome-shell\n', ''
        if argv == ['pacman', '-Qqe']:
            return True, 'filesystem\nfftw\nfirefox\ngnome-shell\nbase\n', ''
        if argv[:2] == ['pacman', '-R']:
            return True, 'firefox\n', ''
        raise AssertionError('Unexpected command: '+str(argv))

    def test_only_explicit_graphical_apps_not_the_whole_system(self):
        allowed = context(self.good_runner)['desktop_arch_packages']()
        self.assertEqual(allowed, {'firefox'})
        for item in ('filesystem', 'fftw', 'base', 'gnome-shell', 'nautilus'):
            self.assertNotIn(item, allowed)

    def test_no_desktop_entries_does_not_expose_the_inventory(self):
        def runner(argv, timeout=0):
            if argv[0] == 'find': return True, '', ''
            if argv == ['pacman', '-Qqe']: return True, 'filesystem\nglibc\n', ''
            raise AssertionError(argv)
        self.assertEqual(context(runner)['desktop_arch_packages'](), set())

    def test_failure_to_check_explicit_reason_fails_closed(self):
        def runner(argv, timeout=0):
            if argv[0] == 'find': return True, '/usr/share/applications/firefox.desktop\n', ''
            if argv[:2] == ['pacman', '-Qqo']: return True, 'firefox\n', ''
            if argv == ['pacman', '-Qqe']: return False, '', 'database unavailable'
            raise AssertionError(argv)
        self.assertIsNone(context(runner)['desktop_arch_packages']())

    def test_unowned_desktop_files_do_not_hide_other_owned_apps(self):
        def runner(argv, timeout=0):
            if argv[0] == 'find': return True, '/usr/share/applications/firefox.desktop\n/usr/share/applications/unowned.desktop\n', ''
            if argv[:2] == ['pacman', '-Qqo']: return False, 'firefox\n', 'No package owns unowned.desktop'
            if argv == ['pacman', '-Qqe']: return True, 'firefox\n', ''
            raise AssertionError(argv)
        self.assertEqual(context(runner)['desktop_arch_packages'](), {'firefox'})

    def test_unavailable_desktop_ownership_fails_closed(self):
        def runner(argv, timeout=0):
            if argv[0] == 'find': return True, '/usr/share/applications/firefox.desktop\n', ''
            if argv[:2] == ['pacman', '-Qqo']: return False, '', 'pacman database unavailable'
            raise AssertionError(argv)
        self.assertIsNone(context(runner)['desktop_arch_packages']())

    def test_removal_preflight_checks_graphical_reason_again(self):
        ns = context(self.good_runner)
        self.assertTrue(ns['removal_preflight']('Arch', 'firefox')[0])
        self.assertFalse(ns['removal_preflight']('Arch', 'filesystem')[0])
        self.assertFalse(ns['removal_preflight']('Arch', 'gnome-shell')[0])
        self.assertFalse(ns['removal_preflight']('Arch', 'nautilus')[0])

    def test_arch_gui_reload_filters_and_does_not_mutate_on_listing(self):
        panel = next(node for node in TREE.body if isinstance(node, ast.ClassDef) and node.name == 'PackageTab')
        reload_node = next(node for node in panel.body if isinstance(node, ast.FunctionDef) and node.name == 'reload')
        code = ast.get_source_segment(SOURCE, reload_node)
        self.assertIn("'Arch': ['pacman', '-Q']", code)
        self.assertIn('allowed = desktop_arch_packages()', code)
        self.assertIn('rows = [r for r in rows if r[2] in allowed]', code)
        self.assertIn("if allowed is None:", code)
        self.assertIn('rows = []', code)


if __name__ == '__main__':
    unittest.main()
