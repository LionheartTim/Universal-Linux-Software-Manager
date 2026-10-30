"""Qt-independent behavioral tests for the actual GUI search/reset methods."""
import ast
import unittest
from pathlib import Path
from types import SimpleNamespace

SRC = (Path(__file__).resolve().parents[1] / 'main.py').read_text(encoding='utf-8')
TREE = ast.parse(SRC)


def gui_method(clsname, method, globals_map=None):
    cls = next(node for node in TREE.body if isinstance(node, ast.ClassDef) and node.name == clsname)
    fn = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == method)
    copy = ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))
    namespace = dict(globals_map or {})
    exec(compile(copy, '<extracted-gui-method>', 'exec'), namespace)
    return namespace[method]


class FakeItem:
    def __init__(self, text):
        self.text = str(text)
        self.extras = {}

    def flags(self): return 7
    def setFlags(self, flags): self.flags_value = flags
    def setToolTip(self, value): self.tooltip = value
    def setIcon(self, value): self.icon = value
    def setData(self, role, value): self.extras[role] = value
    def data(self, role): return self.extras.get(role)


class FakeTable:
    def __init__(self): self.rows = []
    def setSortingEnabled(self, value): pass
    def setUpdatesEnabled(self, value): pass
    def setRowCount(self, value):
        if value == 0: self.rows = []
        else: raise AssertionError('Only reset is expected')
    def rowCount(self): return len(self.rows)
    def insertRow(self, row): self.rows.insert(row, [None] * 7)
    def setItem(self, row, column, value): self.rows[row][column] = value


class FakeText:
    def __init__(self, value=''): self.value = value
    def text(self): return self.value
    def setText(self, value): self.value = value


class FakeCheck:
    def __init__(self, value=False): self.value = value
    def isChecked(self): return self.value


class FakeButton:
    def __init__(self): self.enabled = None
    def setEnabled(self, enabled): self.enabled = enabled


class SearchResetTests(unittest.TestCase):
    def test_updates_clear_search_repopulates_full_inventory(self):
        role = SimpleNamespace(ItemFlag=SimpleNamespace(ItemIsEditable=1),
                               ItemDataRole=SimpleNamespace(UserRole=32))
        ctx = {'Qt': role, 'QTableWidgetItem': FakeItem,
               'package_icon': lambda *args: 'icon',
               'tr': lambda nl, en: en}
        values = gui_method('UpdatesPanel', '_update_row_values', ctx)
        render = gui_method('UpdatesPanel', '_render_filtered_rows', ctx)
        rows = [dict(kind='Flatpak', name='VLC', id='org.videolan.VLC', status='no_update',
                     scope='system', installed_version='3.0', available_version=''),
                dict(kind='AppImage', name='Reblue', id='reblue.AppImage', status='available',
                     scope='USER', installed_version='1.0.0', available_version='1.3.1')]
        obj = SimpleNamespace(entries=rows, table=FakeTable(), search=FakeText('reblue'),
                updates_only=FakeCheck(False), STATUS={
                    'no_update': ('Geen update gevonden','No update found'),
                    'available': ('Update beschikbaar','Update available')},
                update_apply_button=lambda: None)
        obj._update_row_values = lambda row: values(obj, row)
        render(obj)
        self.assertEqual(len(obj.table.rows), 1)
        self.assertEqual(obj.table.rows[0][1].text, 'Reblue')
        obj.search.value = ''
        render(obj)
        self.assertEqual([r[1].text for r in obj.table.rows], ['VLC','Reblue'])
        self.assertEqual(len(obj.entries), 2, 'Filter must never mutate the full inventory')
        obj.search.value = 'no-match'
        render(obj)
        self.assertEqual(len(obj.table.rows), 0)
        obj.search.value = ''
        render(obj)
        self.assertEqual(len(obj.table.rows), 2)

    def test_updates_only_checkbox_still_filters_after_clearing_search(self):
        role = SimpleNamespace(ItemFlag=SimpleNamespace(ItemIsEditable=1),
                               ItemDataRole=SimpleNamespace(UserRole=32))
        ctx = {'Qt': role, 'QTableWidgetItem': FakeItem, 'package_icon': lambda *a: None,
               'tr': lambda nl, en: en}
        values = gui_method('UpdatesPanel', '_update_row_values', ctx)
        render = gui_method('UpdatesPanel', '_render_filtered_rows', ctx)
        obj = SimpleNamespace(entries=[
                dict(kind='Flatpak',name='No update',id='a',status='no_update',scope='user'),
                dict(kind='AppImage',name='Update',id='b',status='available',scope='user')],
              table=FakeTable(), search=FakeText(''), updates_only=FakeCheck(True),
              STATUS={'no_update': ('x','No update found'), 'available':('y','Update available')},
              update_apply_button=lambda: None)
        obj._update_row_values = lambda row: values(obj, row)
        render(obj)
        self.assertEqual([r[1].text for r in obj.table.rows], ['Update'])
        obj.updates_only.value = False
        render(obj)
        self.assertEqual(len(obj.table.rows), 2)

    def test_discover_clears_old_results_and_rejects_late_network_response(self):
        ctx = {'tr': lambda nl, en: en}
        cleared = gui_method('DiscoverPanel', 'clear_results', ctx)
        changed = gui_method('DiscoverPanel', 'on_query_changed', ctx)
        completed = gui_method('DiscoverPanel', 'on_search_completed', ctx)
        obj = SimpleNamespace(_displayed_query='Audacity', query=FakeText(''),
              table=FakeTable(), open_page=FakeButton(), output_label=FakeText('3 found'),
              note=FakeText('Results from Audacity'), show_results=lambda result: None)
        obj.clear_results = lambda: cleared(obj)
        obj.table.rows = [[object()] * 7]
        changed(obj, '')
        self.assertEqual(obj.table.rowCount(), 0)
        self.assertIsNone(obj._displayed_query)
        self.assertFalse(obj.open_page.enabled)
        self.assertNotIn('Audacity', obj.note.value)
        completed(obj, 'Audacity', ([{'name':'Audacity'}], []))
        self.assertEqual(obj.table.rowCount(), 0, 'Late result must not appear after clearing')
        received = []
        obj.query.value = 'VLC'
        obj.show_results = lambda result: received.append(result)
        completed(obj, 'VLC', ([{'name': 'VLC'}], []))
        self.assertEqual(obj._displayed_query, 'VLC')
        self.assertEqual(len(received), 1)

    def test_discover_search_callback_checks_submitted_query(self):
        method = gui_method('DiscoverPanel', 'search')
        code = ast.get_source_segment(SRC, next(
            x for c in TREE.body if isinstance(c, ast.ClassDef) and c.name=='DiscoverPanel'
            for x in c.body if isinstance(x, ast.FunctionDef) and x.name=='search'))
        self.assertIn('self.on_search_completed(text, result)', code)


if __name__ == '__main__': unittest.main()
