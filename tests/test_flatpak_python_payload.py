"""Regression tests: catch launch crashes from omitted local Python modules."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'io.github.LionheartTim.UniversalLinuxSoftwareManager.json'
CHECKER = ROOT / 'scripts' / 'check-packaging.py'
loader = importlib.util.spec_from_file_location('check_packaging', CHECKER)
checker = importlib.util.module_from_spec(loader)
loader.loader.exec_module(checker)


class FlatpakPythonPayloadTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))

    def test_all_local_python_modules_will_ship(self):
        self.assertEqual(checker.validate_manifest(self.manifest, ROOT), [])

    def test_audio_backup_is_in_sources_and_install_commands(self):
        sources = {item['path'] for item in self.manifest['modules'][0]['sources']}
        commands = self.manifest['modules'][0]['build-commands']
        self.assertIn('audio_backup.py', sources)
        self.assertIn('install -Dm644 audio_backup.py /app/bin/audio_backup.py', commands)

    def test_missing_audio_module_would_fail_before_build(self):
        bad = copy.deepcopy(self.manifest)
        module = bad['modules'][0]
        module['sources'] = [x for x in module['sources'] if x['path'] != 'audio_backup.py']
        module['build-commands'] = [x for x in module['build-commands']
                                    if 'audio_backup.py' not in x]
        messages = checker.validate_manifest(bad, ROOT)
        self.assertTrue(any('audio_backup.py' in message for message in messages), messages)

    def test_missing_staged_file_would_stop_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            staging = Path(tmp)
            target = staging / 'files' / 'bin'
            target.mkdir(parents=True)
            for local in ROOT.glob('*.py'):
                (target / local.name).write_bytes(b'placeholder')
            self.assertEqual(checker.validate_staging(ROOT, staging), [])
            (target / 'audio_backup.py').unlink()
            self.assertTrue(any('audio_backup.py' in msg
                                for msg in checker.validate_staging(ROOT, staging)))


if __name__ == '__main__':
    unittest.main()
