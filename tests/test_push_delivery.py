"""推送投递计数的回归测试。

审计 H1：AstrBot ``context.send_message`` 平台失配时返回 False 而非抛异常，
丢弃返回值会把"未送达"计成"已送达"——导致 Companion 新闻指纹被提前提交
（更新永久丢失）且 B 站推送的 delivered==0 重试触发点不可达。
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from astrbot_plugin_Helldivers.clients.bilibili_monitor import BilibiliPost
from astrbot_plugin_Helldivers.main import HelldiversPlugin


class _FakeContext:
    """按预设结果逐次应答 send_message 的最小桩。"""

    def __init__(self, results):
        self._results = list(results)
        self.sessions: list[str] = []

    async def send_message(self, session, chain) -> bool:
        self.sessions.append(session)
        index = min(len(self.sessions) - 1, len(self._results) - 1)
        result = self._results[index]
        if isinstance(result, Exception):
            raise result
        return result


def _bare_plugin(context: _FakeContext) -> HelldiversPlugin:
    """跳过 __init__，仅装配被测方法依赖的 context。"""
    plugin = HelldiversPlugin.__new__(HelldiversPlugin)
    plugin.context = context
    return plugin


class SendBilibiliPostTests(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    def test_all_platform_miss_raises_for_retry(self) -> None:
        post = BilibiliPost(
            dynamic_id="123", author="作者", text="正文", image_urls=()
        )
        context = _FakeContext([False, False])
        plugin = _bare_plugin(context)
        with self.assertRaises(RuntimeError):
            self._run(plugin._send_bilibili_post(post, [], ["s1", "s2"]))
        self.assertEqual(context.sessions, ["s1", "s2"])

    def test_platform_hit_counts_as_delivered(self) -> None:
        post = BilibiliPost(
            dynamic_id="123", author="作者", text="正文", image_urls=()
        )
        context = _FakeContext([True, False])
        plugin = _bare_plugin(context)
        # 一成一败：不抛错（delivered>0），且 False 不得计入送达数
        delivered = self._run(plugin._send_bilibili_post(post, [], ["s1", "s2"]))
        self.assertEqual(delivered, 1)

    def test_send_exception_still_raises_when_all_fail(self) -> None:
        post = BilibiliPost(
            dynamic_id="123", author="作者", text="正文", image_urls=()
        )
        context = _FakeContext([RuntimeError("boom")])
        plugin = _bare_plugin(context)
        with self.assertRaises(RuntimeError):
            self._run(plugin._send_bilibili_post(post, [], ["s1"]))


class PushCompanionNewsTests(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    def _image_file(self) -> Path:
        handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        handle.write(b"\x89PNG\r\n\x1a\nfake")
        handle.close()
        return Path(handle.name)

    def test_platform_miss_is_not_counted_as_delivered(self) -> None:
        image = self._image_file()
        try:
            context = _FakeContext([False])
            plugin = _bare_plugin(context)
            delivered = self._run(plugin._push_companion_news(image, ["s1"]))
            self.assertEqual(delivered, 0)
        finally:
            image.unlink(missing_ok=True)

    def test_platform_hit_counts_delivered(self) -> None:
        image = self._image_file()
        try:
            context = _FakeContext([True, True])
            plugin = _bare_plugin(context)
            delivered = self._run(
                plugin._push_companion_news(image, ["s1", "s2"])
            )
            self.assertEqual(delivered, 2)
        finally:
            image.unlink(missing_ok=True)

    def test_missing_image_returns_zero(self) -> None:
        context = _FakeContext([True])
        plugin = _bare_plugin(context)
        delivered = self._run(
            plugin._push_companion_news(Path("/nonexistent/x.png"), ["s1"])
        )
        self.assertEqual(delivered, 0)
        self.assertEqual(context.sessions, [])


if __name__ == "__main__":
    unittest.main()
