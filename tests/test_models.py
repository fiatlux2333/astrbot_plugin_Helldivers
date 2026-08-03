from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

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

from astrbot_plugin_Helldivers.api_client import HD2Client
from astrbot_plugin_Helldivers.cache import CacheService
from astrbot_plugin_Helldivers.campaign_trends import CampaignTrendStore
from astrbot_plugin_Helldivers.services import HelldiversService
from astrbot_plugin_Helldivers.remote_image_cache import ALLOWED_IMAGE_MIMES
from astrbot_plugin_Helldivers.stats_model import build_stats_view_model
from astrbot_plugin_Helldivers.steam_parser import parse_steam_content
from astrbot_plugin_Helldivers.translator import TranslationCache, TranslationService
from astrbot_plugin_Helldivers.war_state import WarState, campaign_faction


class ModelTests(unittest.TestCase):
    def test_bilibili_long_image_pixel_limit_covers_current_report(self) -> None:
        schema = json.loads(
            (Path(__file__).parents[1] / "_conf_schema.json").read_text(
                encoding="utf-8"
            )
        )
        limit = schema["bilibili_image_max_pixels"]["default"]
        self.assertEqual(limit, 32_000_000)
        self.assertGreater(limit, 2_606 * 8_186)

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
    def test_external_url_validation_rejects_private_targets(self) -> None:
        for url in (
            "http://example.com/data.json",
            "https://127.0.0.1/data.json",
            "https://[::1]/data.json",
            "https://localhost/data.json",
            "https://user:pass@example.com/data.json",
        ):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    HD2Client._external_url_target(url, allow_private=False)
        self.assertEqual(
            HD2Client._external_url_target(
                "https://example.com/data.json", allow_private=False
            ),
            ("example.com", 443),
        )
        self.assertEqual(
            HD2Client._external_url_target(
                "http://127.0.0.1:8080/data.json", allow_private=True
            ),
            ("127.0.0.1", 8080),
        )

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

    async def test_personal_order_does_not_mutate_client_settings(self) -> None:
        class RecordingClient(HD2Client):
            async def request_external_json(self, url, **kwargs):
                self.external_kwargs = kwargs
                return []

        client = RecordingClient(retry_max_attempts=3, timeout=30)
        original_timeout = client.timeout
        result = await client.fetch_personal_order("https://example.com/order.json")
        self.assertEqual(result, [])
        self.assertEqual(client.retry_max_attempts, 3)
        self.assertIs(client.timeout, original_timeout)
        self.assertEqual(client.external_kwargs["timeout"], 10.0)
        self.assertFalse(client.external_kwargs["allow_private"])

    async def test_official_steam_news_uses_single_attempt(self) -> None:
        class RecordingClient(HD2Client):
            def __init__(self) -> None:
                super().__init__()
                self.max_attempts = None
                self.failure_is_warning = None

            async def request_json(self, method, path, **kwargs):
                self.max_attempts = kwargs.get("max_attempts")
                self.failure_is_warning = kwargs.get("failure_is_warning")
                return None

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


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
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
