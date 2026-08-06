from __future__ import annotations

import ast
import asyncio
import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from aiohttp import ClientConnectorDNSError, web
from PIL import Image

from astrbot_plugin_Helldivers.companion_screenshot import (
    CompanionPlaywrightClient,
    CompanionScreenshotClient,
    CompanionScreenshotError,
    CompanionTargetError,
    _browserless_connection_error,
    build_browserless_endpoint,
    build_browserless_payload,
    companion_dss_target,
    companion_latest_news_target,
    parse_companion_news_target,
    parse_companion_planet_target,
)


class CompanionTargetTests(unittest.TestCase):
    def test_news_id_and_url_are_normalized(self) -> None:
        direct = parse_companion_news_target("3844")
        linked = parse_companion_news_target(
            "https://helldiverscompanion.com/#hellpad/gww/news/3844"
        )
        self.assertEqual(direct, linked)
        self.assertEqual(direct.url, linked.url)
        self.assertEqual(direct.viewport, (800, 1000))

    def test_planet_slug_and_url_are_normalized(self) -> None:
        direct = parse_companion_planet_target("Super Earth")
        linked = parse_companion_planet_target(
            "https://helldiverscompanion.com/#hellpad/planets/super_earth"
        )
        self.assertEqual(direct, linked)
        self.assertEqual(direct.value, "super_earth")
        self.assertEqual(direct.viewport, (2560, 1440))
        self.assertEqual(direct.clip, (0, 0, 2560, 1440))

    def test_fixed_news_and_dss_targets_are_trusted(self) -> None:
        news = companion_latest_news_target()
        dss = companion_dss_target()
        self.assertEqual(news.url, "https://helldiverscompanion.com/#news")
        self.assertEqual(news.kind, "news_latest")
        self.assertEqual(news.clip, (268, 154, 744, 644))
        self.assertEqual(
            dss.url,
            "https://helldiverscompanion.com/#hellpad/stations",
        )
        self.assertEqual(dss.kind, "station")
        self.assertEqual(dss.clip, (209, 82, 862, 734))

    def test_untrusted_or_wrong_routes_are_rejected(self) -> None:
        for value in (
            "https://example.com/#hellpad/gww/news/3844",
            "https://helldiverscompanion.com/#settings",
            "https://helldiverscompanion.com:bad/#hellpad/gww/news/3844",
            "javascript:alert(1)",
            "1" * 300,
        ):
            with self.subTest(value=value):
                with self.assertRaises(CompanionTargetError):
                    parse_companion_news_target(value)

    def test_browserless_endpoint_and_payload(self) -> None:
        endpoint = build_browserless_endpoint(
            "https://production.example.com/?foo=bar", "secret"
        )
        self.assertEqual(
            endpoint,
            "https://production.example.com/screenshot?foo=bar&token=secret",
        )
        target = parse_companion_news_target("3844")
        payload = build_browserless_payload(
            target,
            timeout_ms=90_000,
            wait_ms=5_000,
        )
        self.assertEqual(payload["url"], target.url)
        self.assertEqual(payload["options"]["clip"]["width"], 770)
        self.assertEqual(payload["gotoOptions"]["waitUntil"], "networkidle2")
        self.assertIn("A NEW MESSAGE", payload["addScriptTag"][0]["content"])

    def test_dns_error_message_explains_browserless_networking(self) -> None:
        error = _browserless_connection_error(
            "http://browserless:3000/screenshot",
            ClientConnectorDNSError(None, OSError("no such host")),
        )
        self.assertIn("无法解析 Browserless 主机 browserless", error)
        self.assertIn("http://127.0.0.1:3000", error)

    def test_plugin_schema_and_commands_expose_companion_screenshots(self) -> None:
        root = Path(__file__).parents[1]
        schema = json.loads((root / "_conf_schema.json").read_text(encoding="utf-8"))
        self.assertTrue(schema["enable_companion_screenshots"]["default"])
        self.assertEqual(schema["companion_render_backend"]["default"], "playwright")
        self.assertEqual(
            schema["companion_browserless_url"]["default"],
            "http://browserless:3000",
        )

        tree = ast.parse((root / "main.py").read_text(encoding="utf-8"))
        plugin = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "HelldiversPlugin"
        )
        handlers = {
            node.name: node
            for node in plugin.body
            if isinstance(node, ast.AsyncFunctionDef)
        }
        self.assertNotIn("cmd_companion_news", handlers)
        self.assertNotIn("cmd_companion_planet", handlers)
        source = (root / "main.py").read_text(encoding="utf-8")
        self.assertIn("event.stop_event()", source)
        self.assertIn('@filter.command("hd2stats")', source)
        self.assertIn('@filter.command("hd2help"', source)
        self.assertIn('"hdhelp"', source)
        self.assertIn("HDHELP_TEXT", source)
        self.assertIn("/hd2help", source)
        self.assertNotIn('@filter.command("stats"', source)
        self.assertIn('@filter.command("hd2news")', source)
        self.assertNotIn('@filter.command("news"', source)
        self.assertNotIn('"hc_news"', source)
        self.assertNotIn('"hc_planet"', source)
        initialize = handlers["initialize"]
        handled = {
            name.id
            for node in ast.walk(initialize)
            if isinstance(node, ast.ExceptHandler)
            for name in (
                node.type.elts
                if isinstance(node.type, ast.Tuple)
                else [node.type]
            )
            if isinstance(name, ast.Name)
        }
        self.assertIn("ValueError", handled)
        self.assertIn("TypeError", handled)


class CompanionScreenshotClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_playwright_total_timeout_covers_the_whole_capture(self) -> None:
        class SlowClient(CompanionPlaywrightClient):
            async def start(self) -> None:
                return None

            async def _capture_uncached(self, target, output):
                await asyncio.sleep(1)
                return output

        with tempfile.TemporaryDirectory() as tmp:
            client = SlowClient(Path(tmp), timeout=15)
            client.timeout = 0.02
            with self.assertRaisesRegex(
                CompanionScreenshotError,
                "截图总耗时超过",
            ):
                await client.capture(parse_companion_news_target("3844"))

    async def test_capture_writes_valid_image_and_reuses_cache(self) -> None:
        requests: list[dict] = []

        async def screenshot(request: web.Request) -> web.Response:
            requests.append(
                {
                    "query": dict(request.query),
                    "payload": await request.json(),
                }
            )
            buffer = BytesIO()
            Image.new("RGB", (770, 841), (12, 18, 24)).save(buffer, format="PNG")
            return web.Response(body=buffer.getvalue(), content_type="image/png")

        app = web.Application()
        app.router.add_post("/screenshot", screenshot)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        assert site._server is not None
        port = site._server.sockets[0].getsockname()[1]

        try:
            with tempfile.TemporaryDirectory() as tmp:
                client = CompanionScreenshotClient(
                    Path(tmp),
                    endpoint_url=f"http://127.0.0.1:{port}",
                    token="token-value",
                    cache_ttl=300,
                )
                target = parse_companion_news_target("3844")
                first = await client.capture(target)
                second = await client.capture(target)
                self.assertEqual(first, second)
                self.assertTrue(first.is_file())
                self.assertEqual(len(requests), 1)
                self.assertEqual(client._locks, {})
                self.assertEqual(client._lock_refs, {})
                self.assertEqual(requests[0]["query"]["token"], "token-value")
                self.assertEqual(requests[0]["payload"]["url"], target.url)
                with Image.open(first) as image:
                    self.assertEqual(image.size, (770, 841))
        finally:
            await runner.cleanup()


if __name__ == "__main__":
    unittest.main()
