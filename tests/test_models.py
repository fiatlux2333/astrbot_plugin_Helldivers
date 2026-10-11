from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

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

from astrbot_plugin_Helldivers.clients.api_client import HD2Client
from astrbot_plugin_Helldivers.core.cache import CacheService
from astrbot_plugin_Helldivers.core.campaign_trends import CampaignTrendStore
from astrbot_plugin_Helldivers.core.formatters import format_dss_message
from astrbot_plugin_Helldivers.clients.remote_image_cache import ALLOWED_IMAGE_MIMES
from astrbot_plugin_Helldivers.services import HelldiversService
from astrbot_plugin_Helldivers.core.stats_model import build_stats_view_model
from astrbot_plugin_Helldivers.core.steam_parser import parse_steam_content
from astrbot_plugin_Helldivers.clients.translator import TranslationCache, TranslationService
from astrbot_plugin_Helldivers.core.war_state import WarState, campaign_faction


class ModelTests(unittest.TestCase):
    def test_dss_text_omits_tactical_actions(self) -> None:
        message = format_dss_message(
            {
                "id32": 1,
                "planet": {"name": "梅萨", "currentOwner": "Humans"},
                "tacticalActions": [
                    {"display_name": "轨道封锁", "status": 2}
                ],
            }
        )
        self.assertNotIn("战术行动", message)
        self.assertNotIn("轨道封锁", message)

    def test_bilibili_long_image_pixel_limit_covers_current_report(self) -> None:
        schema = json.loads(
            (Path(__file__).parents[1] / "_conf_schema.json").read_text(
                encoding="utf-8"
            )
        )
        limit = schema["bilibili_image_max_pixels"]["default"]
        self.assertEqual(limit, 64_000_000)
        # 2026-09-26 快报长图 2606×19510 ≈ 5083 万像素必须放行
        self.assertGreater(limit, 2_606 * 19_510)

    def test_remote_image_cache_does_not_advertise_avif(self) -> None:
        self.assertNotIn("image/avif", ALLOWED_IMAGE_MIMES)

    def test_api_error_formatter_keeps_empty_timeout_useful(self) -> None:
        self.assertEqual(HD2Client._format_error(TimeoutError()), "TimeoutError")
        self.assertEqual(
            HD2Client._format_error(ValueError("bad response")),
            "ValueError: bad response",
        )

    def test_assignment_normalization_predicate(self) -> None:
        self.assertFalse(HD2Client._looks_like_assignment({}))
        self.assertFalse(HD2Client._looks_like_assignment({"data": []}))
        self.assertTrue(HD2Client._looks_like_assignment({"id": 12}))
        self.assertTrue(HD2Client._looks_like_assignment({"setting": {}}))

    def test_campaign_faction_uses_planet_owner_before_human_campaign(self) -> None:
        campaign = {
            "faction": "Humans",
            "planet": {"currentOwner": "Automaton"},
        }
        self.assertEqual(campaign_faction(campaign), "Automaton")

    def test_defense_progress_uses_event_health(self) -> None:
        campaign = {
            "id": 9,
            "faction": "Humans",
            "planet": {
                "index": 7,
                "name": "Defense",
                "currentOwner": "Humans",
                "health": 1_000,
                "maxHealth": 1_000,
                "event": {
                    "id": 88,
                    "faction": "Terminids",
                    "health": 250,
                    "maxHealth": 1_000,
                },
            },
        }
        row = WarState(campaigns=[campaign]).campaign_rows()[0]
        self.assertTrue(row["is_defense"])
        self.assertAlmostEqual(row["progress"], 75.0)
        self.assertEqual(row["faction"], "Terminids")

    def test_stats_model_uses_mission_time_and_api_accuracy(self) -> None:
        summary = {
            "galaxy_stats": {
                "missionsWon": 9,
                "missionsLost": 1,
                "missionTime": 3_600,
                "timePlayed": 99_999,
                "bulletsFired": 10,
                "bulletsHit": 20,
                "accurracy": 55.5,
                "bugKills": 100,
                "deaths": 10,
            }
        }
        model = build_stats_view_model(summary, status={"time": 86_400})
        stats = model["stats"]
        self.assertEqual(stats["mission_time"], 3_600)
        self.assertEqual(stats["api_accuracy"], 55.5)
        self.assertEqual(model["meta"]["war_day"], 2)

    def test_trend_identity_reset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = CampaignTrendStore(
                Path(tmp) / "history.json", min_sample_age_seconds=1
            )
            first = {
                "planet_index": 1,
                "campaign_id": 10,
                "progress": 10,
            }
            store.record_rows([first], timestamp=1_000)
            later = dict(first, progress=13)
            attached = store.attach([later], timestamp=1_600)
            self.assertAlmostEqual(attached[0]["recent_rate_pph"], 18.0)
            changed = dict(later, campaign_id=11, progress=1)
            attached = store.attach([changed], timestamp=2_200)
            self.assertIsNone(attached[0]["recent_rate_pph"])

    def test_steam_parser_extracts_only_official_images(self) -> None:
        parsed = parse_steam_content(
            "[h1]Update[/h1][p]Hello &amp; democracy[/p]"
            "[img]https://clan.steamstatic.com/images/44156989/a.png[/img]"
            "[img]https://example.com/b.png[/img]"
        )
        self.assertIn("Hello & democracy", parsed.plain_text)
        self.assertEqual(len(parsed.image_candidates), 1)
        self.assertIn("steamstatic.com", parsed.image_candidates[0])


class ApiClientTests(unittest.IsolatedAsyncioTestCase):
    def test_external_hosts_do_not_receive_hd2_contact_headers(self) -> None:
        client = HD2Client(contact="contact@example.com")
        hd2_headers = client._headers_for_url(
            "https://api.helldivers2.dev/api/v1/war"
        )
        steam_headers = client._headers_for_url(
            "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
        )
        self.assertEqual(hd2_headers["X-Super-Contact"], "contact@example.com")
        self.assertNotIn("X-Super-Contact", steam_headers)
        self.assertNotIn("X-Super-Client", steam_headers)

    async def test_official_steam_news_uses_single_attempt(self) -> None:
        class RecordingClient(HD2Client):
            def __init__(self) -> None:
                super().__init__()
                self.max_attempts = None
                self.failure_is_warning = None

            async def request_json(self, method, path, **kwargs):
                self.max_attempts = kwargs.get("max_attempts")
                self.failure_is_warning = kwargs.get("failure_is_warning")

        client = RecordingClient()
        self.assertIsNone(await client.fetch_steam_updates_official())
        self.assertEqual(client.max_attempts, 1)
        self.assertTrue(client.failure_is_warning)

    async def test_steam_news_falls_back_to_community_source(self) -> None:
        class FallbackClient(HD2Client):
            async def fetch_steam_updates_official(self, appid=None, count=None):
                return None

            async def fetch_steam_updates_community(self):
                return [{"id": "fallback"}]

        updates = await FallbackClient().fetch_steam_updates()
        self.assertEqual(updates, [{"id": "fallback"}])

    async def test_companion_gww_news_is_selected_by_route_id(self) -> None:
        class CompanionClient(HD2Client):
            async def request_json(self, method, path, **kwargs):
                self.request = (method, path, kwargs)
                return {
                    "clientTime": 1_785_937_046_432,
                    "timeSinceStart": 79_896_733,
                    "news": [
                        {
                            "id": "3844",
                            "published": 77_821_817,
                            "type": 0,
                            "message": "<i=3>NEW MAJOR ORDER</i>\n\nLiberate MEISSA",
                        }
                    ],
                }

        client = CompanionClient()
        article = await client.fetch_companion_gww_news(3844)
        self.assertIsNotNone(article)
        assert article is not None
        self.assertEqual(article["id"], 3844)
        self.assertEqual(article["source"], "helldiverscompanion")
        self.assertTrue(str(article["published"]).endswith("Z"))
        self.assertEqual(client.request[0], "GET")
        self.assertEqual(client.request[1], client.COMPANION_WAR_DATA_URL)

    async def test_companion_gww_news_returns_none_for_unknown_id(self) -> None:
        class CompanionClient(HD2Client):
            async def request_json(self, method, path, **kwargs):
                return {"news": [{"id": 1, "message": "test"}]}

        self.assertIsNone(await CompanionClient().fetch_companion_gww_news(3844))


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_companion_batch_timeout_keeps_request_running_for_cache(self) -> None:
        release = asyncio.Event()
        cancelled = asyncio.Event()

        class SlowTranslator:
            async def translate_texts(self, texts):
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    raise
                return ["已完成的后台译文" for _ in texts]

        class EmptyCache:
            provider_fingerprint = "test"

            def __init__(self):
                self.stored = []

            async def get(self, namespace, item_id):
                return None

            async def store(self, *args, **kwargs):
                self.stored.append((args, kwargs))

        async def immediate_timeout(tasks, timeout=None):
            # 审计 H2 后走 asyncio.wait（不再调 wait_for）：
            # 直接返回 done=∅ / running=全部，模拟预算立即到期。
            return set(), set(tasks)

        service = object.__new__(HelldiversService)
        service.translator = SlowTranslator()
        service.translation_cache = EmptyCache()
        service.companion_translation_batch_timeout = 4.5
        service.companion_translation_budget = 30.0
        service._companion_translation_tasks = set()
        target = types.SimpleNamespace(kind="news_latest")

        with patch(
            "astrbot_plugin_Helldivers.services.asyncio.wait",
            new=immediate_timeout,
        ):
            outcome = await service.translate_companion_fragments(
                target,
                ["An English briefing that should finish in the background."],
            )

        self.assertEqual(outcome.translations, {})
        self.assertEqual(len(service._companion_translation_tasks), 1)
        self.assertFalse(cancelled.is_set())

        release.set()
        await asyncio.gather(*service._companion_translation_tasks)
        await asyncio.sleep(0)

        self.assertFalse(cancelled.is_set())
        self.assertEqual(len(service.translation_cache.stored), 1)
        self.assertEqual(service._companion_translation_tasks, set())

    async def test_companion_partial_timeout_recycles_finished_batches(self) -> None:
        """≥2 批次且部分在预算内完成：已完成批次必须被回收（审计 H2 泄漏回归）。

        泄漏形态：预算内完成的批次既无回调也无 discard，滞留在
        _companion_translation_tasks；预热循环 5 分钟一次，无界增长。
        """

        release = asyncio.Event()

        class MixedTranslator:
            async def translate_texts(self, texts):
                if any("slow" in text for text in texts):
                    await release.wait()
                    return ["慢批次译文" for _ in texts]
                return [f"快译文 {index}" for index, _ in enumerate(texts)]

        class EmptyCache:
            provider_fingerprint = "test"

            def __init__(self):
                self.stored = []

            async def get(self, namespace, item_id):
                return None

            async def store(self, *args, **kwargs):
                self.stored.append((args, kwargs))

        async def fake_wait(tasks, timeout=None):
            # 让快批次有机会完成，再按真实完成状态切分 done/running
            await asyncio.sleep(0.05)
            done = {t for t in tasks if t.done()}
            running = {t for t in tasks if not t.done()}
            return done, running

        service = object.__new__(HelldiversService)
        service.translator = MixedTranslator()
        service.translation_cache = EmptyCache()
        service.companion_translation_batch_timeout = 4.5
        service.companion_translation_budget = 30.0
        service._companion_translation_tasks = set()
        target = types.SimpleNamespace(kind="news_latest")

        # batch_size=16 → 16 段快文本 + 1 段慢文本 = 2 个批次
        fragments = [f"Fragment {i} needs translation right now." for i in range(16)]
        fragments.append("A very slow briefing that blocks until release.")
        self.assertGreater(len(fragments), 16)

        with patch(
            "astrbot_plugin_Helldivers.services.asyncio.wait",
            new=fake_wait,
        ):
            await service.translate_companion_fragments(target, fragments)

        # 只有超时在途的慢批次留在集合里；预算内完成的快批次必须已被回收
        self.assertEqual(len(service._companion_translation_tasks), 1)

        release.set()
        await asyncio.gather(*service._companion_translation_tasks)
        await asyncio.sleep(0)

        self.assertEqual(service._companion_translation_tasks, set())

    async def test_failed_companion_translation_is_not_cacheable(self) -> None:
        class FailingTranslator:
            async def translate_texts(self, texts):
                return list(texts)

        class EmptyCache:
            provider_fingerprint = "test"

            async def get(self, namespace, item_id):
                return None

            async def store(self, *args, **kwargs):
                raise AssertionError("failed translations must not be cached")

        service = object.__new__(HelldiversService)
        service.translator = FailingTranslator()
        service.translation_cache = EmptyCache()
        target = types.SimpleNamespace(kind="news_latest")

        outcome = await service.translate_companion_fragments(
            target,
            ["An unmapped English briefing sentence."],
        )

        self.assertFalse(outcome.cacheable)
        self.assertFalse(outcome.complete)
        self.assertEqual(outcome.untranslated_count, 1)
        self.assertEqual(outcome.translations, {})

    async def test_failed_cached_translation_is_dropped_by_default(self) -> None:
        class FailingTranslator:
            async def translate_text(self, text):
                return text

        class EmptyCache:
            provider_fingerprint = "test"

            async def get(self, namespace, item_id):
                return None

            async def store(self, *args, **kwargs):
                self.stored = (args, kwargs)

        service = object.__new__(HelldiversService)
        service.enable_translation = True
        service.drop_untranslated_content = True
        service.translator = FailingTranslator()
        service.translation_cache = EmptyCache()

        result = await service._translate_cached_text(
            "news",
            "1",
            "An unmapped English briefing sentence.",
        )

        self.assertEqual(result, "")

    async def test_failed_companion_translation_cache_marks_incomplete(self) -> None:
        class UnusedTranslator:
            async def translate_texts(self, texts):
                raise AssertionError("failed cache should suppress retry until TTL")

        class FailedCache:
            provider_fingerprint = "test"

            async def get(self, namespace, item_id):
                return {
                    "original_text": "Untranslated station briefing",
                    "translated_text": "Untranslated station briefing",
                    "success": False,
                }

        service = object.__new__(HelldiversService)
        service.translator = UnusedTranslator()
        service.translation_cache = FailedCache()
        target = types.SimpleNamespace(kind="station")

        outcome = await service.translate_companion_fragments(
            target,
            ["Untranslated station briefing"],
        )

        self.assertFalse(outcome.cacheable)
        self.assertFalse(outcome.complete)
        self.assertEqual(outcome.untranslated_count, 1)

    async def test_dss_message_preparation_skips_tactical_translation(self) -> None:
        translated: list[str] = []

        async def localize_planets(rows, *, include_english=True):
            return None

        async def translate(namespace, item_id, value):
            translated.append(value)
            return f"translated:{value}"

        service = object.__new__(HelldiversService)
        service._localize_planet_rows = localize_planets
        service._translate_cached_text = translate

        station = await service._prepare_dss_station(
            {
                "planet": {},
                "tacticalActions": [
                    {
                        "name": "Unknown Action",
                        "description": "Unknown action description",
                    }
                ],
            },
            include_actions=False,
        )

        self.assertIsNotNone(station)
        self.assertEqual(translated, [])

    async def test_cache_one_shot_task_is_cancelled_on_stop(self) -> None:
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def blocking_fetcher():
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        with tempfile.TemporaryDirectory() as tmp:
            cache = CacheService(Path(tmp), enable_background=False)
            cache.register("blocking", blocking_fetcher)
            await cache.start()
            await asyncio.wait_for(started.wait(), timeout=1)
            task = cache._once_task
            await cache.stop()
            self.assertIsNotNone(task)
            assert task is not None
            self.assertTrue(task.done())
            self.assertTrue(cancelled.is_set())
            self.assertIsNone(cache._once_task)

    async def test_service_warmup_task_is_cancelled_on_stop(self) -> None:
        class FakeCache:
            request_delay = 0.0
            update_interval = 60

            def register(self, name, fetcher):
                return None

            async def start(self):
                return None

            async def stop(self):
                return None

            async def get(self, name):
                return None

            async def refresh_one(self, name, force=False):
                return True

        with tempfile.TemporaryDirectory() as tmp:
            translator = TranslationService(api_url="", enabled=False)
            service = HelldiversService(
                HD2Client(),
                FakeCache(),
                translator,
                TranslationCache(Path(tmp)),
                enable_translation=False,
            )
            await service.start()
            task = service._warmup_task
            await service.stop()
            self.assertIsNotNone(task)
            assert task is not None
            self.assertTrue(task.done())
            self.assertIsNone(service._warmup_task)

    async def test_translation_session_has_no_hd2_contact_headers(self) -> None:
        translator = TranslationService(
            api_url="https://example.com/translate",
            enabled=False,
        )
        session = await translator._ensure_session()
        try:
            self.assertNotIn("X-Super-Contact", session.headers)
            self.assertNotIn("X-Super-Client", session.headers)
        finally:
            await translator.close()


if __name__ == "__main__":
    unittest.main()
