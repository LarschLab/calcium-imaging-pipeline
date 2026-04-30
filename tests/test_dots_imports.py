from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DotsImportTests(unittest.TestCase):
    def test_dots_runner_imports_repo_utils_from_direct_script_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_site = Path(tmpdir)
            fake_utils = fake_site / "utils"
            fake_utils.mkdir()
            (fake_utils / "__init__.py").write_text("SENTINEL = 'wrong utils module'\n")

            env = os.environ.copy()
            env["PYTHONPATH"] = os.pathsep.join(
                [
                    str(ROOT / "visual_stimulation"),
                    str(fake_site),
                ]
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    textwrap.dedent(
                        f"""
                        import inspect
                        from pathlib import Path

                        import dots_runner

                        actual = Path(inspect.getfile(dots_runner.init_experiment_tree)).resolve()
                        expected = Path({str(ROOT / "utils.py")!r}).resolve()
                        if actual != expected:
                            raise AssertionError(f"expected {{expected}}, got {{actual}}")
                        """
                    ),
                ],
                cwd=tmpdir,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
