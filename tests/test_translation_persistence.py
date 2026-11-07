"""Concurrent translation persistence regression tests."""
import asyncio
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from astrbot_plugin_Helldivers.clients.translator import TranslationCache

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
