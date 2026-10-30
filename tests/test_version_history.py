"""Offline version history / GUI wiring checks. Never update real software."""
import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from version_history import (github_release_history, parse_flatpak_history,
                            flatpak_history, flatpak_revision_command)

REPO = 'HarbourMasters/Shipwright'

def fake_release(tag, appimage=True, prerelease=False):
    asset = {'name':f'SOH-{tag}-linux-x86_64.AppImage', 'size':100,
             'browser_download_url':f'https://github.com/{REPO}/releases/download/{tag}/SOH-{tag}-linux-x86_64.AppImage'}
    return {'tag_name':tag, 'html_url':f'https://github.com/{REPO}/releases/tag/{tag}',
            'published_at':'2026-10-01T00:00:00Z', 'draft':False,'prerelease':prerelease,
            'assets':[asset] if appimage else [{'name':'linux.zip','size':100}]}

class HistoryTests(unittest.TestCase):
    def test_github_history_shows_previous_releases_and_installability(self):
        calls = []
        def fetch(url):
            calls.append(url)
            return [fake_release('v2'), fake_release('v1',appimage=False),
                    fake_release('rc',prerelease=True), fake_release('v0',appimage=True)]
        with patch('online_sources.platform.machine',return_value='x86_64'):
            result, complete=github_release_history(REPO,fetch)
        self.assertEqual([x['version'] for x in result], ['v2','v1','v0'])
        self.assertEqual([x['installable'] for x in result], [True,False,True])
        self.assertTrue(complete)
        self.assertIn('per_page=50&page=1',calls[0])

    def test_github_history_paginates_and_limits(self):
        def fetch(url):
            page=int(url.rsplit('=',1)[-1])
            return [fake_release(f'v{page}-{i}',appimage=False) for i in range(50)]
        versions,complete=github_release_history(REPO,fetch)
        self.assertEqual(len(versions), 150)
        self.assertFalse(complete)

    def test_github_history_skips_untrusted_urls_and_duplicate_tags(self):
        base = fake_release('v1')
        fake = [base, base.copy(),{**fake_release('v2'), 'html_url':'https://hacker.invalid/release'},
                {**fake_release('v3'), 'tag_name':'evil\nmessage'}]
        versions,_=github_release_history(REPO,lambda url:fake)
        self.assertEqual([x['version'] for x in versions], ['v1'])

    def test_invalid_github_repo_rejected_before_lookup(self):
        getter=Mock()
        with self.assertRaises(ValueError):github_release_history('org/../other',getter)
        getter.assert_not_called()

    def test_flatpak_history_parser_accepts_valid_shas_only(self):
        h1='a'*64
        h2='b'*64
        raw=(f'Commit: {h1}\nSubject: Export VLC\nDate: 2026-10-21\n'
             f'Commit: xxxxxxxxx\nSubject: fake\n'
             f'Commit: {h2}\nDate: 2026-10-14\nSubject: previous build\n')
        commits=parse_flatpak_history(raw)
        self.assertEqual([x['commit'] for x in commits],[h1,h2])
        self.assertEqual(commits[1]['subject'],'previous build')

    def test_flatpak_query_never_executes_shell(self):
        sha='a'*64
        def runner(args, timeout):
            self.assertEqual(args,['env','LC_ALL=C','flatpak','remote-info','--log','--app','flathub','org.videolan.VLC'])
            self.assertEqual(timeout,90)
            return True, f'Commit: {sha}\nDate: today',''
        self.assertEqual(flatpak_history(runner,'flathub','org.videolan.VLC')[0]['commit'],sha)
        with self.assertRaises(ValueError):flatpak_history(runner,'flathub; rm -rf /','org.videolan.VLC')

    def test_flatpak_rollback_requires_matching_user_origin(self):
        sha='b'*64
        ok=lambda args,timeout:(True,'flathub\n','')
        self.assertEqual(flatpak_revision_command(ok,'org.videolan.VLC','flathub',sha),
           ['flatpak','update','--user','--app','--noninteractive','-y',f'--commit={sha}','org.videolan.VLC'])
        self.assertIsNone(flatpak_revision_command(lambda args,t:(True,'other\n',''),
                      'org.videolan.VLC','flathub',sha))
        self.assertIsNone(flatpak_revision_command(lambda args,t:(False,'','no user install'),
                      'org.videolan.VLC','flathub',sha))
        with self.assertRaises(ValueError):flatpak_revision_command(ok,'org.videolan.VLC','flathub','$(malware)')

    def test_gui_and_flatpak_manifest_include_version_backend(self):
        root=Path(__file__).resolve().parents[1]
        source=(root/'main.py').read_text()
        self.assertIn('self.table.cellClicked.connect(self.on_result_clicked)',source)
        self.assertIn('class VersionHistoryDialog(QDialog):',source)
        self.assertIn('self.resize(1260, 800)',source)
        self.assertIn('header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)',source)
        data=json.loads((root/'io.github.LionheartTim.UniversalLinuxSoftwareManager.json').read_text())
        self.assertIn('version_history.py',[x['path'] for x in data['modules'][0]['sources']])
        self.assertIn('install -Dm644 version_history.py /app/bin/version_history.py',data['modules'][0]['build-commands'])

if __name__=='__main__':unittest.main()
