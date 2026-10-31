"""Check headers on the wire, including session defaults and redirects."""

import asyncio
import unittest

import aiohttp

from aiohttp import web
from aiohttp.test_utils import TestServer

from astrbot_plugin_Helldivers.clients.api_client import HD2Client


class HeaderPrivacyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.received = []

        async def echo(request):
            self.received.append(dict(request.headers))
            return web.json_response(dict(request.headers))

        external_app = web.Application()
        external_app.router.add_get("/echo", echo)
        self.external = TestServer(external_app)
        await self.external.start_server()
        trusted_app = web.Application()
        trusted_app.router.add_get("/echo", echo)

        async def redirect_external(request):
            raise web.HTTPFound(str(self.external.make_url("/echo")))

        async def redirect_local(request):
            raise web.HTTPFound("/echo")

        async def redirect_loop(request):
            raise web.HTTPFound("/loop")

        async def slow_redirect(request):
            hop = int(request.match_info["hop"])
            await asyncio.sleep(0.08)
            if hop < 3:
                raise web.HTTPFound(f"/slow/{hop + 1}")
            return web.json_response({"ok": True})

        async def slow_body(request):
            response = web.StreamResponse(headers={"Content-Type": "application/json"})
            await response.prepare(request)
            await asyncio.sleep(0.3)
            try:
                await response.write(b'{"ok": true}')
            except ConnectionResetError:
                pass
            return response

        async def redirect_body(request):
            await asyncio.sleep(0.08)
            raise web.HTTPFound("/body")

        trusted_app.router.add_get("/external", redirect_external)
        trusted_app.router.add_get("/local", redirect_local)
        trusted_app.router.add_get("/loop", redirect_loop)
        trusted_app.router.add_get("/slow/{hop}", slow_redirect)
        trusted_app.router.add_get("/body", slow_body)
        trusted_app.router.add_get("/redirect-body", redirect_body)
        self.trusted = TestServer(trusted_app)
        await self.trusted.start_server()
        self.client = HD2Client(
            base_url=str(self.trusted.make_url("/")).rstrip("/"),
            contact="private@example.com", client_name="private-client",
            min_request_interval=0, retry_max_attempts=1,
        )

    async def asyncTearDown(self):
        await self.client.close()
        await self.trusted.close()
        await self.external.close()

    async def test_trusted_request_gets_contact_but_session_defaults_do_not(self):
        headers = await self.client.get_json("/echo")
        self.assertEqual(headers["X-Super-Contact"], "private@example.com")
        self.assertEqual(headers["X-Super-Client"], "private-client")
        session = await self.client.get_session()
        self.assertNotIn("X-Super-Contact", session.headers)
        self.assertNotIn("X-Super-Client", session.headers)

    async def test_other_origin_on_same_host_does_not_get_private_headers(self):
        headers = await self.client.get_json(str(self.external.make_url("/echo")))
        self.assertNotIn("X-Super-Contact", headers)
        self.assertNotIn("X-Super-Client", headers)
        self.assertIn("User-Agent", headers)
        self.assertEqual(headers["Accept"], "application/json")

    async def test_cross_origin_redirect_drops_contact_and_extra_credentials(self):
        headers = await self.client.request_json(
            "GET", "/external", extra_headers={"Authorization": "Bearer private"}
        )
        self.assertNotIn("X-Super-Contact", headers)
        self.assertNotIn("X-Super-Client", headers)
        self.assertNotIn("Authorization", headers)

    async def test_same_origin_redirect_keeps_contact_and_extra_headers(self):
        headers = await self.client.request_json(
            "GET", "/local", extra_headers={"Accept-Language": "en-US"}
        )
        self.assertEqual(headers["X-Super-Contact"], "private@example.com")
        self.assertEqual(headers["Accept-Language"], "en-US")

    async def test_redirect_loop_is_bounded(self):
        self.assertIsNone(await self.client.get_json("/loop"))

    async def test_explicit_total_timeout_covers_all_redirect_hops(self):
        self.assertIsNone(await self.client.request_json("GET", "/slow/0", timeout=0.2))

    async def test_default_total_timeout_covers_all_redirect_hops(self):
        self.client.timeout = aiohttp.ClientTimeout(total=0.2)
        self.assertIsNone(await self.client.get_json("/slow/0"))

    async def test_unlimited_total_timeout_still_allows_redirect_chain(self):
        result = await self.client.request_json(
            "GET", "/slow/0", timeout=aiohttp.ClientTimeout(total=None)
        )
        self.assertEqual(result, {"ok": True})

    async def test_shared_budget_also_covers_final_response_body(self):
        # Each individual hop fits in .35s, but redirect + final body do not.
        self.assertIsNone(await self.client.request_json("GET", "/redirect-body", timeout=0.35))

    def test_scheme_host_and_effective_port_define_trusted_origin(self):
        client = HD2Client(contact="private@example.com")
        for url in (
            "http://api.helldivers2.dev/echo",
            "https://api.helldivers2.dev:444/echo",
            "https://api.helldivers2.dev:0/echo",
            "https://other.example/echo",
        ):
            with self.subTest(url=url):
                self.assertNotIn("X-Super-Contact", client._headers_for_url(url))
        self.assertIn(
            "X-Super-Contact",
            client._headers_for_url("https://API.HELLDIVERS2.DEV:443/echo"),
        )
