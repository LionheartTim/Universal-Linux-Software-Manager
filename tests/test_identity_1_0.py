import json
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
APP_ID = "io.github.LionheartTim.UniversalLinuxSoftwareManager"
NAME = "Universal Linux Software Manager"

class IdentityTests(unittest.TestCase):
    def test_manifest_and_desktop_match(self):
        data = json.loads((ROOT / (APP_ID + ".json")).read_text())
        self.assertEqual(data["id"], APP_ID)
        desktop=(ROOT/(APP_ID+".desktop")).read_text()
        self.assertIn("Name="+NAME, desktop)
        self.assertIn("Icon="+APP_ID, desktop)
        paths=[s["path"] for s in data["modules"][0]["sources"]]
        self.assertIn(APP_ID+".desktop", paths)
        self.assertIn(APP_ID+".metainfo.xml", paths)

    def test_appstream_and_version(self):
        root = ET.parse(ROOT/(APP_ID+".metainfo.xml")).getroot()
        self.assertEqual(root.findtext("id"), APP_ID)
        self.assertEqual(root.findtext("name"), NAME)
        self.assertEqual(root.find("releases/release").get("version"), "1.0.0")

    def test_build_script_and_gui(self):
        script=(ROOT/"scripts/build-bundle.sh").read_text()
        self.assertIn(APP_ID,script)
        self.assertIn("UniversalLinuxSoftwareManager-v1.0.0.flatpak",script)
        main=(ROOT/"main.py").read_text()
        self.assertIn("APP_ID = '"+APP_ID+"'",main)
        self.assertIn("setWindowTitle('"+NAME+"')",main)
        self.assertIn("v1.0.0",main)

if __name__ == "__main__": unittest.main()
