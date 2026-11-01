"""Packaging checks without AstrBot or third-party Python dependencies."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile


SOURCE = Path(__file__).resolve().parents[1] / "pack.sh"
BASH = os.environ.get("PACK_BASH") or shutil.which("bash")
PLUGIN = "astrbot_plugin_Helldivers"


@unittest.skipUnless(BASH, "Bash is not installed")
class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hd2-pack-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "checkout with spaces"
        self.root.mkdir()
        shutil.copyfile(SOURCE, self.root / "pack.sh")
        for name in (
            "__init__.py", "main.py", "services.py", "metadata.yaml",
            "requirements.txt", "README.md", "LICENSE", "logo.png",
            "clients/__init__.py", "clients/jerry_map.py", "clients/jerry_wiki.py",
            "core/__init__.py", "renderers/__init__.py", "assets/LICENSES.md",
        ):
            self.put(name, "# fixture\n")
        self.put("_conf_schema.json", json.dumps({"enabled": {"type": "bool"}}))
        self.put("assets/manifest.json", "{}")
        self.put("assets/user/map.png", "fixture image")
        self.output = self.root / "dist" / f"{PLUGIN}.zip"

    def put(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def run_pack(self):
        environment = dict(os.environ, PYTHON_BIN=sys.executable)
        return subprocess.run(
            [BASH, (self.root / "pack.sh").as_posix()],
            cwd=self.root.parent, env=environment,
            capture_output=True, text=True, timeout=30,
        )

    def assert_success(self):
        result = self.run_pack()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_layout_and_exclusions_from_another_working_directory(self):
        for name in (
            ".env", ".venv/private.txt", ".cache/map.png", "data/config.json",
            "tests/test_private.py", "clients/__pycache__/cached.pyc",
            "clients/.env", "assets/.env", "assets/image.tmp.png",
            "assets/private_config.json",
        ):
            self.put(name, "private fixture")
        self.assert_success()
        with zipfile.ZipFile(self.output) as archive:
            names = archive.namelist()
            self.assertIsNone(archive.testzip())
            self.assertEqual(len(names), len(set(names)))
            for name in (
                "main.py", "metadata.yaml", "_conf_schema.json",
                "requirements.txt", "clients/jerry_map.py", "clients/jerry_wiki.py",
                "assets/user/map.png", "assets/LICENSES.md",
            ):
                self.assertIn(f"{PLUGIN}/{name}", names)
            self.assertTrue(all(name.startswith(f"{PLUGIN}/") for name in names))
            self.assertFalse(any(
                part.startswith(".") or part in {"data", "tests", "__pycache__"}
                for name in names for part in name.split("/")
            ))
            self.assertFalse(any("private" in name or ".tmp." in name for name in names))

    def test_repeat_build_preserves_other_dist_files(self):
        self.put("dist/keep.txt", "keep me")
        self.assert_success()
        previous = self.output.read_bytes()
        self.assert_success()
        self.assertEqual(previous, self.output.read_bytes())
        self.assertEqual((self.root / "dist/keep.txt").read_text(), "keep me")
        self.assertFalse(list(self.output.parent.glob(".pack-*.tmp")))

    def test_bad_input_keeps_last_valid_archive(self):
        self.assert_success()
        previous = self.output.read_bytes()
        for name, invalid in (
            ("_conf_schema.json", "{"),
            ("_conf_schema.json", '{"enabled": {}}'),
            ("main.py", "def broken(:\n"),
        ):
            with self.subTest(name=name, invalid=invalid):
                original = (self.root / name).read_text(encoding="utf-8")
                self.put(name, invalid)
                result = self.run_pack()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ERROR:", result.stderr)
                self.assertEqual(previous, self.output.read_bytes())
                self.put(name, original)

    def test_missing_runtime_module_fails(self):
        (self.root / "clients/jerry_wiki.py").unlink()
        result = self.run_pack()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("jerry_wiki.py", result.stderr)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
