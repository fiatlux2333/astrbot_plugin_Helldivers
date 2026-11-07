"""Regression coverage for partial upstream failures and quota degradation."""

from __future__ import annotations

import asyncio
import json
import tempfile
import os
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from astrbot_plugin_Helldivers.clients.arsenal_client import (
    ArsenalClient,
    DIONATHA_COLLECTIONS,
    REFRESH_INTERVAL,
)
from astrbot_plugin_Helldivers.clients.api_client import HD2Client
from astrbot_plugin_Helldivers.clients.translator import TranslationService
from astrbot_plugin_Helldivers.services import HelldiversService
from astrbot_plugin_Helldivers.core.cache import CacheService


def collection_bytes(collection: str, version: str = "old") -> bytes:
    return json.dumps(
        {
            "meta": {"dataVersion": version},
            "data": [{"id": f"{collection}-1", "name": f"{collection} item"}],
        }
    ).encode()


class EquipmentResilienceTests(unittest.IsolatedAsyncioTestCase):
    async def test_expired_restart_cache_survives_total_network_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "dionatha_weapons.json"
            path.write_bytes(collection_bytes("weapons"))
            old_time = time.time() - REFRESH_INTERVAL - 100
            os.utime(path, (old_time, old_time))
            client = ArsenalClient(root)
            client._fetch_dionatha = AsyncMock(return_value=None)
            self.assertTrue(await client.ensure_dionatha())
            self.assertTrue(client.search("weapons item"))
            self.assertEqual(
                client._dionatha_snapshots["weapons"]["updated_at"], old_time
            )
            self.assertTrue(any("旧数据" in line for line in client.diagnostic_lines()))

    async def test_partial_refresh_keeps_failed_rows_and_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for collection in DIONATHA_COLLECTIONS:
                (root / f"dionatha_{collection}.json").write_bytes(
                    collection_bytes(collection)
                )
            client = ArsenalClient(root)
            await client._try_load_dionatha_disk()
            before = dict(client._dionatha_snapshots)

            async def fetch(session, collection):
                return (
                    collection_bytes(collection, "new")
                    if collection == "boosters"
                    else None
                )

            client._fetch_dionatha = fetch
            self.assertTrue(await client.ensure_dionatha(force=True))
            self.assertEqual(client.dionatha_count, 7)
            self.assertEqual(client._dionatha_snapshots["boosters"]["version"], "new")
            self.assertEqual(client._dionatha_snapshots["weapons"], before["weapons"])
            self.assertEqual(len(client._dionatha_failures), 6)
            reloaded = ArsenalClient(root)
            await reloaded._try_load_dionatha_disk()
            self.assertEqual(reloaded.dionatha_count, 7)

    async def test_invalid_data_cannot_overwrite_valid_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = collection_bytes("weapons")
            (root / "dionatha_weapons.json").write_bytes(old)
            client = ArsenalClient(root)
            client._fetch_dionatha = AsyncMock(
                return_value=b'{"meta": {}, "data": [null]}'
            )
            await client.ensure_dionatha(force=True)
            self.assertEqual((root / "dionatha_weapons.json").read_bytes(), old)
            self.assertTrue(client.search("weapons item"))

    async def test_primary_outage_keeps_supplement_and_enemy_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = ArsenalClient(tmp)
            client._maybe_start_dionatha = lambda: None
            client._download = AsyncMock(return_value=False)
            client._publish_dionatha(
                {
                    "weapons": client._dionatha_snapshot(
                        collection_bytes("weapons"), time.time()
                    )
                }
            )
            client._enemies = [{"nameEn": "Test enemy", "nameZh": "测试敌人"}]
            client._build_index()
            self.assertTrue(await client.ensure_loaded())
            self.assertTrue(client.search("weapons item"))
            self.assertTrue(client.search("测试敌人"))

    async def test_wait_timeout_does_not_cancel_shared_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = ArsenalClient(tmp)
            gate = asyncio.Event()
            client.ensure_dionatha = AsyncMock(side_effect=lambda: None)

            async def sync():
                await gate.wait()
                return True

            client.ensure_dionatha = sync
            await client.wait_for_supplement(timeout=0.001)
            task = client._dionatha_task
            self.assertFalse(task.done())
            await client.wait_for_supplement(timeout=0.001)
            self.assertIs(client._dionatha_task, task)
            gate.set()
            await task
            await client.stop()

    async def test_new_armor_cannot_replace_old_without_its_passive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = collection_bytes("armors")
            (root / "dionatha_armors.json").write_bytes(old)
            new = json.loads(old)
            new["data"][0]["passiveId"] = "missing-passive"
            client = ArsenalClient(root)

            async def fetch(session, collection):
                return json.dumps(new).encode() if collection == "armors" else None

            client._fetch_dionatha = fetch
            await client.ensure_dionatha(force=True)
            self.assertEqual((root / "dionatha_armors.json").read_bytes(), old)
            self.assertIn("armors", client._dionatha_failures)


class Response:
    def __init__(self, status, body, headers=None):
        self.status, self.body, self.headers = status, body, headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self, **kwargs):
        return self.body


class BuiltinQuotaTests(unittest.IsolatedAsyncioTestCase):
    async def test_limits_preserve_text_and_pause_following_requests(self):
        cases = [
            (429, {"code": 429}, 120),
            (429, {"error": "VISITOR_MONTHLY_QUOTA_EXHAUSTED"}, 3600),
            (402, {"error": "INSUFFICIENT_CREDITS"}, 3600),
            (503, {}, 120),
        ]
        for status, body, expected in cases:
            with self.subTest(status=status, body=body):
                session = MagicMock()
                session.closed = False
                session.post.return_value = Response(
                    status, body, {"Retry-After": "120"}
                )
                translator = TranslationService(
                    api_url="https://example.test/ai/translate", session=session
                )
                svc = HelldiversService.__new__(HelldiversService)
                svc.enable_translation = True
                svc.drop_untranslated_content = True
                svc.translator = translator
                svc.translation_cache = MagicMock()
                svc.translation_cache.get = AsyncMock(return_value=None)
                svc.translation_cache.store = AsyncMock()
                text = "A new strategic directive has arrived."
                result = await svc._translate_cached_text("audit", "one", text)
                self.assertEqual(result, text)
                self.assertTrue(translator.in_cooldown())
                self.assertGreater(
                    translator._builtin_cooldown_until - time.monotonic(), expected - 2
                )
                svc.translation_cache.store.assert_not_awaited()
                await translator.translate_text("Another article.")
                self.assertEqual(session.post.call_count, 1)
                translator.resume()
                session.post.return_value = Response(
                    200, {"data": {"translated_text": "新的指令"}}
                )
                self.assertEqual(await translator.translate_text(text), "新的指令")

    async def test_concurrent_batches_make_one_call_on_quota_failure(self):
        session = MagicMock(closed=False)
        session.post.return_value = Response(402, {"error": "INSUFFICIENT_CREDITS"})
        translator = TranslationService(
            api_url="https://example.test/ai/translate", session=session
        )
        result = await asyncio.gather(
            *(translator.translate_text(f"Article {n}") for n in range(5))
        )
        self.assertEqual(session.post.call_count, 1)
        self.assertEqual(result, [f"Article {n}" for n in range(5)])


class ApiCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_companion_uses_war_clock_and_invalid_clocks_are_unknown(self):
        client = HD2Client()
        payload = {
            "clientTime": 1794037610791,
            "timeSinceStart": 87997297,
            "warStatus": {"time": 86097240},
            "news": [{"id": 3989, "published": 85856296}],
        }
        client.request_json = AsyncMock(return_value=payload)
        article = await client.fetch_companion_gww_news(3989)
        self.assertEqual(article["published"], "2026-11-04T12:51:06.791000Z")
        for clock in (None, {}, {"time": float("nan")}, {"time": 1}):
            payload["warStatus"] = clock
            self.assertEqual(
                (await client.fetch_companion_gww_news(3989))["published"], ""
            )

    async def test_dss_failed_refresh_preserves_last_success_and_skips_v1(self):
        client = HD2Client()
        client.get_json = AsyncMock(return_value=None)
        with tempfile.TemporaryDirectory() as tmp:
            cache = CacheService(Path(tmp), enable_background=False)
            cache.register("space_stations", client.fetch_space_stations)
            await cache.set("space_stations", [{"id": 1}])
            entry = await cache.get_entry("space_stations")
            self.assertFalse(await cache.refresh_one("space_stations", force=True))
            self.assertEqual(await cache.get("space_stations"), [{"id": 1}])
            self.assertEqual(
                (await cache.get_entry("space_stations")).updated_at, entry.updated_at
            )
            client.get_json.assert_awaited_once_with("/api/v2/space-stations")


class SnapshotDependencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_passive_removal_cannot_break_retained_armor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            armor = {
                "meta": {"dataVersion": "old"},
                "data": [{"id": "armor", "name": "Armor", "passiveId": "old-passive"}],
            }
            passive = {
                "meta": {"dataVersion": "old"},
                "data": [{"id": "old-passive", "name": "Original Passive"}],
            }
            for collection, payload in (("armors", armor), ("passives", passive)):
                (root / f"dionatha_{collection}.json").write_text(json.dumps(payload))
            client = ArsenalClient(root)

            async def fetch(session, collection):
                return (
                    collection_bytes("passives", "new")
                    if collection == "passives"
                    else None
                )

            client._fetch_dionatha = fetch
            await client.ensure_dionatha(force=True)
            self.assertIn("passives", client._dionatha_failures)
            self.assertEqual(
                client.search("Armor 护甲")[0]["armor"]["passive"], "Original Passive"
            )
            restarted = ArsenalClient(root)
            await restarted.load_cached()
            self.assertEqual(
                restarted.search("Armor 护甲")[0]["armor"]["passive"],
                "Original Passive",
            )
