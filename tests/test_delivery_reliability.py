"""Real delivery/queue paths under image, disk and concurrent capture failures."""
from __future__ import annotations

import asyncio
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from astrbot.api.message_components import Image
from astrbot_plugin_Helldivers.clients.bilibili_monitor import (
    BilibiliMonitor, BilibiliPost, PendingBilibiliPost,
)
from astrbot_plugin_Helldivers.clients.companion_news_monitor import CompanionNewsMonitor, news_fingerprint
from astrbot_plugin_Helldivers.clients.companion_screenshot import (
    CompanionCaptureSnapshot, CompanionPlaywrightClient, companion_latest_news_target,
)
from astrbot_plugin_Helldivers.core.cache import CacheService
from astrbot_plugin_Helldivers.main import HelldiversPlugin

A, B = 'bot:GroupMessage:100', 'bot:GroupMessage:200'


def bilibili(root, sender=None, image_cache=None):
    return BilibiliMonitor(
        root, uid='1', keyword='news', interval=300, cookie='', proxy_url='',
        timeout=5, max_image_bytes=1024,
        send_post=sender or AsyncMock(return_value=0), image_cache=image_cache,
        log_info=lambda *_: None, log_warning=lambda *_: None,
    )


class TempCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def plugin(self):
        plugin = HelldiversPlugin.__new__(HelldiversPlugin)
        plugin.context = SimpleNamespace(send_message=AsyncMock(return_value=True))
        return plugin


class BilibiliImagesTests(TempCase):
    async def test_incomplete_download_survives_reload_then_sends_all_images_once(self):
        good = self.root / 'good.png'
        good.write_bytes(b'image one')
        recovered = self.root / 'recovered.png'
        recovered.write_bytes(b'image two')
        urls = ('https://i0.hdslb.com/one.png', 'https://i0.hdslb.com/two.png')
        post = BilibiliPost('1', 'author', 'news', urls)
        # Include failures that the cache reports without raising, and partial batches.
        for failure in (TimeoutError('CDN timeout'), None, self.root / 'missing.png'):
            with self.subTest(failure=str(failure)), tempfile.TemporaryDirectory() as tmp:
                plugin = self.plugin()
                cache = SimpleNamespace(get=AsyncMock(side_effect=[good, failure]))
                monitor = bilibili(Path(tmp), plugin._send_bilibili_post, cache)
                monitor.subscribe(A)
                monitor.seen_ids = ['0']
                monitor.fetch_posts = AsyncMock(return_value=[post])
                self.assertEqual(await monitor.check_once(), 0)
                plugin.context.send_message.assert_not_awaited()
                state = json.loads(monitor.state_path.read_text())
                self.assertEqual(state['pending_posts'][0]['sessions'], [A])
                restored = bilibili(Path(tmp), plugin._send_bilibili_post,
                                    SimpleNamespace(get=AsyncMock(side_effect=[good, recovered])))
                # Retried from the persisted post even after it left the feed.
                restored.fetch_posts = AsyncMock(return_value=[])
                self.assertEqual(await restored.check_once(), 1)
                chain = plugin.context.send_message.await_args.args[1]
                self.assertEqual(sum(isinstance(c, Image) for c in chain.chain), 2)
                self.assertFalse(restored.pending_posts)
                await restored.check_once()
                self.assertEqual(plugin.context.send_message.await_count, 1)

    async def test_unreadable_or_empty_local_image_is_not_acknowledged(self):
        empty = self.root / 'empty.png'
        empty.write_bytes(b'')
        plugin = self.plugin()
        for path in (empty, self.root / 'missing.png'):
            with self.subTest(path=path.name):
                monitor = bilibili(self.root / path.stem, plugin._send_bilibili_post)
                monitor.subscribe(A)
                post = BilibiliPost('1', 'a', 'news', ('https://i0.hdslb.com/x.png',))
                monitor.pending_posts['1'] = PendingBilibiliPost(post, [A])
                monitor.download_images = AsyncMock(return_value=[path])
                self.assertEqual(await monitor._deliver_pending(['1']), 0)
                self.assertIn('1', monitor.pending_posts)
        plugin.context.send_message.assert_not_awaited()

    async def test_text_only_post_still_delivers(self):
        plugin = self.plugin()
        count = await plugin._send_bilibili_post(BilibiliPost('1', 'a', 'news', ()), [], [A])
        self.assertEqual(count, 1)


class CaptureSnapshotTests(TempCase):
    def client(self):
        client = CompanionPlaywrightClient(self.root / 'captures')
        client.start = AsyncMock()
        return client

    async def test_overlapping_capture_cannot_change_stale_result_or_queued_bytes(self):
        client = self.client()
        target = companion_latest_news_target()
        first_ready, release_first = asyncio.Event(), asyncio.Event()
        second_ready, release_second = asyncio.Event(), asyncio.Event()
        calls = 0

        async def capture_page(target, output):
            nonlocal calls
            calls += 1
            client._last_capture_texts[target.kind] = ['New article']
            if calls == 1:
                output.write_bytes(b'old screenshot')
                client._served_stale.add(target.kind)
                first_ready.set()
                await release_first.wait()
            else:
                second_ready.set()
                await release_second.wait()
                output.write_bytes(b'new screenshot')
            return output

        client._capture_uncached = capture_page
        warmup = asyncio.create_task(client.capture_snapshot(target, force=True))
        await first_ready.wait()
        manual = asyncio.create_task(client.capture(target, force=True))
        await asyncio.sleep(0)
        release_first.set()
        try:
            snapshot = await warmup
            await second_ready.wait()
            monitor = CompanionNewsMonitor(self.root / 'news')
            monitor.subscribe(A)
            baseline = news_fingerprint(['Old article'])
            monitor.commit_fingerprint(baseline)
            plugin = self.plugin()
            plugin.companion_news_monitor = monitor
            plugin.companion_playwright = client
            plugin._companion_news_push_enabled = True
            plugin._prune_push_subscriptions = AsyncMock()
            plugin._push_companion_news = AsyncMock(return_value=0)
            await plugin._check_companion_news_change(snapshot)
            self.assertTrue(snapshot.stale)
            self.assertEqual(monitor.last_fingerprint, baseline)
            self.assertFalse(monitor.pending_news)
        finally:
            release_second.set()
            await asyncio.gather(warmup, manual, return_exceptions=True)

        fresh = await client.capture_snapshot(target)  # Cache hit retains matching metadata.
        self.assertFalse(fresh.stale)
        self.assertEqual(fresh.texts, ('New article',))
        # Replace the shared cache while the caller is doing unrelated awaited work.
        client.cached_output_path(target).write_bytes(b'later screenshot')
        client._last_capture_texts[target.kind] = ['Later article']
        await plugin._check_companion_news_change(fresh)
        fp = news_fingerprint(['New article'])
        self.assertEqual(monitor.pending_image_path(fp).read_bytes(), b'new screenshot')
        self.assertEqual(monitor.last_fingerprint, fp)
        self.assertEqual(client._locks, {})
        self.assertEqual(client._lock_refs, {})

    async def test_failed_capture_does_not_attach_partial_text_to_cached_image(self):
        client = self.client()
        target = companion_latest_news_target()

        async def first(target, output):
            client._last_capture_texts[target.kind] = ['Original article']
            output.write_bytes(b'original')
            return output

        client._capture_uncached = first
        await client.capture_snapshot(target, force=True)

        async def failed(target, output):
            client._last_capture_texts[target.kind] = ['Partial new article']
            raise RuntimeError('render failed')

        client._capture_uncached = failed
        with self.assertRaises(RuntimeError):
            await client.capture_snapshot(target, force=True)
        snapshot = await client.capture_snapshot(target)
        self.assertEqual(snapshot.texts, ('Original article',))
        self.assertEqual(snapshot.image_bytes, b'original')

    async def test_cold_disk_cache_has_no_unverified_article_fingerprint(self):
        client = self.client()
        target = companion_latest_news_target()
        client.cached_output_path(target).write_bytes(b'previous process screenshot')
        snapshot = await client.capture_snapshot(target)
        self.assertEqual(snapshot.texts, ())
        client.start.assert_not_awaited()


class CacheCancellationTests(TempCase):
    async def test_cancellation_holds_writer_lock_until_thread_finishes(self):
        cache = CacheService(self.root)
        entered, release = threading.Event(), threading.Event()
        save = cache._save_disk

        def delayed(name, entry):
            if entry.data == 'old':
                entered.set()
                if not release.wait(5):
                    raise RuntimeError('test writer was not released')
            save(name, entry)

        cache._save_disk = delayed
        old = asyncio.create_task(cache.set('war', 'old'))
        self.assertTrue(await asyncio.to_thread(entered.wait, 5))
        old.cancel()
        new = asyncio.create_task(cache.set('war', 'new'))
        try:
            await asyncio.sleep(0.01)
            self.assertFalse(old.done(), 'cancel must await the existing writer')
            self.assertFalse(new.done(), 'new writer must wait for the old one')
        finally:
            release.set()
            outcomes = await asyncio.gather(old, new, return_exceptions=True)
        self.assertIsInstance(outcomes[0], asyncio.CancelledError)
        self.assertIsNone(outcomes[1])
        self.assertEqual(json.loads(cache._disk_path('war').read_text())['data'], 'new')
        self.assertEqual(await cache.get('war'), 'new')
        self.assertFalse(list(cache.cache_dir.glob('*.tmp')))

    async def test_shutdown_waits_for_cancelled_background_writer(self):
        cache = CacheService(self.root)
        entered, release = threading.Event(), threading.Event()
        save = cache._save_disk

        def delayed(name, entry):
            entered.set()
            if not release.wait(5):
                raise RuntimeError('test writer was not released')
            save(name, entry)

        cache._save_disk = delayed
        cache._task = asyncio.create_task(cache.set('war', 'latest'))
        self.assertTrue(await asyncio.to_thread(entered.wait, 5))
        stop = asyncio.create_task(cache.stop())
        try:
            await asyncio.sleep(0.01)
            self.assertFalse(stop.done())
        finally:
            release.set()
            await stop
        self.assertEqual(json.loads(cache._disk_path('war').read_text())['data'], 'latest')


class SubscriptionTransactionTests(TempCase):
    async def test_failed_subscribe_can_be_retried_and_survives_reload(self):
        for factory in (bilibili, CompanionNewsMonitor):
            with self.subTest(factory=factory.__name__):
                root = self.root / factory.__name__
                monitor = factory(root)
                with patch.object(monitor, '_save_state', side_effect=OSError('disk full')):
                    with self.assertRaises(OSError):
                        monitor.subscribe(A)
                self.assertNotIn(A, monitor.sessions)
                self.assertTrue(monitor.subscribe(A))
                self.assertEqual(factory(root).sessions, [A])

    async def test_failed_unsubscribe_restores_recipients_retries_and_item_identity(self):
        for factory in (bilibili, CompanionNewsMonitor):
            for recipients in ([A], [A, B]):
                with self.subTest(factory=factory.__name__, recipients=recipients):
                    root = self.root / f'{factory.__name__}-{len(recipients)}'
                    monitor = factory(root)
                    for origin in recipients:
                        monitor.subscribe(origin)
                    if isinstance(monitor, BilibiliMonitor):
                        key, attr = '1', 'pending_posts'
                        monitor.pending_posts[key] = PendingBilibiliPost(BilibiliPost(key, 'a', 'news', ()), list(recipients))
                    else:
                        key, attr = 'new', 'pending_news'
                        monitor.commit_fingerprint('baseline')
                        await monitor.queue_news(key, b'image')
                    item = getattr(monitor, attr)[key]
                    item.failed(A, monitor.policy)
                    retries = dict(item.retries)
                    monitor._save_state()
                    original_disk = monitor.state_path.read_bytes()
                    with patch.object(monitor, '_save_state', side_effect=OSError('disk full')):
                        with self.assertRaises(OSError):
                            monitor.unsubscribe(A)
                    self.assertEqual(monitor.sessions, recipients)
                    self.assertIs(getattr(monitor, attr)[key], item)
                    self.assertEqual(item.sessions, recipients)
                    self.assertEqual(item.retries, retries)
                    self.assertEqual(monitor.state_path.read_bytes(), original_disk)
                    if isinstance(monitor, CompanionNewsMonitor):
                        self.assertEqual(monitor.pending_image_path(key).read_bytes(), b'image')
                    self.assertTrue(monitor.unsubscribe(A))
                    restored = factory(root)
                    self.assertNotIn(A, restored.sessions)
                    pending = getattr(restored, attr)
                    if len(recipients) == 1:
                        self.assertFalse(pending)
                    else:
                        self.assertEqual(pending[key].sessions, [B])
                        self.assertNotIn(A, pending[key].retries)
