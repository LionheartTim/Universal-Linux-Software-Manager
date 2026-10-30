"""Discover never performs an install, removal, downgrade or download."""
import ast
import unittest
from pathlib import Path
from version_history import discovery_project_url, discovery_release_url

ROOT = Path(__file__).resolve().parents[1]

class ReadOnlyDiscoverTests(unittest.TestCase):
    def test_project_url_only_for_grounded_sources(self):
        self.assertEqual(discovery_project_url({'kind':'GitHub','id':'audacity/audacity'}),
                         'https://github.com/audacity/audacity')
        self.assertEqual(discovery_project_url({'kind':'Flatpak','id':'org.videolan.VLC','scope':'flathub'}),
                         'https://flathub.org/apps/org.videolan.VLC')
        self.assertEqual(discovery_project_url({'kind':'Flatpak','id':'org.videolan.VLC','scope':'thirdparty'}),None)
        self.assertEqual(discovery_project_url({'kind':'RPM','id':'audacity','scope':'fedora'}),None)
        self.assertEqual(discovery_project_url({'kind':'GitHub','id':'org/../evil'}),None)
        self.assertEqual(discovery_project_url({'kind':'Flatpak','id':'..\nfoo','scope':'flathub'}),None)
        self.assertEqual(discovery_project_url({'kind':'Flatpak','id':'org.videolan.VLC','scope':'other, flathub'}),
                         'https://flathub.org/apps/org.videolan.VLC')

    def test_only_repository_owned_release_urls(self):
        entry={'kind':'GitHub','id':'audacity/audacity'}
        version={'release':{'url':'https://github.com/audacity/audacity/releases/tag/Audacity-3.7.9'}}
        self.assertEqual(discovery_release_url(entry,version), version['release']['url'])
        self.assertIsNone(discovery_release_url(entry, {'release':{'url':'https://evil.test/releases/tag/v2'}}))
        self.assertIsNone(discovery_release_url(entry, {'release':{'url':'https://github.com/other/repo/releases/tag/v2'}}))
        self.assertIsNone(discovery_release_url(entry, {'release':{'url':version['release']['url']+'\n'}}))
        self.assertIsNone(discovery_release_url({'kind':'Flatpak','id':'org.videolan.VLC'},version))

    def test_no_mutating_path_from_discover_panel_or_version_dialog(self):
        main=(ROOT/'main.py').read_text()
        tree=ast.parse(main)
        for classname in ('DiscoverPanel','VersionHistoryDialog'):
            node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==classname)
            forbidden_methods={'install_selected','install_github_release','after_discover_install'}
            self.assertFalse(forbidden_methods.intersection(
                {n.name for n in node.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}))
            # Exclude all actual package operations, not just their visible buttons.
            forbidden={'run_change','install_github_appimage','migrate_github_appimage',
                       'install_command','flatpak_revision_command','upgrade_command'}
            calls=set()
            for call in ast.walk(node):
                if isinstance(call,ast.Call):
                    target=call.func
                    if isinstance(target,ast.Attribute):calls.add(target.attr)
                    elif isinstance(target,ast.Name):calls.add(target.id)
            self.assertFalse(forbidden.intersection(calls),f'{classname} has mutating calls: {calls & forbidden}')
        discover=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='DiscoverPanel')
        text=ast.get_source_segment(main,discover)
        self.assertNotIn('Install latest version',text)
        self.assertNotIn('Choose this version',text)
        self.assertIn('discovery_project_url',text)
        self.assertIn('github_release_history',text)
        self.assertIn('flatpak_history',text)
        self.assertIn('self.discover_tab = DiscoverPanel()',main)

    def test_version_dialog_only_opens_or_copies(self):
        source=(ROOT/'main.py').read_text()
        version=source.split('class VersionHistoryDialog(QDialog):',1)[1].split('class DiscoverPanel(FeaturePanel):',1)[0]
        self.assertIn('QGuiApplication.clipboard().setText(commit)',version)
        self.assertIn('QDesktopServices.openUrl(QUrl(url))',version)
        self.assertNotIn('self.run_change(',version)

if __name__ == '__main__': unittest.main()
