"""Marketplace regressions: official logger, metadata and packaged artifacts."""
from __future__ import annotations

import importlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import yaml
from astrbot.api import logger
from astrbot.core.star.filter.platform_adapter_type import ADAPTER_NAME_2_TYPE
from astrbot.core.star.updater import _PluginUpdater
from packaging.specifiers import SpecifierSet

from astrbot_plugin_Helldivers.scripts.check_release import (
    MAX_RELEASE_BYTES, REQUIRED_FILES, check_files, check_logging, check_path,
)

ROOT = Path(__file__).resolve().parents[1]


def fixture_files():
    return {name: (ROOT / name).read_bytes() for name in REQUIRED_FILES}


class LoggerPolicyTests(unittest.TestCase):
    def test_all_runtime_modules_use_official_logging(self):
        report = check_path(ROOT)
        self.assertEqual(report["runtime_logging"], "passed")

    def test_previously_rejected_modules_share_the_actual_astrbot_logger(self):
        for module in ("clients.arsenal_client", "clients.companion_news_monitor",
                       "renderers.dss_renderer", "renderers.map_renderer",
                       "renderers.stats_renderer", "renderers.visual_assets"):
            with self.subTest(module=module):
                loaded = importlib.import_module(f"astrbot_plugin_Helldivers.{module}")
                self.assertIs(loaded.logger, logger)

    def test_direct_alias_and_fallback_logging_are_rejected(self):
        examples = [
            "import logging\nlogger = logging.getLogger(__name__)",
            "import logging as log\nlogger = log.getLogger(__name__)",
            "from logging import getLogger as make_logger\nlogger = make_logger(__name__)",
            "try:\n    from astrbot.api import logger\nexcept ImportError:\n    import logging\n    logger = logging.getLogger(__name__)",
            "from astrbot import logger\nlogger.warning('wrong import')",
        ]
        for source in examples:
            with self.subTest(source=source):
                self.assertTrue(check_logging("clients/example.py", source.encode()))

    def test_direct_official_import_is_accepted(self):
        self.assertEqual(check_logging("main.py", b"from astrbot.api import logger\nlogger.info('ready')"), [])


class MetadataPolicyTests(unittest.TestCase):
    def test_real_metadata_passes_sdk_validation_and_adapter_lookup(self):
        metadata = yaml.safe_load((ROOT / "metadata.yaml").read_text())
        _PluginUpdater.validate_plugin_metadata(metadata, "metadata.yaml")
        self.assertTrue(set(metadata["support_platforms"]) <= ADAPTER_NAME_2_TYPE.keys())
        self.assertTrue(SpecifierSet(metadata["astrbot_version"]).contains("4.28.2"))
        self.assertEqual(check_files(fixture_files())["version"], "2.0.1")

    def test_missing_wrong_type_and_template_fields_fail(self):
        cases = [("name", "astrbot_plugin_example"), ("author", ""), ("version", 2.0),
                 ("repo", "https://github.com/your-name/repo"), ("desc", ["not a string"]),
                 ("astrbot_version", ">=v4.16"), ("astrbot_version", "latest"),
                 ("support_platforms", "aiocqhttp"), ("support_platforms", ["snowluna"]),
                 ("tags", "helldivers"), ("short_desc", 123), ("social_link", "not a URL")]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                files = fixture_files()
                metadata = yaml.safe_load(files["metadata.yaml"])
                metadata[field] = value
                files["metadata.yaml"] = yaml.safe_dump(metadata).encode()
                with self.assertRaises(ValueError):
                    check_files(files)
        files = fixture_files()
        metadata = yaml.safe_load(files["metadata.yaml"]); metadata.pop("display_name")
        files["metadata.yaml"] = yaml.safe_dump(metadata).encode()
        with self.assertRaises(ValueError):
            check_files(files)

    def test_duplicate_yaml_keys_are_rejected(self):
        files = fixture_files(); files["metadata.yaml"] += b"\nversion: 1.0.0\n"
        with self.assertRaisesRegex(ValueError, "duplicate metadata key"):
            check_files(files)

    def test_optional_fields_may_be_omitted(self):
        files = fixture_files(); metadata = yaml.safe_load(files["metadata.yaml"])
        for field in ("short_desc", "social_link", "support_platforms", "tags", "astrbot_version"):
            metadata.pop(field, None)
        files["metadata.yaml"] = yaml.safe_dump(metadata).encode()
        self.assertEqual(check_files(files)["metadata"], "passed")

    def test_runtime_and_user_agent_version_mismatches_are_rejected(self):
        files = fixture_files()
        files["core/plugin_info.py"] = files["core/plugin_info.py"].replace(b'v2.0.1', b'v1.10.3')
        with self.assertRaisesRegex(ValueError, "runtime version"):
            check_files(files)
        files = fixture_files(); schema = json.loads(files["_conf_schema.json"])
        schema["api_user_agent"]["default"] = "astrbot_plugin_Helldivers/1.10.3"
        files["_conf_schema.json"] = json.dumps(schema).encode()
        with self.assertRaisesRegex(ValueError, "User-Agent"):
            check_files(files)


class ArchivePolicyTests(unittest.TestCase):
    def test_publication_limit_is_16_mb_and_oversized_archive_fails(self):
        self.assertEqual(MAX_RELEASE_BYTES, 16_000_000)
        with self.assertRaisesRegex(ValueError, "exceeds 16 MB"):
            check_files(fixture_files(), archive_bytes=MAX_RELEASE_BYTES + 1)

    def test_archive_contents_are_checked_even_if_source_is_clean(self):
        for extra, content in (("clients/old_renderer.py", b"import logging\n"),
                               (".env", b"placeholder"), ("tests/test_dev.py", b"pass\n"),
                               ("../escape.py", b"pass\n")):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "release.zip"
                with zipfile.ZipFile(path, "w") as archive:
                    for name, body in fixture_files().items():
                        archive.writestr(name, body)
                    archive.writestr(extra, content)
                with self.assertRaises(ValueError):
                    check_path(path)

    def test_clean_archive_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "release.zip"
            with zipfile.ZipFile(path, "w") as archive:
                for name, body in fixture_files().items():
                    archive.writestr(name, body)
            self.assertEqual(check_path(path)["version"], "2.0.1")
