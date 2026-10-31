from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from astrbot_plugin_Helldivers.clients.bilibili_monitor import (
    GALAXY_NEWS_UID,
    LEGACY_GALAXY_NEWS_UID,
    BilibiliMonitor,
    BilibiliPost,
    BilibiliRiskControlError,
    normalize_galaxy_news_uid,
    parse_dynamic,
    parse_opus_feed_item,
    sign_wbi_params,
)


class BilibiliParserTests(unittest.TestCase):
    def test_parse_opus_space_feed_item(self) -> None:
        post = parse_opus_feed_item(
            {
                "opus_id": "1232002523395522569",
                "content": "银河快报0803\n-",
                "cover": {
                    "url": "http://i0.hdslb.com/bfs/new_dyn/report.jpg",
                    "width": 1080,
                    "height": 3200,
                },
            }
        )
        self.assertIsNotNone(post)
        assert post is not None
        self.assertEqual(post.text, "银河快报0803\n-")
        self.assertEqual(
            post.image_urls,
            ("https://i0.hdslb.com/bfs/new_dyn/report.jpg",),
        )

    def test_legacy_galaxy_news_uid_is_migrated(self) -> None:
        self.assertEqual(
            normalize_galaxy_news_uid(LEGACY_GALAXY_NEWS_UID),
            GALAXY_NEWS_UID,
        )
        self.assertEqual(normalize_galaxy_news_uid("123"), "123")

    def test_galaxy_news_command_registration_is_not_permission_filtered(self) -> None:
        source = (Path(__file__).parents[1] / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        plugin = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "HelldiversPlugin"
        )
        handler = next(
            node
            for node in plugin.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "cmd_galaxy_news"
        )
        self.assertEqual(len(handler.decorator_list), 2)
        command = handler.decorator_list[0]
        self.assertIsInstance(command, ast.Call)
        assert isinstance(command, ast.Call)
        self.assertEqual(ast.unparse(command.func), "filter.command")
        aliases = next(
            keyword.value for keyword in command.keywords if keyword.arg == "alias"
        )
        self.assertIsInstance(aliases, ast.List)
        self.assertEqual(
            [item.value for item in aliases.elts if isinstance(item, ast.Constant)],
            ["银河快报推送", "galaxy_news"],
        )

    def test_galaxy_news_messages_include_source_link(self) -> None:
        source = (Path(__file__).parents[1] / "main.py").read_text(encoding="utf-8")
        self.assertIn("原动态：{post.url}", source)
        self.assertNotIn("\\n\\n原动态：{post.url}", source)
        self.assertIn('chain.message(f"\\n原动态：{post.url}")', source)
        self.assertIn('components.append(Plain(f"\\n原动态：{post.url}"))', source)

    def test_wbi_signature_matches_documented_example(self) -> None:
        signed = sign_wbi_params(
            {"foo": "114", "bar": "514", "zab": 1919810},
            "7cd084941338484aae1ad9425b84077c",
            "4932caff0ff746eab6f01bf08b70ac45",
            timestamp=1702204169,
        )
        self.assertEqual(signed["wts"], 1702204169)
        self.assertEqual(signed["w_rid"], "8f6f2b5b3d485fe1886cec6a0be8c5d4")

    def test_parse_draw_dynamic(self) -> None:
        post = parse_dynamic(
            {
                "id_str": "123",
                "modules": {
                    "module_author": {"name": "银河快报"},
                    "module_dynamic": {
                        "desc": {"text": "银河快报0801\n图灵保卫战胜利"},
                        "major": {
                            "draw": {
                                "items": [
                                    {"src": "https://i0.hdslb.com/a.jpg"},
                                    {"src": "https://i0.hdslb.com/b.jpg"},
                                ]
                            }
                        },
                    },
                },
            }
        )
        self.assertIsNotNone(post)
        assert post is not None
        self.assertEqual(post.dynamic_id, "123")
        self.assertIn("银河快报0801", post.text)
        self.assertEqual(len(post.image_urls), 2)

    def test_parse_opus_dynamic(self) -> None:
        post = parse_dynamic(
            {
                "id_str": "456",
                "modules": {
                    "module_dynamic": {
                        "major": {
                            "opus": {
                                "summary": {"text": "银河快报新版正文"},
                                "pics": [{"url": "https://i0.hdslb.com/c.jpg"}],
                            }
                        }
                    }
                },
            }
        )
        self.assertIsNotNone(post)
        assert post is not None
        self.assertEqual(post.text, "银河快报新版正文")
        self.assertEqual(post.image_urls, ("https://i0.hdslb.com/c.jpg",))

    def test_parse_opus_rich_text_nodes(self) -> None:
        post = parse_dynamic(
            {
                "id_str": "803",
                "modules": {
                    "module_author": {"name": "银河快报"},
                    "module_dynamic": {
                        "desc": None,
                        "major": {
                            "opus": {
                                "summary": {
                                    "rich_text_nodes": [
                                        {
                                            "type": "RICH_TEXT_NODE_TYPE_TEXT",
                                            "orig_text": "银河快报0803",
                                        },
                                        {"text": "\n-"},
                                    ]
                                },
                                "pics": [{"url": "//i0.hdslb.com/0803.jpg"}],
                            }
                        },
                    },
                },
            }
        )
        self.assertIsNotNone(post)
        assert post is not None
        self.assertEqual(post.text, "银河快报0803\n-")
        self.assertEqual(post.image_urls, ("https://i0.hdslb.com/0803.jpg",))

    def test_image_url_allowlist(self) -> None:
        self.assertTrue(
            BilibiliMonitor._allowed_image_url("https://i0.hdslb.com/a.jpg")
        )
        self.assertFalse(
            BilibiliMonitor._allowed_image_url("https://hdslb.com.example/a.jpg")
        )
        self.assertFalse(
            BilibiliMonitor._allowed_image_url("http://i0.hdslb.com/a.jpg")
        )


class BilibiliMonitorTests(unittest.IsolatedAsyncioTestCase):
    async def test_download_images_uses_secure_cache(self) -> None:
        class FakeImageCache:
            def __init__(self, path: Path) -> None:
                self.path = path
                self.urls: list[str] = []
                self.closed = False

            async def get(self, url: str, **kwargs):
                self.urls.append(url)
                self.raise_errors = kwargs.get("raise_errors")
                return self.path

            async def close(self):
                self.closed = True

        async def send_post(post, image_paths, sessions) -> None:
            return None

        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "safe.png"
            image_path.write_bytes(b"png")
            image_cache = FakeImageCache(image_path)
            monitor = BilibiliMonitor(
                Path(tmp) / "monitor",
                uid="1",
                keyword="银河快报",
                interval=300,
                cookie="",
                proxy_url="",
                timeout=5,
                max_image_bytes=1024,
                send_post=send_post,
                log_info=lambda message: None,
                log_warning=lambda message: None,
                image_cache=image_cache,
            )
            post = BilibiliPost(
                "1",
                "银河快报",
                "银河快报0803",
                ("https://i0.hdslb.com/report.jpg",),
            )
            self.assertEqual(await monitor.download_images(post), [image_path])
            self.assertEqual(
                image_cache.urls,
                ["https://i0.hdslb.com/report.jpg"],
            )
            self.assertTrue(image_cache.raise_errors)
            await monitor.stop()
            self.assertTrue(image_cache.closed)

    async def test_risk_control_message_requires_login_cookie(self) -> None:
        async def send_post(post, image_paths, sessions) -> None:
            return None

        with tempfile.TemporaryDirectory() as tmp:
            monitor = BilibiliMonitor(
                Path(tmp),
                uid="1",
                keyword="银河快报",
                interval=300,
                cookie="buvid3=guest",
                proxy_url="",
                timeout=5,
                max_image_bytes=1024,
                send_post=send_post,
                log_info=lambda message: None,
                log_warning=lambda message: None,
            )
            self.assertFalse(monitor.has_login_cookie)
            self.assertIn("SESSDATA", monitor._risk_control_message())

            monitor.cookie = "buvid3=device; SESSDATA=logged-in"
            self.assertTrue(monitor.has_login_cookie)
            self.assertIn("可能已过期", monitor._risk_control_message())
            self.assertTrue(issubclass(BilibiliRiskControlError, RuntimeError))

    async def test_baseline_keyword_filter_and_persistence(self) -> None:
        sent: list[str] = []
        batches = [
            [BilibiliPost("2", "银河快报", "普通动态", ())],
            [
                BilibiliPost("4", "银河快报", "银河快报0802", ()),
                BilibiliPost("3", "银河快报", "没有命中", ()),
                BilibiliPost("2", "银河快报", "普通动态", ()),
            ],
        ]

        async def send_post(post, image_paths, sessions) -> None:
            sent.append(post.dynamic_id)

        with tempfile.TemporaryDirectory() as tmp:
            monitor = BilibiliMonitor(
                Path(tmp),
                uid="1",
                keyword="银河快报",
                interval=300,
                cookie="",
                proxy_url="",
                timeout=5,
                max_image_bytes=1024,
                send_post=send_post,
                log_info=lambda message: None,
                log_warning=lambda message: None,
            )

            async def fetch_posts():
                return batches.pop(0)

            async def download_images(post):
                return []

            monitor.fetch_posts = fetch_posts  # type: ignore[method-assign]
            monitor.download_images = download_images  # type: ignore[method-assign]

            latest = monitor.latest_matching(
                [
                    BilibiliPost("7", "银河快报", "普通内容", ()),
                    BilibiliPost("6", "银河快报", "银河快报0803", ()),
                ]
            )
            self.assertIsNotNone(latest)
            assert latest is not None
            self.assertEqual(latest.dynamic_id, "6")

            self.assertEqual(await monitor.check_once(), 0)
            self.assertTrue(monitor.subscribe("aiocqhttp:GroupMessage:123"))
            self.assertEqual(await monitor.check_once(), 1)
            self.assertEqual(sent, ["4"])
            self.assertFalse(monitor.subscribe("aiocqhttp:GroupMessage:123"))

            restored = BilibiliMonitor(
                Path(tmp),
                uid="1",
                keyword="银河快报",
                interval=300,
                cookie="",
                proxy_url="",
                timeout=5,
                max_image_bytes=1024,
                send_post=send_post,
                log_info=lambda message: None,
                log_warning=lambda message: None,
            )
            self.assertIn("4", restored.seen_ids)
            self.assertEqual(restored.sessions, ["aiocqhttp:GroupMessage:123"])


if __name__ == "__main__":
    unittest.main()
