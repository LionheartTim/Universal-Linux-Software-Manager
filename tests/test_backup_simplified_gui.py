"""Prevent regressions in the two-button backup workflow."""
import ast
import unittest
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] / "main.py").read_text()

class SimplifiedBackupGuiTests(unittest.TestCase):
    def test_no_clear_button_or_clear_list_label(self):
        self.assertNotIn("self.clear_button=", SOURCE)
        self.assertNotIn("'Clear list'", SOURCE)
        self.assertNotIn("'Lijst leegmaken'", SOURCE)

    def test_only_two_main_backup_actions_and_two_file_controls(self):
        root=ast.parse(SOURCE)
        panel=next(x for x in root.body if isinstance(x,ast.ClassDef) and x.name=='BackupPanel')
        init=next(x for x in panel.body if isinstance(x,ast.FunctionDef) and x.name=='__init__')
        code=ast.get_source_segment(SOURCE,init)
        self.assertIn("self.export_button=QPushButton",code)
        self.assertIn("self.restore_backup_button=QPushButton",code)
        self.assertIn("self.pick_button=QPushButton",code)
        self.assertIn("self.remove_button=QPushButton",code)
        self.assertNotIn("self.restore_button=QPushButton",code)
        self.assertNotIn("self.restore_settings_button=QPushButton",code)

    def test_old_backup_does_not_get_overwritten_when_adding_files(self):
        self.assertIn("The existing ZIP will not be modified.", SOURCE)
        self.assertIn("self.clear_files()", SOURCE)
        self.assertIn("box.setEnabled(supported)", SOURCE)

    def test_file_restore_and_settings_restore_are_distinct(self):
        root=ast.parse(SOURCE)
        panel=next(x for x in root.body if isinstance(x,ast.ClassDef) and x.name=='BackupPanel')
        names={x.name for x in panel.body if isinstance(x,ast.FunctionDef)}
        self.assertTrue({'restore_backup','open_backup','restore','restore_preferences'} <= names)
        fn=next(x for x in panel.body if isinstance(x,ast.FunctionDef) and x.name=='restore_backup')
        code=ast.get_source_segment(SOURCE,fn)
        self.assertIn('self._restore_next',code)
        self.assertIn('self.restore_active',code)
        self.assertIn('self._restore_settings_queued',SOURCE)

if __name__=='__main__': unittest.main()
