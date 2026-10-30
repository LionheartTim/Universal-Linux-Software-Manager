"""Offline bulk-update safety regression tests. No real packages are changed."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

from bulk_updates import plan_update_all, update_all_summary


def row(kind, pid, scope='system', status='available', **kwargs):
    return {'kind':kind,'id':pid,'name':pid,'scope':scope,'status':status,**kwargs}


class BatchPlanTests(unittest.TestCase):
    def select(self, rows, has_polkit=True):
        return plan_update_all(
            rows,
            lambda entry, manager: (['flatpak','update','--'+entry['scope'],entry['id']]
                                    if entry['kind']=='Flatpak' else
                                    ['pkexec','apt-get','upgrade',entry['id']]
                                    if entry['kind']=='DEB' else None),
            lambda _: 'apt-get',
            lambda release: release.get('asset') if release else None,
            lambda name: name == 'systemd',
            lambda binary: has_polkit if binary == 'pkexec' else True)

    def test_all_available_without_a_selected_row_or_filter(self):
        ready,skipped=self.select([row('Flatpak','obs'),row('Flatpak','discord'),
                                   row('Flatpak','builder'),row('Flatpak','up-to-date',status='no_update')])
        self.assertEqual([x[0]['id'] for x in ready], ['obs','discord','builder'])
        self.assertEqual(skipped,[])

    def test_preserves_different_flatpak_scopes_and_deduplicates_exact_identity(self):
        rows=[row('Flatpak','same','user'),row('Flatpak','same','system'),row('Flatpak','same','user')]
        ready,_=self.select(rows)
        self.assertEqual(len(ready),2)
        self.assertEqual([r[1][2] for r in ready], ['--user','--system'])

    def test_system_and_unsafe_packages_are_never_part_of_the_batch(self):
        ready,skipped=self.select([row('Arch','linux'),row('DEB','systemd'),row('DEB','vlc'),
                                   row('Flatpak','obs')],has_polkit=False)
        self.assertEqual([r[0]['id'] for r in ready], ['obs'])
        self.assertEqual([r[0]['id'] for r in skipped], ['linux','systemd','vlc'])

    def test_unlinked_appimage_is_skipped_and_verified_source_allowed(self):
        rows=[row('AppImage','unknown.AppImage',release={'asset':'foo'}),
              row('AppImage','reblue.AppImage',github_repo='zolaware/reblue',release={'asset':'x'})]
        ready,skipped=self.select(rows)
        self.assertEqual(ready[0][0]['id'],'reblue.AppImage')
        self.assertIsNone(ready[0][1])
        self.assertEqual(skipped[0][0]['id'],'unknown.AppImage')

    def test_summary_keeps_failed_and_skipped_separate(self):
        results=[(row('Flatpak','obs'),'updated','ok'),
                 (row('AppImage','reblue'),'skipped','declined'),
                 (row('Flatpak','discord'),'failed','network failed')]
        self.assertEqual(update_all_summary(results,[(row('Arch','linux'),'unsupported')]),
                         {'updated':1,'skipped':2,'failed':1})

    def test_gui_uses_one_confirm_and_sequential_signal_driven_jobs(self):
        text=(Path(__file__).resolve().parents[1]/'main.py').read_text()
        tree=ast.parse(text)
        cls=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=='UpdatesPanel')
        methods={x.name:ast.get_source_segment(text,x) for x in cls.body if isinstance(x,ast.FunctionDef)}
        self.assertIn("self.apply.clicked.connect(self.update_all)",ast.get_source_segment(text,cls))
        self.assertIn('self.entries, upgrade_command',methods['update_all'])
        self.assertNotIn('currentRow()',methods['update_all'])
        self.assertIn('self._bulk_next()',methods['update_all'])
        self.assertIn('Job(args, action=action)',methods['_bulk_run_job'])
        self.assertIn('if outcome == \'failed\':',methods['_bulk_record'])
        self.assertIn('self._bulk_finish(stopped=True)',methods['_bulk_record'])
        self.assertIn('prepare_appimage_update(release, APP_DIR)',methods['_bulk_next'])
        self.assertIn('discard_prepared(prepared)',methods['_bulk_next'])
        self.assertIn('message.exec()',methods['_bulk_finish'])
        self.assertIn('self.refresh()',methods['_bulk_finish'])


class UpdateAllGUIContractTests(unittest.TestCase):
    @staticmethod
    def load_method(name, symbols):
        text=(Path(__file__).resolve().parents[1]/'main.py').read_text()
        tree=ast.parse(text)
        cls=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=='UpdatesPanel')
        method=next(x for x in cls.body if isinstance(x,ast.FunctionDef) and x.name==name)
        scope=dict(symbols)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])),
                     '<update-all-test>', 'exec'), scope)
        return scope[name]

    def test_update_all_will_run_without_row_selection_after_one_confirmation(self):
        class Message:
            StandardButton=SimpleNamespace(Yes=1,No=2)
            asks=[]
            @classmethod
            def question(cls, *args):
                cls.asks.append(args)
                return 1
            @staticmethod
            def information(*args): raise AssertionError('No info expected')
        called=[]
        e1=row('Flatpak','obs');e2=row('Flatpak','discord')
        obj=SimpleNamespace(busy=False,_bulk_active=False,package_tabs={},entries=[e1,e2],
                            _bulk_next=lambda: called.append('next'))
        obj.set_busy=lambda value: (called.append(('busy',value)),setattr(obj,'busy',value))
        method=self.load_method('update_all',{
            'QMessageBox':Message,'tr':lambda nl,en:en,
            'plan_update_all':lambda entries,*other: ([(e1,['flatpak','update','obs']),
                                                       (e2,['flatpak','update','discord'])],[]),
            'upgrade_command':None,'native_manager':None,'choose_appimage':None,
            'package_is_protected':None,'available':None})
        method(obj)
        self.assertEqual(len(Message.asks),1)
        self.assertIn('Update all?',Message.asks[0][1])
        self.assertEqual(len(obj._bulk_queue),2)
        self.assertEqual(called,[('busy',True),'next'])
        self.assertTrue(obj._bulk_active)

    def test_cancel_all_does_not_start_a_single_update(self):
        class Message:
            StandardButton=SimpleNamespace(Yes=1,No=2)
            @staticmethod
            def question(*args): return 2
            @staticmethod
            def information(*args): raise AssertionError()
        obj=SimpleNamespace(busy=False,_bulk_active=False,package_tabs={},entries=[row('Flatpak','obs')],
                            _bulk_next=lambda: self.fail('No job may start after No'))
        obj.set_busy=lambda value: self.fail('No busy state after No')
        method=self.load_method('update_all',{
            'QMessageBox':Message,'tr':lambda nl,en:en,
            'plan_update_all':lambda entries,*other: ([(entries[0],['flatpak','update','obs'])],[]),
            'upgrade_command':None,'native_manager':None,'choose_appimage':None,
            'package_is_protected':None,'available':None})
        method(obj)
        self.assertFalse(obj._bulk_active)

    def test_first_failed_package_stops_queue_not_second_job(self):
        scheduled=[];done=[]
        method=self.load_method('_bulk_record',{
            'QTimer':SimpleNamespace(singleShot=lambda delay,fn: scheduled.append(fn))})
        entry=row('Flatpak','obs')
        obj=SimpleNamespace(_bulk_active=True,_bulk_results=[],_bulk_changed=set(),
                            _bulk_finish=lambda **kw:done.append(kw),_bulk_next=lambda: None)
        method(obj,entry,'failed','connection lost')
        self.assertEqual(done,[{'stopped':True}])
        self.assertEqual(scheduled,[])
        self.assertEqual(obj._bulk_results[0][1],'failed')


if __name__ == '__main__': unittest.main()
