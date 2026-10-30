"""Network-free tests for manually installed AppImage GitHub links."""
import tempfile
import unittest
from pathlib import Path

from feature_tools import scan_updates
from online_sources import (parse_github_repository, guess_appimage_version,
                            semver_tuple, link_existing_appimage, tracked_installs,
                            github_updates)
from installed_inventory import installed_software, merge_updates

REPO = 'zolaware/reblue'
RELEASE = {
    'tag_name': 'v1.3.1',
    'html_url': 'https://github.com/zolaware/reblue/releases/tag/v1.3.1',
    'draft': False,
    'prerelease': False,
    'assets': [{'name':'reblue-1.3.1-x86_64.AppImage', 'size': 1234,
                'browser_download_url':
                'https://github.com/zolaware/reblue/releases/download/v1.3.1/reblue-1.3.1-x86_64.AppImage'}],
}

class ManualLinkTests(unittest.TestCase):
    def test_github_link_parser(self):
        self.assertEqual(parse_github_repository('https://github.com/zolaware/reblue/'), REPO)
        self.assertEqual(parse_github_repository('zolaware/reblue'), REPO)
        self.assertEqual(parse_github_repository('https://github.com/zolaware/reblue.git'), REPO)
        for url in ('http://github.com/zolaware/reblue', 'https://evil.example/zolaware/reblue',
                    'https://github.com/zolaware/reblue/releases',
                    'https://github.com/zolaware/reblue?tab=code',
                    'https://user@github.com/zolaware/reblue', '../reblue', 'zolaware/reblue;rm'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                parse_github_repository(url)

    def test_version_hint_and_comparison(self):
        self.assertEqual(guess_appimage_version('reblue-1.0.0-x86_64.appimage'), 'v1.0.0')
        self.assertEqual(guess_appimage_version('Unknown.AppImage'), '')
        self.assertEqual(semver_tuple('v1.3.1'), (1, 3, 1))
        self.assertEqual(semver_tuple('v1'), (1,))
        self.assertIsNone(semver_tuple('nightly-2026.10'))

    def test_existing_lowercase_appimage_is_linked_and_update_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'Applications'; folder.mkdir()
            filename='reblue-1.0.0-x86_64.appimage'
            (folder/filename).write_bytes(b'local appimage test fixture')
            tracker=Path(tmp)/'github.json'
            self.assertEqual(link_existing_appimage(folder, filename, REPO, 'v1.0.0', tracker),REPO)
            tracked=tracked_installs(tracker)
            self.assertEqual(tracked[REPO]['file'],filename)
            self.assertEqual(tracked[REPO]['tag'],'v1.0.0')
            found,notes=github_updates(folder, lambda url:RELEASE, tracker)
            self.assertEqual([e['version'] for e in found],['v1.3.1'])
            def runner(argv, limit):return False,'','absent'
            installed,_=installed_software(runner, lambda k: None, folder, tracked)
            rows=merge_updates(installed,found, {('GitHub',REPO)})
            self.assertEqual(rows[0]['status'],'available')
            self.assertEqual(rows[0]['installed_version'],'v1.0.0')
            self.assertEqual(rows[0]['available_version'],'v1.3.1')
            self.assertEqual(rows[0]['release']['repo'],REPO)

    def test_same_and_older_versions_not_offered_as_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'Applications'; folder.mkdir()
            filename='reblue-1.3.1-x86_64.AppImage'; (folder/filename).write_bytes(b'x')
            tracker=Path(tmp)/'github.json'
            for version in ('v1.3.1','v2.0.0'):
                link_existing_appimage(folder,filename,REPO,version,tracker)
                checked=set()
                results,_=github_updates(folder,lambda url: RELEASE,tracker,checked)
                self.assertEqual(results,[])
                self.assertIn(('GitHub',REPO),checked)

    def test_invalid_source_and_symlink_never_linked(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'Applications'; folder.mkdir()
            (folder/'original.AppImage').write_bytes(b'x')
            (folder/'link.AppImage').symlink_to(folder/'original.AppImage')
            tracker=Path(tmp)/'github.json'
            for name,tag in (('../bad.AppImage','v1.0'),('missing.AppImage','v1.0'),
                             ('link.AppImage','v1.0'),('original.AppImage','hello')):
                with self.subTest(name=name),self.assertRaises(ValueError):
                    link_existing_appimage(folder,name,REPO,tag,tracker)
            self.assertFalse(tracker.exists())

    def test_cannot_rebind_to_unrelated_file_or_second_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'Applications'; folder.mkdir()
            (folder/'one.AppImage').write_bytes(b'one')
            (folder/'two.AppImage').write_bytes(b'two')
            tracker=Path(tmp)/'github.json'
            link_existing_appimage(folder,'one.AppImage',REPO,'v1.0.0',tracker)
            with self.assertRaises(ValueError):
                link_existing_appimage(folder,'two.AppImage',REPO,'v1.0.0',tracker)
            with self.assertRaises(ValueError):
                link_existing_appimage(folder,'one.AppImage','other/repo','v1.0.0',tracker)
            self.assertEqual(list(tracked_installs(tracker)),[REPO])

    def test_unhealthy_flatpak_remote_does_not_hide_healthy_updates(self):
        def run(argv, timeout):
            if argv[:2] == ['flatpak','remote-ls']:
                if argv[-1] == 'flathub':return True, 'org.gimp.GIMP\t3.0\n',''
                return False,'','GPG verification enabled, no summary found'
            if argv[:2] == ['flatpak','remotes']:
                return True,'flathub\nclaude-desktop\n',''
            return False,'','not available'
        checked=set()
        results,notes=scan_updates(run,lambda k:None, checked=checked,flatpak_scopes=['user'])
        self.assertIn('org.gimp.GIMP',[r['id'] for r in results])
        self.assertTrue(any('claude-desktop' in n for n in notes))
        self.assertNotIn(('Flatpak','user'), checked)  # one remote failed: never claim all are current

    def test_all_successful_remote_checks_mark_scope_checked(self):
        def run(argv, timeout):
            if argv[:2] == ['flatpak','remote-ls']:
                if len(argv) == 6: return False,'','combined call failed'
                return True,'',''
            if argv[:2] == ['flatpak','remotes']:
                return True,'flathub\n',''
            return False,'','not available'
        checked=set()
        _,notes=scan_updates(run,lambda k:None,checked=checked,flatpak_scopes=['user'])
        self.assertIn(('Flatpak','user'),checked)

    def test_github_link_button_does_not_add_discover_installation(self):
        root=Path(__file__).resolve().parents[1]
        main=(root/'main.py').read_text()
        self.assertIn('class UpdatesPanel',main)
        self.assertIn('def link_selected_source(self)',main)
        self.assertIn('Link GitHub source',main)
        self.assertIn('DiscoverPanel',main)
        self.assertIn('Discover does not download or install anything',main)

if __name__=='__main__':unittest.main()
