"""军需簿客户端基础行为测试：镜像重试、proxy 透传、磁盘缓存加载。"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from astrbot_plugin_Helldivers.clients import arsenal_client as arsenal_module
from astrbot_plugin_Helldivers.clients.arsenal_client import (
    DIONATHA_COLLECTIONS,
    REFRESH_INTERVAL,
    ArsenalClient,
)


class _FakeContent:
    def __init__(self, body: bytes) -> None:
        self._body = body

    async def iter_chunked(self, size: int):
        yield self._body


class _FakeResp:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self.content_length = len(body)
        self.content = _FakeContent(body)


class _RespCtx:
    def __init__(self, resp: _FakeResp) -> None:
        self._resp = resp

    async def __aenter__(self) -> _FakeResp:
        return self._resp

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class _FakeSession:
    """记录每次 get 的 proxy 实参；responses 中的 Exception 模拟连接失败。"""

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str | None]] = []

    def get(self, url: str, proxy: str | None = None) -> _RespCtx:
        self.calls.append((url, proxy))
        resp = self._responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return _RespCtx(resp)


class FetchAnyTests(unittest.TestCase):
    def test_proxy_is_forwarded_to_mirror(self) -> None:
        session = _FakeSession([_FakeResp(200, b"catalog")])
        body = asyncio.run(
            ArsenalClient._fetch_any(
                session,
                ("https://mirror.example/catalog.json",),
                proxy="http://127.0.0.1:7890",
            )
        )
        self.assertEqual(body, b"catalog")
        self.assertEqual(
            session.calls,
            [("https://mirror.example/catalog.json", "http://127.0.0.1:7890")],
        )

    def test_default_is_no_proxy(self) -> None:
        session = _FakeSession([_FakeResp(200, b"x")])
        asyncio.run(
            ArsenalClient._fetch_any(session, ("https://a.example/x.json",))
        )
        self.assertEqual(session.calls, [("https://a.example/x.json", None)])

    def test_falls_through_failed_mirror_to_next(self) -> None:
        session = _FakeSession(
            [TimeoutError("direct blocked"), _FakeResp(200, b"ok")]
        )
        body = asyncio.run(
            ArsenalClient._fetch_any(
                session,
                ("https://raw.example/x.json", "https://mirror.example/x.json"),
            )
        )
        self.assertEqual(body, b"ok")
        self.assertEqual(len(session.calls), 2)

    def test_all_mirrors_failed_returns_none(self) -> None:
        session = _FakeSession(
            [TimeoutError("a"), _FakeResp(502, b""), TimeoutError("c")]
        )
        body = asyncio.run(ArsenalClient._fetch_any(session, ("u1", "u2", "u3")))
        self.assertIsNone(body)
        self.assertEqual(len(session.calls), 3)


class _SessionCtx:
    """包住 _FakeSession 冒充 aiohttp.ClientSession 的 async with。"""

    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> _FakeSession:
        return self._session

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class _BareClient:
    """跳过 __init__ 的网络/目录副作用，只挂测试需要的属性。"""

    @staticmethod
    def make(cache_dir: Path) -> ArsenalClient:
        client = ArsenalClient.__new__(ArsenalClient)
        client.cache_dir = cache_dir
        client._items = []
        client._aliases = {}
        client._dionatha_items = []
        client._index = {}
        client.proxy_url = None
        client.timeout_seconds = 5
        client.user_agent = "unit-test"
        return client


class DownloadProxyTests(unittest.TestCase):
    """锁住 _download → _fetch_any 的 proxy_url 透传链（曾漏传，proxy 配置静默失效）。"""

    def test_download_forwards_proxy_to_every_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            session = _FakeSession(
                [
                    _FakeResp(200, b'{"items": []}'),
                    _FakeResp(200, b'{"entries": []}'),
                ]
            )
            client = _BareClient.make(cache)
            client.proxy_url = "http://127.0.0.1:7890"
            with mock.patch.object(
                arsenal_module.aiohttp,
                "ClientSession",
                lambda **kwargs: _SessionCtx(session),
            ), mock.patch.object(arsenal_module, "HEALTH"):
                ok = asyncio.run(
                    client._download(cache / "catalog.json", cache / "aliases.json")
                )
            self.assertTrue(ok)
            # 主目录与别名两次抓取都必须带上 client.proxy_url
            self.assertEqual(len(session.calls), 2)
            for url, proxy in session.calls:
                self.assertEqual(proxy, "http://127.0.0.1:7890")
            self.assertEqual((cache / "catalog.json").read_bytes(), b'{"items": []}')
            self.assertEqual(
                (cache / "aliases.json").read_bytes(), b'{"entries": []}'
            )


class DionathaDiskLoadTests(unittest.TestCase):
    def _write_collections(self, cache: Path) -> None:
        for col in DIONATHA_COLLECTIONS:
            payload = {
                "meta": {"dataVersion": "v-test"},
                "data": [{"slug": f"{col}-1", "name": f"{col} one"}],
            }
            (cache / f"dionatha_{col}.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )

    def test_disk_load_populates_items_and_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            self._write_collections(cache)
            client = _BareClient.make(cache)
            self.assertTrue(asyncio.run(client._try_load_dionatha_disk()))
            self.assertEqual(client.dionatha_count, len(DIONATHA_COLLECTIONS))
            self.assertGreater(client._dionatha_loaded_at, 0.0)
            # slug 与 id 都应可命中（id = dionatha:<slug>）
            self.assertIn("dionatha:weapons-1", client._index)
            self.assertIn("weapons-1", client._index)

    def test_missing_collection_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            self._write_collections(cache)
            (cache / "dionatha_weapons.json").unlink()
            client = _BareClient.make(cache)
            self.assertFalse(asyncio.run(client._try_load_dionatha_disk()))
            self.assertEqual(client.dionatha_count, 0)

    def test_stale_collection_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            self._write_collections(cache)
            stale = cache / "dionatha_weapons.json"
            old = time.time() - REFRESH_INTERVAL - 10
            os.utime(stale, (old, old))
            client = _BareClient.make(cache)
            self.assertFalse(asyncio.run(client._try_load_dionatha_disk()))

    def test_corrupt_json_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            self._write_collections(cache)
            (cache / "dionatha_weapons.json").write_text(
                "{not json", encoding="utf-8"
            )
            client = _BareClient.make(cache)
            self.assertFalse(asyncio.run(client._try_load_dionatha_disk()))
            self.assertEqual(client.dionatha_count, 0)

    def test_non_object_top_level_returns_false(self) -> None:
        # 合法 JSON 但顶层非对象（如 [1,2,3]）：不该抛 AttributeError 逃逸
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            self._write_collections(cache)
            (cache / "dionatha_weapons.json").write_text(
                "[1, 2, 3]", encoding="utf-8"
            )
            client = _BareClient.make(cache)
            self.assertFalse(asyncio.run(client._try_load_dionatha_disk()))
            self.assertEqual(client.dionatha_count, 0)


if __name__ == "__main__":
    unittest.main()
