import json, unittest
from pathlib import Path
root = Path(__file__).resolve().parents[1]

class ManifestTest(unittest.TestCase):
    def test_manifests(self):
        m = json.loads((root / 'io.github.LionheartTim.UniversalLinuxSoftwareManager.json').read_text())
        self.assertEqual(m['id'], 'io.github.LionheartTim.UniversalLinuxSoftwareManager')
        self.assertEqual(m['runtime-version'], '6.11')
        self.assertEqual(m['base-version'], '6.11')
        self.assertEqual(m['base'], 'com.riverbankcomputing.PyQt.BaseApp')
        self.assertNotIn('--filesystem=host', m['finish-args'])
        src = m['modules'][0]['sources']
        self.assertTrue(all(x['type'] == 'file' and (root / x['path']).is_file() for x in src))

    def test_appstream_developer_identifier_is_lowercase(self):
        from xml.etree import ElementTree
        metadata = root / 'io.github.LionheartTim.UniversalLinuxSoftwareManager.metainfo.xml'
        component = ElementTree.parse(metadata).getroot()
        self.assertEqual(component.findtext('id'), 'io.github.LionheartTim.UniversalLinuxSoftwareManager')
        developer = component.find('developer')
        self.assertIsNotNone(developer)
        self.assertEqual(developer.get('id'), 'io.github.lionhearttim')
        self.assertEqual(developer.findtext('name'), 'LionheartTim')

    def test_desktop_has_one_main_category_and_package_manager_category(self):
        desktop = (root / 'io.github.LionheartTim.UniversalLinuxSoftwareManager.desktop').read_text()
        self.assertIn('Categories=Settings;PackageManager;', desktop)
        self.assertNotIn('Categories=System;Settings;Utility;', desktop)

    def test_snap_explicit_warning_and_signed_default(self):
        text = (root / 'main.py').read_text()
        self.assertIn("'snap', 'ack'", text)
        self.assertIn("'snap', 'install', '--dangerous'", text)
        self.assertIn('This file might be dangerous or malicious.', text)
        self.assertIn('warning.setDefaultButton(QMessageBox.StandardButton.No)', text)
        self.assertIn('unsigned_snap = True', text)

if __name__ == '__main__': unittest.main()
