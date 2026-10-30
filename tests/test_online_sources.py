"""Network-free tests: never fetch real downloads and never modify host apps."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from online_sources import (valid_repo, github_url, github_search, latest_github_release,
    flathub_search, choose_appimage, tracked_installs, save_tracked,
    github_updates, download_appimage, install_github_appimage, _json_request)
from feature_tools import search_software, scan_updates

REPO='publisher/CoolGame'
TAG='v1.2.0'
ASSET={'name':'CoolGame-linux-x86_64.AppImage','size':16,
       'browser_download_url':f'https://github.com/{REPO}/releases/download/{TAG}/CoolGame-linux-x86_64.AppImage'}
RELEASE={'repo':REPO,'tag':TAG,'url':f'https://github.com/{REPO}/releases/tag/{TAG}','assets':[ASSET]}

class FakeResponse:
    def __init__(self,content,url):
        self.body=content;self.url=url;self.pos=0
    def read(self,n=-1):
        if n<0:n=len(self.body)-self.pos
        b=self.body[self.pos:self.pos+n];self.pos+=len(b);return b
    def geturl(self):return self.url
    def __enter__(self):return self
    def __exit__(self,*_):return False

class SourcesTest(unittest.TestCase):
    def test_repo_allowlist_blocks_path_and_commands(self):
        for repo in ('-no/repo','org/a/extra','org/../repo','org/$(curl bad)','org/with space'):
            self.assertFalse(valid_repo(repo))
            with self.assertRaises(ValueError):github_url(repo)
        self.assertTrue(valid_repo(REPO))

    def test_search_results_include_forks_warning(self):
        rows=github_search('ship',lambda url: {'items':[
            {'full_name':REPO,'name':'CoolGame','description':'Linux adventure','fork':True},
            {'full_name':'bad/../../x','name':'oops'}]})
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['kind'],'GitHub')
        self.assertIn('FORK',rows[0]['detail'])

    def test_flathub_catalogue_maps_ids_only(self):
        rows=flathub_search('vlc', lambda url,body: {'hits':[
            {'app_id':'org.videolan.VLC','name':'VLC','summary':'Media player'},
            {'app_id':'bad;rm','name':'bad'}]})
        self.assertEqual([x['id'] for x in rows],['org.videolan.VLC'])
        self.assertEqual(rows[0]['scope'],'flathub')

    def test_releases_exclude_prereleases_and_wrong_origin(self):
        payload={'tag_name':TAG,'html_url':RELEASE['url'],'assets':[ASSET], 'draft':False,'prerelease':False}
        result=latest_github_release(REPO,lambda url:payload)
        self.assertEqual(result['tag'],TAG)
        with self.assertRaises(ValueError):latest_github_release(REPO,lambda url:{**payload,'prerelease':True})
        with self.assertRaises(ValueError):latest_github_release(REPO,lambda url:{**payload,'html_url':'https://other.example/release'})

    def test_appimage_is_restricted_by_arch_ambiguity_and_asset_url(self):
        self.assertEqual(choose_appimage(RELEASE,'x86_64')['name'],ASSET['name'])
        self.assertIsNone(choose_appimage(RELEASE,'aarch64'))
        self.assertIsNone(choose_appimage({**RELEASE,'assets':[ASSET,ASSET]},'x86_64'))
        self.assertIsNone(choose_appimage({**RELEASE,'assets':[{**ASSET,'browser_download_url':'https://evil.test/a.AppImage'}]},'x86_64'))
        self.assertIsNone(choose_appimage({**RELEASE,'assets':[{**ASSET,'name':'cool.zip'}]},'x86_64'))

    def test_untrusted_api_hosts_rejected_without_network(self):
        with self.assertRaises(ValueError):_json_request('https://evil.example/endpoint')
        with self.assertRaises(ValueError):_json_request('http://api.github.com/api')

    def test_registry_skips_bad_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Path(tmp)/'tracker.json'
            save_tracked({REPO:{'file':'cool.AppImage','tag':'v1','sha256':'a'},
                          'bad/x/y':{'file':'../bad.AppImage','tag':'v1'}},f)
            self.assertEqual(list(tracked_installs(f)),[REPO])
            self.assertEqual(f.stat().st_mode & 0o777, 0o600)

    def test_updates_are_only_offered_for_tracked_and_existing_apps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'cool.AppImage').write_bytes(b'fixture')
            tracker=root/'tracker.json'
            save_tracked({REPO:{'file':'cool.AppImage','tag':'v1','sha256':'fake'}},tracker)
            data={'tag_name':TAG,'html_url':RELEASE['url'],'assets':[ASSET]}
            rows,notes=github_updates(root,lambda url:data,tracker)
            if choose_appimage(RELEASE):
                self.assertEqual(len(rows),1)
                self.assertEqual(rows[0]['version'],TAG)
            (root/'cool.AppImage').unlink()
            rows,notes=github_updates(root,lambda url:data,tracker)
            self.assertEqual(rows,[])

    def test_reject_non_github_download_and_truncated_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)/'test.AppImage'
            with self.assertRaises(ValueError):download_appimage({**ASSET,'browser_download_url':'https://evil.example/a.AppImage'},REPO,dest)
            with self.assertRaises(ValueError):download_appimage(ASSET,REPO,dest,
                opener=lambda req,timeout:FakeResponse(b'bad','https://release-assets.githubusercontent.com/sample'))

    def test_appimage_sha256_and_magic(self):
        content=bytearray(24)
        content[:4]=b'\x7fELF'; content[4]=2; content[5]=1; content[18:20]=(62).to_bytes(2,'little')
        content=bytes(content)
        asset={**ASSET,'size':len(content),'digest':'sha256:'+hashlib.sha256(content).hexdigest()}
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'test.AppImage'
            with patch('online_sources.platform.machine',return_value='x86_64'):
                result=download_appimage(asset,REPO,p,
               opener=lambda req,timeout:FakeResponse(content,'https://release-assets.githubusercontent.com/sample'))
            self.assertEqual(result,hashlib.sha256(content).hexdigest())
            with patch('online_sources.platform.machine',return_value='x86_64'), self.assertRaises(ValueError):
                download_appimage({**asset,'digest':'sha256:'+'0'*64},REPO,p,
               opener=lambda req,timeout:FakeResponse(content,'https://release-assets.githubusercontent.com/sample'))
            with patch('online_sources.platform.machine',return_value='aarch64'), self.assertRaises(ValueError):
                download_appimage(asset,REPO,p,opener=lambda req,timeout:FakeResponse(content,'https://release-assets.githubusercontent.com/sample'))

    def test_install_tracks_only_after_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracker=Path(tmp)/'tracker.json'
            class FakeTab:
                def __init__(self):self.names=[]
                def appimage_install(self,p):self.names.append(p.name)
            fake=FakeTab()
            def download(asset,repo,path):
                path.write_bytes(b'\x7fELFtest')
                return 'f'*64
            with patch('online_sources.platform.machine',return_value='x86_64'):
                name=install_github_appimage(RELEASE,fake,tracker,download)
            self.assertEqual(fake.names,[name])
            self.assertEqual(tracked_installs(tracker)[REPO]['tag'],TAG)
            class BrokenTab:
                def appimage_install(self,p):raise OSError('disk full')
            tracker.unlink()
            with patch('online_sources.platform.machine',return_value='x86_64'):
                with self.assertRaises(OSError):install_github_appimage(RELEASE,BrokenTab(),tracker,download)
            self.assertFalse(tracker.exists())

    def test_network_modules_are_packed_and_opted_in(self):
        root=Path(__file__).resolve().parents[1]
        manifest=json.loads((root/'io.github.LionheartTim.UniversalLinuxSoftwareManager.json').read_text())
        self.assertIn('--share=network',manifest['finish-args'])
        self.assertIn('online_sources.py',[x['path'] for x in manifest['modules'][0]['sources']])
        self.assertIn('online_sources.py',' '.join(manifest['modules'][0]['build-commands']))

    def test_combined_search_and_update_keep_legacy_behavior(self):
        def run(args,timeout):return False,'','unavailable'
        def manager(kind):return None
        rows,notes=search_software(run,manager,'Ship of Harkinian',
           flathub_lookup=lambda q:[],
           github_lookup=lambda q:[{'kind':'GitHub','id':REPO,'name':'CoolGame','scope':'GitHub Releases'}])
        self.assertEqual(rows[0]['kind'],'GitHub')
        rows,notes=scan_updates(run,manager,github_lookup=lambda:([{'kind':'GitHub','id':REPO,'name':'CoolGame','scope':'GitHub Releases'}],[]))
        self.assertTrue(any(row['kind']=='GitHub' for row in rows))

if __name__=='__main__':unittest.main()
