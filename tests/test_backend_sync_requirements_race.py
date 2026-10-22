"""Offline regressions for requirements edits while synchronizing a runtime."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from src.core.backend_environment_state import (
    BACKEND_ENVIRONMENT_STATE_NAME,
    current_platform_identity,
    current_python_identity,
)
from src.scripts.sync_backend_runtime_environment import (
    backend_runtime_python_path,
    synchronize_backend_runtime_environment,
)


class RequirementsSnapshotTests(unittest.TestCase):
    def exercise(self, phase):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            core = root / 'requirements-core.txt'
            core.write_text('opencv-contrib-python==4.14.0.94\nqa-package==1.0\n')
            overlay = root / 'requirements-backend-runtime-gpu.txt'
            overlay.write_text('-r requirements-core.txt\n')
            normalizer = root / 'normalizer.py'
            normalizer.write_text('pass\n')
            venv = root / '.venv-backend-runtime-gpu'
            changed = False
            armed = False
            installed_package = "qa-package==1.0"

            def edit():
                nonlocal changed
                if not changed:
                    core.write_text(core.read_text().replace('qa-package==1.0', 'qa-package==2.0'))
                    changed = True

            def runner(command, **_kwargs):
                nonlocal installed_package
                if command[1:3] == ['-m', 'venv']:
                    python = backend_runtime_python_path(venv)
                    python.parent.mkdir(parents=True)
                    python.write_text('synthetic interpreter')
                    if phase == 'before-install':
                        edit()
                elif '-r' in command:
                    installed_package = next(line for line in core.read_text().splitlines() if line.startswith('qa-package=='))
                    if phase == 'during-install':
                        edit()
                return SimpleNamespace(returncode=0, stdout='', stderr='')

            def probe(*_args):
                if phase == 'during-validation' or (phase == 'during-reuse-validation' and armed):
                    edit()
                return {
                    'python': current_python_identity(),
                    'platform': current_platform_identity(),
                    'distributions': ['opencv-contrib-python==4.14.0.94', 'pip==25.3', installed_package],
                }

            options = dict(
                project_root=root, venv=venv, core_requirements=core,
                requirements=overlay, opencv_normalizer=normalizer,
                run_command=runner, probe_environment=probe,
                pip_check=lambda *_: True, import_check=lambda *_: True,
                opencv_check=lambda *_: True,
            )
            if phase is None:
                self.assertFalse(synchronize_backend_runtime_environment(**options).reused)
                self.assertTrue(synchronize_backend_runtime_environment(**options).reused)
            else:
                if phase == 'during-reuse-validation':
                    self.assertFalse(synchronize_backend_runtime_environment(**options).reused)
                    armed = True
                with self.assertRaisesRegex(RuntimeError, 'requirements changed'):
                    synchronize_backend_runtime_environment(**options)
                self.assertFalse((venv / BACKEND_ENVIRONMENT_STATE_NAME).exists())
                # The next call must rebuild rather than reuse the old closure.
                self.assertFalse(synchronize_backend_runtime_environment(**options).reused)

    def test_unchanged_environment_is_reused(self):
        self.exercise(None)

    def test_requirements_edits_cannot_certify_old_environment(self):
        for phase in ('before-install', 'during-install', 'during-validation', 'during-reuse-validation'):
            with self.subTest(phase=phase):
                self.exercise(phase)


if __name__ == '__main__':
    unittest.main()
