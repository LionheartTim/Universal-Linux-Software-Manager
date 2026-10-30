"""Exercise backup/restore completion reset order without requiring PyQt6.

Qt is not installed in the build/test environment; the real GUI must also be
checked on Bazzite. These isolated GUI-method tests catch accidental reset
before the user has read the confirmation dialog.
"""
import ast
import html
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

MAIN = (Path(__file__).resolve().parents[1] / 'main.py').read_text()
TREE = ast.parse(MAIN)
PANEL = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == 'BackupPanel')
FORMATTER = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == 'prominent_notice')
ns = {'html': html}
exec(compile(ast.Module(body=[FORMATTER], type_ignores=[]), '<notice format>', 'exec'), ns)


def method(name, globals_dict):
    node = next(n for n in PANEL.body if isinstance(n, ast.FunctionDef) and n.name == name)
    module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    space = dict(globals_dict, prominent_notice=ns['prominent_notice'])
    exec(compile(module, '<isolated BackupPanel method>', 'exec'), space)
    return space[name]


class Item:
    def __init__(self, label): self.value = label
    def text(self): return self.value


class RestoreTable:
    def __init__(self, values): self.values = [(Item(a), Item(b)) for a,b in values]
    def rowCount(self): return len(self.values)
    def item(self, row, col): return self.values[row][0 if col == 0 else 1]


class RestoreDialog:
    shown = []
    Icon = SimpleNamespace(Information=1, Warning=2)
    StandardButton = SimpleNamespace(Ok=1)
    on_exec = None

    def __init__(self, parent):
        self.parent = parent
        self.attributes = {}
        RestoreDialog.shown.append(self)
    def font(self): return SimpleNamespace(pointSizeF=lambda:10.0)
    def setIcon(self, value): self.attributes['icon'] = value
    def setWindowTitle(self, value): self.attributes['title'] = value
    def setText(self, value): self.attributes['text'] = value
    def setInformativeText(self, value): self.attributes['info'] = value
    def setDetailedText(self, value): self.attributes['details'] = value
    def setStandardButtons(self, value): self.attributes['buttons'] = value
    def exec(self):
        if RestoreDialog.on_exec: RestoreDialog.on_exec(self)


class BackupFinishPopup:
    StandardButton = SimpleNamespace(Yes=1, No=2)
    shown = []
    @staticmethod
    def question(*args): return BackupFinishPopup.StandardButton.Yes
    @staticmethod
    def information(*args):
        BackupFinishPopup.shown.append(args)
        assert args[0].cleared == 0, 'List cleared before the success popup!'


class CompletionResetTests(unittest.TestCase):
    def test_restore_success_popup_before_list_reset(self):
        RestoreDialog.shown = []
        state = SimpleNamespace(restore_active=True, table=RestoreTable([
            ('VLC.AppImage', 'Installed'), ('Theme', 'Restored')]), cleared=0)
        state._update_actions = lambda: None
        state.restore_record=None
        state._restore_errors={}
        state._journal_error=''
        def clear():
            state.cleared += 1
            state.table.values.clear()
        state.clear_files = clear
        def popup(dialog):
            self.assertEqual(state.cleared, 0)
            self.assertEqual(state.table.rowCount(), 2)
            self.assertIn('VLC.AppImage — Installed', dialog.attributes['details'])
            self.assertIn('font-size:11pt; font-weight:700;', dialog.attributes['text'])
            self.assertIn('IMPORTANT: REBOOT YOUR COMPUTER', dialog.attributes['text'])
        RestoreDialog.on_exec = popup
        method('_restore_finish', {'tr': lambda nl,en: en, 'QMessageBox':RestoreDialog})(state)
        self.assertEqual(state.cleared, 1)
        self.assertEqual(state.table.rowCount(), 0)
        self.assertEqual(RestoreDialog.shown[-1].attributes['title'], 'Restore succeeded')
        self.assertFalse(state.restore_active)
        RestoreDialog.on_exec = None

    def test_restore_failure_and_skips_never_claim_succeeded(self):
        for label, status in [('Broken.deb', 'Failed'), ('Skipped.AppImage', 'Skipped'),
                              ('Wrong.rpm', 'Incompatible architecture')]:
            with self.subTest(status=status):
                state=SimpleNamespace(restore_active=True, table=RestoreTable([(label,status)]),cleared=0)
                state._update_actions=lambda:None
                state.restore_record=None
                state._restore_errors={}
                state._journal_error=''
                state.clear_files=lambda: setattr(state,'cleared',state.cleared+1)
                RestoreDialog.shown=[]
                RestoreDialog.on_exec=None
                method('_restore_finish',{'tr':lambda nl,en:en,'QMessageBox':RestoreDialog})(state)
                self.assertNotEqual(RestoreDialog.shown[-1].attributes['title'], 'Restore succeeded')
                self.assertEqual(state.cleared,1)

    def test_backup_success_dialog_before_list_reset(self):
        BackupFinishPopup.shown=[]
        state = SimpleNamespace(busy=False, restore_active=False, table_mode='files',
                                sources=[Path('/sample.AppImage')],desktop='kde',cleared=0)
        state.selected_categories=lambda: set()
        state.clear_files=lambda: setattr(state,'cleared',state.cleared+1)
        state.run_query=lambda build, consumer: consumer({'packages':[{'filename':'sample.AppImage'}]})
        def get_save(*args): return ('/tmp/testing-backup-nonexistent-file-82736246.bu','')
        dialog=SimpleNamespace(getSaveFileName=get_save)
        method('export', {'tr':lambda nl,en:en, 'QMessageBox':BackupFinishPopup,
                          'QFileDialog':dialog, 'HOME':Path('/tmp'),
                          'Path':Path})(state)
        self.assertEqual(len(BackupFinishPopup.shown), 1)
        self.assertIn('Backup saved successfully',BackupFinishPopup.shown[0][2])
        self.assertEqual(state.cleared,1)

    def test_backup_opened_dialog_and_two_click_instruction(self):
        node = next(n for n in PANEL.body if isinstance(n,ast.FunctionDef) and n.name=='open_backup')
        source=ast.get_source_segment(MAIN,node)
        self.assertIn('dialog.exec()',source)
        self.assertIn('summarize_report(report,NL)',source)
        self.assertIn('click Restore backup again',source)

    def test_reset_restores_flags_and_source_selection(self):
        node=next(n for n in PANEL.body if isinstance(n,ast.FunctionDef) and n.name=='clear_files')
        source=ast.get_source_segment(MAIN,node)
        for token in ('self.sources=[]','self.loaded_meta=None','self.loaded_path=None',
                      "self.table_mode='files'",'self.restore_active=False',
                      'self.restore_cursor=0','box.setChecked(False)', 'self._populate([])'):
            self.assertIn(token,source)

if __name__=='__main__': unittest.main()
