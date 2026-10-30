"""Pure formatting and GUI wiring checks (no Qt/X display required)."""
import ast
import html
import unittest
from pathlib import Path

SOURCE=(Path(__file__).resolve().parents[1]/'main.py').read_text(encoding='utf8')
TREE=ast.parse(SOURCE)
FUNCTION=next(n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name=='prominent_notice')
namespace={'html':html}
exec(compile(ast.Module(body=[FUNCTION],type_ignores=[]),'<notice>', 'exec'),namespace)
format_notice=namespace['prominent_notice']
PANEL=next(n for n in TREE.body if isinstance(n,ast.ClassDef) and n.name=='BackupPanel')

class NoticeFormattingTests(unittest.TestCase):
    def test_one_point_larger_and_bold_only_selected_phrase(self):
        actual=format_notice('Count: 2\nClick Restore backup again to start.',
                             'Click Restore backup again to start.',10)
        self.assertIn('Count: 2<br/>',actual)
        self.assertIn('font-size:11pt; font-weight:700;',actual)
        self.assertIn('>Click Restore backup again to start.</span>',actual)
        self.assertEqual(actual.count('<span'),1)

    def test_reboot_sentence_dutch_and_english(self):
        for warning in ('BELANGRIJK: HERSTART JE COMPUTER na dit herstel.',
                        'IMPORTANT: REBOOT YOUR COMPUTER after this restore.'):
            actual=format_notice('Geslaagd: 2\n'+warning,warning,9.5)
            self.assertIn('font-size:10.5pt; font-weight:700;',actual)
            self.assertIn('>'+warning+'</span>',actual)

    def test_other_data_escaped_and_missing_phrase_not_highlighted(self):
        actual=format_notice('File <bad> & stuff','not present',10)
        self.assertIn('&lt;bad&gt; &amp; stuff', actual)
        self.assertNotIn('<span',actual)

    def test_gui_uses_formatted_labels_and_both_dialogs(self):
        open_backup=next(n for n in PANEL.body if isinstance(n,ast.FunctionDef) and n.name=='open_backup')
        restore_finish=next(n for n in PANEL.body if isinstance(n,ast.FunctionDef) and n.name=='_restore_finish')
        pre=ast.get_source_segment(SOURCE,open_backup)
        post=ast.get_source_segment(SOURCE,restore_finish)
        self.assertIn('self.output_label.setText(prominent_notice(',pre)
        self.assertIn('summarize_report(report,NL)',pre)
        self.assertIn('dialog.setText(prominent_notice(',pre)
        self.assertIn('dialog.setText(prominent_notice(',post)
        self.assertIn('if done or restart or partial:',post)
        self.assertIn('IMPORTANT: REBOOT YOUR COMPUTER',post)

if __name__=='__main__':unittest.main()
