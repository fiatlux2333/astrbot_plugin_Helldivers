from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path

if "aiohttp" not in sys.modules:
    aiohttp = types.ModuleType("aiohttp")

    class _ClientTimeout:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class _ClientSession:
        closed = False

    aiohttp.ClientTimeout = _ClientTimeout
    aiohttp.ClientSession = _ClientSession
    sys.modules["aiohttp"] = aiohttp

if "astrbot.api" not in sys.modules:
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")

    class _Logger:
        def __getattr__(self, name):
            return lambda *args, **kwargs: None

    api.logger = _Logger()
    astrbot.api = api
    sys.modules["astrbot"] = astrbot
    sys.modules["astrbot.api"] = api

from astrbot_plugin_Helldivers.translator import TranslationCache, TranslationService


class TranslationTests(unittest.IsolatedAsyncioTestCase):
    def test_builtin_response_shapes(self) -> None:
        extract = TranslationService._extract_builtin_translation
        self.assertEqual(extract({"translatedText": "最高命令"}), "最高命令")
        self.assertEqual(extract({"translated_text": "银河战争"}), "银河战争")
        self.assertEqual(extract({"translation": "民主空间站"}), "民主空间站")
        self.assertEqual(
            extract({"data": {"translatedText": "管理式民主"}}),
            "管理式民主",
        )
        self.assertEqual(
            extract({"data": {"translated_text": "为了超级地球"}}),
            "为了超级地球",
        )
        self.assertEqual(extract({"data": {}}), "")

    def test_uapi_request_uses_current_protocol(self) -> None:
        service = TranslationService(
            api_url="https://uapis.cn/api/v1/ai/translate",
            target_lang="zh-CN",
            api_key="secret",
        )
        payload, headers, params = service._builtin_request("Global event", None)
        self.assertEqual(params, {"target_lang": "zh"})
        self.assertEqual(payload["text"], "Global event")
        self.assertEqual(payload["context"], "entertainment")
        self.assertTrue(payload["preserve_format"])
        self.assertNotIn("targetLanguage", payload)
        self.assertEqual(headers["Authorization"], "Bearer secret")

    def test_generic_builtin_keeps_legacy_protocol(self) -> None:
        service = TranslationService(
            api_url="https://translate.example/api",
            target_lang="zh-CN",
        )
        payload, headers, params = service._builtin_request("Global event", None)
        self.assertIsNone(params)
        self.assertEqual(payload["targetLanguage"], "zh-CN")
        self.assertNotIn("Authorization", headers)

    async def test_provider_change_invalidates_legacy_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = TranslationCache(Path(tmp), provider_fingerprint="new-provider")
            cache._data["news:1"] = {
                "original_text": "Original",
                "translated_text": "旧译文",
                "updated_at": 1,
                "success": True,
                "provider_fingerprint": "",
            }
            self.assertIsNone(await cache.get("news", "1"))

    async def test_failed_translation_uses_short_ttl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = TranslationCache(
                Path(tmp), provider_fingerprint="provider", fallback_ttl=60
            )
            await cache.store(
                "news",
                "1",
                "Original",
                "Original",
                success=False,
                fallback_reason="unchanged",
            )
            entry = await cache.get("news", "1")
            self.assertIsNotNone(entry)
            assert entry is not None
            self.assertFalse(entry["success"])


if __name__ == "__main__":
    unittest.main()
