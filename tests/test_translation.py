from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

try:
    import aiohttp  # type: ignore
except ImportError:  # pragma: no cover - fallback for stripped test envs
    import sys
    import types

    aiohttp = types.ModuleType("aiohttp")

    class _ClientTimeout:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class _ClientSession:
        def __init__(self, *args, **kwargs):
            self.headers = {}
            self.closed = False

        async def close(self):
            self.closed = True

    aiohttp.ClientTimeout = _ClientTimeout
    aiohttp.ClientSession = _ClientSession
    sys.modules["aiohttp"] = aiohttp

try:
    from astrbot.api import logger  # noqa: F401
except ImportError:  # pragma: no cover - fallback for stripped test envs
    import sys
    import types

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
        # 标准 envelope
        self.assertEqual(
            extract('```json\n{"translations":["最新消息","民主空间站"]}\n```'),
            ["最新消息", "民主空间站"],
        )
        # 顶层数组
        self.assertEqual(extract('["最新消息","民主空间站"]'), ["最新消息", "民主空间站"])
        # data 包裹
        self.assertEqual(
            extract('{"data":{"translations":["最新消息","民主空间站"]}}'),
            ["最新消息", "民主空间站"],
        )
        # 长度不等：宽松解析仍返回数组，由调用方决定降级（不再返回 None）
        self.assertEqual(extract('{"translations":["数量不匹配"]}'), ["数量不匹配"])
        # 完全无法解析才返回 None
        self.assertIsNone(extract("not json"))
        self.assertIsNone(extract('{"foo":"bar"}'))

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

    async def test_openai_batch_length_mismatch_keeps_prefix_and_repairs_tail(
        self,
    ) -> None:
        class MismatchService(TranslationService):
            def __init__(self) -> None:
                super().__init__(
                    api_url="https://example.com/v1",
                    mode="openai",
                    api_key="secret",
                )
                self.fallback_calls: list[list[str]] = []

            async def _request_openai_content(self, payload):
                # expected=3, got=4 (one trailing commentary item)
                return json.dumps(
                    {
                        "translations": [
                            "最新消息",
                            "民主空间站",
                            "额外说明",
                            "以上为全部翻译",
                        ]
                    },
                    ensure_ascii=False,
                )

            async def _fallback_single_translate(self, texts, to_lang):
                self.fallback_calls.append(list(texts))
                return [f"补:{text}" for text in texts]

        service = MismatchService()
        result = await service._translate_openai_batch(
            ["News", "Station", "Planet"],
            "zh",
        )
        # Keep first 3 ordered items; discard the 4th extra commentary.
        # No single-item repair needed because keep == expected.
        self.assertEqual(result, ["最新消息", "民主空间站", "额外说明"])
        self.assertEqual(service.fallback_calls, [])

    async def test_openai_batch_short_response_repairs_missing_tail(self) -> None:
        class ShortService(TranslationService):
            def __init__(self) -> None:
                super().__init__(
                    api_url="https://example.com/v1",
                    mode="openai",
                    api_key="secret",
                )
                self.fallback_calls: list[list[str]] = []

            async def _request_openai_content(self, payload):
                # expected=3, got=2
                return json.dumps(
                    {"translations": ["最新消息", "民主空间站"]},
                    ensure_ascii=False,
                )

            async def _fallback_single_translate(self, texts, to_lang):
                self.fallback_calls.append(list(texts))
                return [f"补:{text}" for text in texts]

        service = ShortService()
        result = await service._translate_openai_batch(
            ["News", "Station", "Planet"],
            "zh",
        )
        self.assertEqual(result, ["最新消息", "民主空间站", "补:Planet"])
        self.assertEqual(service.fallback_calls, [["Planet"]])

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

    async def test_openai_429_enters_cooldown_without_retrying(self) -> None:
        class FakeResponse:
            status = 429
            headers = {}

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def text(self):
                return "rate limited"

        class FakeSession:
            def __init__(self):
                self.calls = 0

            def post(self, *args, **kwargs):
                self.calls += 1
                return FakeResponse()

        service = TranslationService(
            api_url="https://example.com/v1",
            mode="openai",
            api_key="secret",
            error_cooldown=60,
        )
        session = FakeSession()

        async def get_session():
            return session

        service._ensure_session = get_session
        first = await service._request_openai_content({"model": "test"})
        second = await service._request_openai_content({"model": "test"})

        self.assertEqual(first, "")
        self.assertEqual(second, "")
        self.assertEqual(session.calls, 1)

    async def test_openai_without_key_still_requests_endpoint(self) -> None:
        class FakeResponse:
            status = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def text(self):
                return ""

            async def json(self, content_type=None):
                return {"choices": [{"message": {"content": "翻译结果"}}]}

        class FakeSession:
            def __init__(self):
                self.calls: list[tuple[str, dict]] = []

            def post(self, url, **kwargs):
                self.calls.append((url, kwargs))
                return FakeResponse()

        service = TranslationService(
            api_url="https://example.com/v1",
            mode="openai",
            api_key="",
        )
        session = FakeSession()

        async def get_session():
            return session

        service._ensure_session = get_session
        content = await service._request_openai_content({"model": "test"})

        self.assertEqual(content, "翻译结果")
        self.assertEqual(len(session.calls), 1)
        self.assertNotIn("Authorization", session.calls[0][1]["headers"])

    async def test_openai_stream_reassembles_sse_content(self) -> None:
        class FakeContent:
            def __aiter__(self):
                async def iterate():
                    yield (
                        b'data: {"choices":[{"delta":{"content":'
                        b'"{\\\"translations\\\":[\\\"\\u65b0"}}]}\n'
                    )
                    yield (
                        b'data: {"choices":[{"delta":{"content":'
                        b'"\\u95fb\\\",\\\"\\u7a7a\\u95f4\\u7ad9\\\"]}"}}]}\n'
                    )
                    yield b"data: [DONE]\n"

                return iterate()

        class FakeResponse:
            status = 200
            content = FakeContent()

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakeSession:
            def __init__(self):
                self.headers = {}

            def post(self, *args, **kwargs):
                self.headers = kwargs.get("headers") or {}
                return FakeResponse()

        service = TranslationService(
            api_url="https://example.com/v1",
            mode="openai",
            api_key="secret",
            stream=True,
        )

        session = FakeSession()

        async def get_session():
            return session

        service._ensure_session = get_session
        content = await service._request_openai_content(
            {"model": "test", "stream": True}
        )

        self.assertEqual(content, '{"translations":["\u65b0\u95fb","\u7a7a\u95f4\u7ad9"]}')
        self.assertEqual(
            service._extract_openai_batch(content),
            ["\u65b0\u95fb", "\u7a7a\u95f4\u7ad9"],
        )
        self.assertEqual(session.headers.get("Accept"), "text/event-stream")

    async def test_openai_404_tries_fallback_endpoint(self) -> None:
        class FakeResponse:
            def __init__(self, status, content=""):
                self.status = status
                self._content = content

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def text(self):
                return self._content

            async def json(self, content_type=None):
                return {"choices": [{"message": {"content": "备用译文"}}]}

        class FakeSession:
            def __init__(self):
                self.calls: list[str] = []

            def post(self, url, **kwargs):
                self.calls.append(url)
                if len(self.calls) == 1:
                    return FakeResponse(404, "not found")
                return FakeResponse(200)

        service = TranslationService(
            api_url="https://example.com/v1",
            mode="openai",
            api_key="secret",
        )
        session = FakeSession()

        async def get_session():
            return session

        service._ensure_session = get_session
        content = await service._request_openai_content({"model": "test"})

        self.assertEqual(content, "备用译文")
        self.assertGreaterEqual(len(session.calls), 2)

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
