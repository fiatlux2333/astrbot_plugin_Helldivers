from __future__ import annotations

import asyncio
import hashlib
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

from astrbot_plugin_Helldivers.api_client import HD2Client
from astrbot_plugin_Helldivers.glossary import preapply_glossary
from astrbot_plugin_Helldivers.services import HelldiversService
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
        self.assertIn("超级地球", prompt)
        self.assertIn("Super Earth→超级地球", prompt)
        self.assertIn("Stratagem→战略配备", prompt)
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

    async def test_openai_min_interval_paces_requests(self) -> None:
        class FakeResponse:
            status = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def text(self):
                return ""

            async def json(self, content_type=None):
                return {"choices": [{"message": {"content": "译文"}}]}

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
            min_interval=0.25,
        )
        session = FakeSession()

        async def get_session():
            return session

        service._ensure_session = get_session
        loop = asyncio.get_running_loop()
        start = loop.time()
        await service._request_openai_content({"model": "test"})
        after_first = loop.time()
        await service._request_openai_content({"model": "test"})
        after_second = loop.time()

        self.assertEqual(session.calls, 2)
        self.assertLess(after_first - start, 0.2)
        self.assertGreaterEqual(after_second - after_first, 0.2)

    async def test_openai_min_interval_paces_concurrent_requests(self) -> None:
        # 回归：先占坑再睡眠。此前"睡醒才占坑"的实现会让并发协程读到
        # 同一目标时刻，实际同时发出请求。
        sent_at: list[float] = []

        class FakeResponse:
            status = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def text(self):
                return ""

            async def json(self, content_type=None):
                return {"choices": [{"message": {"content": "译文"}}]}

        class FakeSession:
            def post(self, *args, **kwargs):
                sent_at.append(asyncio.get_running_loop().time())
                return FakeResponse()

        service = TranslationService(
            api_url="https://example.com/v1",
            mode="openai",
            api_key="secret",
            min_interval=0.05,
        )
        session = FakeSession()

        async def get_session():
            return session

        service._ensure_session = get_session
        await asyncio.gather(
            *[
                service._request_openai_content({"model": "test"})
                for _ in range(4)
            ]
        )

        self.assertEqual(len(sent_at), 4)
        gaps = [b - a for a, b in zip(sent_at, sent_at[1:])]
        for gap in gaps:
            self.assertGreaterEqual(gap, 0.04)

    async def test_openai_min_interval_zero_keeps_requests_unpaced(self) -> None:
        class FakeResponse:
            status = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def text(self):
                return ""

            async def json(self, content_type=None):
                return {"choices": [{"message": {"content": "译文"}}]}

        class FakeSession:
            def post(self, *args, **kwargs):
                return FakeResponse()

        service = TranslationService(
            api_url="https://example.com/v1",
            mode="openai",
            api_key="secret",
        )
        session = FakeSession()

        async def get_session():
            return session

        service._ensure_session = get_session
        loop = asyncio.get_running_loop()
        start = loop.time()
        await service._request_openai_content({"model": "test"})
        await service._request_openai_content({"model": "test"})

        self.assertLess(loop.time() - start, 0.2)

    async def test_openai_timeout_marks_transient_failure(self) -> None:
        class FakeSession:
            def post(self, *args, **kwargs):
                raise asyncio.TimeoutError()

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

        self.assertEqual(content, "")
        self.assertTrue(service.in_transient_failure())
        self.assertFalse(service.in_cooldown())


class _StubServiceCache:
    """HelldiversService 构造所需的最小缓存桩（本测试不触碰业务缓存）。"""

    request_delay = 0.0
    update_interval = 60

    def register(self, name, fetcher):
        return None

    async def get(self, name):
        return None


class _StubSteamTranslator:
    """steam 卡片翻译测试桩：记录批量调用，可模拟限流冷却。"""

    def __init__(
        self,
        translations: dict[str, str] | None = None,
        *,
        cooldown: bool = False,
        transient: bool = False,
    ) -> None:
        self.translations = translations or {}
        self.cooldown = cooldown
        self.transient = transient
        self.batch_calls: list[list[str]] = []

    def in_cooldown(self) -> bool:
        return self.cooldown

    def in_transient_failure(self) -> bool:
        return self.transient

    async def translate_texts(self, texts: list[str]) -> list[str]:
        self.batch_calls.append(list(texts))
        if self.cooldown:
            # 与真实 translator 一致：冷却快速路径直接返回原文
            return list(texts)
        return [self.translations.get(text, text) for text in texts]

    async def translate_text(self, text: str) -> str:
        values = await self.translate_texts([text])
        return values[0]


class SteamCardBatchTranslationTests(unittest.IsolatedAsyncioTestCase):
    """steam 卡片两段式翻译：批量送译 + 冷却瞬态回退 + 旧缓存兼容。"""

    CONTENT = (
        "[h2]Development Notes[/h2]"
        "[p]A huge creature moves under the ground.[/p]"
        "[p]Players can trigger its ambush with explosions.[/p]"
        "[list][*]MASSIVE[*]ELUSIVE[*]DANGEROUS[/list]"
    )
    TRANSLATIONS = {
        "Dev Blog": "开发博客",
        "Development Notes": "开发笔记",
        "A huge creature moves under the ground.": "一只巨兽在地下移动。",
        "Players can trigger its ambush with explosions.": "玩家可以用爆炸触发它的伏击。",
        "MASSIVE": "巨大",
        "ELUSIVE": "难觅",
        "DANGEROUS": "危险",
    }

    @staticmethod
    def _preapplied(translations: dict[str, str]) -> dict[str, str]:
        # 送译基线是术语预替换后的文本，桩字典必须用同一基线做键。
        return {
            preapply_glossary(source): target for source, target in translations.items()
        }

    def _service(
        self, tmp: str, translator: _StubSteamTranslator
    ) -> HelldiversService:
        return HelldiversService(
            HD2Client(),
            _StubServiceCache(),
            translator,
            TranslationCache(Path(tmp), provider_fingerprint="test"),
            enable_translation=True,
        )

    def _update(self) -> dict[str, str]:
        return {"id": "42", "title": "Dev Blog", "content": self.CONTENT}

    @staticmethod
    def _all_texts(parsed) -> str:
        return " ".join(
            block.text + "".join(block.items) for block in parsed.blocks
        )

    async def test_blocks_batch_into_a_single_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            translator = _StubSteamTranslator(self._preapplied(self.TRANSLATIONS))
            service = self._service(tmp, translator)
            title, parsed = await service._prepare_steam_content(self._update())

            self.assertEqual(title, "开发博客")
            texts = self._all_texts(parsed)
            self.assertIn("一只巨兽在地下移动。", texts)
            self.assertIn("巨大", texts)
            # 标题 + 6 个正文槽位打包成一次批量请求，而不是 7 个单发请求
            self.assertEqual(len(translator.batch_calls), 1)
            self.assertEqual(len(translator.batch_calls[0]), 7)
            # 成功译文写入缓存
            self.assertTrue(service.translation_cache._data)

    async def test_cooldown_failure_keeps_english_without_negative_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            translator = _StubSteamTranslator(cooldown=True)
            service = self._service(tmp, translator)
            title, parsed = await service._prepare_steam_content(self._update())

            # 瞬态限流：不剔除内容，整卡以英文兜底
            self.assertEqual(title, "Dev Blog")
            texts = self._all_texts(parsed)
            self.assertIn("A huge creature moves under the ground.", texts)
            self.assertIn("MASSIVE", texts)
            # 不写负缓存，冷却结束后轮转可自动补翻
            self.assertEqual(service.translation_cache._data, {})

    async def test_persistent_failure_drops_and_caches_negative(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            translator = _StubSteamTranslator()  # 始终原样返回 → 视为持久失败
            service = self._service(tmp, translator)
            title, parsed = await service._prepare_steam_content(self._update())

            self.assertEqual(title, "")
            self.assertEqual(parsed.blocks, ())
            entries = list(service.translation_cache._data.values())
            self.assertTrue(entries)
            self.assertTrue(all(not entry["success"] for entry in entries))

    async def test_existing_cache_entries_still_hit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            translator = _StubSteamTranslator()
            service = self._service(tmp, translator)
            text = "A huge creature moves under the ground."
            digest = hashlib.sha1(
                preapply_glossary(text).encode("utf-8")
            ).hexdigest()[:12]
            await service.translation_cache.store(
                "steam_card", f"42:block:1:{digest}", preapply_glossary(text), "旧缓存译文"
            )
            title, parsed = await service._prepare_steam_content(self._update())

            # 其余槽位仍需送译；缓存命中的槽位不重复请求
            sent = [item for call in translator.batch_calls for item in call]
            self.assertNotIn(preapply_glossary(text), sent)
            self.assertIn("旧缓存译文", self._all_texts(parsed))

    async def test_rate_limited_warmup_converges_over_two_rounds(self) -> None:
        class QuotaTranslator(_StubSteamTranslator):
            """每轮只放行 2 次批量请求，随后进入冷却（模拟 5 次/分钟配额）。"""

            def __init__(self, translations):
                super().__init__(translations)
                self.remaining_calls = 2

            async def translate_texts(self, texts):
                if self.remaining_calls <= 0:
                    self.cooldown = True
                else:
                    self.remaining_calls -= 1
                return await super().translate_texts(texts)

        paragraphs = "".join(
            f"[p]Sample paragraph number {i} about the war effort.[/p]"
            for i in range(26)
        )
        translations = {
            "Dev Blog": "开发博客",
            **{
                f"Sample paragraph number {i} about the war effort.":
                    f"第{i}段战争努力样本。"
                for i in range(26)
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            translator = QuotaTranslator(self._preapplied(translations))
            service = self._service(tmp, translator)
            update = {"id": "42", "title": "Dev Blog", "content": paragraphs}

            title1, parsed1 = await service._prepare_steam_content(update)
            texts1 = self._all_texts(parsed1)
            # 第一轮：配额内部分翻译成功（标题 + 前 15 段）；
            # 限流后剩余段英文兜底而非掏空，且不写负缓存
            self.assertEqual(title1, "开发博客")
            self.assertIn("第0段战争努力样本。", texts1)
            self.assertIn("第14段战争努力样本。", texts1)
            self.assertIn("Sample paragraph number 25", texts1)
            self.assertNotIn("第25段战争努力样本。", texts1)
            self.assertEqual(len(service.translation_cache._data), 16)
            self.assertTrue(
                all(entry["success"] for entry in service.translation_cache._data.values())
            )

            # 第二轮（冷却结束）：已译段走缓存，剩余段补翻，整卡收敛
            translator.cooldown = False
            translator.remaining_calls = 2
            title2, parsed2 = await service._prepare_steam_content(update)
            texts2 = self._all_texts(parsed2)
            self.assertEqual(title2, "开发博客")
            self.assertNotIn("Sample paragraph number 25", texts2)
            self.assertIn("第25段战争努力样本。", texts2)
            # 每个槽位恰好入缓存一次：标题 + 26 段，无重复无负缓存
            self.assertEqual(len(service.translation_cache._data), 27)
            # 请求总量有界：第一轮 4 块 + 第二轮 2 块
            self.assertEqual(len(translator.batch_calls), 6)

    async def test_rate_limited_covers_cooldown_and_transient_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cooldown_only = _StubSteamTranslator(cooldown=True)
            service = self._service(tmp, cooldown_only)
            self.assertTrue(service._translation_rate_limited())

            transient_only = _StubSteamTranslator(transient=True)
            service2 = self._service(tmp, transient_only)
            self.assertTrue(service2._translation_rate_limited())

            healthy = _StubSteamTranslator()
            service3 = self._service(tmp, healthy)
            self.assertFalse(service3._translation_rate_limited())

    async def test_dispatch_failure_during_cooldown_keeps_original(self) -> None:
        message = "Attacking forces repelled. The operation was a complete success."
        with tempfile.TemporaryDirectory() as tmp:
            translator = _StubSteamTranslator(cooldown=True)  # 返回原文
            service = self._service(tmp, translator)
            result = await service._translate_dispatch(
                {"id": 7, "message": message}
            )

            # 瞬态失败：快讯正文回退英文原文，且不写负缓存
            self.assertEqual(result, message)
            self.assertEqual(service.translation_cache._data, {})

    async def test_dispatch_persistent_failure_drops_and_caches(self) -> None:
        message = "Attacking forces repelled. The operation was a complete success."
        with tempfile.TemporaryDirectory() as tmp:
            translator = _StubSteamTranslator()  # 原样返回 → 持久失败
            service = self._service(tmp, translator)
            result = await service._translate_dispatch(
                {"id": 7, "message": message}
            )

            self.assertEqual(result, "")
            entries = list(service.translation_cache._data.values())
            self.assertEqual(len(entries), 1)
            self.assertFalse(entries[0]["success"])


if __name__ == "__main__":
    unittest.main()
