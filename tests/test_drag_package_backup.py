import copy
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from local_file_backup import (package_type,validate_source,create_backup,inspect_backup,
                               extract_package,extract_settings)

class DragPackageBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def installer(self,filename,data=b'!<arch>\n' + b'example payload'):
        p=self.root/filename
        p.write_bytes(data)
        return p

    def test_type_mapping(self):
        self.assertEqual(package_type('Foo-1.AppImage'),'AppImage')
        self.assertEqual(package_type('test.pkg.tar.zst'),'Arch')
        self.assertEqual(package_type('example.flatpak'),'Flatpak')
        self.assertEqual(package_type('example.rpm'),'RPM')
        self.assertIsNone(package_type('example.flatpakref'))
        self.assertIsNone(package_type('file.sh'))
        self.assertIsNone(package_type('../example.rpm'))

    def test_backup_and_restore_exact_deb(self):
        installer=self.installer('example.deb')
        archive=self.root/'backup.zip'
        created=create_backup(archive,[installer],source_desktop='kde',source_distro={'fedora'})
        self.assertEqual(created['packages'][0]['kind'],'DEB')
        validated=inspect_backup(archive)
        extracted=extract_package(archive,0,self.root,validated) if False else None
        restore_root=self.root/'restore';restore_root.mkdir()
        extracted=extract_package(archive,0,restore_root,validated)
        self.assertEqual(installer.read_bytes(),extracted.read_bytes())

    def test_mixed_formats(self):
        app=self.installer('game.AppImage',b'\x7fELF'+b'x'*128)
        rpm=self.installer('example.rpm',b'\xed\xab\xee\xdb'+b'r'*128)
        flatpak=self.installer('app.flatpak',b'bundle-data')
        archive=self.root/'backup.zip'
        create_backup(archive,[app,rpm,flatpak])
        self.assertEqual([e['kind'] for e in inspect_backup(archive)['packages']],
                         ['AppImage','RPM','Flatpak'])
        root=self.root/'r';root.mkdir()
        self.assertEqual(extract_package(archive,0,root).stat().st_mode & 0o700,0o700)

    def test_invalid_file_rejected(self):
        with self.assertRaises(ValueError):validate_source(self.installer('bad.rpm',b'not-an-rpm'))
        with self.assertRaises(ValueError):validate_source(self.installer('file.flatpakref',b'https://example.test'))
        with self.assertRaises(ValueError):validate_source(self.installer('fake.deb',b''))

    def test_reject_duplicate_file_name(self):
        a=self.installer('x.deb')
        with self.assertRaises(ValueError):create_backup(self.root/'zip.zip',[a,a])

    def test_checksum_tampering_rejected(self):
        a=self.installer('x.deb')
        archive=self.root/'zip.zip';create_backup(archive,[a])
        manifest=inspect_backup(archive)
        with zipfile.ZipFile(archive,'w') as z:
            z.writestr('packages/0',b'corrupt payload')
        with self.assertRaises(ValueError):inspect_backup(archive)

    def test_extra_archive_member_rejected(self):
        a=self.installer('x.deb')
        archive=self.root/'zip.zip';create_backup(archive,[a])
        with zipfile.ZipFile(archive,'a') as z:z.writestr('../../wrong',b'nope')
        with self.assertRaises(ValueError):inspect_backup(archive)

    def test_settings_archive_included(self):
        a=self.installer('x.deb')
        nested=self.root/'settings.zip';nested.write_bytes(b'fake settings zip')
        archive=self.root/'backup.zip'
        create_backup(archive,[a],nested,source_desktop='gnome')
        inspected=inspect_backup(archive)
        root=self.root/'unpack';root.mkdir()
        self.assertEqual(extract_settings(archive,root,inspected).read_bytes(),b'fake settings zip')

    def test_reject_unsafe_symlink(self):
        a=self.installer('x.deb')
        b=self.root/'linked.deb';b.symlink_to(a)
        with self.assertRaises(ValueError):create_backup(self.root/'zip.zip',[b])

    def test_empty_without_settings(self):
        with self.assertRaises(ValueError):create_backup(self.root/'none.zip',[])

if __name__=='__main__': unittest.main()
