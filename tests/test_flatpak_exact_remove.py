"""Two PyQt BaseApp branches must not be confused in app uninstall."""
import ast
from pathlib import Path
import unittest
from flatpak_exact_remove import FlatpakRef, parse_installed, parse_inventory, plan_uninstall, verify_removed

ID = 'com.riverbankcomputing.PyQt.BaseApp'
OLDER = FlatpakRef(ID, 'user', f'app/{ID}/x86_64/6.10')
NEWER = FlatpakRef(ID, 'user', f'app/{ID}/x86_64/6.11')


class FlatpakExactRemoveTests(unittest.TestCase):
    def test_two_pyqt_branches_select_only_old_one(self):
        raw = '\n'.join(f'{r.application}\t{r.installation}\t{r.ref}' for r in (OLDER, NEWER))
        installed = parse_installed(raw)
        self.assertEqual(installed, [OLDER, NEWER])
        self.assertEqual(plan_uninstall(OLDER, installed),
                         ['flatpak', 'uninstall', '--user', '--noninteractive', '-y', OLDER.ref])
        self.assertNotIn(NEWER.ref, plan_uninstall(OLDER, installed))
        self.assertFalse(verify_removed(OLDER, installed))
        self.assertTrue(verify_removed(OLDER, [NEWER]))
        self.assertFalse(verify_removed(NEWER, [NEWER]))

    def test_existing_other_branch_prevents_data_deletion(self):
        with self.assertRaisesRegex(ValueError, 'shared user data'):
            plan_uninstall(OLDER, [OLDER, NEWER], delete_data=True)

    def test_only_app_with_no_other_ref_can_delete_data_if_explicit(self):
        cmd = plan_uninstall(OLDER, [OLDER], delete_data=True)
        self.assertIn('--delete-data', cmd)
        self.assertEqual(cmd[-1], OLDER.ref)
        self.assertNotIn('--delete-data', plan_uninstall(OLDER, [OLDER]))

    def test_ref_changed_since_gui_load_fails_closed(self):
        with self.assertRaisesRegex(ValueError, 'changed'):
            plan_uninstall(OLDER, [NEWER])
        with self.assertRaisesRegex(ValueError, 'uniquely'):
            plan_uninstall(OLDER, [OLDER, OLDER])

    def test_location_mismatch_is_blocked(self):
        with self.assertRaises(ValueError):
            plan_uninstall(OLDER, [FlatpakRef(ID, 'system', OLDER.ref)])
        named = FlatpakRef(ID, 'secondary', OLDER.ref)
        self.assertIn('--installation=secondary', plan_uninstall(named, [named]))
        system = FlatpakRef(ID, 'system', OLDER.ref)
        self.assertIn('--system', plan_uninstall(system, [system]))

    def test_invalid_refs_do_not_bypass_checks(self):
        for ref in ('', ID, f'app/{ID}/x86_64', f'runtime/{ID}/x86_64/6.10',
                    f'app/{ID}/x86_64/../bad', f'app/{ID}/x86_64/6.10;rm'):
            with self.subTest(ref=ref):
                with self.assertRaises(ValueError):
                    plan_uninstall(FlatpakRef(ID, 'user', ref), [FlatpakRef(ID, 'user', ref)])

    def test_full_app_gui_listing_and_header_supported(self):
        raw = ('Name\tApplication\tVersion\tInstallation\tRef\n'
               f'PyQt BaseApp\t{ID}\t6.10.2\tuser\t{OLDER.ref}\n'
               f'PyQt BaseApp\t{ID}\t6.11.0\tuser\t{NEWER.ref}\n')
        self.assertEqual(parse_installed(raw, columns='gui'), [OLDER, NEWER])

    def test_empty_is_safe_missing_column_is_blocked(self):
        self.assertEqual(parse_installed(''), [])
        with self.assertRaises(ValueError):
            parse_installed(f'{ID}\tuser')

    def test_main_wires_ref_through_load_and_delete_and_verify(self):
        src=(Path(__file__).resolve().parents[1]/'main.py').read_text()
        ast.parse(src)
        self.assertIn('arch:full,branch:full,installation:full',src)
        self.assertIn('parse_inventory(output)',src)
        self.assertIn('item.setData(Qt.ItemDataRole.UserRole, record[5])', src)
        self.assertIn('selected_ref = FlatpakRef(name, str(flatpak_installation), str(flatpak_ref))',src)
        self.assertIn('args = plan_uninstall(selected_ref, installed_refs, delete_data=delete_data)', src)
        self.assertIn('removal_ref=selected_ref if k == \'Flatpak\' else None', src)
        self.assertIn('verify_removed(self.flatpak_removal_ref, parse_inventory(output))',src)
        self.assertNotIn("'--noninteractive', '-y', name]\n            if delete_data", src)

if __name__ == '__main__':
    unittest.main()
