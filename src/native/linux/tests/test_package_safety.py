"""Output-boundary tests use only synthetic temporary files and archives."""
import importlib.util
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

PACKAGE_PATH = Path(__file__).resolve().parents[1] / 'package.py'
spec = importlib.util.spec_from_file_location('vantage_linux_package_safety', PACKAGE_PATH)
packager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packager)


class PackageSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='vantage-package-safety-')
        self.root = Path(self.temp.name)
        self.stage = self.root / 'stage'
        self.stage.mkdir()
        (self.stage / packager.MARKER_NAME).write_text(json.dumps(packager.package_marker('x86_64')))
        (self.stage / 'synthetic.txt').write_text('first version')
        self.output = self.root / 'out'
        self.output.mkdir()
        self.target = self.output / 'Vantage-linux-x86_64.tar.gz'
    def tearDown(self):
        self.temp.cleanup()
    def build(self):
        return packager.atomic_archive(self.stage, self.output, 'x86_64')
    def assert_no_archive_temporary_files(self):
        self.assertEqual(list(self.output.glob('.vantage-archive-*')), [])

    def test_existing_symlink_never_truncates_pointed_to_file(self):
        victim = self.root / 'unrelated.txt'
        victim.write_text('keep me unchanged')
        self.target.symlink_to(victim)
        with self.assertRaisesRegex(ValueError, 'symbolic link'):
            self.build()
        self.assertEqual(victim.read_text(), 'keep me unchanged')
        self.assertTrue(self.target.is_symlink())
        self.assert_no_archive_temporary_files()

    def test_dangling_symlink_is_rejected(self):
        victim = self.root / 'must-not-be-created.txt'
        self.target.symlink_to(victim)
        with self.assertRaisesRegex(ValueError, 'symbolic link'):
            self.build()
        self.assertFalse(victim.exists())
        self.assert_no_archive_temporary_files()

    def test_unrelated_regular_file_is_not_replaced(self):
        self.target.write_bytes(b'unrelated user data')
        with self.assertRaisesRegex(ValueError, 'not a marked Vantage build'):
            self.build()
        self.assertEqual(self.target.read_bytes(), b'unrelated user data')
        self.assert_no_archive_temporary_files()

    def test_unrelated_tar_archive_is_not_replaced(self):
        with tarfile.open(self.target, 'w:gz') as archive:
            archive.add(self.stage / 'synthetic.txt', arcname='unrelated.txt')
        before = self.target.read_bytes()
        with self.assertRaisesRegex(ValueError, 'not a marked Vantage build'):
            self.build()
        self.assertEqual(self.target.read_bytes(), before)

    def test_own_marked_archive_can_be_atomically_replaced(self):
        self.build()
        (self.stage / 'synthetic.txt').write_text('second version')
        self.assertEqual(self.build(), self.target)
        with tarfile.open(self.target, 'r:gz') as archive:
            self.assertEqual(archive.extractfile('Vantage/synthetic.txt').read(), b'second version')
        self.assert_no_archive_temporary_files()

    def test_failed_archive_write_preserves_previous_artifact(self):
        self.build()
        before = self.target.read_bytes()
        with patch.object(tarfile.TarFile, 'add', side_effect=RuntimeError('synthetic write failure')):
            with self.assertRaisesRegex(RuntimeError, 'synthetic write failure'):
                self.build()
        self.assertEqual(self.target.read_bytes(), before)
        self.assert_no_archive_temporary_files()

    def test_target_changed_during_build_is_not_overwritten(self):
        self.build()
        original_add = tarfile.TarFile.add
        def changed(archive, *args, **kwargs):
            result = original_add(archive, *args, **kwargs)
            self.target.write_text('new unrelated file')
            return result
        with patch.object(tarfile.TarFile, 'add', changed):
            with self.assertRaisesRegex(ValueError, 'not a marked Vantage build'):
                self.build()
        self.assertEqual(self.target.read_text(), 'new unrelated file')
        self.assert_no_archive_temporary_files()

    def test_new_target_created_at_publish_is_not_clobbered(self):
        original_link = packager.os.link
        def raced(source, target, **kwargs):
            self.target.write_text('arrived during final publication')
            return original_link(source, target, **kwargs)
        with patch.object(packager.os, 'link', raced):
            with self.assertRaises(FileExistsError):
                self.build()
        self.assertEqual(self.target.read_text(), 'arrived during final publication')
        self.assert_no_archive_temporary_files()

    def test_dangerous_output_locations_rejected_before_creation(self):
        repo, runtime, source, data = [self.root / name for name in ('repo', 'runtime', 'source', 'data')]
        for path in (repo, runtime, source, data):
            path.mkdir()
        for path in (repo, self.root, runtime, runtime / 'nested', source / 'generated', data / 'archive'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                packager.resolve_output_directory(path, runtime, source, repo, data_roots=[data])
        safe = repo / 'dist/native/linux'
        self.assertEqual(packager.resolve_output_directory(safe, runtime, source, repo, data_roots=[data]), safe)
        self.assertFalse(safe.exists())

    def test_output_symlink_parent_rejected(self):
        link = self.root / 'output-link'
        link.symlink_to(self.output, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symbolic links'):
            packager.resolve_output_directory(link / 'nested', self.stage, self.root / 'source', self.root / 'repo', data_roots=[])
        self.assertFalse((self.output / 'nested').exists())

    def test_stage_inside_runtime_prevents_recursive_copy(self):
        with self.assertRaisesRegex(ValueError, 'inside the backend source'):
            packager.validate_stage_location(self.stage / 'deep/new-stage', self.stage)
        packager.validate_stage_location(self.root / 'separate-stage', self.stage)


if __name__ == '__main__':
    unittest.main()
