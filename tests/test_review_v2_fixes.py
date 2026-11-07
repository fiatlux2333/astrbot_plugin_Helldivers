"""Regressions for the v2 review: migration, delivery, refresh and routing."""
from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from astrbot_plugin_Helldivers.clients.arsenal_client import ArsenalClient, DIONATHA_COLLECTIONS
from astrbot_plugin_Helldivers.clients.bilibili_monitor import BilibiliMonitor, BilibiliPost
from astrbot_plugin_Helldivers.clients.companion_news_monitor import CompanionNewsMonitor, news_fingerprint
from astrbot_plugin_Helldivers.clients.translator import TranslationService
from astrbot_plugin_Helldivers.core.persistence import write_json_atomic
from astrbot_plugin_Helldivers.core.push_policy import PushPolicy
from astrbot_plugin_Helldivers.main import HelldiversPlugin
from astrbot_plugin_Helldivers.renderers.card_specs import build_arsenal_candidates_card

A, B = "test:GroupMessage:100", "test:GroupMessage:200"


def bili(root, policy=None):
    monitor = BilibiliMonitor(root, uid="1", keyword="news", interval=300, cookie="", proxy_url="",
        timeout=5, max_image_bytes=1024, send_post=AsyncMock(return_value=0),
        log_info=lambda *_: None, log_warning=lambda *_: None, policy=policy)
    monitor.download_images = AsyncMock(return_value=[])
    return monitor


def collection(rows, version="old"):
    return json.dumps({"meta": {"dataVersion": version}, "data": rows}).encode()


class TempCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)


class MigrationTests(TempCase):
    async def test_local_v2_companion_outbox_remains_deliverable(self):
        fp = "a" * 40
        outbox = self.root / "outbox"; outbox.mkdir()
        image = outbox / f"{hashlib.sha256(fp.encode()).hexdigest()}.png"
        image.write_bytes(b"local v2 snapshot")
        state = {"state_version": 2, "sessions": [A, B], "last_fingerprint": fp,
                 "pending_news": [{"fingerprint": fp, "sessions": [B]}]}
        (self.root / "state.json").write_text(json.dumps(state))
        monitor = CompanionNewsMonitor(self.root)
        self.assertFalse(monitor._state_error)
        self.assertEqual(monitor.pending_news[fp].sessions, [B])
        self.assertFalse(monitor.check_fingerprint(news_fingerprint(["unchanged news"])))
        send = AsyncMock(return_value=1)
        await monitor.retry_pending(send)
        self.assertEqual(send.await_args.args[1], [B])
        self.assertFalse(CompanionNewsMonitor(self.root).pending_news)

    async def test_both_bili_formats_preserve_only_unacknowledged_recipient(self):
        for legacy in (True, False):
            with self.subTest(legacy=legacy):
                root = self.root / str(legacy); root.mkdir()
                row = {"post": {"dynamic_id": "42", "author": "a", "text": "news", "image_urls": []},
                       "sessions": [B], "queued_at": time.time()}
                state = {"uid": "1", "sessions": [A, B], "seen_ids": ["42"], "baseline_initialized": True}
                state.update({"pending": {"42": row}} if legacy else {"state_version": 2, "pending_posts": [row]})
                original = json.dumps(state).encode(); (root / "state.json").write_bytes(original)
                monitor = bili(root)
                self.assertEqual(monitor.pending_posts["42"].sessions, [B])
                self.assertEqual(next(root.glob("state.before-v3.*.json")).read_bytes(), original)
                self.assertEqual(json.loads((root / "state.json").read_text())["state_version"], 3)
                await monitor._deliver_pending(["42"])
                restored = bili(root)
                restored.send_post.return_value = 1
                await restored._deliver_pending(["42"])
                self.assertEqual(restored.send_post.await_args.args[2], [B])
                self.assertFalse(bili(root).pending_posts)

    async def test_legacy_companion_image_and_recipients_migrate_together(self):
        fp = "v2:previous"
        old_image = self.root / f"pending_{hashlib.sha256(fp.encode()).hexdigest()}.png"
        old_image.write_bytes(b"old article screenshot")
        state = {"sessions": [A, B], "last_fingerprint": fp, "pending": {fp: [B]}, "queued_at": {fp: time.time()}}
        original = json.dumps(state).encode(); (self.root / "state.json").write_bytes(original)
        monitor = CompanionNewsMonitor(self.root)
        self.assertFalse(monitor._state_error)
        self.assertEqual(monitor.pending_image_path(fp).read_bytes(), old_image.read_bytes())
        self.assertEqual(next(self.root.glob("state.before-v3.*.json")).read_bytes(), original)
        sent = []
        async def send(path, sessions):
            sent.append((path.read_bytes(), sessions)); return 1
        await monitor.retry_pending(send)
        self.assertEqual(sent, [(b"old article screenshot", [B])])
        self.assertFalse(CompanionNewsMonitor(self.root).pending_news)
        self.assertTrue(old_image.exists(), "rollback screenshot must remain available")

    async def test_unknown_and_malformed_states_cannot_be_overwritten(self):
        for factory in (bili, CompanionNewsMonitor):
            for raw in (b'{"state_version":99,"sessions":[]}', b'{"pending":[],"sessions":[]}', b'{broken'):
                with self.subTest(factory=factory.__name__, raw=raw):
                    (self.root / "state.json").write_bytes(raw)
                    monitor = factory(self.root)
                    with self.assertRaises(RuntimeError):
                        monitor.subscribe(A)
                    self.assertEqual((self.root / "state.json").read_bytes(), raw)

    async def test_incomplete_image_migration_leaves_legacy_state_for_retry(self):
        state = {"sessions": [B], "last_fingerprint": "b", "pending": {"a": [B], "b": [B]}}
        original = json.dumps(state).encode(); (self.root / "state.json").write_bytes(original)
        for fp in ("a", "b"):
            (self.root / f"pending_{hashlib.sha256(fp.encode()).hexdigest()}.png").write_bytes(fp.encode())
        copy_image = CompanionNewsMonitor._copy_image
        calls = 0
        def fail_second(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("disk full")
            copy_image(*args)
        with patch.object(CompanionNewsMonitor, "_copy_image", side_effect=fail_second):
            monitor = CompanionNewsMonitor(self.root)
        self.assertTrue(monitor._state_error)
        self.assertEqual((self.root / "state.json").read_bytes(), original)
        restored = CompanionNewsMonitor(self.root)
        self.assertEqual(set(restored.pending_news), {"a", "b"})
        self.assertFalse(restored._state_error)


class DeliveryTests(TempCase):
    def news(self, policy=None):
        monitor = CompanionNewsMonitor(self.root / "news", policy=policy)
        monitor.subscribe(A)
        monitor.commit_fingerprint("baseline")
        self.image = self.root / "source.png"
        self.image.write_bytes(b"123456")
        return monitor

    async def test_relative_time_changes_do_not_send_again_but_body_changes_do(self):
        monitor = self.news()
        texts = ["Directive", "Liberate planet", "5 minutes ago"]
        monitor.commit_fingerprint(news_fingerprint(texts))
        plugin = HelldiversPlugin.__new__(HelldiversPlugin)
        plugin.companion_news_monitor = monitor
        plugin.companion_playwright = SimpleNamespace(capture_texts=lambda _: texts)
        plugin._companion_news_push_enabled = True
        plugin._prune_push_subscriptions = AsyncMock()
        plugin._served_companion_stale = lambda _: False
        plugin._push_companion_news = AsyncMock(return_value=1)
        for age in ("10 minutes ago", "15 minutes ago", "Published an hour ago"):
            texts[-1] = age
            await plugin._check_companion_news_change(self.image)
        plugin._push_companion_news.assert_not_awaited()
        texts[1] = "Defend planet"
        await plugin._check_companion_news_change(self.image)
        plugin._push_companion_news.assert_awaited_once()

    async def test_old_sha1_baseline_migrates_without_resetting_pending(self):
        monitor = self.news()
        await monitor.queue_news("old-pending", self.image)
        monitor.commit_fingerprint("a" * 40)
        self.assertFalse(monitor.check_fingerprint(news_fingerprint(["same story"])))
        self.assertEqual(monitor.pending_news["old-pending"].sessions, [A])
        self.assertTrue(monitor.check_fingerprint(news_fingerprint(["new story"])))

    async def test_repeated_pending_fingerprint_does_not_restore_successful_group(self):
        monitor = self.news(); monitor.subscribe(B)
        await monitor.queue_news("one", self.image)
        await monitor.retry_pending(AsyncMock(side_effect=[1, 0]))
        await monitor.queue_news("two", self.image)
        self.assertFalse(await monitor.queue_news("one", self.image))
        self.assertEqual(monitor.pending_news["one"].sessions, [B])

    async def test_retention_count_bytes_expiry_and_restart_cleanup(self):
        policy = PushPolicy(max_entries=2, max_image_bytes=100, ttl_seconds=100)
        monitor = self.news(policy)
        for fp in ("one", "two", "three"):
            await monitor.queue_news(fp, self.image)
        self.assertEqual(list(monitor.pending_news), ["two", "three"])
        self.assertFalse(monitor.pending_image_path("one").exists())
        monitor.policy = PushPolicy(max_image_bytes=6, ttl_seconds=100)
        monitor.prune_pending()
        self.assertEqual(list(monitor.pending_news), ["three"])
        monitor.pending_news["three"].queued_at = time.time() - 101
        monitor._save_state()
        restored = CompanionNewsMonitor(monitor.data_dir, policy=policy)
        self.assertFalse(restored.pending_news)
        self.assertEqual(list(restored.outbox_dir.glob("*.png")), [])

    async def test_oversized_capture_is_logged_and_not_repeatedly_queued(self):
        monitor = self.news(PushPolicy(max_image_bytes=5))
        with patch("astrbot_plugin_Helldivers.clients.companion_news_monitor.logger") as logger:
            self.assertFalse(await monitor.queue_news("oversized", self.image))
            self.assertFalse(await monitor.queue_news("oversized", self.image))
            logger.warning.assert_called_once()
        self.assertFalse(monitor.pending_news)

    async def test_failure_backoff_survives_restart_and_acknowledgement(self):
        monitor = self.news()
        await monitor.queue_news("one", self.image)
        send = AsyncMock(return_value=0)
        await monitor.retry_pending(send)
        await monitor.retry_pending(send)
        self.assertEqual(send.await_count, 2)
        restored = CompanionNewsMonitor(monitor.data_dir)
        send.return_value = 1
        await restored.retry_pending(send)
        self.assertEqual(send.await_count, 2)
        retry_at = restored.pending_news["one"].retries[A]["retry_at"]
        with patch("astrbot_plugin_Helldivers.core.push_policy.time.time", return_value=retry_at + 1):
            await restored.retry_pending(send)
        self.assertFalse(CompanionNewsMonitor(monitor.data_dir).pending_news)

    async def test_bili_retention_runs_even_when_feed_is_unavailable(self):
        monitor = bili(self.root, PushPolicy(max_entries=2, ttl_seconds=10))
        monitor.subscribe(A); monitor.seen_ids = ["baseline"]
        monitor.fetch_posts = AsyncMock(return_value=[BilibiliPost(str(n), "author", "news", ()) for n in (3, 2, 1)])
        await monitor.check_once()
        self.assertEqual(set(monitor.pending_posts), {"2", "3"})
        for item in monitor.pending_posts.values():
            item.queued_at = time.time() - 11
        monitor._save_state()
        monitor.fetch_posts.side_effect = RuntimeError("upstream down")
        with self.assertRaises(RuntimeError):
            await monitor.check_once()
        self.assertFalse(bili(self.root).pending_posts)

    async def test_concurrent_retries_do_not_duplicate_successful_delivery(self):
        monitor = self.news()
        await monitor.queue_news("one", self.image)
        send = AsyncMock(return_value=1)
        await asyncio.gather(monitor.retry_pending(send), monitor.retry_pending(send))
        send.assert_awaited_once()

    async def test_failed_state_commit_does_not_advance_news_discovery(self):
        monitor = self.news()
        original = monitor.state_path.read_bytes()
        with patch.object(monitor, "_save_state", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                await monitor.queue_news("new", self.image)
        self.assertEqual(monitor.last_fingerprint, "baseline")
        self.assertFalse(monitor.pending_news)
        self.assertEqual(monitor.state_path.read_bytes(), original)
        self.assertTrue(await monitor.queue_news("new", self.image))

    async def test_failed_bili_commit_keeps_posts_discoverable_and_unsent(self):
        monitor = bili(self.root)
        monitor.subscribe(A); monitor.seen_ids = ["baseline"]
        monitor.fetch_posts = AsyncMock(return_value=[BilibiliPost("new", "a", "news", ())])
        with patch.object(monitor, "_save_state", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                await monitor.check_once()
        self.assertEqual(monitor.seen_ids, ["baseline"])
        self.assertFalse(monitor.pending_posts)
        monitor.send_post.assert_not_awaited()
        monitor.send_post.return_value = 1
        await monitor.check_once()
        monitor.send_post.assert_awaited_once()


class EquipmentTests(TempCase):
    def primary(self):
        (self.root / "catalog.json").write_text(json.dumps({"items": [{"id": "good", "nameEn": "Good"}]}))
        (self.root / "aliases.json").write_text('{"entries":[]}')
        return ArsenalClient(self.root)

    async def test_bad_primary_and_aliases_never_replace_valid_memory_or_disk(self):
        for bad, alias in (({"items": [{"id": "bad", "alternateNames": 42}]}, False),
                           ({"entries": [{"equipmentId": "bad", "aliases": 42}]}, True)):
            client = self.primary()
            good = json.loads((self.root / "catalog.json").read_text())
            async def fetch(session, urls, **kwargs):
                is_alias = "aliases" in urls[0]
                return json.dumps(bad if is_alias == alias else ({"entries": []} if is_alias else good)).encode()
            client._fetch_any = fetch
            self.assertTrue(await client.ensure_loaded(force=True, refresh_supplement=False))
            self.assertEqual(client.search("Good")[0]["id"], "good")
            self.assertFalse((self.root / "primary_snapshot.json").exists())
            restored = ArsenalClient(self.root); await restored.load_cached()
            self.assertEqual(restored.search("Good")[0]["id"], "good")

    async def test_catalog_and_aliases_commit_as_a_pair(self):
        client = self.primary()
        async def fetch(session, urls, **kwargs):
            if "aliases" in urls[0]:
                return None
            return b'{"items":[{"id":"new","nameEn":"New"}]}'
        client._fetch_any = fetch
        await client.ensure_loaded(force=True, refresh_supplement=False)
        self.assertFalse(client.search("New"))
        async def successful(session, urls, **kwargs):
            if "aliases" in urls[0]:
                return b'{"entries":[{"equipmentId":"new","aliases":["new-alias"]}]}'
            return b'{"items":[{"id":"new","nameEn":"New"}]}'
        client._fetch_any = successful
        await client.ensure_loaded(force=True, refresh_supplement=False)
        restored = ArsenalClient(self.root); await restored.load_cached()
        self.assertEqual(restored.search("new-alias")[0]["id"], "new")

    async def armor_rename(self):
        for name in DIONATHA_COLLECTIONS:
            row = {"id": name, "name": name}
            if name == "passives":
                row["id"] = "old-passive"
            elif name == "armors":
                row["passiveId"] = "old-passive"
            (self.root / f"dionatha_{name}.json").write_bytes(collection([row]))
        client = ArsenalClient(self.root); await client._try_load_dionatha_disk()
        async def fetch(session, name):
            row = {"id": name, "name": name}
            if name == "passives":
                row["id"] = "new-passive"
            elif name == "armors":
                row["passiveId"] = "new-passive"
            return collection([row], "new")
        client._fetch_dionatha = fetch
        return client

    async def test_coherent_passive_rename_updates_both_collections_and_restarts(self):
        client = await self.armor_rename()
        await client.ensure_dionatha(force=True)
        self.assertFalse(client._dionatha_failures)
        restored = ArsenalClient(self.root); await restored.load_cached()
        for name in ("armors", "passives"):
            self.assertEqual(restored._dionatha_snapshots[name]["version"], "new")
        self.assertEqual(restored._dionatha_snapshots["armors"]["rows"][0]["passiveId"],
                         restored._dionatha_snapshots["passives"]["rows"][0]["id"])

    async def test_failed_pair_write_retains_last_good_pair(self):
        client = await self.armor_rename()
        def write(path, payload):
            if path.name == "dionatha_armor_snapshot.json":
                raise OSError("disk full")
            write_json_atomic(path, payload)
        with patch("astrbot_plugin_Helldivers.clients.arsenal_client.write_json_atomic", side_effect=write):
            await client.ensure_dionatha(force=True)
        self.assertEqual(client._dionatha_failures, {"armors", "passives"})
        restored = ArsenalClient(self.root); await restored.load_cached()
        self.assertEqual(restored._dionatha_snapshots["armors"]["version"], "old")
        self.assertEqual(restored._dionatha_snapshots["passives"]["version"], "old")

    async def test_cancelled_pair_commit_finishes_before_releasing_writer(self):
        client = await self.armor_rename()
        started, release = threading.Event(), threading.Event()
        def write(path, payload):
            started.set()
            if not release.wait(5):
                raise TimeoutError("test wait")
            write_json_atomic(path, payload)
        with patch("astrbot_plugin_Helldivers.clients.arsenal_client.write_json_atomic", side_effect=write):
            task = asyncio.create_task(client.ensure_dionatha(force=True))
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 3))
                task.cancel()
                await asyncio.sleep(0.01)
                self.assertFalse(task.done())
            finally:
                release.set()
                result = await asyncio.gather(task, return_exceptions=True)
        self.assertIsInstance(result[0], asyncio.CancelledError)
        restored = ArsenalClient(self.root); await restored.load_cached()
        self.assertEqual(restored._dionatha_snapshots["armors"]["version"], "new")
        self.assertEqual(restored._dionatha_snapshots["passives"]["version"], "new")

    def test_same_category_wasp_candidates_have_unique_working_hints(self):
        client = ArsenalClient(self.root)
        client._items = [{"id": "sta-x3-w-a-s-p-launcher", "nameEn": "StA-X3 W.A.S.P. Launcher", "productKind": "support-weapon"}]
        client._dionatha_items = [client._dionatha_to_item("weapons", {
            "id": "sta-x3-wasp-launcher", "name": "StA-X3 W.A.S.P. Launcher", "category": "support"}, "new", {})]
        client._build_index()
        matches = client.search("StA-X3 W.A.S.P. Launcher")
        self.assertEqual(len(matches), 2)
        card = build_arsenal_candidates_card("WASP", matches)
        for item in matches:
            self.assertEqual(client.search(item["_query_hint"]), [item])
            self.assertIn(item["_query_hint"], str(card))


class TranslationAndRoutingTests(TempCase):
    async def test_valid_unchanged_translation_does_not_pause_other_text(self):
        response = MagicMock(status=200)
        response.json = AsyncMock(side_effect=[{"data": {"translated_text": "500 KG"}}, {"data": {"translated_text": "解放者"}}])
        context = MagicMock(); context.__aenter__ = AsyncMock(return_value=response)
        context.__aexit__ = AsyncMock(return_value=False)
        session = MagicMock(closed=False); session.post.return_value = context
        translator = TranslationService(api_url="https://example.test/ai/translate", session=session)
        self.assertEqual(await translator.translate_text("500 KG"), "500 KG")
        self.assertFalse(translator.in_transient_failure())
        self.assertEqual(await translator.translate_text("Liberator"), "解放者")
        self.assertEqual(session.post.call_count, 2)

    async def test_local_dss_and_planet_use_pillow_without_a_browser(self):
        plugin = HelldiversPlugin.__new__(HelldiversPlugin)
        plugin.companion_backend = "local"
        plugin._capture_companion_page = AsyncMock(side_effect=AssertionError("browser must not be used"))
        path = self.root / "card.png"; path.write_bytes(b"rendered card")
        service = SimpleNamespace(get_dss_image=AsyncMock(return_value=[path]),
            get_planet_image=AsyncMock(return_value=("", [path])),
            resolve_companion_planet=AsyncMock(return_value=("", "SUPER EARTH", "super_earth_(0)")))
        plugin._svc = lambda: service
        event = SimpleNamespace(message_str="/planet 0", plain_result=lambda text: text, chain_result=lambda chain: chain)
        for name in ("cmd_dss", "cmd_planet"):
            outputs = [msg async for msg in getattr(HelldiversPlugin, name).__wrapped__(plugin, event)]
            self.assertEqual(len(outputs), 1)
            self.assertIsInstance(outputs[0], list)
        service.get_dss_image.assert_awaited_once()
        service.get_planet_image.assert_awaited_once_with("SUPER EARTH")
        plugin._capture_companion_page.assert_not_awaited()
