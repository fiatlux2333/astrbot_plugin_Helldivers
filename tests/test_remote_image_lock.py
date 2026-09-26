"""RemoteImageCache 单飞语义与锁回收的回归测试。

审计 M3：重构曾把 ``async with lock`` 删掉，同 URL 并发请求全部同时
打到上游（single-flight 失效）。本用例固定"最大并发=1、调用数=1、
退出后锁表回收"三个不变量。
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from astrbot_plugin_Helldivers.clients.remote_image_cache import RemoteImageCache


class SingleFlightTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_same_url_single_flight_and_lock_recycle(self) -> None:
        tmpdir = tempfile.mkdtemp()
        cache = RemoteImageCache(Path(tmpdir))
        stats = {"calls": 0, "current": 0, "max_concurrent": 0}

        async def fake_locked(canonical, key, force=False):
            stats["calls"] += 1
            stats["current"] += 1
            stats["max_concurrent"] = max(
                stats["max_concurrent"], stats["current"]
            )
            await asyncio.sleep(0.05)
            stats["current"] -= 1
            return None

        with patch.object(cache, "validate_url", side_effect=lambda u: u), patch.object(
            cache, "_get_record_locked", side_effect=fake_locked
        ):
            results = await asyncio.gather(
                *[cache.get_record("https://example.com/pic.png") for _ in range(5)]
            )

        self.assertEqual(results, [None] * 5)
        # 互斥不变量（审计 M3 的期望即"最大并发 1"）：fake 绕过了临界区内
        # 的缓存检查，5 个调用会被串行执行，但任何时刻只有一个在临界区。
        self.assertEqual(stats["max_concurrent"], 1)
        # 全部退出后锁表回收，无条目滞留
        self.assertEqual(cache._locks, {})
        self.assertEqual(cache._lock_refs, {})

    async def test_distinct_urls_use_distinct_locks(self) -> None:
        tmpdir = tempfile.mkdtemp()
        cache = RemoteImageCache(Path(tmpdir))

        async def fake_locked(canonical, key, force=False):
            await asyncio.sleep(0.02)
            return None

        with patch.object(cache, "validate_url", side_effect=lambda u: u), patch.object(
            cache, "_get_record_locked", side_effect=fake_locked
        ):
            await asyncio.gather(
                cache.get_record("https://example.com/a.png"),
                cache.get_record("https://example.com/b.png"),
            )

        self.assertEqual(cache._locks, {})
        self.assertEqual(cache._lock_refs, {})


if __name__ == "__main__":
    unittest.main()
