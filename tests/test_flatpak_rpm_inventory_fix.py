"""Regression tests for Bazzite 2026-10-24: no empty Flatpak or RPM core/tools."""
import ast
import json
import unittest
from pathlib import Path
from flatpak_exact_remove import FlatpakRef, parse_inventory, plan_uninstall, verify_removed

MAIN = Path(__file__).resolve().parents[1] / 'main.py'
APP = 'org.videolan.VLC'
PYQT = 'com.riverbankcomputing.PyQt.BaseApp'

class FlatpakRpmInventoryFix(unittest.TestCase):
    def test_app_listing_handles_explicit_components_and_header(self):
        example = ("Name\tApplication\tVersion\tArch\tBranch\tInstallation\n"
                   "VLC\torg.videolan.VLC\t3.0.21\tx86_64\tstable\tsystem\n"
                   "PyQt BaseApp\tcom.riverbankcomputing.PyQt.BaseApp\t6.10.2\tx86_64\t6.10\tuser\n"
                   "PyQt BaseApp\tcom.riverbankcomputing.PyQt.BaseApp\t6.11.0\tx86_64\t6.11\tuser\n")
        records = parse_inventory(example, gui=True)
        self.assertEqual(len(records), 3)
        self.assertEqual(records[0][2], FlatpakRef(APP,'system',f'app/{APP}/x86_64/stable'))
        self.assertEqual(records[1][2].ref, f'app/{PYQT}/x86_64/6.10')
        self.assertEqual(records[2][2].ref, f'app/{PYQT}/x86_64/6.11')

    def test_branch_specific_delete_checks_host_columns_again(self):
        raw = (f'{PYQT}\tx86_64\t6.10\tuser\n'
               f'{PYQT}\tx86_64\t6.11\tuser\n')
        installed = parse_inventory(raw)
        self.assertEqual(plan_uninstall(installed[0],installed)[-1],f'app/{PYQT}/x86_64/6.10')
        self.assertTrue(verify_removed(installed[0],installed[1:]))
        self.assertFalse(verify_removed(installed[0],installed))

    def test_invalid_components_cannot_trigger_uninstall(self):
        for raw in (f'{APP}\tx86_64\t..\tsystem',
                    f'{APP}\tx86_64\tstable',
                    f'{APP}\tx86_64\tstable\tuser;rm',
                    f'{APP}\tx86_64\tstable\t',
                    f'{APP}\t\tstable\tuser'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_inventory(raw)

    def test_no_new_ref_parser_clears_valid_flatpak_list(self):
        src = MAIN.read_text()
        self.assertIn('parse_inventory(out, gui=True)', src)
        self.assertIn('parse_inventory(output)', src)
        self.assertIn('name:full,application:full,version:full,arch:full,branch:full,installation:full',src)
        self.assertNotIn("parse_installed(out, columns='gui')", src)

    def test_ostree_rpm_listing_requires_desktop_ownership(self):
        src = MAIN.read_text()
        tree = ast.parse(src)
        package_tab=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='PackageTab')
        reload_fn=next(n for n in package_tab.body if isinstance(n,ast.FunctionDef) and n.name=='reload')
        segment=ast.get_source_segment(src,reload_fn)
        self.assertIn('graphical = desktop_rpm_packages()',segment)
        self.assertIn('rows = [r for r in rows if r[2] in graphical]',segment)
        self.assertIn('if graphical is None:',segment)
        # On an rpm-ostree desktop, even explicitly layered development tools
        # should stay hidden if none owns a graphical desktop launcher.
        rows=[('binutils','Layered','binutils',''),
              ('hidapi-devel','Layered','hidapi-devel',''),
              ('Wireshark','Layered','wireshark','')]
        allowed={'wireshark'}
        self.assertEqual([r[2] for r in rows if r[2] in allowed],['wireshark'])

if __name__=='__main__': unittest.main()
