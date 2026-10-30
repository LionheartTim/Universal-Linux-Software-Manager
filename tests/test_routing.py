"""No host commands: load and test small pure parts of main.py via AST."""
import ast, pathlib, re, unittest
src = pathlib.Path(__file__).resolve().parents[1] / 'main.py'
tree = ast.parse(src.read_text(encoding='utf-8'))
fn_names = {'native_manager', 'suitable_manager', 'package_is_protected',
            'rpm_package_name', 'requested_layers', 'flatpak_removal_installation_arg'}
functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in fn_names]
ns = {'re': re, 'host_os_families': lambda: set(),
      'available': lambda _: False, 'command': lambda *args: (False,'',''),
      'tr': lambda nl,en: en}
exec(compile(ast.Module(body=functions, type_ignores=[]), str(src), 'exec'), ns)

class TestRouting(unittest.TestCase):
    def route(self, family, available):
        ns['host_os_families'] = lambda: set(family)
        ns['available'] = lambda program: program in available
        ns['command'] = lambda *args: (False, '', '')
    def test_fedora(self):
        self.route(['fedora'], ['dnf5', 'rpm'])
        self.assertEqual(ns['native_manager']('RPM'), 'dnf5')
        self.assertIsNone(ns['native_manager']('DEB'))
        self.assertIsNone(ns['native_manager']('Arch'))
    def test_opensuse(self):
        self.route(['opensuse-tumbleweed', 'suse'], ['zypper','rpm'])
        self.assertEqual(ns['native_manager']('RPM'), 'zypper')
        self.assertIsNone(ns['native_manager']('DEB'))
    def test_microos_blocked(self):
        self.route(['opensuse-microos', 'suse'], ['zypper'])
        self.assertIsNone(ns['native_manager']('RPM'))
    def test_ubuntu_with_foreign_dnf(self):
        self.route(['ubuntu','debian'], ['apt-get','dnf'])
        self.assertEqual(ns['native_manager']('DEB'), 'apt-get')
        self.assertIsNone(ns['native_manager']('RPM'))
    def test_arch(self):
        self.route(['arch'], ['pacman','dnf'])
        self.assertEqual(ns['native_manager']('Arch'), 'pacman')
        self.assertIsNone(ns['native_manager']('RPM'))
    def test_protected(self):
        self.assertTrue(ns['package_is_protected']('glibc'))
        self.assertTrue(ns['package_is_protected']('linux-image-6.2'))
        self.assertFalse(ns['package_is_protected']('wireshark'))
    def test_rpm_layers(self):
        packages = ns['requested_layers']({'requested-packages':['wireshark'],
             'requested-local-packages':['chatgpt-26.1007.21434-1.x86_64']})
        self.assertEqual(packages, {'wireshark','chatgpt'})
    def test_flatpak_installations(self):
        self.assertEqual(ns['flatpak_removal_installation_arg']('user'), '--user')
        self.assertEqual(ns['flatpak_removal_installation_arg']('system'), '--system')
        self.assertEqual(ns['flatpak_removal_installation_arg']('custom'), '--installation=custom')
        self.assertIsNone(ns['flatpak_removal_installation_arg']('../../other'))

if __name__ == '__main__': unittest.main()
