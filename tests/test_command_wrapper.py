from __future__ import annotations

import unittest

from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Star

from astrbot_plugin_Helldivers.main import _command_handler


class _FakePlugin(Star):
    def __init__(self) -> None:  # noqa: D107 - 测试桩，无需初始化 Star
        pass


class _FakeEvent(AstrMessageEvent):
    """只实现包装器行为依赖的最小事件桩。"""

    def __init__(self) -> None:
        self._stopped = False
        self.stop_calls = 0

    def stop_event(self) -> None:
        self.stop_calls += 1
        self._stopped = True

    def is_stopped(self) -> bool:
        return self._stopped


class CommandHandlerWrapperTests(unittest.TestCase):
    def _run(self, coro):
        import asyncio

        return asyncio.run(coro)

    def test_multi_yield_not_truncated_and_stop_after_last(self) -> None:
        @_command_handler
        async def handler(plugin: Star, event: AstrMessageEvent):
            yield "ack"
            yield "done"

        plugin, event = _FakePlugin(), _FakeEvent()
        stop_flags_at_yield: list[bool] = []

        async def drive():
            async for item in handler(plugin, event):
                stop_flags_at_yield.append(event.is_stopped())

        self._run(drive())
        self.assertEqual(stop_flags_at_yield, [False, False])
        self.assertTrue(event.is_stopped())
        self.assertEqual(event.stop_calls, 1)

    def test_zero_yield_handler_still_stops_event(self) -> None:
        @_command_handler
        async def handler(plugin: Star, event: AstrMessageEvent):
            return
            yield  # pragma: no cover - 使函数成为异步生成器

        plugin, event = _FakePlugin(), _FakeEvent()

        async def drive():
            async for _ in handler(plugin, event):
                pass  # pragma: no cover - 不应有产出

        self._run(drive())
        self.assertTrue(event.is_stopped())

    def test_coroutine_handler_result_yielded_then_stops(self) -> None:
        @_command_handler
        async def handler(plugin: Star, event: AstrMessageEvent):
            return "reply"

        plugin, event = _FakePlugin(), _FakeEvent()
        stop_flags_at_yield: list[bool] = []

        async def drive():
            async for item in handler(plugin, event):
                stop_flags_at_yield.append((item, event.is_stopped()))

        self._run(drive())
        self.assertEqual(stop_flags_at_yield, [("reply", False)])
        self.assertTrue(event.is_stopped())

    def test_coroutine_handler_none_result_still_stops(self) -> None:
        @_command_handler
        async def handler(plugin: Star, event: AstrMessageEvent):
            return None

        plugin, event = _FakePlugin(), _FakeEvent()

        async def drive():
            async for _ in handler(plugin, event):
                pass  # pragma: no cover - 不应有产出

        self._run(drive())
        self.assertTrue(event.is_stopped())

    def test_handler_exception_still_stops_event(self) -> None:
        @_command_handler
        async def handler(plugin: Star, event: AstrMessageEvent):
            yield "ack"
            raise RuntimeError("boom")

        plugin, event = _FakePlugin(), _FakeEvent()

        async def drive():
            async for _ in handler(plugin, event):
                pass

        with self.assertRaises(RuntimeError):
            self._run(drive())
        self.assertTrue(event.is_stopped())

    def test_stacked_legacy_args_drop_stale_plugin(self) -> None:
        """4.16-4.26 热重载残留的堆叠调用 (old, new, event) 必须正常工作。

        位置参数里除识别出的 plugin/event 外只会是陈旧实例，一律丢弃；
        此前按位置转发会把旧实例当指令参数导致 TypeError。
        """

        @_command_handler
        async def handler(plugin: Star, event: AstrMessageEvent):
            yield "ok"

        old_plugin, plugin, event = _FakePlugin(), _FakePlugin(), _FakeEvent()

        async def drive():
            return [item async for item in handler(old_plugin, plugin, event)]

        self.assertEqual(self._run(drive()), ["ok"])
        self.assertTrue(event.is_stopped())

    def test_handler_receives_keyword_params(self) -> None:
        """AstrBot 以 **kwargs 传指令参数，包装器不得丢参。"""

        @_command_handler
        async def handler(
            plugin: Star, event: AstrMessageEvent, name: str = ""
        ):
            yield f"name={name}"

        plugin, event = _FakePlugin(), _FakeEvent()

        async def drive():
            return [
                item async for item in handler(plugin, event, name="foo")
            ]

        self.assertEqual(self._run(drive()), ["name=foo"])


if __name__ == "__main__":
    unittest.main()
