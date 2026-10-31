"""Retention and concurrent persistence regression tests."""

from __future__ import annotations

import asyncio
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from astrbot_plugin_Helldivers.clients.bilibili_monitor import BilibiliMonitor, BilibiliPost
from astrbot_plugin_Helldivers.clients.companion_news_monitor import CompanionNewsMonitor
from astrbot_plugin_Helldivers.clients.translator import TranslationCache
from astrbot_plugin_Helldivers.core.push_policy import PENDING_TTL_SECONDS


def bilibili(path: Path) -> BilibiliMonitor:
    monitor = BilibiliMonitor(
        path, uid="1", keyword="news", interval=300, cookie="", proxy_url="",
        timeout=5, max_image_bytes=1024, send_post=AsyncMock(return_value=0),
        log_info=lambda *_: None, log_warning=lambda *_: None,
    )
    monitor.download_images = AsyncMock(return_value=[])
    return monitor


class RetentionTests(unittest.IsolatedAsyncioTestCase):
    async def test_companion_205_updates_are_bounded_and_old_images_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            source.write_bytes(b"snapshot")
            monitor = CompanionNewsMonitor(root / "state")
            monitor.subscribe("offline")
            for index in range(205):
                await monitor.enqueue(f"v2:{index}", source)
            self.assertEqual(len(monitor.pending), 100)
            self.assertEqual(len(list(monitor.data_dir.glob("pending_*.png"))), 100)
            self.assertNotIn("v2:104", monitor.pending)
            self.assertIn("v2:105", monitor.pending)
            self.assertEqual(monitor.sessions, ["offline"])
            restored = CompanionNewsMonitor(monitor.data_dir)
            self.assertEqual(restored.pending, monitor.pending)
            self.assertEqual(restored.queued_at, monitor.queued_at)

    async def test_companion_byte_budget_and_expiry_cleanup_on_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            source.write_bytes(b"123456")
            monitor = CompanionNewsMonitor(root / "state")
            monitor.subscribe("offline")
            with patch(
                "astrbot_plugin_Helldivers.clients.companion_news_monitor.MAX_PENDING_IMAGE_BYTES", 10
            ):
                await monitor.enqueue("v2:first", source)
                await monitor.enqueue("v2:second", source)
                self.assertEqual(list(monitor.pending), ["v2:second"])
                self.assertFalse(monitor.pending_image("v2:first").exists())
            monitor.queued_at["v2:second"] = time.time() - PENDING_TTL_SECONDS - 1
            monitor._save_state()
            orphan = monitor.data_dir / "pending_orphan.png"
            orphan.write_bytes(b"orphan")
            restored = CompanionNewsMonitor(monitor.data_dir)
            self.assertEqual(restored.pending, {})
            self.assertEqual(restored.queued_at, {})
            self.assertEqual(list(restored.data_dir.glob("pending_*.png")), [])
            self.assertEqual(restored.last_fingerprint, "v2:second")
            self.assertEqual(restored.sessions, ["offline"])

    async def test_companion_oversized_snapshot_is_not_copied_or_requeued(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.png"
            source.write_bytes(b"too-large")
            monitor = CompanionNewsMonitor(Path(tmp) / "state")
            monitor.subscribe("offline")
            with patch(
                "astrbot_plugin_Helldivers.clients.companion_news_monitor.MAX_PENDING_IMAGE_BYTES", 1
            ):
                await monitor.enqueue("v2:large", source)
            self.assertEqual(monitor.pending, {})
            self.assertEqual(monitor.last_fingerprint, "v2:large")
            self.assertFalse(monitor.pending_image("v2:large").exists())

    async def test_companion_legacy_state_uses_snapshot_mtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            monitor = CompanionNewsMonitor(root)
            image = monitor.pending_image("v2:legacy")
            image.write_bytes(b"old")
            (root / "state.json").write_text(json.dumps({
                "sessions": ["offline"], "last_fingerprint": "v2:legacy",
                "pending": {"v2:legacy": ["offline"]},
            }))
            restored = CompanionNewsMonitor(root)
            self.assertAlmostEqual(restored.queued_at["v2:legacy"], image.stat().st_mtime)
            self.assertEqual(CompanionNewsMonitor(root).queued_at, restored.queued_at)

    async def test_bilibili_bounds_backlog_then_expires_even_during_feed_outage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            monitor = bilibili(root)
            monitor.subscribe("offline")
            monitor.seen_ids = ["baseline"]
            monitor.fetch_posts = AsyncMock(return_value=[
                BilibiliPost(str(i), "author", "news", ()) for i in reversed(range(205))
            ])
            await monitor.check_once()
            self.assertEqual(len(monitor.pending), 100)
            self.assertNotIn("104", monitor.pending)
            self.assertIn("105", monitor.pending)
            self.assertEqual(monitor.send_post.await_count, 100)
            restored = bilibili(root)
            self.assertEqual(restored.pending, json.loads(json.dumps(monitor.pending)))
            for entry in restored.pending.values():
                entry["queued_at"] = time.time() - PENDING_TTL_SECONDS - 1
            restored.fetch_posts = AsyncMock(side_effect=RuntimeError("offline feed"))
            with self.assertRaisesRegex(RuntimeError, "offline feed"):
                await restored.check_once()
            restored.send_post.assert_not_awaited()
            self.assertEqual(restored.pending, {})
            self.assertEqual(bilibili(root).pending, {})
            self.assertEqual(restored.sessions, ["offline"])

    async def test_bilibili_legacy_timestamp_migrates_once_and_expiry_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "state.json").write_text(json.dumps({
                "uid": "1", "sessions": ["offline"], "seen_ids": ["old"],
                "pending": {"new": {
                    "post": {"dynamic_id": "new", "author": "a", "text": "news", "image_urls": []},
                    "sessions": ["offline"],
                }},
            }))
            monitor = bilibili(root)
            timestamp = monitor.pending["new"]["queued_at"]
            self.assertEqual(bilibili(root).pending["new"]["queued_at"], timestamp)
            monitor.pending["new"]["queued_at"] = time.time() - PENDING_TTL_SECONDS - 1
            monitor._save_state()
            self.assertEqual(bilibili(root).pending, {})


class InvalidPendingTests(unittest.IsolatedAsyncioTestCase):
    def entry(self, dynamic_id="good"):
        return {
            "post": {"dynamic_id": dynamic_id, "author": "author", "text": "news", "image_urls": []},
            "sessions": ["offline"], "queued_at": time.time(),
        }

    async def test_invalid_persisted_records_are_removed_and_valid_post_is_delivered(self):
        invalid = [
            None, {}, {"post": {}, "sessions": ["offline"]},
            {"post": {"dynamic_id": "bad", "author": "a", "text": "news", "image_urls": None},
             "sessions": ["offline"]},
            {"post": {"dynamic_id": "wrong-id", "author": "a", "text": "news", "image_urls": []},
             "sessions": ["offline"]},
        ]
        for bad in invalid:
            with self.subTest(entry=bad), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "state.json").write_text(json.dumps({
                    "uid": "1", "sessions": ["offline"], "seen_ids": ["baseline"],
                    "pending": {"bad": bad, "good": self.entry()},
                }))
                monitor = bilibili(root)
                self.assertEqual(list(monitor.pending), ["good"])
                self.assertNotIn("bad", json.loads((root / "state.json").read_text())["pending"])
                monitor.send_post.return_value = 1
                monitor.fetch_posts = AsyncMock(return_value=[])
                self.assertEqual(await monitor.check_once(), 1)
                self.assertEqual(monitor.send_post.call_args.args[0].dynamic_id, "good")
                self.assertEqual(monitor.pending, {})

    async def test_in_memory_bad_record_is_pruned_before_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            monitor = bilibili(Path(tmp))
            monitor.subscribe("offline")
            monitor.pending = {"bad": {"post": {}, "sessions": ["offline"]}, "good": self.entry()}
            monitor.send_post.return_value = 1
            self.assertEqual(await monitor._deliver_pending(), 1)
            self.assertEqual(monitor.pending, {})

    async def test_record_corrupted_during_previous_send_does_not_abort_later_posts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            monitor = bilibili(root)
            monitor.subscribe("offline")
            monitor.pending = {key: self.entry(key) for key in ("first", "bad", "last")}

            async def send(post, *_):
                if post.dynamic_id == "first":
                    monitor.pending["bad"]["post"] = {}
                return 1

            monitor.send_post.side_effect = send
            self.assertEqual(await monitor._deliver_pending(), 2)
            self.assertEqual(
                [call.args[0].dynamic_id for call in monitor.send_post.await_args_list],
                ["first", "last"],
            )
            self.assertEqual(bilibili(root).pending, {})


class TranslationWriteTests(unittest.IsolatedAsyncioTestCase):
    async def exercise_concurrent_flush(self, *, cancel=False, add_new=True):
        with tempfile.TemporaryDirectory() as tmp:
            cache = TranslationCache(Path(tmp))
            cache.SAVE_DEBOUNCE_SECONDS = 3600
            started = threading.Event()
            release = threading.Event()
            original_write = cache._write_payload
            writes = []

            def delayed_write(payload):
                writes.append(json.loads(payload))
                if len(writes) == 1:
                    started.set()
                    if not release.wait(5):
                        raise RuntimeError("test writer timed out")
                original_write(payload)

            with patch.object(cache, "_write_payload", side_effect=delayed_write):
                await cache.store("news", "old", "old", "translated")
                first = asyncio.create_task(cache.flush())
                second = None
                try:
                    self.assertTrue(await asyncio.to_thread(started.wait, 3))
                    if add_new:
                        await cache.store("news", "new", "new", "translated")
                    if cancel:
                        first.cancel()
                    second = asyncio.create_task(cache.flush())
                    await asyncio.sleep(0.03)
                    self.assertFalse(second.done(), "flush must wait for the active disk writer")
                    self.assertEqual(len(writes), 1, "writers must not overlap")
                finally:
                    release.set()
                    results = await asyncio.gather(
                        *([first, second] if second else [first]), return_exceptions=True
                    )
                if cancel:
                    self.assertIsInstance(results[0], asyncio.CancelledError)
                else:
                    self.assertIsNone(results[0])
                self.assertIsNone(results[-1])
                expected = {"news:old", "news:new"} if add_new else {"news:old"}
                self.assertEqual(set(json.loads(cache.path.read_text())), expected)
                self.assertFalse(cache._dirty)

    async def test_concurrent_flush_cannot_overwrite_newer_snapshot(self):
        await self.exercise_concurrent_flush()

    async def test_shutdown_flush_waits_even_when_dirty_flag_is_clear(self):
        await self.exercise_concurrent_flush(add_new=False)

    async def test_cancelled_flush_finishes_thread_before_next_writer(self):
        await self.exercise_concurrent_flush(cancel=True)

    async def test_disk_failure_remains_dirty_and_can_be_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = TranslationCache(Path(tmp))
            await cache.store("news", "new", "original", "translated")
            with patch("astrbot_plugin_Helldivers.clients.translator.os.replace",
                       side_effect=OSError("disk unavailable")):
                await cache.flush()
            self.assertTrue(cache._dirty)
            self.assertEqual(list(Path(tmp).glob("*.tmp")), [])
            await cache.flush()
            self.assertFalse(cache._dirty)
            self.assertIn("news:new", json.loads(cache.path.read_text()))
