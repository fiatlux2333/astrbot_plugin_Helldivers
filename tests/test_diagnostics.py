"""diagnostics.py 健康登记与 /hd2ping 报告的单元测试。"""

from __future__ import annotations

import asyncio
import time
import unittest
from unittest.mock import AsyncMock, patch

from astrbot_plugin_Helldivers.clients.api_client import HD2Client
from astrbot_plugin_Helldivers.core.diagnostics import (
    EXPECTED_SOURCES,
    HEALTH,
    HealthRecord,
    build_ping_report,
    format_source_line,
    humanize_age,
    humanize_uptime,
    key_for_host,
)


class KeyForHostTests(unittest.TestCase):
    def test_known_hosts(self) -> None:
        cases = {
            "https://api.helldivers2.dev/raw/api/Stats/war/801/summary": "hd2_api",
            "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/": "steam",
            "https://helldiverscompanion.com/api/steam-api/news": "companion",
            "https://helldivers.wiki.gg/api.php": "wiki",
            "https://raw.githubusercontent.com/SalmonC/HD2Tool/main/x.json": "hd2tool",
            "https://gh-proxy.org/https://raw.githubusercontent.com/x/y": "hd2tool",
            "https://cdn.jsdelivr.net/gh/SalmonC/HD2Tool@main/x.json": "hd2tool",
        }
        for url, expected in cases.items():
            with self.subTest(url=url):
                self.assertEqual(key_for_host(url), expected)

    def test_unknown_host_falls_back_to_hostname(self) -> None:
        self.assertEqual(
            key_for_host("https://example.com/live/orders.json"), "example.com"
        )


class RegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        HEALTH.reset()

    def tearDown(self) -> None:
        HEALTH.reset()

    def test_record_ok_updates_counters_and_consecutive(self) -> None:
        HEALTH.record_fail("hd2_api", detail="HTTP 502")
        HEALTH.record_fail("hd2_api", detail="HTTP 502")
        HEALTH.record_ok("hd2_api", detail="GET /x", latency_ms=123.4)
        snap = HEALTH.snapshot()
        record = snap["hd2_api"]
        self.assertEqual(record.ok_count, 1)
        self.assertEqual(record.fail_count, 2)
        self.assertEqual(record.consecutive_failures, 0)
        self.assertEqual(record.last_ok_detail, "GET /x")
        self.assertAlmostEqual(record.last_latency_ms, 123.4)

    def test_consecutive_failures_reset_only_by_ok(self) -> None:
        for _ in range(3):
            HEALTH.record_fail("wiki", detail="HTTP 503")
        record = HEALTH.snapshot()["wiki"]
        self.assertEqual(record.consecutive_failures, 3)
        HEALTH.record_ok("wiki", detail="api.php query")
        self.assertEqual(HEALTH.snapshot()["wiki"].consecutive_failures, 0)

    def test_record_never_raises_on_bad_input(self) -> None:
        HEALTH.record_ok("", detail=None, latency_ms="abc")  # type: ignore[arg-type]
        record = HEALTH.snapshot()["unknown"]
        self.assertEqual(record.ok_count, 1)
        self.assertIsNone(record.last_latency_ms)

    def test_mark_boot_resets_and_rebases_uptime(self) -> None:
        HEALTH.record_ok("steam", detail="news")
        HEALTH.mark_boot()
        self.assertEqual(HEALTH.snapshot(), {})
        self.assertLessEqual(HEALTH.uptime_seconds, 1.0)

    def test_snapshot_is_a_copy(self) -> None:
        HEALTH.record_ok("hd2_api", detail="x")
        snap = HEALTH.snapshot()
        snap["hd2_api"].ok_count = 999
        self.assertEqual(HEALTH.snapshot()["hd2_api"].ok_count, 1)


class HumanizeTests(unittest.TestCase):
    def test_humanize_age(self) -> None:
        self.assertEqual(humanize_age(None), "从未")
        self.assertEqual(humanize_age(30), "刚刚")
        self.assertEqual(humanize_age(119), "1分钟前")
        self.assertEqual(humanize_age(3600), "1小时前")
        self.assertEqual(humanize_age(3 * 86400 + 5), "3天前")

    def test_humanize_uptime(self) -> None:
        self.assertEqual(humanize_uptime(30), "0分钟")
        self.assertEqual(humanize_uptime(300), "5分钟")
        self.assertEqual(humanize_uptime(3 * 3600 + 120), "3小时2分")
        self.assertEqual(humanize_uptime(2 * 86400 + 3600), "2天1小时")


class ReportFormatTests(unittest.TestCase):
    def setUp(self) -> None:
        HEALTH.reset()
        self.now = time.time()

    def _record(self, source: str, **kwargs) -> HealthRecord:
        return HealthRecord(source=source, **kwargs)

    def test_symbols(self) -> None:
        ok = self._record("hd2_api", ok_count=5, last_ok_at=self.now - 60)
        self.assertTrue(format_source_line(ok, now=self.now).startswith("✅"))

        warn = self._record(
            "steam",
            ok_count=5,
            fail_count=1,
            last_ok_at=self.now - 600,
            last_fail_at=self.now - 300,
            last_fail_detail="HTTP 429",
        )
        self.assertTrue(format_source_line(warn, now=self.now).startswith("⚠️"))

        down = self._record(
            "wiki", fail_count=3, consecutive_failures=3, last_fail_at=self.now
        )
        line = format_source_line(down, now=self.now)
        self.assertTrue(line.startswith("❌"))
        self.assertIn("连续失败3", line)

        never = self._record("bilibili", fail_count=2, last_fail_at=self.now)
        self.assertIn("从未成功", format_source_line(never, now=self.now))

        untouched = self._record("hd2tool")
        self.assertIn("暂无记录", format_source_line(untouched, now=self.now))

    def test_report_includes_expected_missing_sources(self) -> None:
        HEALTH.record_ok("hd2_api", detail="GET /x", latency_ms=42.0)
        report = build_ping_report(
            HEALTH.snapshot(),
            title="🩺 测试报告",
            info_lines=["运行 1分钟"],
            cache_lines=["war_status 刚刚"],
            expected_sources=EXPECTED_SOURCES,
            now=self.now,
        )
        self.assertIn("🩺 测试报告", report)
        self.assertIn("运行 1分钟", report)
        self.assertIn("✅ 主API", report)
        for label in ("Companion", "Wiki", "截图"):
            self.assertIn(f"➖ {label}", report)
        self.assertIn("war_status 刚刚", report)

    def test_detail_truncation(self) -> None:
        record = self._record(
            "hd2_api",
            ok_count=1,
            last_ok_at=self.now,
            last_ok_detail="x" * 200,
        )
        line = format_source_line(record, now=self.now)
        self.assertLess(len(line), 120)
        self.assertIn("…", line)


class _FakeResponse:
    def __init__(self, status: int, payload=None):
        self.status = status
        self.headers: dict[str, str] = {}
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def text(self):
        return "fake body"

    async def json(self, content_type=None):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def _next_response(self):
        response = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return response

    def request(self, method, url, **kwargs):
        return self._next_response()

    def get(self, url, **kwargs):
        return self._next_response()


def _make_client() -> HD2Client:
    return HD2Client(base_url="https://api.helldivers2.dev", min_request_interval=0.0)


class HD2ClientInstrumentationTests(unittest.TestCase):
    def setUp(self) -> None:
        HEALTH.reset()

    def tearDown(self) -> None:
        HEALTH.reset()

    def _run(self, coro):
        return asyncio.run(coro)

    def test_success_records_ok(self) -> None:
        client = _make_client()
        session = _FakeSession([_FakeResponse(200, {"ok": True})])
        client.get_session = AsyncMock(return_value=session)
        data = self._run(client.request_json("GET", "/raw/api/WarSeason/801/Status"))
        self.assertEqual(data, {"ok": True})
        record = HEALTH.snapshot()["hd2_api"]
        self.assertEqual(record.ok_count, 1)
        self.assertIn("GET /raw/api/WarSeason/801/Status", record.last_ok_detail)
        self.assertIsNotNone(record.last_latency_ms)

    def test_final_http_failure_records_fail(self) -> None:
        client = _make_client()
        session = _FakeSession([_FakeResponse(503)])
        client.get_session = AsyncMock(return_value=session)
        data = self._run(
            client.request_json(
                "GET", "/raw/api/X", max_attempts=1, failure_is_warning=True
            )
        )
        self.assertIsNone(data)
        record = HEALTH.snapshot()["hd2_api"]
        self.assertEqual(record.fail_count, 1)
        self.assertIn("HTTP 503", record.last_fail_detail)

    def test_non_retryable_dns_error_records_fail(self) -> None:
        client = _make_client()

        def raise_dns(*args, **kwargs):
            raise OSError("getaddrinfo failed")

        session = _FakeSession([])
        session.request = raise_dns
        client.get_session = AsyncMock(return_value=session)
        data = self._run(client.request_json("GET", "/raw/api/X"))
        self.assertIsNone(data)
        record = HEALTH.snapshot()["hd2_api"]
        self.assertEqual(record.fail_count, 1)
        self.assertIn("getaddrinfo", record.last_fail_detail)

    def test_steam_and_companion_keys_are_separated(self) -> None:
        client = _make_client()
        session = _FakeSession(
            [
                _FakeResponse(200, {"appnews": {}}),
                _FakeResponse(200, {"appnews": {}}),
            ]
        )
        client.get_session = AsyncMock(return_value=session)
        self._run(client.request_json("GET", "https://api.steampowered.com/x"))
        self._run(client.request_json("GET", "https://helldiverscompanion.com/y"))
        snap = HEALTH.snapshot()
        self.assertIn("steam", snap)
        self.assertIn("companion", snap)
        self.assertNotIn("hd2_api", snap)

if __name__ == "__main__":
    unittest.main()
