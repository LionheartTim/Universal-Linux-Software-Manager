"""Contract tests for local BU archives and queued restore status UI."""
import ast
import tempfile
import unittest
import zipfile
from pathlib import Path
from local_file_backup import create_backup, inspect_backup, extract_package

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT/'main.py').read_text()

class BackupStatusTests(unittest.TestCase):
    def test_bu_file_is_checked_container_not_script(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td)
            sample=td/'probe.AppImage'; sample.write_bytes(b'\x7fELF' + b'0' * 80)
            dest=td/'sample.bu'
            create_backup(dest,[sample])
            self.assertEqual(dest.read_bytes()[:2],b'PK')
            meta=inspect_backup(dest)
            self.assertEqual(meta['packages'][0]['filename'],sample.name)
            with zipfile.ZipFile(dest) as z:
                self.assertEqual(set(z.namelist()),{'manifest.json','packages/0'})
            out=td/'extract';out.mkdir()
            restored=extract_package(dest,0,out)
            self.assertEqual(restored.read_bytes(),sample.read_bytes())

    def test_gui_has_readonly_status_and_queue(self):
        tree=ast.parse(MAIN)
        p=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=='BackupPanel')
        methods={x.name for x in p.body if isinstance(x,ast.FunctionDef)}
        self.assertTrue({'_status','_restore_next','_restore_settings_queued','_restore_finish'} <= methods)
        init=next(x for x in p.body if isinstance(x,ast.FunctionDef) and x.name=='__init__')
        source=ast.get_source_segment(MAIN,init)
        self.assertIn('self.table.setColumnCount(4)',source)
        self.assertIn("tr('Status','Status')",source)
        self.assertIn('self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)',source)
        self.assertIn('self.restore_backup_button=QPushButton',source)
        self.assertIn('self.export_button=QPushButton',source)

    def test_status_only_marks_installed_after_backend_completion(self):
        tree=ast.parse(MAIN)
        p=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=='BackupPanel')
        fn=next(x for x in p.body if isinstance(x,ast.FunctionDef) and x.name=='_restore_next')
        snippet=ast.get_source_segment(MAIN,fn)
        self.assertIn('target.job.done.connect(installed)',snippet)
        self.assertIn("self._status(i,'Geïnstalleerd','Installed')",snippet)
        self.assertIn("self._status(i,'Mislukt','Failed')",snippet)
        self.assertIn("self._status(i,'Overgeslagen','Skipped')",snippet)
        self.assertIn('QMessageBox.StandardButton.Cancel',snippet)
        self.assertIn('approved=True',snippet)

if __name__=='__main__': unittest.main()
