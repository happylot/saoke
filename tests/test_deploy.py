import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('receiver', Path(__file__).parents[1] / 'deploy/receive.py')
receiver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(receiver)
SHA = 'a' * 40
EMPTY = {'meta': {}, 'balance': '0.00', 'cashback': '0',
         'statement': {}, 'cards': [], 'txns': []}


def archive(files):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w:gz') as tar:
        for name, content in files.items():
            if isinstance(content, tarfile.TarInfo):
                tar.addfile(content)
            else:
                info = tarfile.TarInfo(name)
                info.size = len(content)
                tar.addfile(info, io.BytesIO(content))
    return stream.getvalue()


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.files = {'index.html': b'<!doctype html><title>Test</title>',
                      'data.json': json.dumps(EMPTY).encode(), 'version.txt': SHA.encode()}

    def run_deploy(self, command=None, error=None):
        response = SimpleNamespace(stdout=SHA + '\n')
        with patch.object(receiver, 'BASE', self.base), \
             patch.dict(receiver.os.environ, {'SSH_ORIGINAL_COMMAND': command or 'deploy ' + SHA}), \
             patch.object(receiver.sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(archive(self.files)))), \
             patch.object(receiver.subprocess, 'run', return_value=response, side_effect=error):
            receiver.deploy()

    def test_valid_release_is_activated(self):
        self.run_deploy()
        self.assertTrue((self.base / 'current').is_symlink())
        self.assertEqual((self.base / 'current/version.txt').read_text(), SHA)
        self.assertEqual({p.name for p in (self.base / 'current').iterdir()}, set(self.files))

    def test_extra_paths_and_wrong_revision_are_rejected(self):
        for name, content in [('../outside', b'bad'), ('.env', b'bad'), ('version.txt', b'b' * 40)]:
            with self.subTest(name=name):
                original = self.files.copy()
                self.files[name] = content
                with self.assertRaises(ValueError):
                    self.run_deploy()
                self.files = original
                self.assertFalse((self.base / 'current').exists())

    def test_symlink_entries_are_rejected(self):
        info = tarfile.TarInfo('index.html')
        info.type = tarfile.SYMTYPE
        info.linkname = '/etc/passwd'
        self.files['index.html'] = info
        with self.assertRaises(ValueError):
            self.run_deploy()

    def test_financial_data_is_rejected(self):
        self.files['data.json'] = json.dumps({**EMPTY, 'cards': [{'last4': '1234'}]}).encode()
        with self.assertRaisesRegex(ValueError, 'empty deployment data'):
            self.run_deploy()

    def test_failed_https_check_restores_previous_release(self):
        previous = self.base / 'releases/previous'
        previous.mkdir(parents=True)
        (previous / 'version.txt').write_text('previous')
        (self.base / 'current').symlink_to(previous)
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_deploy(error=subprocess.CalledProcessError(22, 'curl'))
        self.assertEqual((self.base / 'current').resolve(), previous.resolve())
        self.assertEqual(list((self.base / 'releases').iterdir()), [previous])

    def test_shell_commands_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Only deploy'):
            self.run_deploy(command='sh -c id')


if __name__ == '__main__':
    unittest.main()
