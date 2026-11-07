"""Regression coverage for retired groups and durable delivery acknowledgements."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from astrbot.api.event import AstrMessageEvent
from astrbot.core.platform.message_session import MessageSesion
from astrbot_plugin_Helldivers.clients.bilibili_monitor import (
    BilibiliMonitor,
    BilibiliPost,
)
from astrbot_plugin_Helldivers.clients.companion_news_monitor import (
    CompanionNewsMonitor,
)
from astrbot_plugin_Helldivers.core.push import (
    QQGroupSubscriptionChecker,
    group_session,
)
from astrbot_plugin_Helldivers.clients.companion_screenshot import CompanionCaptureSnapshot
from astrbot_plugin_Helldivers.main import HelldiversPlugin

A = "bot:GroupMessage:100"
B = "bot:GroupMessage:1051645731"


class _Client:
    def __init__(self, groups):
        self.groups = groups
        self.status = {"online": True, "good": True}
        self.calls = []

    async def call_action(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["action"] == "get_status":
            return self.status
        if isinstance(self.groups, Exception):
            raise self.groups
        return self.groups


class _Context:
    def __init__(self):
        self.platforms = {}
        self.results = {}
        self.sent = []

    def add_platform(self, platform_id, groups, name="aiocqhttp"):
        client = _Client(groups)
        self.platforms[platform_id] = SimpleNamespace(
            meta=lambda: SimpleNamespace(name=name), get_client=lambda: client
        )
        return client

    def get_platform_inst(self, platform_id):
        return self.platforms.get(platform_id)

    async def send_message(self, origin, chain):
        self.sent.append(origin)
        result = self.results.get(origin, True)
        if isinstance(result, BaseException):
            raise result
        return result


def _plugin(context):
    plugin = HelldiversPlugin.__new__(HelldiversPlugin)
    plugin.context = context
    plugin.config = {}
    plugin.bilibili_monitor = None
    plugin.companion_news_monitor = None
    plugin.companion_playwright = SimpleNamespace(capture_texts=lambda _: ["new news"])
    plugin._companion_news_push_enabled = True
    plugin._served_companion_stale = lambda _: False
    return plugin


def _bilibili(directory, plugin, uid="1"):
    monitor = BilibiliMonitor(
        directory,
        uid=uid,
        keyword="银河快报",
        interval=300,
        cookie="",
        proxy_url="",
        timeout=5,
        max_image_bytes=1024,
        send_post=AsyncMock(wraps=plugin._send_bilibili_post),
        log_info=lambda _: None,
        log_warning=lambda _: None,
    )
    monitor.fetch_posts = AsyncMock(return_value=[])
    image = directory / "fixture.png"
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(b"image")
    monitor.download_images = AsyncMock(side_effect=lambda post: [image for _ in post.image_urls])
    return monitor


def _post(dynamic_id):
    return BilibiliPost(
        str(dynamic_id),
        "银河快报",
        f"银河快报 {dynamic_id}",
        ("https://i0.hdslb.com/report.jpg",),
    )


class _Event(AstrMessageEvent):
    def __init__(self, origin, admin=False):
        self.session = MessageSesion.from_str(origin)
        self.role = "admin" if admin else "member"
        self.stopped = False

    def get_group_id(self):
        parsed = group_session(self.unified_msg_origin)
        return parsed[1] if parsed else ""

    def plain_result(self, text):
        return text

    def stop_event(self):
        self.stopped = True


class _AsyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.context = _Context()
        self.plugin = _plugin(self.context)


class SubscriptionReconciliationTests(_AsyncTests):
    async def test_prune_removes_both_subscriptions_and_pending_recipients(self):
        bili = _bilibili(self.directory / "bili", self.plugin)
        bili.seen_ids = ["0"]
        bili.subscribe(A)
        bili.subscribe(B)
        bili.fetch_posts.return_value = [_post(1)]
        self.context.results = {A: False, B: False}
        await bili.check_once()

        news = CompanionNewsMonitor(self.directory / "news")
        news.subscribe(B)
        news.commit_fingerprint("baseline")
        image = self.directory / "news.png"
        image.write_bytes(b"screenshot")
        await news.queue_news("changed", image)
        snapshot = news.pending_image_path("changed")
        self.plugin.bilibili_monitor = bili
        self.plugin.companion_news_monitor = news
        client = self.context.add_platform("bot", [{"group_id": 100}])
        bili.before_check = self.plugin._prune_push_subscriptions
        self.context.results[A] = True
        self.context.sent.clear()

        await bili.check_once()

        self.assertEqual(self.context.sent, [A])
        self.assertEqual(bili.sessions, [A])
        self.assertFalse(bili.pending_posts)
        self.assertEqual(news.sessions, [])
        self.assertFalse(news.pending_news)
        self.assertFalse(snapshot.exists())
        self.assertEqual(
            client.calls,
            [
                {"action": "get_group_list", "no_cache": True},
                {"action": "get_status"},
            ],
        )
        self.assertEqual(_bilibili(bili.data_dir, self.plugin).sessions, [A])
        self.assertEqual(CompanionNewsMonitor(news.data_dir).sessions, [])

    async def test_failed_or_malformed_group_query_preserves_subscriptions(self):
        for groups in (TimeoutError(), False, None, {}, [{}], [{"group_id": "bad"}]):
            with self.subTest(groups=groups):
                self.context.add_platform("bot", groups)
                checker = QQGroupSubscriptionChecker(self.context)
                self.assertEqual(await checker.removed_sessions([A, B]), set())

    async def test_successful_empty_group_list_removes_all_qq_groups(self):
        self.context.add_platform("bot", [])
        checker = QQGroupSubscriptionChecker(self.context)
        self.assertEqual(await checker.removed_sessions([A, B]), {A, B})

    async def test_offline_or_unconfirmed_qq_account_preserves_subscriptions(self):
        client = self.context.add_platform("bot", [])
        for status in ({"online": False}, {"online": True, "good": False}, {}, None):
            with self.subTest(status=status):
                client.status = status
                checker = QQGroupSubscriptionChecker(self.context)
                self.assertEqual(await checker.removed_sessions([A, B]), set())

    async def test_platforms_are_isolated_and_other_adapters_are_preserved(self):
        self.context.add_platform("bot", [{"group_id": 100}])
        self.context.add_platform("other", [{"group_id": 1051645731}])
        discord = "discord:GroupMessage:100"
        missing = "disabled:GroupMessage:100"
        self.context.add_platform("discord", [], name="discord")
        other_a = A.replace("bot:", "other:")
        other_b = B.replace("bot:", "other:")
        checker = QQGroupSubscriptionChecker(self.context)
        self.assertEqual(
            await checker.removed_sessions([A, B, other_a, other_b, discord, missing]),
            {B, other_a},
        )

    async def test_unique_sessions_resolve_to_the_actual_qq_group(self):
        self.context.add_platform("bot", [{"group_id": 100}])
        checker = QQGroupSubscriptionChecker(self.context)
        self.assertEqual(
            await checker.removed_sessions(
                ["bot:GroupMessage:777_100", "bot:GroupMessage:777_200"]
            ),
            {"bot:GroupMessage:777_200"},
        )


class BilibiliPendingDeliveryTests(_AsyncTests):
    def monitor(self):
        return _bilibili(self.directory / "bili", self.plugin)

    async def test_partial_delivery_retries_only_failed_group_after_restart(self):
        monitor = self.monitor()
        monitor.seen_ids = ["0"]
        monitor.subscribe(A)
        monitor.subscribe(B)
        monitor.fetch_posts.return_value = [_post(1)]
        self.context.results[B] = False
        self.assertEqual(await monitor.check_once(), 1)

        restored = self.monitor()
        self.assertEqual(restored.pending_posts["1"].sessions, [B])
        self.assertEqual(
            restored.pending_posts["1"].post.image_urls, _post(1).image_urls
        )
        self.context.results[B] = True
        self.context.sent.clear()
        # The failed post has already disappeared from the source feed.
        self.assertEqual(await restored.check_once(), 1)
        self.assertEqual(self.context.sent, [B])
        self.assertFalse(self.monitor().pending_posts)

    async def test_all_seven_failures_are_saved_without_blocking_later_posts(self):
        monitor = self.monitor()
        monitor.seen_ids = ["0"]
        monitor.subscribe(A)
        self.context.results[A] = False
        monitor.fetch_posts.return_value = [_post(i) for i in range(7, 0, -1)]
        self.assertEqual(await monitor.check_once(), 0)
        self.assertEqual(len(self.monitor().pending_posts), 7)
        self.assertEqual(monitor.send_post.await_count, 7)

        restored = self.monitor()
        restored.fetch_posts.return_value = [_post(8)]
        self.context.results[A] = True
        self.assertEqual(await restored.check_once(), 8)
        self.assertEqual(
            [call.args[0].dynamic_id for call in restored.send_post.await_args_list],
            [str(i) for i in range(1, 9)],
        )
        self.assertFalse(self.monitor().pending_posts)

    async def test_pending_delivery_proceeds_even_when_source_api_is_down(self):
        monitor = self.monitor()
        monitor.seen_ids = ["0"]
        monitor.subscribe(A)
        self.context.results[A] = False
        monitor.fetch_posts.return_value = [_post(1)]
        await monitor.check_once()

        restored = self.monitor()
        restored.fetch_posts.side_effect = RuntimeError("source unavailable")
        self.context.results[A] = True
        self.context.sent.clear()
        with self.assertRaisesRegex(RuntimeError, "source unavailable"):
            await restored.check_once()
        self.assertEqual(self.context.sent, [A])
        self.assertFalse(self.monitor().pending_posts)

    async def test_cancelled_batch_preserves_unacknowledged_groups_and_later_posts(
        self,
    ):
        monitor = self.monitor()
        monitor.seen_ids = ["0"]
        monitor.subscribe(A)
        monitor.subscribe(B)
        monitor.fetch_posts.return_value = [_post(2), _post(1)]
        self.context.results[B] = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await monitor.check_once()

        restored = self.monitor()
        self.assertEqual(restored.pending_posts["1"].sessions, [B])
        self.assertEqual(restored.pending_posts["2"].sessions, [A, B])
        self.context.results[B] = True
        self.context.sent.clear()
        await restored.check_once()
        self.assertEqual(self.context.sent, [B, A, B])

    async def test_unsubscribe_and_new_subscriber_do_not_restore_old_recipients(self):
        monitor = self.monitor()
        monitor.seen_ids = ["0"]
        monitor.subscribe(A)
        monitor.subscribe(B)
        self.context.results = {A: False, B: False}
        monitor.fetch_posts.return_value = [_post(1)]
        await monitor.check_once()
        monitor.unsubscribe(B)
        monitor.subscribe("bot:GroupMessage:200")
        self.context.results[A] = True
        self.context.sent.clear()
        await monitor.check_once()
        self.assertEqual(self.context.sent, [A])
        self.assertFalse(self.monitor().pending_posts)

    async def test_uid_change_preserves_subscriptions_and_resets_old_outbox(self):
        monitor = self.monitor()
        monitor.seen_ids = ["0"]
        monitor.subscribe(A)
        monitor.fetch_posts.return_value = [_post(1)]
        self.context.results[A] = False
        await monitor.check_once()
        restored = _bilibili(monitor.data_dir, self.plugin, uid="2")
        self.assertEqual(restored.sessions, [A])
        self.assertFalse(restored.pending_posts)
        restored.fetch_posts.return_value = [_post(2)]
        self.assertEqual(await restored.check_once(), 0)

    async def test_empty_initial_feed_does_not_consume_the_first_future_post(self):
        monitor = self.monitor()
        monitor.subscribe(A)
        self.assertEqual(await monitor.check_once(), 0)
        monitor.fetch_posts.return_value = [_post(1)]
        self.assertEqual(await monitor.check_once(), 1)

    async def test_legacy_state_migrates_without_resending_seen_posts(self):
        data_dir = self.directory / "bili"
        data_dir.mkdir()
        (data_dir / "state.json").write_text(
            json.dumps({"uid": "1", "sessions": [A], "seen_ids": ["1"]})
        )
        monitor = self.monitor()
        monitor.fetch_posts.return_value = [_post(2), _post(1)]
        self.assertEqual(await monitor.check_once(), 1)
        self.assertEqual(monitor.send_post.await_args.args[0].dynamic_id, "2")


class CompanionPendingDeliveryTests(_AsyncTests):
    def monitor(self):
        return CompanionNewsMonitor(self.directory / "news")

    def image(self, content=b"first screenshot"):
        path = self.directory / "capture.png"
        path.write_bytes(content)
        return path

    async def test_partial_delivery_retries_original_snapshot_after_restart(self):
        monitor = self.monitor()
        monitor.subscribe(A)
        monitor.subscribe(B)
        monitor.commit_fingerprint("baseline")
        image = self.image()
        self.context.results[B] = False
        await monitor.queue_news("changed", image)
        await monitor.retry_pending(self.plugin._push_companion_news)
        image.write_bytes(b"newer screenshot")

        restored = self.monitor()
        self.assertEqual(restored.pending_news["changed"].sessions, [B])
        self.assertEqual(
            restored.pending_image_path("changed").read_bytes(), b"first screenshot"
        )
        self.context.results[B] = True
        self.context.sent.clear()
        self.assertEqual(
            await restored.retry_pending(self.plugin._push_companion_news), 1
        )
        self.assertEqual(self.context.sent, [B])
        self.assertFalse(self.monitor().pending_news)
        self.assertFalse(restored.pending_image_path("changed").exists())

    async def test_later_news_keeps_both_pending_snapshots(self):
        monitor = self.monitor()
        monitor.subscribe(A)
        monitor.commit_fingerprint("baseline")
        self.context.results[A] = False
        image = self.image()
        await monitor.queue_news("one", image)
        await monitor.retry_pending(self.plugin._push_companion_news)
        image.write_bytes(b"second screenshot")
        await monitor.queue_news("two", image)
        restored = self.monitor()
        contents = []

        async def send(path, sessions):
            contents.append(path.read_bytes())
            return 1

        await restored.retry_pending(send)
        self.assertEqual(contents, [b"first screenshot", b"second screenshot"])
        self.assertFalse(self.monitor().pending_news)

    async def test_snapshot_failure_does_not_commit_the_new_fingerprint(self):
        monitor = self.monitor()
        monitor.subscribe(A)
        monitor.commit_fingerprint("baseline")
        with self.assertRaises(OSError):
            await monitor.queue_news("changed", self.directory / "missing.png")
        self.assertEqual(self.monitor().last_fingerprint, "baseline")
        self.assertFalse(monitor.pending_news)

    async def test_cancelled_delivery_keeps_only_unacknowledged_group(self):
        monitor = self.monitor()
        monitor.subscribe(A)
        monitor.subscribe(B)
        monitor.commit_fingerprint("baseline")
        await monitor.queue_news("changed", self.image())
        self.context.results[B] = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await monitor.retry_pending(self.plugin._push_companion_news)
        self.assertEqual(self.monitor().pending_news["changed"].sessions, [B])

    async def test_unchanged_capture_still_retries_failed_group_in_main(self):
        monitor = self.monitor()
        monitor.subscribe(A)
        monitor.subscribe(B)
        monitor.commit_fingerprint("baseline")
        self.plugin.companion_news_monitor = monitor
        self.context.results[B] = False
        image = self.image()
        await self.plugin._check_companion_news_change(CompanionCaptureSnapshot(image.read_bytes(), ("new news",), False))
        self.assertEqual(len(monitor.pending_news), 1)
        self.context.results[B] = True
        self.context.sent.clear()
        await self.plugin._check_companion_news_change(CompanionCaptureSnapshot(image.read_bytes(), ("new news",), False))
        self.assertEqual(self.context.sent, [B])
        self.assertFalse(monitor.pending_news)

    async def test_disabled_push_pauses_existing_outbox_until_reenabled(self):
        monitor = self.monitor()
        monitor.subscribe(A)
        monitor.commit_fingerprint("baseline")
        image = self.image()
        await monitor.queue_news("changed", image)
        self.plugin.companion_news_monitor = monitor
        self.plugin._companion_news_push_enabled = False
        await self.plugin._check_companion_news_change(CompanionCaptureSnapshot(image.read_bytes(), ("new news",), False))
        self.assertEqual(self.context.sent, [])
        self.assertIn("changed", monitor.pending_news)
        self.plugin._companion_news_push_enabled = True
        await self.plugin._check_companion_news_change(CompanionCaptureSnapshot(image.read_bytes(), ("new news",), False))
        self.assertFalse(monitor.pending_news)

    async def test_failed_capture_does_not_block_saved_snapshot_delivery(self):
        monitor = self.monitor()
        monitor.subscribe(A)
        monitor.commit_fingerprint("baseline")
        await monitor.queue_news("changed", self.image())
        self.plugin.companion_news_monitor = monitor
        self.plugin.config["companion_warmup_kinds"] = "news_latest"
        self.plugin.companion_playwright.capture_snapshot = AsyncMock(
            side_effect=RuntimeError("news page unavailable")
        )
        with (
            patch(
                "astrbot_plugin_Helldivers.main.asyncio.sleep",
                new=AsyncMock(side_effect=[None, asyncio.CancelledError()]),
            ),
            self.assertRaises(asyncio.CancelledError),
        ):
            await self.plugin._companion_warmup_loop()
        self.assertEqual(self.context.sent, [A])
        self.assertFalse(self.monitor().pending_news)


class PushAdministrationTests(_AsyncTests):
    async def test_admin_can_unsubscribe_old_group_from_private_chat(self):
        monitor = _bilibili(self.directory / "bili", self.plugin)
        monitor.subscribe(B)
        self.plugin.bilibili_monitor = monitor
        event = _Event("bot:FriendMessage:123", admin=True)
        replies = [
            reply
            async for reply in self.plugin.cmd_galaxy_news_unsubscribe(
                event, target="1051645731"
            )
        ]
        self.assertIn("已取消", replies[0])
        self.assertFalse(monitor.sessions)
        self.assertTrue(event.stopped)

    async def test_non_admin_cannot_unsubscribe_another_group(self):
        monitor = self.monitor_with_subscription(B)
        event = _Event(A)
        message = self.plugin._unsubscribe_push(
            monitor, event, "1051645731", "银河快报"
        )
        self.assertIn("仅 AstrBot 管理员", message)
        self.assertEqual(monitor.sessions, [B])

    async def test_current_group_unsubscribe_remains_available_to_members(self):
        monitor = self.monitor_with_subscription(A)
        message = self.plugin._unsubscribe_push(monitor, _Event(A), "", "银河快报")
        self.assertIn("已取消本群", message)
        self.assertFalse(monitor.sessions)

    async def test_group_number_is_limited_to_current_platform(self):
        monitor = self.monitor_with_subscription(B)
        other = B.replace("bot:", "other:")
        monitor.subscribe(other)
        event = _Event("bot:FriendMessage:123", admin=True)
        self.plugin._unsubscribe_push(monitor, event, "1051645731", "银河快报")
        self.assertEqual(monitor.sessions, [other])
        self.plugin._unsubscribe_push(monitor, event, other, "银河快报")
        self.assertFalse(monitor.sessions)

    async def test_group_number_removes_all_unique_sessions_for_that_group(self):
        monitor = self.monitor_with_subscription("bot:GroupMessage:111_100")
        # Legacy files could contain subscriptions from two users in one group.
        monitor.sessions.append("bot:GroupMessage:222_100")
        event = _Event("bot:FriendMessage:123", admin=True)
        self.plugin._unsubscribe_push(monitor, event, "100", "银河快报")
        self.assertFalse(monitor.sessions)

    async def test_member_can_unsubscribe_group_subscribed_by_another_user(self):
        monitor = self.monitor_with_subscription("bot:GroupMessage:111_100")
        event = _Event("bot:GroupMessage:222_100")
        self.plugin._unsubscribe_push(monitor, event, "", "银河快报")
        self.assertFalse(monitor.sessions)

    async def test_new_unique_session_subscription_does_not_duplicate_group(self):
        monitor = self.monitor_with_subscription("bot:GroupMessage:111_100")
        self.assertFalse(monitor.subscribe("bot:GroupMessage:222_100"))
        self.assertEqual(monitor.sessions, ["bot:GroupMessage:111_100"])

    async def test_subscription_listing_is_admin_only(self):
        self.plugin.bilibili_monitor = self.monitor_with_subscription(B)
        member = _Event("bot:FriendMessage:123")
        replies = [reply async for reply in self.plugin.cmd_push_subscriptions(member)]
        self.assertNotIn(B, replies[0])
        admin = _Event("bot:FriendMessage:123", admin=True)
        replies = [reply async for reply in self.plugin.cmd_push_subscriptions(admin)]
        self.assertIn(B, replies[0])

    def monitor_with_subscription(self, origin):
        monitor = _bilibili(self.directory / "bili", self.plugin)
        monitor.subscribe(origin)
        return monitor
