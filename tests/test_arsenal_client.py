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
                    _FakeResp(200, b'{"items": [{"id": "test"}]}'),
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
            self.assertEqual((cache / "catalog.json").read_bytes(), b'{"items": [{"id": "test"}]}')
            self.assertEqual(
                (cache / "aliases.json").read_bytes(), b'{"entries": []}'
            )


class CatalogValidationTests(unittest.IsolatedAsyncioTestCase):
    CATALOG = b'{"items": [{"id": "good", "nameEn": "Good item"}]}'
    ALIASES = b'{"entries": []}'

    def make_client(self, root):
        client = _BareClient.make(root)
        client._lock = asyncio.Lock()
        client._loaded_at = 0
        client._refresh_retry_at = 0
        client._maybe_start_dionatha = mock.Mock()
        return client

    async def test_invalid_http_200_falls_through_to_valid_mirror(self):
        session = _FakeSession([
            _FakeResp(200, b"<html>gateway error</html>"),
            _FakeResp(200, self.CATALOG),
        ])
        body = await ArsenalClient._fetch_any(
            session, ("bad", "good"), validator=ArsenalClient._validate_catalog
        )
        self.assertEqual(body, self.CATALOG)
        self.assertEqual(len(session.calls), 2)

    async def test_invalid_alias_download_does_not_replace_good_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog, aliases = root / "catalog.json", root / "aliases.json"
            catalog.write_bytes(self.CATALOG)
            aliases.write_bytes(self.ALIASES)
            client = self.make_client(root)
            session = _FakeSession([
                _FakeResp(200, b'{"items": [{"id": "new"}]}'),
                _FakeResp(200, b"<html>not aliases</html>"),
            ])
            with mock.patch.object(arsenal_module, "RAW_URLS", ("catalog",)), \
                 mock.patch.object(arsenal_module, "ALIAS_URLS", ("aliases",)), \
                 mock.patch.object(arsenal_module.aiohttp, "ClientSession",
                                   lambda **_: _SessionCtx(session)):
                self.assertFalse(await client._download(catalog, aliases))
            self.assertEqual(catalog.read_bytes(), self.CATALOG)
            self.assertEqual(aliases.read_bytes(), self.ALIASES)

    async def test_fresh_but_invalid_disk_cache_is_repaired_immediately(self):
        for bad in (b"<html>bad</html>", b"[]", b'{"items": []}',
                    b'{"items": [3]}', b'{"items": [{"id": "x"}], "meta": 3}'):
            with self.subTest(body=bad), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                catalog, aliases = root / "catalog.json", root / "aliases.json"
                catalog.write_bytes(bad)
                aliases.write_bytes(self.ALIASES)
                client = self.make_client(root)

                async def repair(*_):
                    catalog.write_bytes(self.CATALOG)
                    aliases.write_bytes(self.ALIASES)
                    return True

                client._download = mock.AsyncMock(side_effect=repair)
                self.assertTrue(await client.ensure_loaded())
                client._download.assert_awaited_once()
                self.assertEqual(client.search("good")[0]["id"], "good")

    async def test_failed_forced_refresh_preserves_last_good_disk_and_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog, aliases = root / "catalog.json", root / "aliases.json"
            catalog.write_bytes(self.CATALOG)
            aliases.write_bytes(self.ALIASES)
            client = self.make_client(root)
            client._download = mock.AsyncMock(return_value=False)
            self.assertTrue(await client.ensure_loaded(force=True))
            self.assertEqual(client.search("good")[0]["id"], "good")
            self.assertEqual(catalog.read_bytes(), self.CATALOG)
            # Corrupt disk must not destroy already loaded usable data either.
            catalog.write_bytes(b"<html>bad</html>")
            self.assertTrue(await client.ensure_loaded(force=True))
            self.assertEqual(client.search("good")[0]["id"], "good")

    async def test_invalid_alias_disk_cache_triggers_repair_without_mutating_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog, aliases = root / "catalog.json", root / "aliases.json"
            catalog.write_bytes(self.CATALOG)
            aliases.write_bytes(self.ALIASES)
            client = self.make_client(root)
            self.assertTrue(client._load_from(catalog, aliases))
            catalog.write_bytes(b'{"items": [{"id": "replacement"}]}')
            aliases.write_bytes(b'{"entries": [{"aliases": 4}]}')
            self.assertFalse(client._load_from(catalog, aliases))
            self.assertEqual(client._items[0]["id"], "good")
            client._download = mock.AsyncMock(return_value=False)
            self.assertTrue(await client.ensure_loaded(force=True))
            client._download.assert_awaited_once()

    async def test_missing_aliases_and_failed_download_still_allow_catalog_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "catalog.json").write_bytes(self.CATALOG)
            client = self.make_client(root)
            client._download = mock.AsyncMock(return_value=False)
            self.assertTrue(await client.ensure_loaded())
            client._download.assert_awaited_once()
            self.assertEqual(client.search("good")[0]["id"], "good")
            self.assertEqual(client._loaded_at, 0)

    async def test_failed_refresh_backs_off_with_usable_stale_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = root / "catalog.json"
            catalog.write_bytes(self.CATALOG)
            (root / "aliases.json").write_bytes(self.ALIASES)
            old = time.time() - REFRESH_INTERVAL - 10
            os.utime(catalog, (old, old))
            client = self.make_client(root)
            client._download = mock.AsyncMock(return_value=False)
            with mock.patch.object(arsenal_module.time, "monotonic", return_value=1000) as clock:
                self.assertTrue(await client.ensure_loaded())
                self.assertTrue(await client.ensure_loaded())
                client._download.assert_awaited_once()
                self.assertEqual(client.search("good")[0]["id"], "good")
                # Expiring the retry window, not a successful refresh TTL,
                # makes the next query try the mirrors again.
                clock.return_value = 1000 + arsenal_module.CATALOG_RETRY_BACKOFF + 1
                self.assertTrue(await client.ensure_loaded())
                self.assertEqual(client._download.await_count, 2)

    async def test_failed_initial_download_backs_off_without_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = self.make_client(Path(tmp))
            client._download = mock.AsyncMock(return_value=False)
            self.assertFalse(await client.ensure_loaded())
            self.assertFalse(await client.ensure_loaded())
            client._download.assert_awaited_once()

    async def test_forced_refresh_bypasses_backoff_and_success_resets_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client = self.make_client(root)
            client._download = mock.AsyncMock(return_value=False)
            self.assertFalse(await client.ensure_loaded())
            self.assertGreater(client._refresh_retry_at, 0)

            async def repair(*_):
                (root / "catalog.json").write_bytes(self.CATALOG)
                (root / "aliases.json").write_bytes(self.ALIASES)
                return True

            client._download.side_effect = repair
            self.assertTrue(await client.ensure_loaded(force=True))
            self.assertEqual(client._download.await_count, 2)
            self.assertEqual(client._refresh_retry_at, 0)
            self.assertTrue(await client.ensure_loaded())
            self.assertEqual(client._download.await_count, 2)

    async def test_missing_aliases_fallback_also_honors_retry_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "catalog.json").write_bytes(self.CATALOG)
            client = self.make_client(root)
            client._download = mock.AsyncMock(return_value=False)
            self.assertTrue(await client.ensure_loaded())
            self.assertTrue(await client.ensure_loaded())
            client._download.assert_awaited_once()
            self.assertEqual(client.search("good")[0]["id"], "good")


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
