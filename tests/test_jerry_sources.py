from __future__ import annotations

import asyncio
import copy
import hashlib
import io
import json
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image

from astrbot_plugin_Helldivers.clients.jerry_map import (
    FONT_URL, MAP_URL, JerryMapClient, snapshot_time, validate_image,
)
from astrbot_plugin_Helldivers.clients.jerry_wiki import (
    CATALOGS, JerryWikiClient, QueryState, merge_chinese, names, render_detail,
)


def sample_data():
    docs = [
        ["./weapon.html?id=ar23", "AR-23 解放者 AR-23 Liberator", "武器", "主武器", "可靠的步枪"],
        ["./weapon.html?id=ar23p", "AR-23P 穿透者 AR-23P Penetrator", "武器", "主武器", "中甲步枪"],
        ["./mechanic.html?id=damage#armor", "伤害机制 › 护甲", "游戏机制", "伤害", "护甲机制正文"],
        ["./patchnote.html?id=1.0#fix", "更新 › 修复", "更新公告", "1.0", "修复问题"],
    ]
    files = {file: {key: []} for file, key in CATALOGS.values()}
    files.update({
        "search_index.json": {"v": 1, "digest": "a", "count": len(docs), "docs": docs},
        "search_entries.json": {"v": 1, "digest": "a", "count": len(docs), "docs": [d[:4] for d in docs]},
        "weapons.json": {"weapons": [
            {"id": "ar23", "name": "AR-23 解放者", "name_en": "AR-23 Liberator",
             "aliases": ["标准步枪"], "description": "English description",
             "description_zh": "可靠的中文说明", "stats_full": {"damage": 70, "capacity": 45}},
            {"id": "ar23p", "name": "AR-23P 穿透者", "name_en": "AR-23P Penetrator",
             "description_zh": "穿透者中文说明"},
        ]},
        "mechanics/damage.json": {"id": "damage", "sections": [
            {"id": "other", "title": "Other", "content": "Other text"},
            {"id": "armor", "title": "Armor", "content": "English armor text",
             "subsections": [{"id": "nested", "content": "Nested original"}]},
        ]},
        "mechanics/damage_zh.json": {"sections_zh": [
            {"id": "armor", "title_zh": "护甲", "content_zh": "护甲中文正文",
             "subsections_zh": [{"id": "nested", "content_zh": "嵌套中文"}]},
            {"id": "other", "title_zh": "其他", "content_zh": "其他中文"},
        ]},
        "patchnotes.json": {"versions": [{"id": "1.0", "sections": [
            {"id": "fix", "heading": "Fix", "items": [{"text": "Fixed crash"}]},
        ]}]},
        "patchnotes_zh.json": {"versions_zh": [{"id": "1.0", "mt": True, "sections_zh": [
            {"id": "fix", "heading_zh": "修复", "items_zh": ["修复崩溃"]},
        ]}]},
    })
    return files


class WikiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.client = JerryWikiClient(Path(self.tmp.name))
        self.files = sample_data()

        async def download(file):
            data = copy.deepcopy(self.files[file])
            self.client._validate(file, data)
            return data
        self.client._download = AsyncMock(side_effect=download)

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    async def test_chinese_english_model_and_alias(self):
        for q in ("解放者", "AR-23", "AR23", "Liberator", "标准步枪"):
            with self.subTest(q=q):
                result = await self.client.query(q)
                self.assertIn("可靠的中文说明", result)
                self.assertIn("伤害: 70", result)
                self.assertNotIn("English description", result)
                self.assertNotIn("wiki.gg", result)
        result = await self.client.query("AR-23P")
        self.assertIn("穿透者中文说明", result)
        self.assertNotIn("可靠的中文说明", result)

    async def test_body_only_matches_do_not_auto_resolve(self):
        result = await self.client.query("可靠")
        self.assertIn("/wiki AR-23", result)
        self.assertNotIn("可靠的中文说明", result)

    async def test_multiple_aliases_are_ambiguous(self):
        self.files["weapons.json"]["weapons"][1]["aliases"] = ["标准步枪"]
        result = await self.client.query("标准步枪")
        self.assertIn("/wiki AR-23 ", result)
        self.assertIn("/wiki AR-23P ", result)
        self.assertNotIn("出处：", result)

    async def test_unknown_and_input_limit(self):
        self.assertIn("未找到", await self.client.query("完全不存在的词"))
        self.assertIn("1–160", await self.client.query("x" * 161))

    async def test_detailed_limit_and_no_model_translation(self):
        self.files["weapons.json"]["weapons"][0]["description_zh"] = "中文长文" * 2000
        normal = await self.client.query("AR23")
        full = await self.client.query("AR23", full=True)
        self.assertIn("详细内容", full)
        self.assertIn("截断", normal)
        self.assertIn("截断", full)
        self.assertGreater(len(full), len(normal))

    async def test_mechanic_merges_by_id_including_children(self):
        result = await self.client.query("护甲", full=True)
        self.assertIn("护甲中文正文", result)
        self.assertIn("嵌套中文", result)
        self.assertNotIn("其他中文", result)
        self.assertNotIn("English armor", result)

    async def test_patchnotes_chinese_and_machine_label(self):
        result = await self.client.query("修复")
        self.assertIn("修复崩溃", result)
        self.assertIn("机翻", result)
        self.assertNotIn("Fixed crash", result)

    async def test_duplicate_titles_can_be_selected(self):
        docs = self.files["search_index.json"]["docs"]
        docs[3][1] = "修复"
        docs.append(["./patchnote.html?id=2.0#fix", "修复", "更新公告", "2.0", "修复问题"])
        self.files["search_index.json"]["count"] = len(docs)
        self.files["search_entries.json"]["docs"] = [d[:4] for d in docs]
        self.files["search_entries.json"]["count"] = len(docs)
        result = await self.client.query("修复")
        choices = [line.removeprefix("/wiki ") for line in result.splitlines() if line.startswith("/wiki ")]
        self.assertEqual(len(set(choices)), 2)
        selected = await self.client.query(choices[0])
        self.assertIn("修复崩溃", selected)

    def test_table_cells_keep_header_names(self):
        result = render_detail({"tables": [{
            "title": "奖励", "headers": ["名称", "价格"], "rows": [["装备", 0]],
        }]})
        self.assertIn("名称: 装备", result)
        self.assertIn("价格: 0", result)

    def test_html_tables_are_not_flattened_into_unlabelled_numbers(self):
        result = render_detail({"tables": [{"html": "<table><tr><td>12345</td></tr></table>"}]})
        self.assertIn("表格未展开", result)
        self.assertNotIn("12345", result)

    async def test_http_fetches_only_static_json_and_rejects_redirects(self):
        from aiohttp import web
        received = []
        redirect = False

        async def handler(request):
            received.append(request.path)
            if redirect:
                raise web.HTTPFound("https://helldivers.wiki.gg/api.php")
            return web.json_response(self.files["weapons.json"])
        app = web.Application()
        app.router.add_get("/HD2_Wiki/data/wiki/zh/weapons.json", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        self.client.base_url = f"http://127.0.0.1:{port}/HD2_Wiki/"
        try:
            data = await JerryWikiClient._download(self.client, "weapons.json")
            self.assertEqual(len(data["weapons"]), 2)
            redirect = True
            with self.assertRaises(ValueError):
                await JerryWikiClient._download(self.client, "weapons.json")
            self.assertEqual(received, ["/HD2_Wiki/data/wiki/zh/weapons.json"] * 2)
        finally:
            await runner.cleanup()

    async def test_missing_translation_retains_original(self):
        self.files["weapons.json"]["weapons"][0].pop("description_zh")
        result = await self.client.query("AR23")
        self.assertIn("English description", result)
        self.assertIn("暂无中文", result)

    async def test_corrupt_index_is_unavailable_not_not_found(self):
        self.files["search_index.json"]["docs"] = [["bad"]]
        result = await self.client.query("AR23")
        self.assertIn("暂不可用", result)
        self.assertNotIn("未找到", result)

    async def test_detail_failure_labels_index_excerpt(self):
        self.files["mechanics/damage.json"] = {}
        result = await self.client.query("护甲")
        self.assertIn("索引摘录", result)
        self.assertIn("不是完整正文", result)

    async def test_each_main_category(self):
        for page, (file, key) in CATALOGS.items():
            with self.subTest(page=page):
                row = {"id": "sample", "name_zh": "测试条目", "description_zh": "分类正文"}
                self.files[file] = {key: [{"tasks": [row]}] if page == "mission.html" else [row]}
                detail = await self.client._detail(
                    [f"./{page}?id=sample", "测试条目", "", "", ""], QueryState()
                )
                self.assertIn("分类正文", render_detail(detail))

    async def test_mission_duplicate_ids_follow_site_last_match(self):
        self.files["missions.json"] = {"categories": [
            {"tasks": [{"id": "sample", "name_zh": "通用任务", "description_zh": "旧描述"}]},
            {"tasks": [{"id": "sample", "name_zh": "特殊任务", "description_zh": "源站最终描述"}]},
        ]}
        result = await self.client._detail(["./mission.html?id=sample", "", "", "", ""], QueryState())
        self.assertEqual(result["description_zh"], "源站最终描述")

    async def test_failed_refresh_preserves_last_good_cache(self):
        await self.client._get("weapons.json", QueryState())
        self.client._memory["weapons.json"]["saved_at"] = time.time() - 2 * 86400
        self.client._download.side_effect = ValueError("broken source")
        state = QueryState()
        data = await self.client._get("weapons.json", state)
        self.assertEqual(len(data["weapons"]), 2)
        self.assertTrue(state.notes)
        self.client._memory["weapons.json"]["saved_at"] = time.time() - 8 * 86400
        with self.assertRaises(RuntimeError):
            await self.client._get("weapons.json", QueryState())

    async def test_backoff_is_not_extended_by_repeated_queries(self):
        self.client._download.side_effect = ValueError("broken source")
        with self.assertRaises(ValueError):
            await self.client._get("weapons.json", QueryState())
        deadline = self.client._backoff["weapons.json"]
        for _ in range(3):
            with self.assertRaises(RuntimeError):
                await self.client._get("weapons.json", QueryState())
        self.assertEqual(self.client._backoff["weapons.json"], deadline)
        self.client._download.assert_awaited_once()

    async def test_shared_request_cancellation(self):
        started, release = asyncio.Event(), asyncio.Event()
        calls = 0

        async def slow(file):
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return self.files[file]
        self.client._download.side_effect = slow
        first = asyncio.create_task(self.client._get("weapons.json", QueryState()))
        await started.wait()
        second = asyncio.create_task(self.client._get("weapons.json", QueryState()))
        await asyncio.sleep(0)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        release.set()
        await second
        self.assertEqual(calls, 1)
        self.assertFalse(self.client._tasks)

    async def test_close_cancels_pending_request(self):
        started = asyncio.Event()

        async def slow(file):
            started.set()
            await asyncio.Event().wait()
        self.client._download.side_effect = slow
        task = asyncio.create_task(self.client._get("weapons.json", QueryState()))
        await started.wait()
        await self.client.close()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(self.client._tasks)

    def test_source_and_result_urls_are_restricted(self):
        for url in ("https://helldivers.wiki.gg/wiki/X", "//evil.test/a", "../../api.php"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.client._url(url)
        self.assertNotEqual(
            self.client.cache_dir,
            JerryWikiClient(Path(self.tmp.name), base_url="https://example.org/wiki/").cache_dir,
        )

    def test_legacy_wiki_config_is_not_active(self):
        root = Path(__file__).parents[1]
        schema = json.loads((root / "_conf_schema.json").read_text("utf-8"))
        main = (root / "main.py").read_text("utf-8")
        for key in ("wiki_base", "wiki_api_path", "wiki_prefer_hd2", "translate_wiki"):
            self.assertNotIn(key, schema)
            self.assertNotIn(f'self._cfg("{key}"', main)

    def test_model_suffixes_and_combination_prefixes_remain_distinct(self):
        aliases = names({"name": "AX/AR-23 Guard Dog"})
        self.assertNotIn("ar23", aliases)
        self.assertIn("ax/ar23", aliases)

    def test_translation_item_length_mismatch_does_not_shift(self):
        result = merge_chinese(
            {"sections": [{"id": "a", "items": ["one", "two"]}]},
            {"sections_zh": [{"id": "a", "items_zh": ["二"]}]},
        )
        self.assertNotIn("items_zh", result["sections"][0])


class MapTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.client = JerryMapClient(Path(self.tmp.name))

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    def test_snapshot_clock(self):
        now = datetime.now(timezone.utc)
        snapshot_time(now.isoformat())
        for value in (None, "", "bad", now.replace(tzinfo=None).isoformat(),
                      (now - timedelta(minutes=31)).isoformat(),
                      (now + timedelta(minutes=2)).isoformat()):
            with self.subTest(value=value), self.assertRaises(ValueError):
                snapshot_time(value)

    def test_blank_and_broken_images_rejected(self):
        output = io.BytesIO()
        Image.new("RGB", (2560, 1440), "black").save(output, format="PNG")
        for data in (output.getvalue(), b"not an image"):
            with self.assertRaises(ValueError):
                validate_image(data)

    def mock_browser(self):
        stamp = datetime.now(timezone.utc).isoformat()
        response = Mock(status=200, json=AsyncMock(return_value={
            "fetchedAt": stamp, "planets": [{"index": 0}],
        }))
        future = asyncio.get_running_loop().create_future()
        future.set_result(response)
        pending = Mock(
            __aenter__=AsyncMock(return_value=SimpleNamespace(value=future)),
            __aexit__=AsyncMock(return_value=False),
        )
        image = io.BytesIO()
        Image.effect_noise((320, 180), 40).resize(
            (2560, 1440), Image.Resampling.NEAREST,
        ).convert("RGB").save(image, format="PNG")
        page = Mock(
            url=MAP_URL,
            expect_response=Mock(return_value=pending),
            goto=AsyncMock(return_value=Mock(status=200)),
            evaluate=AsyncMock(), wait_for_function=AsyncMock(),
            add_style_tag=AsyncMock(),
            screenshot=AsyncMock(return_value=image.getvalue()),
        )
        context = Mock(
            new_page=AsyncMock(return_value=page), close=AsyncMock(),
            add_init_script=AsyncMock(), route=AsyncMock(),
        )
        self.client._browser = Mock(
            new_context=AsyncMock(return_value=context), close=AsyncMock(),
        )
        self.client._start = AsyncMock()
        return page, context

    async def test_navigation_and_waits_use_configured_budget(self):
        page, context = self.mock_browser()
        self.client.timeout = 65
        _, path = await self.client.capture()
        page.goto.assert_awaited_once_with(MAP_URL, wait_until="commit", timeout=65_000)
        context.set_default_timeout.assert_called_once_with(65_000)
        context.add_init_script.assert_awaited_once()
        context.route.assert_awaited_once_with(FONT_URL, self.client._route_font)
        self.assertEqual(page.wait_for_function.await_count, 3)
        self.assertTrue(path.is_file())
        context.close.assert_awaited_once()

    async def test_browser_uses_compatible_transport_and_configured_proxy(self):
        runtime = Mock(chromium=Mock(launch=AsyncMock(return_value=Mock(close=AsyncMock()))),
                       stop=AsyncMock())
        manager = Mock(start=AsyncMock(return_value=runtime))
        self.client.proxy_url = "http://127.0.0.1:7890"
        with patch("playwright.async_api.async_playwright", return_value=manager):
            await self.client._start()
        options = runtime.chromium.launch.await_args.kwargs
        self.assertIn("--disable-http2", options["args"])
        self.assertIn("--disable-quic", options["args"])
        self.assertEqual(options["proxy"], {"server": self.client.proxy_url})

    async def test_remote_font_skipped_only_after_local_face_loaded(self):
        for ready in (True, False, RuntimeError("frame unavailable")):
            with self.subTest(ready=ready):
                evaluate = AsyncMock()
                if isinstance(ready, Exception):
                    evaluate.side_effect = ready
                else:
                    evaluate.return_value = ready
                route = Mock(
                    request=Mock(frame=Mock(evaluate=evaluate)),
                    abort=AsyncMock(), continue_=AsyncMock(),
                )
                await self.client._route_font(route)
                if ready is True:
                    route.abort.assert_awaited_once()
                    route.continue_.assert_not_awaited()
                else:
                    route.abort.assert_not_awaited()
                    route.continue_.assert_awaited_once()

    async def test_failure_diagnostics_show_resource_path_without_query(self):
        page, context = self.mock_browser()
        resource = Mock(url=(
            "https://jerry114514.github.io/HD2-Galatic_war-Map/js/critical.js"
            "?private_token=do-not-log"
        ))

        async def navigate(*_args, **_kwargs):
            listeners = {args[0]: args[1] for args, _ in context.on.call_args_list}
            listeners["request"](resource)
            raise TimeoutError("Blocked script")

        page.goto.side_effect = navigate
        with self.assertRaises(TimeoutError):
            await self.client.capture()
        self.assertIn("/js/critical.js", self.client.capture_detail)
        self.assertNotIn("private_token", self.client.capture_detail)
        self.assertNotIn("do-not-log", self.client.capture_detail)

    async def test_navigation_failure_keeps_stage_and_closes_context(self):
        page, context = self.mock_browser()
        page.goto.side_effect = TimeoutError("Navigation unavailable")
        with self.assertRaises(TimeoutError):
            await self.client.capture()
        self.assertEqual(self.client.capture_stage, "navigation")
        page.screenshot.assert_not_awaited()
        context.close.assert_awaited_once()
        self.assertIsNone(self.client._browser)

    async def test_http_error_does_not_wait_for_map_readiness(self):
        page, context = self.mock_browser()
        page.goto.return_value = Mock(status=503)
        with self.assertRaisesRegex(ValueError, "document request failed"):
            await self.client.capture()
        page.wait_for_function.assert_not_awaited()
        page.screenshot.assert_not_awaited()
        context.close.assert_awaited_once()

    async def test_coalesces_and_preserves_other_waiter(self):
        started, release = asyncio.Event(), asyncio.Event()

        async def capture():
            started.set()
            await release.wait()
            return "time", Path("map.png")
        self.client._capture_page = AsyncMock(side_effect=capture)
        first = asyncio.create_task(self.client.capture())
        await started.wait()
        second = asyncio.create_task(self.client.capture())
        await asyncio.sleep(0)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        release.set()
        self.assertEqual((await second)[1], Path("map.png"))
        self.client._capture_page.assert_awaited_once()
        self.assertIsNone(self.client._task)

    async def test_timeout_cleans_browser(self):
        self.client.timeout = 0.03
        self.client._capture_page = AsyncMock(side_effect=lambda: None)

        async def block():
            await asyncio.Event().wait()
        self.client._capture_page.side_effect = block
        self.client._stop_browser = AsyncMock()
        with self.assertRaises(TimeoutError):
            await self.client.capture()
        self.assertTrue(self.client._stop_browser.await_count)
        self.assertIsNone(self.client._task)

    async def test_cache_rejects_old_snapshot_even_when_image_is_fresh(self):
        root = Path(self.tmp.name)
        (root / "galaxy.json").write_text(json.dumps({
            "captured_at": time.time(),
            "fetched_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        }), encoding="utf-8")
        self.assertIsNone(self.client._cached())

    async def test_fresh_cache_is_verified_and_avoids_browser(self):
        root = Path(self.tmp.name)
        output = io.BytesIO()
        Image.effect_noise((320, 180), 40).resize(
            (2560, 1440), Image.Resampling.NEAREST,
        ).convert("RGB").save(output, format="PNG")
        image = output.getvalue()
        (root / "galaxy.png").write_bytes(image)
        stamp = datetime.now(timezone.utc).isoformat()
        meta = {
            "captured_at": time.time(), "fetched_at": stamp,
            "sha256": hashlib.sha256(image).hexdigest(),
        }
        (root / "galaxy.json").write_text(json.dumps(meta), encoding="utf-8")
        self.client._start = AsyncMock(side_effect=AssertionError("Must use cache"))
        self.assertEqual(await self.client.capture(), (stamp, root / "galaxy.png"))
        self.client._start.assert_not_awaited()
        meta["sha256"] = "mismatched"
        (root / "galaxy.json").write_text(json.dumps(meta), encoding="utf-8")
        self.assertIsNone(self.client._cached())

    async def test_close_cancels_active_capture(self):
        started = asyncio.Event()

        async def capture():
            started.set()
            await asyncio.Event().wait()
        self.client._capture_page = AsyncMock(side_effect=capture)
        self.client._stop_browser = AsyncMock()
        task = asyncio.create_task(self.client.capture())
        await started.wait()
        await self.client.close()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertIsNone(self.client._task)
        with self.assertRaises(RuntimeError):
            await self.client.capture()


class CommandSourceTests(unittest.IsolatedAsyncioTestCase):
    def service(self):
        from astrbot_plugin_Helldivers.services import HelldiversService
        svc = object.__new__(HelldiversService)
        svc.enable_map = svc.enable_wiki = True
        svc.map_screenshot = type("Screenshot", (), {})()
        svc.map_screenshot.capture = AsyncMock(return_value=("2026-10-31T18:00:00+08:00", Path("map.png")))
        svc._get_local_map_result = AsyncMock(return_value=("本地地图", Path("local.png")))
        return svc

    async def test_map_success_never_queries_old_source(self):
        svc = self.service()
        caption, path = await svc.get_map_result()
        svc._get_local_map_result.assert_not_awaited()
        self.assertEqual(path, Path("map.png"))
        self.assertNotIn("http", caption)

    async def test_map_failure_falls_back_without_link(self):
        for error in (ImportError("playwright"), TimeoutError(), ValueError("blank image"), RuntimeError("browser")):
            with self.subTest(error=error):
                svc = self.service()
                svc.map_screenshot.capture.side_effect = error
                caption, path = await svc.get_map_result()
                self.assertEqual(path, Path("local.png"))
                self.assertNotIn("http", caption)

    async def test_both_fail_and_disabled(self):
        svc = self.service()
        svc.map_screenshot.capture.side_effect = RuntimeError()
        svc._get_local_map_result.side_effect = RuntimeError()
        caption, path = await svc.get_map_result()
        self.assertIsNone(path)
        self.assertNotIn("http", caption)
        svc.enable_map = False
        svc.map_screenshot.capture.reset_mock()
        await svc.get_map_result()
        svc.map_screenshot.capture.assert_not_awaited()

    async def test_cancel_does_not_trigger_fallback(self):
        svc = self.service()
        svc.map_screenshot.capture.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await svc.get_map_result()
        svc._get_local_map_result.assert_not_awaited()

    async def test_wiki_passes_chinese_without_translation(self):
        svc = self.service()
        svc.wiki_client = type("Wiki", (), {})()
        svc.wiki_client.query = AsyncMock(return_value="静态中文内容")
        svc._translate_wiki_extract = AsyncMock(side_effect=AssertionError("No translation"))
        self.assertEqual(await svc.get_wiki_message("一个未收录中文词", full=True), "静态中文内容")
        svc.wiki_client.query.assert_awaited_once_with("一个未收录中文词", full=True)
        svc._translate_wiki_extract.assert_not_awaited()
