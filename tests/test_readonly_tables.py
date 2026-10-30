"""Prevent Qt item editor activation in read-only information tables."""
import ast
import unittest
from pathlib import Path

MAIN = (Path(__file__).resolve().parents[1] / 'main.py').read_text(encoding='utf-8')
TREE = ast.parse(MAIN)


def class_source(name):
    cls = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == name)
    return ast.get_source_segment(MAIN, cls)


class ReadOnlyTableTests(unittest.TestCase):
    def test_all_list_panels_disable_cell_editing(self):
        for cls in ('PackageTab', 'UpdatesPanel', 'DiscoverPanel', 'BackupPanel'):
            with self.subTest(panel=cls):
                body = class_source(cls)
                self.assertIn('self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)', body)

    def test_history_dialog_remains_readonly(self):
        self.assertIn('self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)',
                      class_source('VersionHistoryDialog'))

    def test_dynamic_rows_have_noneditable_flags(self):
        for cls in ('UpdatesPanel', 'DiscoverPanel', 'BackupPanel'):
            with self.subTest(panel=cls):
                body = class_source(cls)
                self.assertIn('~Qt.ItemFlag.ItemIsEditable', body)

    def test_discover_click_opens_versions_not_editor(self):
        body = class_source('DiscoverPanel')
        self.assertIn('self.table.cellClicked.connect(self.on_result_clicked)', body)
        self.assertIn('github_release_history', body)
        self.assertIn('flatpak_history', body)
        self.assertIn('adjustable_columns(self.table', body)

    def test_updates_selection_actions_still_connected(self):
        body = class_source('UpdatesPanel')
        self.assertIn('self.table.itemSelectionChanged.connect(self.update_apply_button)', body)
        self.assertIn('self.apply.clicked.connect(self.update_all)', body)
        self.assertIn('self.link_source.clicked.connect(self.link_selected_source)', body)


if __name__ == '__main__':
    unittest.main()
