from __future__ import annotations

import math
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

from astrbot_plugin_Helldivers.awaiting_orders_renderer import AwaitingOrdersRenderer
from astrbot_plugin_Helldivers.dashboard_renderer import DashboardRenderer
from astrbot_plugin_Helldivers.dss_renderer import DSSRenderer
from astrbot_plugin_Helldivers.dispatch_renderer import DispatchRenderer
from astrbot_plugin_Helldivers.global_event_renderer import GlobalEventRenderer
from astrbot_plugin_Helldivers.map_renderer import MapRenderer
from astrbot_plugin_Helldivers.major_order_renderer import MajorOrderRenderer
from astrbot_plugin_Helldivers.stats_model import build_stats_view_model
from astrbot_plugin_Helldivers.stats_renderer import StatsRenderer
from astrbot_plugin_Helldivers.steam_parser import parse_steam_content
from astrbot_plugin_Helldivers.steam_renderer import (
    SteamRenderer,
    _visual_asset_image,
)
from astrbot_plugin_Helldivers.warfront_renderer import WarfrontRenderer


class RendererTests(unittest.TestCase):
    def test_steam_hero_falls_back_to_bundled_warbond_art(self) -> None:
        # 无帖子配图时 /steam 卡片头图必须是捆绑的当前债券横幅，而非旗帜或渐变
        hero = _visual_asset_image(None)
        self.assertIsNotNone(hero)
        assert hero is not None
        self.assertEqual(hero.size, (1976, 630))

    def assert_png(
        self, path: Path | None, size: tuple[int, int] | None = None
    ) -> None:
        self.assertIsNotNone(path)
        assert path is not None
        self.assertTrue(path.exists())
        with Image.open(path) as image:
            if size:
                self.assertEqual(image.size, size)
            self.assertEqual(image.format, "PNG")
            image.verify()

    def test_specialized_renderers(self) -> None:
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            self.assert_png(
                AwaitingOrdersRenderer(output).render(),
                (960, 510),
            )

            row = {
                "name": "测试星球",
                "planet_name": "测试星球",
                "planet_index": 1,
                "campaign_id": 2,
                "players": 1234,
                "progress": 42.5,
                "liberation": 42.5,
                "regen": 1.0,
                "faction": "Automaton",
            }
            sections = {
                "total_players": 1234,
                "urgent": [],
                "defending": [],
                "attacking": {
                    "Automaton": {
                        "main": [row],
                        "low": [],
                        "total_players": 1234,
                        "count": 1,
                    }
                },
            }
            dashboard = DashboardRenderer(output).render(sections)
            self.assert_png(dashboard)

            stats = build_stats_view_model(
                {
                    "galaxy_stats": {
                        "missionsWon": 10,
                        "missionsLost": 2,
                        "missionTime": 7200,
                        "bugKills": 500,
                        "deaths": 10,
                    }
                },
                planets=[
                    {
                        "index": 1,
                        "name": "A",
                        "currentOwner": "Terminids",
                        "statistics": {"playerCount": 100},
                    }
                ],
                status={"time": 86_400},
            )
            self.assert_png(StatsRenderer(output).render(stats), (960, 1320))

            station = {
                "id32": 749875195,
                "electionEnd": (now + timedelta(hours=3)).isoformat(),
                "planet": {
                    "name": "GAELLIVARE",
                    "sector": "TALUS",
                    "currentOwner": "Humans",
                    "health": 8,
                    "maxHealth": 10,
                    "statistics": {"playerCount": 500},
                },
                "tacticalActions": [
                    {
                        "id32": 1,
                        "name": "EAGLE STORM",
                        "display_name": "鹰风暴",
                        "status": 1,
                        "costs": [
                            {
                                "itemMixId": 3992382197,
                                "currentValue": 1,
                                "targetValue": 10,
                            }
                        ],
                    }
                ],
            }
            self.assert_png(
                DSSRenderer(output).render(station, force=True), (1200, 960)
            )

            self.assert_png(
                MajorOrderRenderer(output).render(
                    {"expiresIn": 3600},
                    index=1,
                    title="保卫超级地球",
                    brief="敌军正在向防线推进。",
                    task_desc="解放希斯并巩固补给线。",
                ),
                (1200, 900),
            )
            dispatches = DispatchRenderer(output).render(
                {
                    "id": 3823,
                    "title": "新最高命令",
                    "published": "2026-07-20T08:42:39Z",
                },
                index=1,
                message_text="最高指挥部已发布新的战况简报。" * 80,
            )
            self.assertGreater(len(dispatches), 1)
            for dispatch in dispatches:
                self.assert_png(dispatch)

            points = []
            factions = ["Humans", "Terminids", "Automaton", "Illuminate"]
            for index in range(20):
                angle = index / 20 * math.tau
                points.append(
                    {
                        "index": index,
                        "name": f"P{index}",
                        "x": math.cos(angle) * 0.7,
                        "y": math.sin(angle) * 0.7,
                        "owner": factions[index % 4],
                        "sector": f"S{index // 4}",
                        "hash": index,
                        "waypoints": [index + 1] if index < 19 else [],
                    }
                )
            self.assert_png(
                MapRenderer(output).render(points, force=True), (1100, 1100)
            )

            event = {
                "eventId": 1,
                "title": "SUCCESS",
                "message": "The operation succeeded.",
                "expireTime": 1000,
            }
            self.assert_png(
                GlobalEventRenderer(output).render(
                    event,
                    war_time=100,
                    translated={
                        "display_title": "行动成功",
                        "display_message": "超级地球已经取得胜利。",
                    },
                )
            )

            parsed = parse_steam_content("[h1]Update[/h1][p]Managed democracy.[/p]")
            steam_paths = SteamRenderer(output).render(
                {
                    "id": "1",
                    "title": "News",
                    "content": "",
                    "url": "https://steamcommunity.com",
                },
                parsed=parsed,
            )
            self.assertTrue(steam_paths)
            for path in steam_paths:
                self.assert_png(path)

            warfront_path = WarfrontRenderer(output).render([row], faction="Automaton")
            self.assert_png(warfront_path)
            assert warfront_path is not None
            with Image.open(warfront_path) as warfront_image:
                self.assertEqual(warfront_image.width, 1180)
                self.assertGreaterEqual(warfront_image.height, 1000)


if __name__ == "__main__":
    unittest.main()
