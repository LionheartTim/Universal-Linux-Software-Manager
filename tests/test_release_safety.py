"""Host-free tests for release hardening; imports method/functions by AST (no PyQt needed)."""
import ast
import os
import pathlib
import shutil
import stat
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'main.py').read_text(encoding='utf-8')
TREE = ast.parse(SOURCE)
FUNCTIONS = {n.name: n for n in TREE.body if isinstance(n, ast.FunctionDef)}
PACKAGE_TAB = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == 'PackageTab')
INSTALL_METHOD = next(n for n in PACKAGE_TAB.body if isinstance(n, ast.FunctionDef) and n.name == 'appimage_install')


def extracted(nodes, namespace):
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(ROOT/'main.py'), 'exec'), namespace)


class TestEnvironment(unittest.TestCase):
    def test_no_manager_disabled(self):
        ns = dict(native_manager=lambda kind: None, tr=lambda nl, en: en, available=lambda p: False,
                  writable_location=lambda _: True)
        extracted([FUNCTIONS['environment_capabilities']], ns)
        self.assertEqual(ns['environment_capabilities']('RPM')[:2], (False, False))

    def test_missing_pkexec_disables_native_changes(self):
        ns = dict(native_manager=lambda kind: 'dnf5', tr=lambda nl, en: en,
                  available=lambda p: p == 'rpm', writable_location=lambda _: True)
        extracted([FUNCTIONS['environment_capabilities']], ns)
        allow_install, allow_remove, reason = ns['environment_capabilities']('RPM')
        self.assertEqual((allow_install, allow_remove), (False, False))
        self.assertIn('pkexec', reason)

    def test_ostree_uses_its_own_authorization(self):
        ns = dict(native_manager=lambda kind: 'rpm-ostree', tr=lambda nl, en: en,
                  available=lambda p: False, writable_location=lambda _: True)
        extracted([FUNCTIONS['environment_capabilities']], ns)
        self.assertEqual(ns['environment_capabilities']('RPM')[:2], (True, True))

    def test_unwritable_appimage_dest_is_disabled(self):
        ns = dict(native_manager=lambda kind: 'appimage', tr=lambda nl, en: en,
                  available=lambda p: False, writable_location=lambda _: False,
                  APP_DIR=pathlib.Path('/bad'), DESKTOP_DIR=pathlib.Path('/bad'))
        extracted([FUNCTIONS['environment_capabilities']], ns)
        self.assertEqual(ns['environment_capabilities']('AppImage')[:2], (False, False))


class TestAtomicAppImage(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = pathlib.Path(self.temp.name)
        self.app_dir = self.base / 'Applications'
        self.desktop_dir = self.base / 'launchers'
        self.source = self.base / 'sample.AppImage'
        self.source.write_bytes(b'portable app bytes' * 350)
        self.ns = dict(os=os, stat=stat, tempfile=tempfile, shutil=shutil,
                       Path=pathlib.Path, APP_DIR=self.app_dir, DESKTOP_DIR=self.desktop_dir,
                       tr=lambda nl, en: en,
                       safe_quoted_path=lambda p: str(p),
                       desktop_path=lambda name: self.desktop_dir/(name+'.desktop'))
        extracted([INSTALL_METHOD], self.ns)
        self.install = self.ns['appimage_install']

    def test_complete_install_and_no_partials(self):
        self.install(None, self.source)
        dest = self.app_dir/self.source.name
        self.assertEqual(dest.read_bytes(), self.source.read_bytes())
        self.assertTrue(dest.stat().st_mode & stat.S_IXUSR)
        self.assertTrue((self.desktop_dir/(self.source.name+'.desktop')).is_file())
        self.assertEqual(list(self.app_dir.glob('*.partial')), [])
        self.assertEqual(list(self.app_dir.glob('.*.partial')), [])
        self.assertEqual(list(self.desktop_dir.glob('.*.partial')), [])

    def test_duplicate_does_not_overwrite_existing_app(self):
        self.install(None, self.source)
        self.source.write_bytes(b'changed data')
        with self.assertRaisesRegex(RuntimeError, 'already exists'):
            self.install(None, self.source)
        self.assertNotEqual((self.app_dir/self.source.name).read_bytes(), self.source.read_bytes())

    def test_launcher_failure_rolls_back_new_app(self):
        self.ns['desktop_path'] = lambda _: self.base/'missing-dir'/'launcher.desktop'
        with self.assertRaises(OSError):
            self.install(None, self.source)
        self.assertFalse((self.app_dir/self.source.name).exists())
        self.assertEqual(list(self.app_dir.glob('.*.partial')), [])
        self.assertEqual(list(self.desktop_dir.glob('.*.partial')), [])

    def test_empty_appimage_is_rejected(self):
        self.source.write_bytes(b'')
        with self.assertRaisesRegex(RuntimeError, 'empty'):
            self.install(None, self.source)
        self.assertFalse((self.app_dir/self.source.name).exists())


class TestReleaseFiles(unittest.TestCase):
    def test_legal_metadata_and_checklist(self):
        import xml.etree.ElementTree as ET
        self.assertTrue((ROOT/'LICENSE').is_file())
        self.assertTrue((ROOT/'RELEASE_CHECKLIST.md').is_file())
        xml = ET.parse(ROOT/'io.github.LionheartTim.UniversalLinuxSoftwareManager.metainfo.xml').getroot()
        self.assertEqual(xml.find('project_license').text, 'GPL-3.0-only')
        self.assertTrue(xml.find('launchable').text.endswith('.desktop'))
        self.assertTrue(xml.find('releases/release') is not None)

    def test_close_is_blocked_during_jobs(self):
        center = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == 'Center')
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'closeEvent' for n in center.body))

if __name__ == '__main__': unittest.main()
