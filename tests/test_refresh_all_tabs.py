"""Static and targeted behavioral checks for all nine refresh controls."""
import ast
import unittest
from pathlib import Path
from types import SimpleNamespace

SOURCE=(Path(__file__).resolve().parents[1]/'main.py').read_text()
MODULE=ast.parse(SOURCE)


def cls(name):
    return next(x for x in MODULE.body if isinstance(x,ast.ClassDef) and x.name == name)


def method(klass,name,environment=None):
    node=next(x for x in cls(klass).body if isinstance(x,ast.FunctionDef) and x.name==name)
    loc=dict(environment or {})
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<method>','exec'),loc)
    return loc[name]


class RefreshCoverageTests(unittest.TestCase):
    def test_nine_tabs_expose_explicit_refresh_buttons(self):
        for name,wire in [('PackageTab','self.refresh_button.clicked.connect(self.reload)'),
                          ('UpdatesPanel','self.refresh_button.clicked.connect(self.refresh)'),
                          ('DiscoverPanel','self.refresh_button.clicked.connect(self.refresh)'),
                          ('BackupPanel','self.refresh_button.clicked.connect(self.refresh)')]:
            section=ast.get_source_segment(SOURCE,cls(name))
            self.assertIn(wire,section, name)
            self.assertIn("tr('Verversen', 'Refresh')",section)
        self.assertIn("('Flatpak', 'AppImage', 'RPM', 'DEB', 'Arch', 'Snap')",SOURCE)

    def test_busy_package_tab_does_not_reload(self):
        tab=SimpleNamespace(busy=True,kind='Flatpak')
        method('PackageTab','reload')(tab)

    def test_busy_backup_tab_does_not_clear_selection(self):
        tab=SimpleNamespace(busy=False,restore_active=True,sources=['existing'],table_mode='files')
        method('BackupPanel','refresh')(tab)
        self.assertEqual(tab.sources,['existing'])

    def test_empty_discover_query_does_not_search(self):
        called=[]
        tab=SimpleNamespace(busy=False,query=SimpleNamespace(text=lambda:''),
                            clear_results=lambda:called.append('clear'),
                            search=lambda:called.append('search'))
        method('DiscoverPanel','refresh')(tab)
        self.assertEqual(called,['clear'])

    def test_refresh_button_disabled_during_package_action(self):
        section=ast.get_source_segment(SOURCE,cls('PackageTab'))
        self.assertIn('self.search, self.refresh_button): w.setEnabled(False)',section)
        section=ast.get_source_segment(SOURCE,cls('BackupPanel'))
        self.assertIn('self.refresh_button.setEnabled(not self.restore_active)',section)


if __name__=='__main__':unittest.main()
