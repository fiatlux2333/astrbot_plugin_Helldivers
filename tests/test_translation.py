from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

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

    def test_openai_batch_response_parser(self) -> None:
        extract = TranslationService._extract_openai_batch
        self.assertEqual(
            extract(
                '```json\n{"translations":["最新消息","民主空间站"]}\n```',
                2,
            ),
            ["最新消息", "民主空间站"],
        )
        self.assertIsNone(extract('{"translations":["数量不匹配"]}', 2))
        self.assertIsNone(extract("not json", 2))

    def test_hd2_localization_prompt_enforces_game_tone_and_terms(self) -> None:
        prompt = TranslationService._localization_system_prompt(
            "简体中文", batch=True
        )
        self.assertIn("不是逐词翻译器", prompt)
        self.assertIn("Super Earth=超级地球", prompt)
        self.assertIn("Stratagem=战略配备", prompt)
        self.assertIn("防御战役", prompt)
        self.assertIn("不要输出其他内容", prompt)

    async def test_translate_texts_uses_one_openai_batch_call(self) -> None:
        class BatchService(TranslationService):
            def __init__(self) -> None:
                super().__init__(
                    api_url="https://example.com/v1",
                    mode="openai",
                    api_key="secret",
                )
                self.batch_calls = 0

            async def _translate_openai_batch(self, texts, to_lang):
                self.batch_calls += 1
                return [f"译:{text}" for text in texts]

        service = BatchService()
        result = await service.translate_texts(["News", "Station", "Planet"])
        self.assertEqual(result, ["译:News", "译:Station", "译:Planet"])
        self.assertEqual(service.batch_calls, 1)

    async def test_builtin_batch_uses_one_marked_request(self) -> None:
        class BatchService(TranslationService):
            def __init__(self) -> None:
                super().__init__(api_url="https://example.com/translate")
                self.calls = 0

            async def _translate_builtin(self, text, to_lang):
                self.calls += 1
                return text.replace("News", "新闻").replace("Station", "空间站")

        service = BatchService()
        result = await service.translate_texts(["News", "Station"])
        self.assertEqual(result, ["新闻", "空间站"])
        self.assertEqual(service.calls, 1)

    async def test_openai_502_retries_once(self) -> None:
        class FakeResponse:
            def __init__(self, status, payload=None):
                self.status = status
                self.payload = payload or {}

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def text(self):
                return "bad gateway"

            async def json(self, content_type=None):
                return self.payload

        class FakeSession:
            def __init__(self):
                self.responses = [
                    FakeResponse(502),
                    FakeResponse(
                        200,
                        {
                            "choices": [
                                {"message": {"content": "重试成功"}}
                            ]
                        },
                    ),
                ]
                self.calls = 0

            def post(self, *args, **kwargs):
                response = self.responses[self.calls]
                self.calls += 1
                return response

        service = TranslationService(
            api_url="https://example.com/v1",
            mode="openai",
            api_key="secret",
        )
        session = FakeSession()

        async def get_session():
            return session

        service._ensure_session = get_session
        with patch(
            "astrbot_plugin_Helldivers.translator.asyncio.sleep",
            new=AsyncMock(),
        ):
            content = await service._request_openai_content({"model": "test"})
        self.assertEqual(content, "重试成功")
        self.assertEqual(session.calls, 2)

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
