"""Host-free unit checks for RPM routing and controlled removal commands."""
import ast
import pathlib
import re
import unittest

p = pathlib.Path(__file__).resolve().parents[1] / 'main.py'
ast_tree = ast.parse(p.read_text(encoding='utf-8'))
functions = {'desktop_rpm_packages', 'rpm_erase_test', 'rpm_regular_remove_args',
             'rpm_transaction_preview', 'package_is_protected', 'removal_preflight'}
nodes = [n for n in ast_tree.body if isinstance(n, ast.FunctionDef) and n.name in functions]
ns = {'re': re, 'tr': lambda nl,en: en, 'command': lambda *_args, **_kwargs: (False, '', ''),
      'native_manager': lambda _: 'dnf5', 'available': lambda x: x == 'pkexec'}
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(p), 'exec'), ns)

class TestNativeRpm(unittest.TestCase):
    def test_protected(self):
        self.assertTrue(ns['package_is_protected']('gnome-shell'))
        self.assertTrue(ns['package_is_protected']('systemd'))
        self.assertFalse(ns['package_is_protected']('wireshark'))
    def test_desktop_ownership(self):
        def fake(argv, timeout=0):
            if argv[0] == 'find': return True, '/usr/share/applications/a.desktop\n/usr/share/applications/b.desktop\n', ''
            if argv[0] == 'rpm': return True, 'wireshark\ngnome-shell\n', ''
            return False, '', ''
        ns['command'] = fake
        self.assertEqual(ns['desktop_rpm_packages'](), {'wireshark'})
    def test_rpm_erase_preflight(self):
        ns['command'] = lambda *_a, **_k: (True, '', '')
        self.assertEqual(ns['rpm_erase_test']('wireshark'), (True, ''))
        ns['command'] = lambda *_a, **_k: (False, '', 'requires protected-core-package')
        self.assertFalse(ns['rpm_erase_test']('wireshark')[0])
    def test_regular_managers_no_force(self):
        for manager in ('dnf', 'dnf5', 'zypper'):
            cmd = ns['rpm_regular_remove_args'](manager, 'wireshark')
            self.assertIn('wireshark', cmd)
            self.assertNotIn('--nodeps', cmd)
            self.assertNotIn('--force', cmd)
            self.assertNotIn('--allowerasing', cmd)
        self.assertIn('--no-autoremove', ns['rpm_regular_remove_args']('dnf5', 'wireshark'))
        self.assertIn('--no-clean-deps', ns['rpm_regular_remove_args']('zypper', 'wireshark'))
    def test_rpm_preflight_blocks_dependency_failure(self):
        ns['native_manager'] = lambda _: 'zypper'
        ns['desktop_rpm_packages'] = lambda: {'wireshark'}
        ns['rpm_erase_test'] = lambda name: (False, 'otherpackage requires wireshark')
        self.assertFalse(ns['removal_preflight']('RPM', 'wireshark')[0])
        ns['rpm_erase_test'] = lambda name: (True, '')
        self.assertTrue(ns['removal_preflight']('RPM', 'wireshark')[0])
    def test_dnf_requires_user_requested(self):
        ns['native_manager'] = lambda _: 'dnf5'
        ns['desktop_rpm_packages'] = lambda: {'wireshark'}
        ns['command'] = lambda *_a, **_k: (True, 'firefox\n', '')
        self.assertFalse(ns['removal_preflight']('RPM', 'wireshark')[0])
    def test_zypper_dry_run(self):
        commands=[]
        def mock(argv, timeout=0):
            commands.append(argv)
            return True, 'The following package is going to be REMOVED:\n wireshark', ''
        ns['command'] = mock
        ok, preview = ns['rpm_transaction_preview']('zypper', 'wireshark')
        self.assertTrue(ok)
        self.assertIn('--dry-run', commands[-1])
        self.assertIn('--no-clean-deps', commands[-1])

if __name__ == '__main__': unittest.main()
