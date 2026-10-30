"""Info tab regression tests that run without Qt or network access."""
import ast
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Pure content module works on headless CI (Qt is required only to draw the UI).
import sys
sys.path.insert(0, str(ROOT))
from help_content import TOPICS, TOPIC_IDS, TOPIC_BY_ID


class InfoHelpTests(unittest.TestCase):
    def test_unique_stable_chapter_ids_and_categories(self):
        self.assertGreaterEqual(len(TOPICS), 18)
        self.assertEqual(len(TOPICS), len(TOPIC_IDS))
        self.assertEqual(len(TOPICS), len(set(TOPIC_IDS)))
        for category, slug, title, body in TOPICS:
            self.assertIn(category, {'Getting Started', 'Package Formats', 'Using the Manager', 'Help and Support'})
            self.assertRegex(slug, r'^[a-z][a-z0-9-]*$')
            self.assertTrue(title.strip())
            self.assertGreater(len(body), 125)
            self.assertEqual(TOPIC_BY_ID[slug][2], title)

    def test_package_and_function_topics_exist(self):
        topics = set(TOPIC_IDS)
        self.assertTrue({'welcome', 'navigation', 'comparison', 'flatpak', 'appimage',
                         'rpm', 'deb', 'arch', 'snap', 'installing', 'updates',
                         'discover', 'backup', 'desktop', 'security', 'troubleshoot',
                         'faq', 'about'}.issubset(topics))

    def test_internal_html_links_reference_topics(self):
        for _category, slug, _title, body in TOPICS:
            for anchor in re.findall(r'href=["\']#([^"\']+)', body):
                self.assertIn(anchor, TOPIC_IDS, f'{slug} has broken link to {anchor}')
            self.assertNotRegex(body.lower(), r'<script|<iframe|javascript:|onerror=|onclick=')

    def test_critical_current_behavior_documented(self):
        text = '\n'.join(t[3] for t in TOPICS).lower()
        for required in ('.bu', 'one-time restore', 'before kwin', 'audio',
                         'strictly read-only', 'never downloads', 'system',
                         'user', 'no match', 'flathub', 'github', 'reboot required',
                         'f1', 'ctrl+f', 'rpm-ostree', 'snapd', 'dangerous'):
            self.assertIn(required, text)

    def test_main_adds_info_after_existing_nine_tabs(self):
        src = (ROOT / 'main.py').read_text(encoding='utf-8')
        center = src[src.index('class Center('):]
        self.assertIn("tabs.addTab(self.backup_tab, tr('Back-up / Herstellen','Backup / Restore'))", center)
        self.assertIn("tabs.addTab(self.info_tab, 'Info')", center)
        self.assertLess(center.index("tabs.addTab(self.backup_tab,"), center.index("tabs.addTab(self.info_tab,"))
        self.assertIn('self.help_shortcut.activated.connect(self.open_context_help)', center)
        self.assertIn('self.tabs_widget.setCurrentWidget(self.info_tab)', center)
        self.assertIn('self.info_tab.show_topic(topic)', center)
        for mapping in ('flatpak', 'appimage', 'rpm', 'deb', 'arch', 'snap'):
            self.assertIn(mapping, TOPIC_BY_ID)

    def test_widget_has_navigation_and_offline_search(self):
        src = (ROOT / 'info_help.py').read_text(encoding='utf-8')
        tree = ast.parse(src)
        classes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'InfoPanel']
        self.assertEqual(len(classes), 1)
        methods = {node.name for node in classes[0].body if isinstance(node, ast.FunctionDef)}
        self.assertTrue({'show_topic', 'go_back', 'go_forward', 'find_next', 'focus_find',
                         '_tree_clicked', '_anchor_clicked'}.issubset(methods))
        self.assertIn('self.browser.setOpenExternalLinks(False)', src)
        self.assertIn('self.browser.setOpenLinks(False)', src)
        self.assertNotIn('QWebEngine', src)
        self.assertNotIn('requests.', src)

    def test_flatpak_ships_both_new_python_modules(self):
        manifest = json.loads((ROOT / 'io.github.LionheartTim.UniversalLinuxSoftwareManager.json').read_text())
        module = manifest['modules'][0]
        sources = [v['path'] for v in module['sources'] if v['type'] == 'file']
        commands = module['build-commands']
        for filename in ('help_content.py', 'info_help.py'):
            self.assertIn(filename, sources)
            self.assertIn(f'install -Dm644 {filename} /app/bin/{filename}', commands)


if __name__ == '__main__':
    unittest.main()
