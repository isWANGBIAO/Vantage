import json
import os
from pathlib import Path
import plistlib
import tempfile
import unittest

from validate_output import MARKER, MARKER_PATH, is_same_or_descendant, validate_output
from publish_bundle import publish_bundle


class PackageOutputTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.runtime = self.root / "runtime"
        self.runtime.mkdir()
        self.output = self.root / "output with spaces"

    def test_separate_new_output_is_allowed(self):
        self.assertEqual(validate_output(self.runtime, self.output), self.output)

    def test_output_inside_input_and_equal_input_are_rejected(self):
        for output in (self.runtime, self.runtime / "nested/output"):
            with self.assertRaises(ValueError):
                validate_output(self.runtime, output)

    def test_runtime_inside_target_is_rejected(self):
        runtime = self.output / "Vantage.app/Contents/Resources/backend-runtime"
        runtime.mkdir(parents=True)
        with self.assertRaises(ValueError):
            validate_output(runtime, self.output)

    def test_symlink_into_runtime_is_rejected(self):
        self.output.symlink_to(self.runtime, target_is_directory=True)
        with self.assertRaises(ValueError):
            validate_output(self.runtime, self.output)

    def test_unrecognized_target_is_preserved(self):
        target = self.output / "Vantage.app"
        target.mkdir(parents=True)
        original = target / "important.txt"
        original.write_text("synthetic original")
        with self.assertRaises(ValueError):
            validate_output(self.runtime, self.output)
        self.assertEqual(original.read_text(), "synthetic original")

    def test_only_recognized_output_may_be_replaced(self):
        target = self.output / "Vantage.app"
        marker = target / MARKER_PATH
        marker.parent.mkdir(parents=True)
        marker.write_text(json.dumps(MARKER))
        (target / "Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "app.vantage.native"}))
        self.assertEqual(validate_output(self.runtime, self.output), self.output)
        marker.write_text(json.dumps({"format": "other"}))
        with self.assertRaises(ValueError):
            validate_output(self.runtime, self.output)

    def test_symlinked_target_is_rejected(self):
        self.output.mkdir()
        (self.output / "Vantage.app").symlink_to(self.runtime, target_is_directory=True)
        with self.assertRaises(ValueError):
            validate_output(self.runtime, self.output)

    def test_repository_and_personal_data_boundaries(self):
        repository = self.root / "repo"
        repository.mkdir()
        for output in (repository, self.root, repository / "src/output"):
            with self.assertRaises(ValueError):
                validate_output(self.runtime, output, repository=repository, data_paths=[])
        self.assertEqual(validate_output(self.runtime, repository / "build/native", repository=repository, data_paths=[]), repository / "build/native")
        data = self.root / "personal-data"
        for output in (data, data / "bundle", self.root):
            with self.assertRaises(ValueError):
                validate_output(self.runtime, output, data_paths=[data])

    def test_safe_destination_symlink_is_also_rejected(self):
        real = self.root / "real-output"
        real.mkdir()
        self.output.symlink_to(real, target_is_directory=True)
        with self.assertRaises(ValueError):
            validate_output(self.runtime, self.output)

    def make_bundle(self, path, text):
        marker = path / MARKER_PATH
        marker.parent.mkdir(parents=True)
        marker.write_text(json.dumps(MARKER))
        (path / "Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "app.vantage.native"}))
        (path / "original.txt").write_text(text)
        return path

    def test_publish_failure_restores_previous_without_deleting_it(self):
        target = self.make_bundle(self.output / "Vantage.app", "old")
        staged = self.make_bundle(self.output / "stage/Vantage.app", "new")
        def fail_install(source, destination):
            if source == staged:
                raise OSError("synthetic move failure")
            os.rename(source, destination)
        with self.assertRaises(OSError):
            publish_bundle(staged, target, rename=fail_install)
        self.assertEqual((target / "original.txt").read_text(), "old")
        self.assertEqual((staged / "original.txt").read_text(), "new")

    def test_success_preserves_identified_previous_bundle(self):
        target = self.make_bundle(self.output / "Vantage.app", "old")
        staged = self.make_bundle(self.output / "stage/Vantage.app", "new")
        backup = publish_bundle(staged, target)
        self.assertEqual((target / "original.txt").read_text(), "new")
        self.assertIsNotNone(backup)
        self.assertEqual((backup / "original.txt").read_text(), "old")

    def test_case_aliases_cannot_bypass_runtime_repository_or_data_checks(self):
        with self.assertRaises(ValueError):
            validate_output(self.runtime, self.root / "RUNTIME/out")
        repository = self.root / "repository"
        repository.mkdir()
        for output in (self.root / "REPOSITORY", self.root / "REPOSITORY/src/out"):
            with self.assertRaises(ValueError):
                validate_output(self.runtime, output, repository=repository, data_paths=[])
        with self.assertRaises(ValueError):
            validate_output(self.runtime, self.root / "PERSONAL/data", data_paths=[self.root / "personal"])
        self.assertFalse(is_same_or_descendant(self.root / "runtime-other", self.runtime))

    def test_unicode_equivalent_runtime_and_data_paths_are_rejected(self):
        runtime = self.root / "Café"
        runtime.mkdir()
        with self.assertRaises(ValueError):
            validate_output(runtime, self.root / "Cafe\u0301/out")
        with self.assertRaises(ValueError):
            validate_output(self.runtime, self.root / "Donne\u0301es/out", data_paths=[self.root / "Données"])

    def test_staged_target_case_and_unicode_aliases_are_rejected(self):
        staged = self.make_bundle(self.output / "vantage.app", "case original")
        with self.assertRaises(ValueError):
            publish_bundle(staged, self.output / "Vantage.app")
        self.assertEqual((staged / "original.txt").read_text(), "case original")
        unicode_stage = self.make_bundle(self.output / "Café/Vantage.app", "unicode original")
        with self.assertRaises(ValueError):
            publish_bundle(unicode_stage, self.output / "Cafe\u0301/Vantage.app")
        self.assertEqual((unicode_stage / "original.txt").read_text(), "unicode original")


if __name__ == "__main__":
    unittest.main()
