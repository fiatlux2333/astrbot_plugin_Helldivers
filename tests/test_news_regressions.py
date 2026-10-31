from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from astrbot_plugin_Helldivers.clients.bilibili_monitor import BilibiliMonitor, BilibiliPost
from astrbot_plugin_Helldivers.clients.companion_news_monitor import (
    CompanionNewsMonitor,
    news_fingerprint,
)
from astrbot_plugin_Helldivers.main import HelldiversPlugin


def make_bilibili(path: Path, sender: AsyncMock) -> BilibiliMonitor:
    monitor = BilibiliMonitor(
        path, uid="1", keyword="news", interval=300, cookie="", proxy_url="",
        timeout=5, max_image_bytes=1024, send_post=sender,
        log_info=lambda *_: None, log_warning=lambda *_: None,
    )
    monitor.download_images = AsyncMock(return_value=[])
    return monitor


class FingerprintTests(unittest.TestCase):
    def test_relative_times_do_not_change_identity(self):
        expected = news_fingerprint(["Title", "Article body", "JUST NOW"])
        for label in ("5 MINUTES AGO", "10 minutes ago", "1 HOUR AGO",
                      "YESTERDAY", "TODAY", "DAYS AGO", "Published 2 days ago"):
            with self.subTest(label=label):
                self.assertEqual(expected, news_fingerprint(["Title", "Article body", label]))
        self.assertNotEqual(expected, news_fingerprint(["Title", "Changed body"]))
        self.assertEqual("", news_fingerprint(["5 MINUTES AGO"]))

    def test_normalizes_whitespace_and_separate_time_lines(self):
        self.assertEqual(
            news_fingerprint(["Title", "Article body", "5 MINUTES AGO"]),
            news_fingerprint([" Title ", "Article  body\n10 MINUTES AGO"]),
        )

    def test_does_not_strip_time_mentioned_in_article(self):
        self.assertNotEqual(
            news_fingerprint(["Title", "The battle ended 5 minutes ago"]),
            news_fingerprint(["Title", "The battle ended 10 minutes ago"]),
        )

    def test_legacy_fingerprint_is_rebaselined_without_history_push(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "state.json").write_text(json.dumps({
                "sessions": ["a"], "last_fingerprint": "legacy-sha1",
            }))
            monitor = CompanionNewsMonitor(path)
            fingerprint = news_fingerprint(["Article"])
            self.assertFalse(monitor.check_fingerprint(fingerprint))
            self.assertEqual(CompanionNewsMonitor(path).last_fingerprint, fingerprint)


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_bilibili_partial_delivery_survives_reload_and_feed_rollover(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            sender = AsyncMock(side_effect=[1, RuntimeError("offline")])
            monitor = make_bilibili(path, sender)
            monitor.seen_ids = ["old"]
            monitor.subscribe("a")
            monitor.subscribe("b")
            monitor.fetch_posts = AsyncMock(return_value=[BilibiliPost("new", "author", "news", ())])
            self.assertEqual(await monitor.check_once(), 1)
            self.assertEqual(monitor.pending["new"]["sessions"], ["b"])
            sender = AsyncMock(return_value=1)
            restored = make_bilibili(path, sender)
            restored.fetch_posts = AsyncMock(return_value=[])
            await restored.check_once()
            self.assertEqual(sender.await_count, 1)
            self.assertEqual(sender.call_args.args[2], ["b"])
            self.assertEqual(restored.pending, {})
            await restored.check_once()
            self.assertEqual(sender.await_count, 1)

    async def test_bilibili_total_failure_and_false_return_are_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            sender = AsyncMock(side_effect=[0, RuntimeError("offline"), 1, 1])
            monitor = make_bilibili(Path(tmp), sender)
            monitor.seen_ids = ["old"]
            monitor.subscribe("a")
            monitor.subscribe("b")
            monitor.fetch_posts = AsyncMock(return_value=[BilibiliPost("new", "author", "news", ())])
            self.assertEqual(await monitor.check_once(), 0)
            self.assertEqual(monitor.pending["new"]["sessions"], ["a", "b"])
            await monitor.check_once()
            self.assertEqual(monitor.pending, {})

    async def test_bilibili_retries_during_feed_outage_and_honors_unsubscribe(self):
        with tempfile.TemporaryDirectory() as tmp:
            sender = AsyncMock(return_value=0)
            monitor = make_bilibili(Path(tmp), sender)
            monitor.seen_ids = ["old"]
            monitor.subscribe("a")
            monitor.subscribe("b")
            monitor.fetch_posts = AsyncMock(return_value=[BilibiliPost("new", "author", "news", ())])
            await monitor.check_once()
            monitor.unsubscribe("a")
            sender.reset_mock()
            sender.return_value = 1
            monitor.fetch_posts = AsyncMock(side_effect=RuntimeError("feed down"))
            with self.assertRaisesRegex(RuntimeError, "feed down"):
                await monitor.check_once()
            self.assertEqual(sender.call_args.args[2], ["b"])
            self.assertEqual(monitor.pending, {})

    async def test_companion_partial_delivery_keeps_original_image_after_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            image = path / "capture.png"
            image.write_bytes(b"original-news")
            plugin = HelldiversPlugin.__new__(HelldiversPlugin)
            monitor = CompanionNewsMonitor(path / "state")
            monitor.subscribe("a")
            monitor.subscribe("b")
            plugin.companion_news_monitor = monitor
            plugin._companion_news_push_enabled = True
            texts = ["Old article", "5 MINUTES AGO"]
            plugin.companion_playwright = SimpleNamespace(capture_texts=lambda _: texts)
            plugin._served_companion_stale = lambda _: False
            plugin._push_companion_news = AsyncMock(side_effect=[1, 0])
            await plugin._check_companion_news_change(image)
            plugin._push_companion_news.assert_not_awaited()
            texts[1] = "10 MINUTES AGO"
            await plugin._check_companion_news_change(image)
            plugin._push_companion_news.assert_not_awaited()
            texts[0] = "New article"
            await plugin._check_companion_news_change(image)
            fingerprint = news_fingerprint(texts)
            self.assertEqual(monitor.pending[fingerprint], ["b"])
            image.write_bytes(b"another-news")
            plugin.companion_news_monitor = CompanionNewsMonitor(path / "state")
            observed = []

            async def send(snapshot, sessions):
                observed.append((snapshot.read_bytes(), sessions))
                return 1

            plugin._push_companion_news = AsyncMock(side_effect=send)
            await plugin._deliver_pending_companion_news()
            self.assertEqual(observed, [(b"original-news", ["b"])])
            self.assertEqual(plugin.companion_news_monitor.pending, {})
            self.assertFalse(monitor.pending_image(fingerprint).exists())
            await plugin._check_companion_news_change(image)
            self.assertEqual(plugin._push_companion_news.await_count, 1)

    async def test_companion_queue_retains_multiple_updates_and_unsubscribe(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            image = path / "source.png"
            monitor = CompanionNewsMonitor(path / "state")
            monitor.subscribe("a")
            for fingerprint in ("v2:first", "v2:second"):
                image.write_bytes(fingerprint.encode())
                await monitor.enqueue(fingerprint, image)
            monitor.unsubscribe("a")
            monitor.subscribe("a")
            restored = CompanionNewsMonitor(path / "state")
            self.assertEqual(restored.pending, {})
            self.assertEqual(list(restored.data_dir.glob("pending_*.png")), [])
            for fingerprint in list(restored.pending):
                restored.finish_pending(fingerprint)
            self.assertEqual(restored.pending, {})

    async def test_companion_stale_image_is_not_queued(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin = HelldiversPlugin.__new__(HelldiversPlugin)
            monitor = CompanionNewsMonitor(Path(tmp))
            monitor.subscribe("a")
            monitor.check_fingerprint(news_fingerprint(["Old article"]))
            plugin.companion_news_monitor = monitor
            plugin._companion_news_push_enabled = True
            plugin.companion_playwright = SimpleNamespace(capture_texts=lambda _: ["New article"])
            plugin._served_companion_stale = lambda _: True
            plugin._push_companion_news = AsyncMock()
            await plugin._check_companion_news_change(Path(tmp) / "stale.png")
            self.assertEqual(monitor.pending, {})
            self.assertEqual(monitor.last_fingerprint, news_fingerprint(["Old article"]))
            plugin._push_companion_news.assert_not_awaited()

    async def test_companion_disabled_push_does_not_drain_queue(self):
        plugin = HelldiversPlugin.__new__(HelldiversPlugin)
        plugin._companion_news_push_enabled = False
        plugin.companion_news_monitor = SimpleNamespace(pending={"v2:test": ["a"]})
        plugin._push_companion_news = AsyncMock()
        await plugin._deliver_pending_companion_news()
        plugin._push_companion_news.assert_not_awaited()


class CommandTests(unittest.IsolatedAsyncioTestCase):
    def plugin(self):
        plugin = HelldiversPlugin.__new__(HelldiversPlugin)
        plugin.config = {}
        plugin.companion_enabled = True
        plugin.companion_backend = "local"
        plugin.companion_playwright = None
        plugin._companion_news_push_enabled = True
        plugin._companion_warmup_task = None
        plugin._capture_companion_page = AsyncMock(side_effect=AssertionError("browser used"))
        plugin.service = SimpleNamespace(
            get_dss_image=AsyncMock(return_value=[Path("local.png")]),
            get_planet_image=AsyncMock(return_value=("", [Path("local.png")])),
            resolve_companion_planet=AsyncMock(return_value=("", "Heeth", "heeth_(1)")),
        )
        return plugin

    async def test_local_dss_uses_pillow(self):
        plugin = self.plugin()
        event = SimpleNamespace(chain_result=lambda c: c, plain_result=lambda t: t)
        replies = [x async for x in HelldiversPlugin.cmd_dss.__wrapped__(plugin, event)]
        plugin.service.get_dss_image.assert_awaited_once()
        plugin._capture_companion_page.assert_not_awaited()
        self.assertEqual(len(replies), 1)

    async def test_local_planet_accepts_names_ids_slugs_and_links(self):
        for query in ("Heeth", "1", "希斯", "heeth", "heeth_(1)",
                      "https://helldiverscompanion.com/#hellpad/planets/heeth_(1)"):
            with self.subTest(query=query):
                plugin = self.plugin()
                event = SimpleNamespace(message_str=f"/planet {query}",
                                        chain_result=lambda c: c, plain_result=lambda t: t)
                replies = [x async for x in HelldiversPlugin.cmd_planet.__wrapped__(plugin, event)]
                self.assertEqual(len(replies), 1)
                self.assertEqual(plugin.service.get_planet_image.await_count, 1)
                self.assertEqual(plugin.service.get_planet_image.call_args.args[0].casefold(), "heeth")
                plugin._capture_companion_page.assert_not_awaited()

    async def test_local_render_error_returns_friendly_reply(self):
        plugin = self.plugin()
        plugin.service.get_dss_image.side_effect = RuntimeError("failed")
        event = SimpleNamespace(plain_result=lambda t: t)
        replies = [x async for x in HelldiversPlugin.cmd_dss.__wrapped__(plugin, event)]
        self.assertEqual(len(replies), 1)
        self.assertIsInstance(replies[0], str)

    async def test_push_includes_news_when_warmup_list_omits_it(self):
        plugin = self.plugin()
        for config in ("station", "invalid", "news_latest,station,news_latest"):
            plugin.config = {"companion_warmup_kinds": config}
            kinds = [target.kind for target in plugin._companion_warmup_targets()]
            self.assertEqual(kinds.count("news_latest"), 1)
        plugin._companion_news_push_enabled = False
        plugin.config = {"companion_warmup_kinds": "station"}
        self.assertEqual([t.kind for t in plugin._companion_warmup_targets()], ["station"])

    async def test_unavailable_browser_refuses_subscription(self):
        plugin = self.plugin()
        plugin.companion_backend = "playwright"
        plugin.companion_news_monitor = SimpleNamespace(subscribe=lambda _: self.fail("subscribed"))
        event = SimpleNamespace(plain_result=lambda t: t, unified_msg_origin="a")
        replies = [x async for x in HelldiversPlugin.cmd_news_subscribe.__wrapped__(plugin, event)]
        self.assertEqual(len(replies), 1)
        self.assertIn("未就绪", replies[0])
        self.assertIsNone(plugin._companion_warmup_task)

    async def test_disabled_warmup_refuses_subscription(self):
        plugin = self.plugin()
        plugin.companion_backend = "playwright"
        plugin.config = {"companion_warmup_enabled": False}
        plugin.companion_playwright = object()
        plugin.companion_news_monitor = SimpleNamespace(subscribe=lambda _: self.fail("subscribed"))
        event = SimpleNamespace(plain_result=lambda t: t, unified_msg_origin="a")
        replies = [x async for x in HelldiversPlugin.cmd_news_subscribe.__wrapped__(plugin, event)]
        self.assertIn("预热未启用", replies[0])
        self.assertIsNone(plugin._companion_warmup_task)

    async def test_warmup_retries_queue_even_when_capture_fails(self):
        plugin = self.plugin()
        plugin.config = {"companion_warmup_kinds": "station"}
        plugin.companion_news_monitor = object()
        plugin.companion_playwright = SimpleNamespace(capture=AsyncMock(side_effect=RuntimeError("offline")))
        plugin._deliver_pending_companion_news = AsyncMock()
        with patch("astrbot_plugin_Helldivers.main.asyncio.sleep",
                   new=AsyncMock(side_effect=[None, asyncio.CancelledError])):
            with self.assertRaises(asyncio.CancelledError):
                await plugin._companion_warmup_loop()
        plugin._deliver_pending_companion_news.assert_awaited_once()
        self.assertEqual(plugin.companion_playwright.capture.call_args.args[0].kind, "news_latest")

    async def test_subscription_starts_detector_and_restarts_done_task(self):
        plugin = self.plugin()
        plugin.companion_backend = "playwright"
        plugin.companion_playwright = object()
        plugin.config = {"companion_warmup_kinds": "station"}
        plugin.companion_news_monitor = SimpleNamespace(subscribe=lambda _: True)
        plugin._companion_warmup_task = asyncio.create_task(asyncio.sleep(0))
        await plugin._companion_warmup_task
        event = SimpleNamespace(plain_result=lambda t: t, unified_msg_origin="a")
        try:
            replies = [x async for x in HelldiversPlugin.cmd_news_subscribe.__wrapped__(plugin, event)]
            self.assertIn("已订阅", replies[0])
            self.assertFalse(plugin._companion_warmup_task.done())
            self.assertIn("news_latest", [t.kind for t in plugin._companion_warmup_targets()])
        finally:
            plugin._companion_warmup_task.cancel()
            await asyncio.gather(plugin._companion_warmup_task, return_exceptions=True)


if __name__ == "__main__":
    unittest.main()
